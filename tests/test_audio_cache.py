import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from novelavoz import audio_cache,books,exporter


class AudioCacheTests(unittest.TestCase):
    def write(self,path,data):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)

    def test_clear_only_unused_cache_preserving_books_models_and_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);library=root/'books';a=library/('a'*16);b=library/('b'*16)
            self.write(a/'cache/processed.wav',b'1234');self.write(a/'cache/source/native.wav',b'12345678')
            self.write(b/'cache/running.wav',b'12345')
            keep=[a/'book.json',a/'original.epub',a/'derived/cover.jpg',root/'voices/model.onnx',root/'exports/book.opus']
            for file in keep:self.write(file,b'keep')
            with patch.object(books,'BOOKS',library):
                before=audio_cache.summary(audio_cache.inventory({'b'*16}))
                self.assertEqual((before['deletable_bytes'],before['protected_bytes']),(12,5))
                result=audio_cache.clear({'b'*16})
            self.assertEqual((result['deleted_files'],result['freed_bytes'],result['total_bytes']),(2,12,5))
            self.assertTrue((b/'cache/running.wav').exists())
            self.assertTrue(all(file.read_bytes()==b'keep' for file in keep))

    def test_active_and_queued_books_are_protected_by_server_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);states={}
            for i,status in enumerate(('running','queued','done')):
                book_id=f'{i+1:016x}';self.write(root/book_id/'cache/audio.wav',b'1234')
                states[str(i)]={'book_id':book_id,'status':status}
            with patch.object(books,'BOOKS',root),patch.object(exporter,'STATES',states),patch.object(exporter,'status_list'):
                result=exporter.cache_operation(clear=True)
            self.assertEqual(result['protected_books'],2)
            self.assertEqual((result['deleted_files'],result['protected_bytes']),(1,8))

    def test_locked_file_is_reported_without_stopping_other_deletions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/('a'*16)/'cache/audio.wav';self.write(file,b'data')
            with patch.object(books,'BOOKS',root),patch.object(Path,'unlink',side_effect=PermissionError('locked')):
                result=audio_cache.clear(set())
            self.assertEqual(result['failed_files'],1);self.assertEqual(result['freed_bytes'],0)
            self.assertTrue(file.exists())

    def test_non_project_folders_are_never_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'other-project/cache/audio.wav';self.write(file,b'data')
            with patch.object(books,'BOOKS',root):
                self.assertEqual(audio_cache.clear(set())['deleted_files'],0)
                self.assertFalse(audio_cache.safe_cached_file(file))
            self.assertTrue(file.exists())
