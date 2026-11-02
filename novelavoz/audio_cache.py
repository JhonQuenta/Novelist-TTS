"""Inventory and remove generated book cache only; never follow links."""
import os
import re
import stat
from pathlib import Path
from . import books


def regular_path(path):
    try:
        info=path.lstat()
        return not path.is_symlink() and not (getattr(info,'st_file_attributes',0)&0x400)
    except OSError:return False


def inventory(protected):
    root=books.BOOKS.resolve();items=[]
    if not root.is_dir():return items
    for book in root.iterdir():
        if not re.fullmatch(r'[a-f0-9]{16}',book.name) or not regular_path(book) or not book.is_dir():continue
        cache=book/'cache'
        if not regular_path(cache) or not cache.is_dir():continue
        if cache.resolve().parent!=book.resolve() or book.resolve().parent!=root:continue
        for folder,dirs,files in os.walk(cache,followlinks=False):
            parent=Path(folder)
            dirs[:]=[name for name in dirs if regular_path(parent/name)]
            for name in files:
                path=parent/name
                if not regular_path(path):continue
                try:
                    info=path.lstat()
                    if stat.S_ISREG(info.st_mode) and path.resolve().is_relative_to(cache.resolve()):
                        items.append((path,info.st_size,book.name in protected))
                except OSError:continue
    return items


def summary(items):
    return {'files':len(items),'total_bytes':sum(size for _,size,_ in items),
        'deletable_files':sum(not protected for _,_,protected in items),
        'deletable_bytes':sum(size for _,size,protected in items if not protected),
        'protected_bytes':sum(size for _,size,protected in items if protected)}

def safe_cached_file(path):
    root=books.BOOKS.resolve()
    try:relative=path.relative_to(root)
    except ValueError:return False
    if len(relative.parts)<3 or relative.parts[1]!='cache' or not re.fullmatch(r'[a-f0-9]{16}',relative.parts[0]):return False
    parent=path
    while parent!=root:
        if not regular_path(parent):return False
        parent=parent.parent
    return path.resolve().is_relative_to(root/relative.parts[0]/'cache')


def clear(protected):
    deleted=0;freed=0;failed=0
    for path,size,busy in inventory(protected):
        if busy:continue
        try:
            # Recheck immediately before removal; only the cached file is removed.
            if not safe_cached_file(path):continue
            path.unlink();deleted+=1;freed+=size
        except FileNotFoundError:pass
        except OSError:failed+=1
    return {'ok':True,'deleted_files':deleted,'freed_bytes':freed,'failed_files':failed,
        **summary(inventory(protected))}
