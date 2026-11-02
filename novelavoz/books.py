from __future__ import annotations
import hashlib, json, os, re, sys, zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from epubstudio.epub import EpubProject, local_name, safe_extract, safe_filename, chapter_key

DATA = Path(os.environ.get('NOVELAVOZ_DATA_DIR',str(ROOT / 'data'))).resolve()
BOOKS = DATA / 'books'

def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def confined(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Ruta fuera del proyecto.')
    return path

def book_path(book_id):
    if not re.fullmatch(r'[a-f0-9]{16}', book_id):
        raise ValueError('Proyecto inválido.')
    return BOOKS / book_id

def load_book(book_id):
    book=json.loads((book_path(book_id) / 'book.json').read_text(encoding='utf-8'))
    if book.get('cover_detection_version',0)<2:
        project=EpubProject(book_path(book_id))
        old=project.cover_item()
        old_id=old.id if old else None
        detected=detect_cover(project,book['images'])
        original_cover=book.get('cover')
        if not book.get('cover_user_set') and original_cover in (None,old_id):
            book['cover']=detected
        else: book['cover_user_set']=True
        if book.get('background')==original_cover and not book.get('background_user_set'):
            book['background']=None
        book['cover_detection_version']=2
        save_book(book)
    selected_voice=book.get('settings',{}).get('voice',{})
    if selected_voice.get('engine')=='melo':
        from .supertonic_engine import ready as supertonic_ready
        from .narrator import ready as narrator_ready
        if supertonic_ready('supertonic-M1'):replacement={'engine':'supertonic','voice':'supertonic-M1'}
        elif narrator_ready('narrator-es-MX-Jorge-1.0.2.0'):replacement={'engine':'narrator','voice':'narrator-es-MX-Jorge-1.0.2.0'}
        else:replacement={'engine':'edge','voice':'es-MX-JorgeNeural'}
        book['settings']['voice']={**selected_voice,**replacement}
        save_book(book)
    if selected_voice.get('engine') in ('google','kokoro'):
        from .narrator import ready
        local_voice='narrator-es-MX-Jorge-1.0.2.0'
        replacement={'engine':'narrator','voice':local_voice} if ready(local_voice) else {'engine':'edge','voice':'es-MX-JorgeNeural'}
        book['settings']['voice']={**selected_voice,**replacement}
        save_book(book)
    if selected_voice.get('engine') in ('sapi','onecore'):
        book['settings']['voice']={**selected_voice,'engine':'edge','voice':'es-MX-JorgeNeural'}
        save_book(book)
    return book

def detect_cover(project, images):
    """EPUB 2/3 metadata, guide and cover XHTML including SVG xlink images."""
    by_id={i['id']:i for i in images}
    by_path={str((project.book_dir/i['path']).resolve()):i['id'] for i in images}
    for item in project.manifest.values():
        if 'cover-image' in item.properties.split() and item.id in by_id: return item.id
    for node in project.opf_root.iter():
        if local_name(node.tag)=='meta' and node.attrib.get('name','').lower()=='cover':
            if node.attrib.get('content') in by_id: return node.attrib['content']
    candidates=[]
    for node in project.opf_root.iter():
        if local_name(node.tag)=='reference' and 'cover' in node.attrib.get('type','').lower():
            candidates.append((project.opf_dir/unquote(urlsplit(node.attrib.get('href','')).path)).resolve())
    for item in project.manifest.values():
        if item.media_type not in ('application/xhtml+xml','text/html'): continue
        path=project.resolve_item(item)
        hints=' '.join((item.id,item.href,path.stem)).casefold()
        if re.search(r'cover|portada|cubierta',hints): candidates.append(path)
    for path in dict.fromkeys(candidates):
        if str(path) in by_path: return by_path[str(path)]
        try: root=ET.parse(path).getroot()
        except (OSError,ET.ParseError): continue
        for node in root.iter():
            raw=node.attrib.get('src') or node.attrib.get('href') or node.attrib.get('{http://www.w3.org/1999/xlink}href') or node.attrib.get('data')
            if not raw: continue
            target=urlsplit(raw)
            if target.scheme or target.netloc: continue
            image_id=by_path.get(str((path.parent/unquote(target.path)).resolve()))
            if image_id: return image_id
    for image in images:
        if re.search(r'cover|portada|cubierta',image['path'].casefold()): return image['id']
    return images[0]['id'] if images else None

def effective_background(book):
    return book.get('background') or book.get('cover')

def save_book(book):
    atomic_json(book_path(book['id']) / 'book.json', book)

def library():
    BOOKS.mkdir(parents=True, exist_ok=True)
    result = []
    for path in BOOKS.glob('*/book.json'):
        try:
            b = load_book(path.parent.name)
            result.append({k:b[k] for k in ('id','title','author','cover','chapters')})
        except (ValueError, OSError):
            pass
    return result

def import_epub(payload, filename):
    book_id = hashlib.sha256(payload).hexdigest()[:16]
    directory = book_path(book_id)
    if (directory / 'book.json').exists():
        return load_book(book_id)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / 'source.epub'
    source.write_bytes(payload)
    # Same parser and safe extraction as NovelaEPUB; additionally cap expansion.
    with zipfile.ZipFile(source) as z:
        if len(z.infolist()) > 20000 or sum(i.file_size for i in z.infolist()) > 1024**3:
            raise ValueError('El EPUB excede el límite de extracción (1 GB / 20 000 archivos).')
        if any(i.flag_bits & 1 for i in z.infolist()):
            raise ValueError('EPUB cifrado no compatible.')
    safe_extract(source, directory / 'book')
    project = EpubProject(directory)
    summary = project.summary()
    documents = project.spine_paths()
    roots = {str(p): ET.parse(p).getroot() for p in documents}
    labels = project.chapter_labels()
    navigation = {}
    nav = next((m for m in project.manifest.values() if 'nav' in m.properties.split()), None)
    if nav:
        path = project.resolve_item(nav)
        try:
            navroot = ET.parse(path).getroot()
            tocs = [n for n in navroot.iter() if local_name(n.tag)=='nav' and 'toc' in n.attrib.get('{http://www.idpf.org/2007/ops}type','').split()]
            for a in (tocs[0] if tocs else navroot).iter():
                if local_name(a.tag)=='a' and a.attrib.get('href'):
                    target = urlsplit(a.attrib['href'])
                    key = str(confined(directory / 'book', str((path.parent / unquote(target.path)).relative_to(directory / 'book'))))
                    navigation.setdefault(key, []).append((unquote(target.fragment), ''.join(a.itertext()).strip()))
        except (ET.ParseError, OSError):
            pass
    ncx = project.manifest.get(project.spine_element.attrib.get('toc',''))
    if ncx and not navigation:
        path = project.resolve_item(ncx)
        try:
            for point in ET.parse(path).getroot().iter():
                if local_name(point.tag) != 'navpoint': continue
                content = next((n for n in list(point) if local_name(n.tag)=='content'), None)
                label = next((n for n in point.iter() if local_name(n.tag)=='text'), None)
                if content is None: continue
                target = urlsplit(content.attrib.get('src',''))
                key = str((path.parent / unquote(target.path)).resolve())
                navigation.setdefault(key, []).append((unquote(target.fragment), ''.join(label.itertext()).strip() if label is not None else 'Capítulo'))
        except (ET.ParseError, OSError): pass
    chapters, occurrences = [], []
    images = [{**i, 'rotation':0, 'excluded':False} for i in summary['images']]
    image_by_path = {i['path']:i for i in images}
    document_items={str(project.resolve_item(item)):item for item in project.manifest.values() if item.media_type in ('application/xhtml+xml','text/html')}
    current = None
    def start(title):
        nonlocal current
        current = {'id':len(chapters)+1, 'title':title, 'text':'', 'image_ids':[], 'excluded':False}
        chapters.append(current)
    for path in documents:
        root = roots[str(path)]
        item=document_items.get(str(path))
        hints=' '.join((path.stem,item.id if item else '',item.href if item else '',item.properties if item else '')).casefold()
        document_title=''
        for preferred in ('h1','h2','title'):
            node=next((n for n in root.iter() if local_name(n.tag)==preferred),None)
            if node is not None:
                document_title=''.join(node.itertext()).strip().casefold()
                if document_title: break
        if re.search(r'(?:^|[\W_])(?:cover|portada)(?:[\W_]|$)',hints) or document_title in ('cover','portada','front cover','cubierta'):
            continue
        if item and 'nav' in item.properties.split(): continue
        entries = dict(navigation.get(str(path), []))
        desired = entries.get('') or labels[str(path)]
        if current is None or (('' in entries or not entries) and chapter_key(desired)!=chapter_key(current['title'])):
            start(desired)
        pending = []
        def flush():
            if pending:
                text = re.sub(r'\s+', ' ', ''.join(pending)).strip()
                pending.clear()
                if text:
                    current['text'] += ('\n' if current['text'] else '') + text
        def visit(node):
            tag = local_name(node.tag)
            if tag in ('script','style','nav','head'): return
            anchor = node.attrib.get('id','')
            if anchor and anchor in entries:
                flush()
                if (current['text'] or current['image_ids']) and chapter_key(entries[anchor])!=chapter_key(current['title']):
                    start(entries[anchor])
                elif not current['text']: current['title'] = entries[anchor]
            if tag in ('img','image'):
                flush()
                href = node.attrib.get('src') or node.attrib.get('href') or node.attrib.get('{http://www.w3.org/1999/xlink}href','')
                try:
                    target = (path.parent / unquote(urlsplit(href).path)).resolve()
                    relative = target.relative_to(directory / 'book').as_posix()
                except ValueError: relative = ''
                if relative in image_by_path:
                    oid = f'occ-{len(occurrences)+1}'
                    occurrences.append({'id':oid, 'image_id':image_by_path[relative]['id'], 'chapter_id':current['id'], 'offset':len(current['text']), 'excluded':False, 'duration':20, 'time':None})
                    current['image_ids'].append(oid)
                return
            block = tag in ('p','h1','h2','h3','h4','h5','h6','li','div','section','blockquote','br','figcaption')
            if block: flush()
            if node.text: pending.append(node.text)
            for child in node:
                visit(child)
                if child.tail: pending.append(child.tail)
            if block: flush()
        body = next((n for n in root.iter() if local_name(n.tag)=='body'), root)
        visit(body)
        flush()
    for chapter in chapters:
        chapter['characters'] = len(chapter['text'])
        if not chapter['text'].strip(): chapter['excluded'] = True
    cover = detect_cover(project,images)
    book = {'id':book_id,'title':summary['title'],'author':summary['author'],'source_name':safe_filename(filename),'chapters':chapters,'images':images,'occurrences':occurrences,'cover':cover,'background':None,'cover_detection_version':2,'cover_user_set':False,'settings':{}}
    save_book(book)
    return book

def image_file(book, image_id, rotated=True):
    image = next((i for i in book['images'] if i['id']==image_id), None)
    if not image: raise ValueError('Imagen no encontrada.')
    original = confined(book_path(book['id']) / 'book', image['path'])
    if not rotated or not image.get('rotation'): return original
    from PIL import Image
    derived = book_path(book['id']) / 'derived' / (hashlib.sha256(image_id.encode()).hexdigest()[:16]+f"-{image['rotation']}.png")
    if not derived.exists():
        derived.parent.mkdir(exist_ok=True)
        with Image.open(original) as img:
            img.rotate(-image['rotation'], expand=True).save(derived)
    return derived

def split_text(text, limit=280):
    """Pack complete sentences to a soft target, retaining original offsets.

    Only pathological sentences over 1200 characters need a clause/word fallback.
    A target length must never turn an ordinary phrase into two utterances.
    """
    chunks=[]
    abbreviations={'sr.','sra.','srta.','dr.','dra.','prof.','ud.','uds.','etc.','núm.','pág.','mr.','mrs.'}
    for paragraph in re.finditer(r'[^\n]+',text):
        words=list(re.finditer(r'\S+',paragraph.group()))
        if not words:continue
        sentences=[];start=0
        for i,word in enumerate(words):
            token=word.group().rstrip('»”"\'’)]}')
            ending=bool(re.search(r'[.!?。！？]$',token))
            if token.lower() in abbreviations or re.fullmatch(r'[A-ZÁÉÍÓÚÑ]\.',token):ending=False
            if ending or i==len(words)-1:
                sentences.append((start,i+1));start=i+1
        units=[]
        for start,end in sentences:
            while words[end-1].end()-words[start].start()>1200 and end-start>1:
                boundary=start+1
                while boundary<end and words[boundary].end()-words[start].start()<=1200:boundary+=1
                clauses=[i+1 for i in range(start,boundary) if re.search(r'[,;:，；：][»”"\'’)]}]*$',words[i].group()) and words[i].end()-words[start].start()>=300]
                cut=clauses[-1] if clauses else boundary
                units.append((words[start].start(),words[cut-1].end()));start=cut
            units.append((words[start].start(),words[end-1].end()))
        a,b=units[0]
        for next_a,next_b in units[1:]:
            if next_b-a<=limit:b=next_b
            else:
                offset=paragraph.start()
                chunks.append({'text':text[offset+a:offset+b],'offset':offset+a,'end_offset':offset+b})
                a,b=next_a,next_b
        offset=paragraph.start()
        chunks.append({'text':text[offset+a:offset+b],'offset':offset+a,'end_offset':offset+b})
    return chunks

def make_batches(chapters, selected, size):
    chosen = [c for c in chapters if c['id'] in selected and c['text'].strip()]
    if not chosen: raise ValueError('Selecciona al menos un capítulo con texto.')
    size = len(chosen) if size == 0 else max(1, int(size))
    return [chosen[i:i+size] for i in range(0,len(chosen),size)]
