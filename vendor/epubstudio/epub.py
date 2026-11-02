from __future__ import annotations

import base64
import copy
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import tempfile
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from .repair import repair_misplaced_dialogue_comma_fragments, repair_stutter_comma_fragments
from .glossary import (
    CONTEXTUAL_EFFECT_WORDS,
    FALSE_CANDIDATE_LEADERS,
    GENERIC_TRANSLATABLE_PHRASES,
    ROMANIZED_EFFECT_ROOTS,
    STANDALONE_HONORIFICS,
    contains_honorific,
    english_honorific_base,
    extract_honorific_terms,
    is_context_sensitive_honorific,
    is_contextual_role_honorific,
    is_honorific_term,
    is_stutter_honorific_fragment,
    parse_prefixed_role_honorific,
    translate_contextual_role_honorific,
    translate_english_honorific_base,
    translate_prefixed_role_honorific,
)


XHTML_NS = "http://www.w3.org/1999/xhtml"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

ROLE_TRANSLATIONS = {
    "Duke": "Duque", "Duchess": "Duquesa", "Marquis": "Marqués",
    "Marchioness": "Marquesa", "Count": "Conde", "Countess": "Condesa",
    "Viscount": "Vizconde", "Baron": "Barón", "Baroness": "Baronesa",
    "Crown Prince": "Príncipe Heredero", "Crown Princess": "Princesa Heredera",
    "Mage Tower Lord": "Señor de la Torre de Magos",
    "Tower Lord": "Señor de la Torre", "City Lord": "Señor de la Ciudad",
    "Sect Master": "Maestro de Secta", "Sect Leader": "Líder de la Secta",
    "Team Leader": "Líder de equipo", "Assistant Manager": "Subgerente",
    "Young Master": "Joven Maestro", "Young Lady": "Joven Señorita",
    "Lady": "Dama", "Lord": "Señor", "Saintess": "Santa",
    "Emperor": "Emperador", "Empress": "Emperatriz", "Princess": "Princesa",
    "Prince": "Príncipe", "Grandmaster": "Gran Maestro", "Madam": "Señora",
    "Madame": "Señora", "Auntie": "Tía", "Aunt": "Tía",
}

ET.register_namespace("", XHTML_NS)
ET.register_namespace("opf", OPF_NS)
ET.register_namespace("dc", DC_NS)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


TRANSLATABLE_BLOCK_TAGS = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd",
    "caption", "figcaption", "td", "th",
})
NESTED_BLOCK_TAGS = TRANSLATABLE_BLOCK_TAGS | frozenset({
    "address", "article", "aside", "blockquote", "div", "footer", "header",
    "main", "nav", "ol", "section", "table", "tbody", "tfoot", "thead", "tr", "ul",
})


def _flatten_words_split_by_inline_markup(body: ET.Element) -> int:
    """Join a block when inline markup can corrupt its translation.

    Some generated EPUBs encode censored words as ``p<i>*</i>ssy``. Treating
    each XML text/tail as a separate translation unit turns that into three
    unrelated requests and can yield results such as ``felaciónoppa``. For the
    affected block we keep the exact visible source text as one translation
    unit. We do the same when opening and closing dialogue quotes are separated
    by inline emphasis, because otherwise neither fragment owns the complete
    quote pair. Inline elements remain in the tree but become empty; this
    sacrifices styling only in these risky blocks and preserves the sentence's
    meaning, spacing and punctuation.
    """
    flattened = 0
    joinable = frozenset("*_'\N{RIGHT SINGLE QUOTATION MARK}")

    def text_references(node: ET.Element) -> list[tuple[ET.Element, str, str]]:
        references: list[tuple[ET.Element, str, str]] = []

        def collect(current: ET.Element) -> None:
            if current.text is not None:
                references.append((current, "text", current.text))
            for child in list(current):
                collect(child)
                if child.tail is not None:
                    references.append((child, "tail", child.tail))

        collect(node)
        return references

    for node in list(body.iter()):
        if local_name(node.tag) not in TRANSLATABLE_BLOCK_TAGS:
            continue
        descendants = list(node.iter())[1:]
        if any(local_name(child.tag) in NESTED_BLOCK_TAGS or local_name(child.tag) == "br" for child in descendants):
            continue
        references = text_references(node)
        if len(references) < 2:
            continue
        visible = "".join(value for _, _, value in references)
        split_inside_word = False
        for (_, _, left), (_, _, right) in zip(references, references[1:]):
            if not left or not right or left[-1].isspace() or right[0].isspace():
                continue
            left_char, right_char = left[-1], right[0]
            if (
                (left_char.isalnum() or left_char in joinable)
                and (right_char.isalnum() or right_char in joinable)
                and (left_char.isalnum() or right_char.isalnum())
            ):
                split_inside_word = True
                break
        stripped = visible.strip()
        quote_pairs = {"\"": "\"", "'": "'", "“": "”", "‘": "’", "«": "»"}
        quote_spans_inline_markup = bool(
            stripped
            and quote_pairs.get(stripped[0]) == stripped[-1]
            and sum(bool(value.strip()) for _, _, value in references) > 1
        )
        if not split_inside_word and not quote_spans_inline_markup:
            continue
        node.text = visible
        for child in descendants:
            child.text = None
            child.tail = None
        flattened += 1
    return flattened


def safe_filename(value: str, fallback: str = "libro", limit: int = 180) -> str:
    """Return a Windows-safe filename while preserving readable spaces."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned[:limit].rstrip(" .") or fallback)


def chapter_key(label: str) -> str:
    """Collapse multipart chapter labels without merging unrelated chapters."""
    normalized = unicodedata.normalize("NFKC", label).strip().casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    match = re.match(r"^(cap[ií]tulo\s+[\divxlcdm]+|pr[oó]logo|ep[ií]logo|sinopsis|ilustraciones|contenido|cubierta|p[aá]gina de t[ií]tulo)(?:\s*[:—-].*)?$", normalized)
    return match.group(1) if match else normalized


def safe_extract(epub_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(epub_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if destination != target and destination not in target.parents:
                raise ValueError("El EPUB contiene una ruta insegura.")
        archive.extractall(destination)


def zip_epub(folder: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    if temp.exists():
        temp.unlink()
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        mimetype = folder / "mimetype"
        if mimetype.exists():
            archive.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)
        else:
            archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path == mimetype:
                continue
            archive.write(path, path.relative_to(folder).as_posix(), compress_type=zipfile.ZIP_DEFLATED)
    temp.replace(output)


@dataclass
class ManifestItem:
    id: str
    href: str
    media_type: str
    properties: str
    element: ET.Element


@dataclass
class TextSlot:
    file_path: Path
    node: ET.Element
    attribute: str
    original: str

    def set(self, value: str) -> None:
        setattr(self.node, self.attribute, value)


class EpubProject:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()
        self.book_dir = self.project_dir / "book"
        self.meta_path = self.project_dir / "project.json"
        self._load_package()

    @classmethod
    def create(cls, data_root: Path, source_name: str, payload: bytes) -> "EpubProject":
        project_id = uuid.uuid4().hex[:12]
        project_dir = data_root / "projects" / project_id
        project_dir.mkdir(parents=True)
        source = project_dir / "source.epub"
        source.write_bytes(payload)
        safe_extract(source, project_dir / "book")
        project = cls(project_dir)
        metadata = {
            "id": project_id,
            "source_name": Path(source_name).name,
            "title": project.title,
        }
        project.meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return project

    @property
    def id(self) -> str:
        return self.project_dir.name

    def _load_package(self) -> None:
        container = ET.parse(self.book_dir / "META-INF" / "container.xml")
        rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
        if rootfile is None:
            raise ValueError("No se encontró el paquete OPF del EPUB.")
        self.opf_rel = PurePosixPath(rootfile.attrib["full-path"])
        self.opf_path = self.book_dir / Path(*self.opf_rel.parts)
        self.opf_dir = self.opf_path.parent
        self.opf_tree = ET.parse(self.opf_path)
        self.opf_root = self.opf_tree.getroot()
        self.manifest_element = self.opf_root.find(f"{{{OPF_NS}}}manifest")
        self.spine_element = self.opf_root.find(f"{{{OPF_NS}}}spine")
        if self.manifest_element is None or self.spine_element is None:
            raise ValueError("El EPUB no contiene manifest o spine.")
        self.manifest: dict[str, ManifestItem] = {}
        for item in list(self.manifest_element):
            entry = ManifestItem(
                item.attrib.get("id", ""),
                unquote(item.attrib.get("href", "")),
                item.attrib.get("media-type", ""),
                item.attrib.get("properties", ""),
                item,
            )
            self.manifest[entry.id] = entry
        self.spine_ids = [
            item.attrib.get("idref", "")
            for item in list(self.spine_element)
            if item.attrib.get("idref") in self.manifest
        ]
        title_node = self.opf_root.find(f".//{{{DC_NS}}}title")
        self.title = (title_node.text or "Libro") if title_node is not None else "Libro"
        creators = ["".join(node.itertext()).strip() for node in self.opf_root.findall(f".//{{{DC_NS}}}creator")]
        self.author = " & ".join(value for value in creators if value)
        language_node = self.opf_root.find(f".//{{{DC_NS}}}language")
        self.language = (language_node.text or "").strip() if language_node is not None else ""

    def save_package(self) -> None:
        self.opf_tree.write(self.opf_path, encoding="utf-8", xml_declaration=True)

    def resolve_item(self, item: ManifestItem) -> Path:
        return (self.opf_dir / Path(*PurePosixPath(item.href).parts)).resolve()

    def spine_paths(self) -> list[Path]:
        return [self.resolve_item(self.manifest[item_id]) for item_id in self.spine_ids]

    def chapter_labels(self) -> dict[str, str]:
        labels: dict[str, str] = {}
        nav = next((m for m in self.manifest.values() if "nav" in m.properties.split()), None)
        if nav and self.resolve_item(nav).exists():
            try:
                tree = ET.parse(self.resolve_item(nav))
                for anchor in tree.getroot().iter():
                    if local_name(anchor.tag) != "a" or "href" not in anchor.attrib:
                        continue
                    href = unquote(urlsplit(anchor.attrib["href"]).path)
                    target = (self.resolve_item(nav).parent / Path(*PurePosixPath(href).parts)).resolve()
                    label = "".join(anchor.itertext()).strip()
                    if label:
                        # Some EPUBs append a second, simplified TOC. Keep the
                        # first (usually richer) label for each target.
                        labels.setdefault(str(target), label)
            except ET.ParseError:
                pass
        ncx_id = self.spine_element.attrib.get("toc")
        ncx = self.manifest.get(ncx_id or "")
        if ncx and self.resolve_item(ncx).exists():
            try:
                tree = ET.parse(self.resolve_item(ncx))
                for point in tree.getroot().iter():
                    if local_name(point.tag) != "navpoint":
                        continue
                    content = next((x for x in point.iter() if local_name(x.tag) == "content"), None)
                    text = next((x for x in point.iter() if local_name(x.tag) == "text"), None)
                    if content is None or text is None:
                        continue
                    href = unquote(urlsplit(content.attrib.get("src", "")).path)
                    target = (self.resolve_item(ncx).parent / Path(*PurePosixPath(href).parts)).resolve()
                    if text.text:
                        labels.setdefault(str(target), text.text.strip())
            except ET.ParseError:
                pass
        spine_paths = self.spine_paths()
        # A real EPUB index marks chapter starts, while the spine may contain
        # several XHTML files (text continuations and illustrations) for each
        # entry. Propagate each indexed label up to the next indexed target so
        # the UI and splitter expose logical chapters rather than raw files.
        indexed = [(index, labels[str(path)]) for index, path in enumerate(spine_paths) if str(path) in labels]
        if indexed:
            first_label = indexed[0][1]
            current_label = first_label
            boundaries = dict(indexed)
            for index, path in enumerate(spine_paths):
                current_label = boundaries.get(index, current_label)
                labels[str(path)] = current_label
        for index, path in enumerate(spine_paths, 1):
            if str(path) not in labels:
                labels[str(path)] = self._document_title(path) or f"Capítulo {index}"
        return labels

    def _document_title(self, path: Path) -> str:
        try:
            root = ET.parse(path).getroot()
            for preferred in ("h1", "h2", "title"):
                for node in root.iter():
                    if local_name(node.tag) == preferred:
                        value = "".join(node.itertext()).strip()
                        if value:
                            return value[:180]
        except (ET.ParseError, OSError):
            return ""
        return ""

    def summary(self) -> dict:
        labels = self.chapter_labels()
        chapters = [
            {"index": index, "path": path.relative_to(self.book_dir).as_posix(), "title": labels[str(path)]}
            for index, path in enumerate(self.spine_paths(), 1)
        ]
        groups = self._group_chapters(chapters)
        source_name = ""
        if self.meta_path.exists():
            try:
                source_name = json.loads(self.meta_path.read_text(encoding="utf-8")).get("source_name", "")
            except (OSError, json.JSONDecodeError):
                pass
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "language": self.language,
            "source_name": source_name,
            "chapters": chapters,
            "chapter_count": len(chapters),
            "chapter_groups": groups,
            "logical_chapter_count": len(groups),
            "images": self.images(),
            "cover": self.cover_image(),
        }

    @staticmethod
    def _group_chapters(chapters: list[dict]) -> list[dict]:
        groups: list[dict] = []
        for chapter in chapters:
            key = chapter_key(chapter["title"])
            if groups and groups[-1]["key"] == key:
                groups[-1]["indices"].append(chapter["index"])
                groups[-1]["parts"] += 1
                continue
            groups.append({
                "index": len(groups) + 1,
                "first_index": chapter["index"],
                "indices": [chapter["index"]],
                "title": chapter["title"],
                "parts": 1,
                "key": key,
            })
        for group in groups:
            group.pop("key", None)
        return groups

    def images(self) -> list[dict]:
        result = []
        for item in self.manifest.values():
            if not item.media_type.startswith("image/"):
                continue
            path = self.resolve_item(item)
            if path.exists():
                result.append({
                    "id": item.id,
                    "path": path.relative_to(self.book_dir).as_posix(),
                    "media_type": item.media_type,
                    "bytes": path.stat().st_size,
                })
        return result

    def cover_item(self) -> ManifestItem | None:
        item = next((m for m in self.manifest.values() if "cover-image" in m.properties.split()), None)
        if item:
            return item
        for meta in self.opf_root.iter():
            if local_name(meta.tag) == "meta" and meta.attrib.get("name", "").lower() == "cover":
                candidate = self.manifest.get(meta.attrib.get("content", ""))
                if candidate and candidate.media_type.startswith("image/"):
                    return candidate
        cover_docs = [
            m for m in self.manifest.values()
            if m.media_type in {"application/xhtml+xml", "text/html"} and "cover" in (m.id + " " + m.href).lower()
        ]
        for document in cover_docs:
            path = self.resolve_item(document)
            try:
                root = ET.parse(path).getroot()
            except (ET.ParseError, OSError):
                continue
            for node in root.iter():
                raw = node.attrib.get("src") or node.attrib.get("href") or ""
                if not raw:
                    continue
                target = (path.parent / unquote(urlsplit(raw).path)).resolve()
                found = next((m for m in self.manifest.values() if self.resolve_item(m) == target and m.media_type.startswith("image/")), None)
                if found:
                    return found
        return next((m for m in self.manifest.values() if m.media_type.startswith("image/")), None)

    def cover_image(self) -> dict | None:
        item = self.cover_item()
        if not item:
            return None
        path = self.resolve_item(item)
        if not path.exists():
            return None
        return {
            "id": item.id,
            "path": path.relative_to(self.book_dir).as_posix(),
            "media_type": item.media_type,
            "bytes": path.stat().st_size,
        }

    def replace_cover(self, payload: bytes, media_type: str) -> None:
        if media_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("La portada debe ser JPEG, PNG o WebP.")
        item = self.cover_item()
        if item:
            self.resolve_item(item).write_bytes(payload)
            item.media_type = media_type
            item.element.set("media-type", media_type)
            if self.opf_root.attrib.get("version", "3").startswith("3") and "cover-image" not in item.properties.split():
                item.properties = (item.properties + " cover-image").strip()
                item.element.set("properties", item.properties)
        else:
            extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[media_type]
            path = self.opf_dir / ("novelaepub-cover" + extension)
            path.write_bytes(payload)
            attributes = {"id": "novelaepub_cover", "href": path.name, "media-type": media_type}
            if self.opf_root.attrib.get("version", "3").startswith("3"):
                attributes["properties"] = "cover-image"
            element = ET.SubElement(self.manifest_element, f"{{{OPF_NS}}}item", attributes)
            self.manifest["novelaepub_cover"] = ManifestItem(
                "novelaepub_cover", path.name, media_type, "cover-image", element
            )
        if not any(local_name(node.tag) == "meta" and node.attrib.get("name", "").lower() == "cover" for node in self.opf_root.iter()):
            metadata = self.opf_root.find(f"{{{OPF_NS}}}metadata")
            if metadata is not None:
                ET.SubElement(metadata, f"{{{OPF_NS}}}meta", {"name": "cover", "content": item.id if item else "novelaepub_cover"})
        self.save_package()

    def replace_image(self, relative_path: str, payload: bytes) -> None:
        path = (self.book_dir / relative_path).resolve()
        if self.book_dir not in path.parents or not path.exists():
            raise ValueError("Imagen no válida.")
        path.write_bytes(payload)

    def delete_image(self, relative_path: str) -> None:
        path = (self.book_dir / relative_path).resolve()
        if self.book_dir not in path.parents or not path.exists():
            raise ValueError("Imagen no válida.")
        doomed = [item for item in self.manifest.values() if self.resolve_item(item) == path]
        for item in doomed:
            self.manifest_element.remove(item.element)
            self.manifest.pop(item.id, None)
        path.unlink()
        for document in self.spine_paths():
            try:
                tree = ET.parse(document)
            except ET.ParseError:
                continue
            changed = False
            for parent in tree.getroot().iter():
                for child in list(parent):
                    if local_name(child.tag) not in {"img", "image", "object"}:
                        continue
                    raw = child.attrib.get("src") or child.attrib.get("href") or child.attrib.get("data") or ""
                    candidate = (document.parent / unquote(urlsplit(raw).path)).resolve()
                    if candidate == path:
                        parent.remove(child)
                        changed = True
            if changed:
                tree.write(document, encoding="utf-8", xml_declaration=True)
        self.save_package()

    def repair(
        self,
        output: Path,
        options: dict | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        ambiguity_reviewer: Callable[[list[dict]], list[dict]] | None = None,
    ) -> dict:
        """Create a repaired copy without changing language, styling or images."""
        options = {
            "repair_split_paragraphs": True,
            "repair_stutters": True,
            "repair_epub_compatibility": True,
            "refresh_navigation": False,
            "gemini_review": False,
            "gemini_api_key": "",
            "gemini_model": "gemini-3.5-flash-lite",
            **(options or {}),
        }
        with tempfile.TemporaryDirectory(prefix="novelaepub-repair-") as temp_name:
            temp = Path(temp_name)
            shutil.copytree(self.book_dir, temp / "book")
            clone = EpubProject._from_book(temp, self.title)
            total_steps = 12 if options["gemini_review"] else 4
            if progress:
                progress(1, total_steps, "Aplicando reparaciones locales")
            repaired_paragraphs = clone.repair_split_paragraphs() if options["repair_split_paragraphs"] else 0
            repaired_terminal_punctuation = clone.repair_terminal_punctuation() if options["repair_split_paragraphs"] else 0
            repaired_dialogue_quotes = clone.repair_dialogue_quotes()
            repaired_stutters = clone.repair_stutters() if options["repair_stutters"] else 0
            gemini_report = {
                "gemini_candidates": 0,
                "gemini_reviewed": 0,
                "gemini_joins": 0,
                "gemini_periods_added": 0,
                "gemini_skipped": 0,
                "gemini_review_warning": "",
            }
            if options["gemini_review"]:
                if progress:
                    progress(2, total_steps, "Buscando cortes ambiguos para Gemini")
                try:
                    reviewer = ambiguity_reviewer
                    if reviewer is None:
                        from .engines import review_epub_repair_candidates

                        api_key = str(options.get("gemini_api_key", "")).strip()
                        if not api_key:
                            raise ValueError("Introduce una API key de Gemini para activar la revisión contextual.")
                        model = str(options.get("gemini_model", "")).strip() or "gemini-3.5-flash-lite"
                        def reviewer(candidates: list[dict]) -> list[dict]:
                            def gemini_progress(done: int, total: int) -> None:
                                if progress:
                                    progress(
                                        min(2 + done, 10), total_steps,
                                        f"Gemini: lote {done}/{total}",
                                    )

                            return review_epub_repair_candidates(
                                api_key, model, candidates, progress=gemini_progress
                            )
                    gemini_report = clone.review_ambiguous_paragraphs(reviewer)
                except Exception as exc:
                    gemini_report["gemini_review_warning"] = str(exc)
            compatibility_report = {
                "svg_wrappers_fixed": 0,
                "cover_metadata_repaired": 0,
                "missing_manifest_items_removed": 0,
            }
            if options["repair_epub_compatibility"]:
                if progress:
                    progress(11 if options["gemini_review"] else 3, total_steps, "Reparando compatibilidad interna")
                compatibility_report = clone._repair_epub_compatibility()
                clone._remove_os_artifacts()
            if options["refresh_navigation"]:
                clone.refresh_navigation_labels()
            clone.save_package()
            if progress:
                progress(total_steps, total_steps, "Creando el EPUB reparado")
            zip_epub(clone.book_dir, output)
            source_path = self.project_dir / "source.epub"
            return {
                "repaired_split_paragraphs": repaired_paragraphs,
                "repaired_terminal_punctuation": repaired_terminal_punctuation,
                "repaired_dialogue_quotes": repaired_dialogue_quotes,
                "repaired_stutters": repaired_stutters,
                "gemini_review_enabled": bool(options["gemini_review"]),
                **gemini_report,
                **compatibility_report,
                "original_size": source_path.stat().st_size if source_path.exists() else 0,
                "output_size": output.stat().st_size,
            }

    def optimize(self, output: Path, preset: str = "universal", options: dict | None = None, progress: Callable[[int, int, str], None] | None = None) -> dict:
        options = {
            "grayscale": False,
            "auto_contrast": False,
            "resize_images": True,
            "rotate_landscape": False,
            "jpeg_quality": 100,
            "clean_text": True,
            "clean_metadata": True,
            "maximize_images": True,
            "lossless_size_optimization": True,
            "remove_paragraph_spacing": True,
            "compact_justification": False,
            "convert_images_to_jpeg": False,
            **(options or {}),
        }
        with tempfile.TemporaryDirectory(prefix="novelaepub-opt-") as temp_name:
            temp = Path(temp_name)
            shutil.copytree(self.book_dir, temp / "book")
            clone = EpubProject._from_book(temp, self.title)
            original_labels = clone.chapter_labels()
            css_path = clone.opf_dir / "novelaepub-reader.css"
            css_path.write_text(self._minimal_css(
                preset,
                bool(options["maximize_images"]),
                bool(options["remove_paragraph_spacing"]),
                bool(options["compact_justification"]),
            ), encoding="utf-8")
            css_href = css_path.relative_to(clone.opf_dir).as_posix()
            css_id = "novelaepub_reader_css"
            ET.SubElement(clone.manifest_element, f"{{{OPF_NS}}}item", {
                "id": css_id, "href": css_href, "media-type": "text/css"
            })
            for item in list(clone.manifest.values()):
                if item.media_type == "text/css":
                    path = clone.resolve_item(item)
                    if path.exists():
                        path.unlink()
                    clone.manifest_element.remove(item.element)
                    clone.manifest.pop(item.id, None)
                elif item.media_type in {"application/font-sfnt", "application/vnd.ms-opentype", "font/ttf", "font/otf", "font/woff", "font/woff2"}:
                    path = clone.resolve_item(item)
                    if path.exists():
                        path.unlink()
                    clone.manifest_element.remove(item.element)
                    clone.manifest.pop(item.id, None)
            for document in clone.spine_paths():
                document_css_href = os.path.relpath(css_path, document.parent).replace("\\", "/")
                clone._clean_document(
                    document,
                    document_css_href,
                    bool(options["clean_text"]),
                    convert_italics=preset == "xteink-x4",
                )
            if options["clean_metadata"]:
                clone._clean_metadata()
            clone._remove_os_artifacts()
            image_items = [item for item in clone.manifest.values() if item.media_type.startswith("image/")]
            processed = 0
            for index, item in enumerate(image_items, 1):
                if progress:
                    progress(index - 1, len(image_items), f"Procesando imagen {index}/{len(image_items)}")
                if clone._process_image(clone.resolve_item(item), preset, options):
                    processed += 1
                if progress:
                    progress(index, len(image_items), f"Imagen {index}/{len(image_items)} lista")
            jpeg_converted = 0
            if preset == "xteink-x4" and options["convert_images_to_jpeg"]:
                jpeg_converted = clone._convert_images_to_baseline_jpeg(options)
            size_report = {"duplicate_images_removed": 0, "unused_images_removed": 0, "auxiliary_files_removed": 0}
            if options["lossless_size_optimization"]:
                size_report = clone._lossless_optimize_resources()
            chapter_titles = options.get("chapter_titles")
            if isinstance(chapter_titles, dict) and chapter_titles:
                clone.apply_chapter_titles(chapter_titles)
            else:
                navigation_entries = [(path.name, original_labels[str(path)]) for path in clone.spine_paths()]
                clone._rebuild_navigation(navigation_entries, clone.title)
            clone.save_package()
            zip_epub(clone.book_dir, output)
            source_path = self.project_dir / "source.epub"
            original_size = source_path.stat().st_size if source_path.exists() else 0
            output_size = output.stat().st_size
            return {
                "images_total": len(image_items), "images_processed": processed,
                "images_converted_to_jpeg": jpeg_converted,
                "original_size": original_size, "output_size": output_size,
                **size_report,
            }

    def remove_repeated_text(self, output: Path, target_text: str | list[str], progress: Callable[[int, int, str], None] | None = None) -> dict:
        """Remove all complete block occurrences from a cloned EPUB."""
        values = target_text if isinstance(target_text, list) else [target_text]
        targets = list(dict.fromkeys(self._normalize_search_text(value) for value in values))
        targets = [target for target in targets if len(target) >= 3]
        if not targets:
            raise ValueError("Pega al menos tres caracteres del texto que deseas eliminar.")

        with tempfile.TemporaryDirectory(prefix="novelaepub-text-clean-") as temp_name:
            temp = Path(temp_name)
            shutil.copytree(self.book_dir, temp / "book")
            clone = EpubProject._from_book(temp, self.title)
            documents = clone.spine_paths()
            removed = 0
            changed_files = 0
            target_matches = [0] * len(targets)
            for index, document in enumerate(documents, 1):
                if progress:
                    progress(index - 1, len(documents), f"Buscando en capítulo {index}/{len(documents)}")
                try:
                    tree = ET.parse(document)
                except ET.ParseError:
                    if progress:
                        progress(index, len(documents), f"Capítulo {index}/{len(documents)} revisado")
                    continue
                body = next((node for node in tree.getroot().iter() if local_name(node.tag) == "body"), None)
                document_removed = 0
                if body is not None:
                    for target_index, target in enumerate(targets):
                        matches = self._remove_text_blocks(body, target)
                        document_removed += matches
                        target_matches[target_index] += matches
                if document_removed:
                    tree.write(document, encoding="utf-8", xml_declaration=True)
                    removed += document_removed
                    changed_files += 1
                if progress:
                    progress(index, len(documents), f"Capítulo {index}/{len(documents)} revisado")
            clone.save_package()
            zip_epub(clone.book_dir, output)
            return {
                "removed_occurrences": removed,
                "files_changed": changed_files,
                "files_scanned": len(documents),
                "target_count": len(targets),
                "targets_matched": sum(count > 0 for count in target_matches),
                "target_matches": target_matches,
            }

    @staticmethod
    def _normalize_search_text(value: str) -> str:
        value = unicodedata.normalize("NFC", value or "").replace("\u00a0", " ")
        return re.sub(r"\s+", " ", value).strip()

    @classmethod
    def _remove_text_blocks(cls, root: ET.Element, target: str) -> int:
        """Remove matching blocks, including targets split over sibling blocks."""
        block_names = {
            "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt",
            "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
            "header", "li", "main", "nav", "ol", "p", "section", "table", "tbody",
            "td", "tfoot", "th", "thead", "tr", "ul",
        }

        def visible_text(node: ET.Element) -> str:
            return cls._normalize_search_text("".join(node.itertext()))

        def detach(parent: ET.Element, children: list[ET.Element]) -> None:
            for child in children:
                tail = child.tail or ""
                siblings = list(parent)
                position = siblings.index(child)
                if tail:
                    if position:
                        previous = siblings[position - 1]
                        previous.tail = (previous.tail or "") + tail
                    else:
                        parent.text = (parent.text or "") + tail
                parent.remove(child)

        def visit(parent: ET.Element) -> int:
            count = sum(visit(child) for child in list(parent))
            while True:
                children = list(parent)
                match = None
                for start, child in enumerate(children):
                    if local_name(child.tag) not in block_names:
                        continue
                    combined = ""
                    for end in range(start, len(children)):
                        candidate = children[end]
                        if local_name(candidate.tag) not in block_names:
                            break
                        text = visible_text(candidate)
                        if not text:
                            continue
                        combined = f"{combined} {text}".strip()
                        if combined == target:
                            match = children[start:end + 1]
                            break
                        if len(combined) >= len(target) or not target.startswith(combined):
                            break
                    if match:
                        break
                if not match:
                    break
                detach(parent, match)
                count += 1
            return count

        return visit(root)

    @classmethod
    def _from_book(cls, root: Path, title: str) -> "EpubProject":
        obj = cls.__new__(cls)
        obj.project_dir = root
        obj.book_dir = root / "book"
        obj.meta_path = root / "project.json"
        obj._load_package()
        return obj

    def _clean_document(self, path: Path, css_href: str, clean_text: bool = True, convert_italics: bool = False) -> None:
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            raw = path.read_text(encoding="utf-8", errors="replace")
            if convert_italics:
                def replace_italic(match: re.Match) -> str:
                    content = match.group(2)
                    visible = re.sub(r"<[^>]+>", "", content).strip()
                    return content if visible.startswith("«") and visible.endswith("»") else f"«{content}»"
                raw = re.sub(r"<\s*(em|i)\b[^>]*>(.*?)<\s*/\s*\1\s*>", replace_italic, raw, flags=re.I | re.S)
            raw = re.sub(r"\sstyle\s*=\s*(['\"]).*?\1", "", raw, flags=re.I | re.S)
            raw = re.sub(r"<style\b[^>]*>.*?</style\s*>", "", raw, flags=re.I | re.S)
            raw = re.sub(r"<link\b[^>]*rel\s*=\s*(['\"])stylesheet\1[^>]*>", "", raw, flags=re.I)
            path.write_text(raw, encoding="utf-8")
            return
        root = tree.getroot()
        if convert_italics:
            self._convert_italics_to_quotes(root)
        for parent in root.iter():
            for child in list(parent):
                if local_name(child.tag) in {"style"}:
                    parent.remove(child)
                elif local_name(child.tag) == "link" and "stylesheet" in child.attrib.get("rel", "").lower():
                    parent.remove(child)
            for attr in list(parent.attrib):
                if local_name(attr) in {"style", "width", "height", "color", "face", "size", "bgcolor", "role", "tabindex"} or local_name(attr).startswith("data-"):
                    del parent.attrib[attr]
            if clean_text:
                if parent.text:
                    parent.text = self._clean_text_value(parent.text)
                if parent.tail:
                    parent.tail = self._clean_text_value(parent.tail)
        head = next((node for node in root.iter() if local_name(node.tag) == "head"), None)
        if head is not None:
            ET.SubElement(head, f"{{{XHTML_NS}}}link", {
                "rel": "stylesheet", "type": "text/css", "href": css_href
            })
        tree.write(path, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _convert_italics_to_quotes(root: ET.Element) -> None:
        """Replace italic emphasis with guillemets for CrossInk/Xteink X4."""
        def is_italic(node: ET.Element) -> bool:
            style = node.attrib.get("style", "")
            return local_name(node.tag) in {"em", "i"} or bool(
                re.search(r"(?:^|;)\s*font-style\s*:\s*(?:italic|oblique)\b", style, re.I)
            )

        def strip_italic(node: ET.Element) -> None:
            if is_italic(node):
                style = node.attrib.get("style", "")
                namespace = node.tag.split("}", 1)[0] + "}" if "}" in node.tag else ""
                node.tag = f"{namespace}span"
                if style:
                    cleaned = re.sub(r"(?:^|;)\s*font-style\s*:\s*(?:italic|oblique)\s*;?", ";", style, flags=re.I)
                    cleaned = cleaned.strip(" ;")
                    if cleaned:
                        node.attrib["style"] = cleaned
                    else:
                        node.attrib.pop("style", None)
            for child in list(node):
                strip_italic(child)

        def visit(parent: ET.Element) -> None:
            children = list(parent)
            index = 0
            while index < len(children):
                child = children[index]
                if not is_italic(child):
                    visit(child)
                    index += 1
                    continue
                run = [child]
                cursor = index
                while cursor + 1 < len(children) and not (children[cursor].tail or "").strip() and is_italic(children[cursor + 1]):
                    cursor += 1
                    run.append(children[cursor])
                combined = " ".join("".join(item.itertext()).strip() for item in run).strip()
                has_open = combined.startswith("«")
                has_close = "»" in combined
                for item in run:
                    strip_italic(item)
                if not has_open:
                    run[0].text = "«" + (run[0].text or "")
                if not has_close:
                    run[-1].tail = "»" + (run[-1].tail or "")
                index = cursor + 1

        visit(root)

    @staticmethod
    def _minimal_css(
        preset: str,
        maximize_images: bool = True,
        remove_paragraph_spacing: bool = True,
        compact_justification: bool = False,
    ) -> str:
        page_margin = "0" if preset == "xteink-x4" else "0.15em"
        image_css = "display:block; max-width:100%; max-height:100vh; width:auto; height:auto; object-fit:contain; margin:auto; page-break-inside:avoid; break-inside:avoid;" if maximize_images else "max-width:100%; height:auto; object-fit:contain;"
        paragraph_margin = "0" if remove_paragraph_spacing else "0 0 0.65em 0"
        justification_css = "" if not compact_justification else """
p, li, blockquote {
  text-align: justify;
  text-align-last: left;
  text-justify: inter-word;
  hyphens: auto;
  -webkit-hyphens: auto;
  -epub-hyphens: auto;
  hyphenate-limit-chars: 6 3 3;
  -webkit-hyphenate-limit-before: 3;
  -webkit-hyphenate-limit-after: 3;
  word-spacing: normal;
  letter-spacing: normal;
  orphans: 2;
  widows: 2;
}
"""
        return f"""html, body {{ margin: {page_margin}; padding: 0; }}
@page {{ margin: {page_margin}; }}
body {{ font-family: serif; font-size: 1em; line-height: 1.35; color: inherit; background: transparent; }}
p {{ margin: {paragraph_margin}; text-indent: 0; }}
{justification_css}
h1, h2, h3 {{ page-break-after: avoid; text-align: center; margin: 1em 0; }}
img, svg {{ {image_css} }}
figure {{ margin: 0; padding: 0; text-align: center; page-break-inside: avoid; break-inside: avoid; }}
blockquote {{ margin: 0.7em 1em; }}
pre, code {{ white-space: pre-wrap; }}
"""

    @staticmethod
    def _clean_text_value(value: str) -> str:
        replacements = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"}
        for source, target in replacements.items():
            value = value.replace(source, target)
        value = unicodedata.normalize("NFC", value)
        value = re.sub(r"[ \t]{2,}", " ", value)
        value = re.sub(r"[ \t]+([,.;:!?])", r"\1", value)
        return value

    def _clean_metadata(self) -> None:
        unwanted = ("calibre", "amazon", "kindle", "ibooks", "kobo", "google-play", "google_play")
        metadata = next((node for node in self.opf_root if local_name(node.tag) == "metadata"), None)
        if metadata is None:
            return
        for node in list(metadata):
            haystack = " ".join([local_name(node.tag), *node.attrib.values()]).lower()
            if any(token in haystack for token in unwanted):
                metadata.remove(node)

    def _remove_os_artifacts(self) -> None:
        names = {".ds_store", "thumbs.db", "desktop.ini"}
        for path in list(self.book_dir.rglob("*")):
            if path.is_file() and (path.name.lower() in names or "__macosx" in {part.lower() for part in path.parts}):
                path.unlink()

    def _repair_epub_compatibility(self) -> dict:
        """Unwrap simple SVG images and synchronize cover/manifest metadata."""
        wrappers_fixed = 0

        # Replace inline SVG wrappers containing only one raster image. These
        # wrappers are common in store covers and fail on several small readers.
        for document in self._content_resource_documents():
            if document.suffix.lower() == ".svg":
                continue
            try:
                tree = ET.parse(document)
            except (ET.ParseError, OSError):
                continue
            changed = False
            for parent in tree.getroot().iter():
                for child in list(parent):
                    if local_name(child.tag) != "svg":
                        continue
                    images = [node for node in child.iter() if local_name(node.tag) == "image"]
                    visible = [node for node in child.iter() if local_name(node.tag) in {"path", "rect", "circle", "ellipse", "polygon", "polyline", "line", "text", "use"}]
                    if len(images) != 1 or visible:
                        continue
                    source = next((value for key, value in images[0].attrib.items() if local_name(key) == "href"), "")
                    if not source or source.startswith(("#", "data:")):
                        continue
                    target = (document.parent / unquote(urlsplit(source).path)).resolve()
                    if not target.exists() or target.suffix.lower() == ".svg":
                        continue
                    image = ET.Element(f"{{{XHTML_NS}}}img", {"src": source, "alt": ""})
                    image.tail = child.tail
                    parent.insert(list(parent).index(child), image)
                    parent.remove(child)
                    wrappers_fixed += 1
                    changed = True
            if changed:
                tree.write(document, encoding="utf-8", xml_declaration=True)

        # Replace simple external SVG wrappers with the raster they contain.
        for item in list(self.manifest.values()):
            if item.media_type != "image/svg+xml":
                continue
            svg_path = self.resolve_item(item)
            try:
                root = ET.parse(svg_path).getroot()
            except (ET.ParseError, OSError):
                continue
            images = [node for node in root.iter() if local_name(node.tag) == "image"]
            visible = [node for node in root.iter() if local_name(node.tag) in {"path", "rect", "circle", "ellipse", "polygon", "polyline", "line", "text", "use"}]
            if len(images) != 1 or visible:
                continue
            source = next((value for key, value in images[0].attrib.items() if local_name(key) == "href"), "")
            raster_path = (svg_path.parent / unquote(urlsplit(source).path)).resolve() if source else svg_path
            raster = next((entry for entry in self.manifest.values() if self.resolve_item(entry) == raster_path and entry.media_type.startswith("image/") and entry.media_type != "image/svg+xml"), None)
            if raster is None or not raster_path.exists():
                continue
            self._replace_resource_references(svg_path, raster_path)
            if "cover-image" in item.properties.split():
                properties = set(raster.properties.split())
                properties.add("cover-image")
                raster.properties = " ".join(sorted(properties))
                raster.element.set("properties", raster.properties)
            for node in self.opf_root.iter():
                if local_name(node.tag) == "meta" and node.attrib.get("content") == item.id:
                    node.set("content", raster.id)
            self.manifest_element.remove(item.element)
            self.manifest.pop(item.id, None)
            svg_path.unlink(missing_ok=True)
            wrappers_fixed += 1

        missing_removed = 0
        missing_ids: set[str] = set()
        for item in list(self.manifest.values()):
            if urlsplit(item.href).scheme or self.resolve_item(item).exists():
                continue
            missing_ids.add(item.id)
            self.manifest_element.remove(item.element)
            self.manifest.pop(item.id, None)
            missing_removed += 1
        if missing_ids:
            for itemref in list(self.spine_element):
                if itemref.attrib.get("idref") in missing_ids:
                    self.spine_element.remove(itemref)
            self.spine_ids = [item_id for item_id in self.spine_ids if item_id not in missing_ids]

        cover_repaired = 0
        cover = self.cover_item()
        if cover and self.resolve_item(cover).exists() and cover.media_type.startswith("image/"):
            for item in self.manifest.values():
                properties = [value for value in item.properties.split() if value != "cover-image" or item.id == cover.id]
                if item.id == cover.id and "cover-image" not in properties:
                    properties.append("cover-image")
                updated = " ".join(properties)
                if updated != item.properties:
                    item.properties = updated
                    if updated:
                        item.element.set("properties", updated)
                    else:
                        item.element.attrib.pop("properties", None)
                    cover_repaired = 1
            metadata = next((node for node in self.opf_root if local_name(node.tag) == "metadata"), None)
            if metadata is not None:
                cover_meta = [node for node in list(metadata) if local_name(node.tag) == "meta" and node.attrib.get("name", "").casefold() == "cover"]
                if len(cover_meta) != 1 or not cover_meta or cover_meta[0].attrib.get("content") != cover.id:
                    for node in cover_meta:
                        metadata.remove(node)
                    ET.SubElement(metadata, f"{{{OPF_NS}}}meta", {"name": "cover", "content": cover.id})
                    cover_repaired = 1
        return {
            "svg_wrappers_fixed": wrappers_fixed,
            "cover_metadata_repaired": cover_repaired,
            "missing_manifest_items_removed": missing_removed,
        }

    def _convert_images_to_baseline_jpeg(self, options: dict) -> int:
        """Convert supported raster resources to non-progressive JPEG and update links."""
        Image, _ = self._pillow()
        quality = max(1, min(int(options.get("jpeg_quality", 100)), 100))
        converted = 0
        for item in list(self.manifest.values()):
            if item.media_type not in {"image/png", "image/gif", "image/webp", "image/bmp", "image/tiff"}:
                continue
            old_path = self.resolve_item(item)
            if not old_path.exists():
                continue
            new_path = old_path.with_suffix(".jpg")
            counter = 2
            while new_path.exists() and new_path != old_path:
                new_path = old_path.with_name(f"{old_path.stem}-baseline-{counter}.jpg")
                counter += 1
            try:
                with Image.open(old_path) as opened:
                    image = opened.copy()
                if image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    background = Image.new("RGBA", rgba.size, "white")
                    background.alpha_composite(rgba)
                    image = background.convert("RGB")
                elif image.mode not in {"L", "RGB"}:
                    image = image.convert("RGB")
                image.save(new_path, "JPEG", quality=quality, optimize=True, progressive=False)
            except (OSError, ValueError):
                continue
            self._replace_resource_references(old_path, new_path)
            item.href = new_path.relative_to(self.opf_dir).as_posix()
            item.media_type = "image/jpeg"
            item.element.set("href", item.href)
            item.element.set("media-type", item.media_type)
            if old_path != new_path:
                old_path.unlink(missing_ok=True)
            converted += 1
        return converted

    def _lossless_optimize_resources(self) -> dict:
        """Remove redundant EPUB resources without recompressing image pixels."""
        auxiliary_names = {
            "calibre_bookmarks.txt", "itunesmetadata.plist", "thumbs.db", "desktop.ini",
            ".ds_store", "com.apple.ibooks.display-options.xml",
        }
        auxiliary_removed = 0
        for path in list(self.book_dir.rglob("*")):
            if path.is_file() and path.name.casefold() in auxiliary_names:
                path.unlink()
                auxiliary_removed += 1

        duplicate_removed = 0
        digests: dict[str, ManifestItem] = {}
        for item in list(self.manifest.values()):
            if not item.media_type.startswith("image/"):
                continue
            path = self.resolve_item(item)
            if not path.exists():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            canonical = digests.get(digest)
            if canonical is None:
                digests[digest] = item
                continue
            canonical_path = self.resolve_item(canonical)
            self._replace_resource_references(path, canonical_path)
            if "cover-image" in item.properties.split() and "cover-image" not in canonical.properties.split():
                properties = (canonical.properties + " cover-image").strip()
                canonical.element.set("properties", properties)
                canonical.properties = properties
            for node in self.opf_root.iter():
                if local_name(node.tag) == "meta" and node.attrib.get("content") == item.id:
                    node.set("content", canonical.id)
            self.manifest_element.remove(item.element)
            self.manifest.pop(item.id, None)
            if path != canonical_path and path.exists():
                path.unlink()
            duplicate_removed += 1

        referenced = self._referenced_resource_paths()
        protected_ids = {
            node.attrib.get("content", "") for node in self.opf_root.iter()
            if local_name(node.tag) == "meta" and node.attrib.get("name", "").casefold() == "cover"
        }
        unused_removed = 0
        for item in list(self.manifest.values()):
            if not item.media_type.startswith("image/"):
                continue
            path = self.resolve_item(item)
            if path in referenced or item.id in protected_ids or "cover-image" in item.properties.split():
                continue
            self.manifest_element.remove(item.element)
            self.manifest.pop(item.id, None)
            if path.exists():
                path.unlink()
            unused_removed += 1
        return {
            "duplicate_images_removed": duplicate_removed,
            "unused_images_removed": unused_removed,
            "auxiliary_files_removed": auxiliary_removed,
        }

    def _content_resource_documents(self) -> list[Path]:
        media_types = {"application/xhtml+xml", "image/svg+xml", "text/html"}
        return [self.resolve_item(item) for item in self.manifest.values() if item.media_type in media_types and self.resolve_item(item).exists()]

    def _replace_resource_references(self, old_path: Path, new_path: Path) -> None:
        for document in self._content_resource_documents():
            try:
                tree = ET.parse(document)
            except ET.ParseError:
                continue
            changed = False
            for node in tree.getroot().iter():
                for attribute, raw in list(node.attrib.items()):
                    if local_name(attribute) not in {"src", "href", "data", "poster"} or not raw or raw.startswith(("#", "data:")):
                        continue
                    candidate = (document.parent / unquote(urlsplit(raw).path)).resolve()
                    if candidate == old_path:
                        suffix = f"#{urlsplit(raw).fragment}" if urlsplit(raw).fragment else ""
                        node.set(attribute, os.path.relpath(new_path, document.parent).replace("\\", "/") + suffix)
                        changed = True
            if changed:
                tree.write(document, encoding="utf-8", xml_declaration=True)

    def _referenced_resource_paths(self) -> set[Path]:
        referenced: set[Path] = set()
        for document in self._content_resource_documents():
            try:
                root = ET.parse(document).getroot()
            except ET.ParseError:
                continue
            for node in root.iter():
                for attribute, raw in node.attrib.items():
                    if local_name(attribute) not in {"src", "href", "data", "poster"} or not raw or raw.startswith(("#", "data:")):
                        continue
                    referenced.add((document.parent / unquote(urlsplit(raw).path)).resolve())
        return referenced

    @staticmethod
    def _pillow():
        try:
            from PIL import Image, ImageOps
            return Image, ImageOps
        except ImportError as exc:
            raise RuntimeError("El procesamiento de imágenes necesita Pillow. Ejecuta instalar-imagenes.bat una sola vez.") from exc

    def _process_image(self, path: Path, preset: str, options: dict) -> bool:
        if not path.exists() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}:
            return False
        Image, ImageOps = self._pillow()
        targets = {"xteink-x4": (480, 800), "bigme-b6": (758, 1024), "bigme-b6-300": (1072, 1448), "universal": (1200, 1600)}
        target = targets.get(preset, targets["universal"])
        try:
            with Image.open(path) as opened:
                image = ImageOps.exif_transpose(opened)
                if getattr(image, "is_animated", False):
                    image.seek(0)
                image = image.copy()
            changed = False
            if image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                background.alpha_composite(rgba)
                image = background.convert("RGB")
                changed = True
            if options.get("rotate_landscape") and image.width > image.height:
                image = image.rotate(-90, expand=True)
                changed = True
            if options.get("resize_images"):
                previous_size = image.size
                image.thumbnail(target, Image.Resampling.LANCZOS)
                changed = changed or image.size != previous_size
            if options.get("grayscale"):
                image = image.convert("L")
                changed = True
                if options.get("auto_contrast"):
                    image = ImageOps.autocontrast(image)
            quality = max(40, min(int(options.get("jpeg_quality", 100)), 100))
            suffix = path.suffix.lower()
            if suffix in {".jpg", ".jpeg", ".webp"} and quality < 100:
                changed = True
            if not changed and suffix != ".png":
                return False
            if not changed and suffix == ".png" and not options.get("lossless_size_optimization"):
                return False
            if suffix in {".jpg", ".jpeg"}:
                if image.mode not in {"L", "RGB"}:
                    image = image.convert("RGB")
                image.save(path, "JPEG", quality=quality, optimize=True, progressive=False)
            elif suffix == ".png":
                image.save(path, "PNG", optimize=True)
            elif suffix == ".webp":
                image.save(path, "WEBP", quality=quality, method=6)
            elif suffix == ".bmp":
                image.save(path, "BMP")
            elif suffix == ".gif":
                image.save(path, "GIF", optimize=True)
            else:
                image.save(path, "TIFF", compression="tiff_lzw")
            return True
        except (OSError, ValueError):
            return False

    def rotate_landscape_images(self) -> dict:
        options = {"rotate_landscape": True, "resize_images": False, "grayscale": False, "jpeg_quality": 95}
        rotated = 0
        Image, _ = self._pillow()
        for item in self.manifest.values():
            if not item.media_type.startswith("image/"):
                continue
            path = self.resolve_item(item)
            try:
                with Image.open(path) as image:
                    landscape = image.width > image.height
            except OSError:
                continue
            if landscape and self._process_image(path, "universal", options):
                rotated += 1
        return {"rotated": rotated}

    def split(self, output_dir: Path, chapters_per_part: int, output_name: str = "") -> list[Path]:
        if chapters_per_part < 1:
            raise ValueError("La cantidad de capítulos por parte debe ser mayor que cero.")
        labels, paths, groups = self._split_source()
        chunks = [groups[start:start + chapters_per_part] for start in range(0, len(groups), chapters_per_part)]
        return self._write_split_parts(output_dir, chunks, labels, paths, output_name)

    def split_into_parts(self, output_dir: Path, part_count: int, output_name: str = "") -> list[Path]:
        """Split into a requested number of balanced logical-chapter parts."""
        labels, paths, groups = self._split_source()
        if len(groups) < 2:
            raise ValueError("El EPUB necesita al menos dos capítulos o secciones para dividirse.")
        if part_count < 2:
            raise ValueError("La cantidad de partes debe ser al menos 2.")
        part_count = min(part_count, len(groups))
        base, remainder = divmod(len(groups), part_count)
        # Put the extra chapters in the final parts: 501 / 2 -> 250 + 251.
        sizes = [base] * (part_count - remainder) + [base + 1] * remainder
        chunks = []
        start = 0
        for size in sizes:
            chunks.append(groups[start:start + size])
            start += size
        return self._write_split_parts(output_dir, chunks, labels, paths, output_name)

    def _split_source(self) -> tuple[dict[str, str], list[Path], list[dict]]:
        labels = self.chapter_labels()
        paths = self.spine_paths()
        raw_chapters = [
            {"index": index, "title": labels[str(path)]}
            for index, path in enumerate(paths, 1)
        ]
        return labels, paths, self._group_chapters(raw_chapters)

    def _write_split_parts(self, output_dir: Path, chunks: list[list[dict]], labels: dict[str, str], paths: list[Path], output_name: str) -> list[Path]:
        outputs: list[Path] = []
        base_name = safe_filename(output_name or self.title)
        output_dir.mkdir(parents=True, exist_ok=True)
        for part_index, selected_groups in enumerate(chunks, 1):
            positions = [index - 1 for group in selected_groups for index in group["indices"]]
            selected_paths = [paths[position] for position in positions]
            selected_id_order = [self.spine_ids[position] for position in positions]
            selected_ids = set(selected_id_order)
            with tempfile.TemporaryDirectory(prefix="novelaepub-split-") as temp_name:
                temp = Path(temp_name)
                shutil.copytree(self.book_dir, temp / "book")
                clone = EpubProject._from_book(temp, self.title)
                excluded_paths = {
                    clone.resolve_item(clone.manifest[item_id])
                    for item_id in clone.spine_ids if item_id not in selected_ids
                }
                for itemref in list(clone.spine_element):
                    if itemref.attrib.get("idref") not in selected_ids:
                        clone.spine_element.remove(itemref)
                for item_id in list(clone.spine_ids):
                    if item_id in selected_ids:
                        continue
                    item = clone.manifest.get(item_id)
                    if item:
                        clone.manifest_element.remove(item.element)
                        path = clone.resolve_item(item)
                        if path.exists():
                            path.unlink()
                clone.spine_ids = selected_id_order
                part_title = f"{self.title} — Parte {part_index}"
                title_node = clone.opf_root.find(f".//{{{DC_NS}}}title")
                if title_node is not None:
                    title_node.text = part_title
                original_selected = selected_paths
                part_labels = [(path.name, labels[str(original)]) for path, original in zip(clone.spine_paths(), original_selected)]
                clone._rebuild_navigation(part_labels, part_title)
                clone.save_package()
                output = output_dir / f"{base_name} - Parte {part_index:03d}.epub"
                zip_epub(clone.book_dir, output)
                outputs.append(output)
        return outputs

    def retain_spine_indices(self, selected_indices: list[int]) -> None:
        selected_positions = {index - 1 for index in selected_indices if 1 <= index <= len(self.spine_ids)}
        if not selected_positions:
            raise ValueError("Debes seleccionar al menos un capítulo.")
        labels = self.chapter_labels()
        old_ids = list(self.spine_ids)
        selected_ids = [item_id for pos, item_id in enumerate(old_ids) if pos in selected_positions]
        selected_label_values = [labels[str(path)] for pos, path in enumerate(self.spine_paths()) if pos in selected_positions]
        for position, itemref in reversed(list(enumerate(list(self.spine_element)))):
            if position not in selected_positions:
                self.spine_element.remove(itemref)
        for position, item_id in enumerate(old_ids):
            if position in selected_positions:
                continue
            item = self.manifest.get(item_id)
            if not item or "nav" in item.properties.split():
                continue
            path = self.resolve_item(item)
            self.manifest_element.remove(item.element)
            self.manifest.pop(item_id, None)
            if path.exists():
                path.unlink()
        self.spine_ids = selected_ids
        entries = [(path.name, label) for path, label in zip(self.spine_paths(), selected_label_values)]
        self._rebuild_navigation(entries, self.title)
        self.save_package()

    def _rebuild_navigation(self, entries: list[tuple[str, str]], part_title: str) -> None:
        spine_paths = self.spine_paths()
        if len(entries) == len(spine_paths):
            paired_entries = list(zip(spine_paths, entries))
        else:
            # Repair may intentionally omit cover/title pages from the TOC.
            # Match the supplied filename instead of shifting every following
            # label onto the previous spine item.
            unused = list(spine_paths)
            paired_entries = []
            for raw_name, label in entries:
                normalized = PurePosixPath(str(raw_name)).as_posix()
                match = next((
                    path for path in unused
                    if path.name == PurePosixPath(normalized).name
                    or path.relative_to(self.book_dir).as_posix() == normalized
                ), None)
                if match is None:
                    continue
                unused.remove(match)
                paired_entries.append((match, (raw_name, label)))
        nav = next((m for m in self.manifest.values() if "nav" in m.properties.split()), None)
        if nav:
            nav_path = self.resolve_item(nav)
            relative_entries = []
            for spine_path, (_, label) in paired_entries:
                href = os.path.relpath(spine_path, nav_path.parent).replace("\\", "/")
                if not relative_entries or chapter_key(relative_entries[-1][1]) != chapter_key(label):
                    relative_entries.append((href, label))
            root = ET.Element(f"{{{XHTML_NS}}}html")
            head = ET.SubElement(root, f"{{{XHTML_NS}}}head")
            ET.SubElement(head, f"{{{XHTML_NS}}}title").text = part_title
            body = ET.SubElement(root, f"{{{XHTML_NS}}}body")
            nav_node = ET.SubElement(body, f"{{{XHTML_NS}}}nav", {"{http://www.idpf.org/2007/ops}type": "toc"})
            ET.SubElement(nav_node, f"{{{XHTML_NS}}}h1").text = "Índice"
            ordered = ET.SubElement(nav_node, f"{{{XHTML_NS}}}ol")
            for href, label in relative_entries:
                li = ET.SubElement(ordered, f"{{{XHTML_NS}}}li")
                ET.SubElement(li, f"{{{XHTML_NS}}}a", {"href": href}).text = label
            ET.ElementTree(root).write(nav_path, encoding="utf-8", xml_declaration=True)
        ncx_id = self.spine_element.attrib.get("toc")
        ncx = self.manifest.get(ncx_id or "")
        if ncx:
            ncx_path = self.resolve_item(ncx)
            ET.register_namespace("", NCX_NS)
            root = ET.Element(f"{{{NCX_NS}}}ncx", {"version": "2005-1"})
            doc_title = ET.SubElement(root, f"{{{NCX_NS}}}docTitle")
            ET.SubElement(doc_title, f"{{{NCX_NS}}}text").text = part_title
            nav_map = ET.SubElement(root, f"{{{NCX_NS}}}navMap")
            ncx_entries: list[tuple[Path, str]] = []
            for spine_path, (_, label) in paired_entries:
                if not ncx_entries or chapter_key(ncx_entries[-1][1]) != chapter_key(label):
                    ncx_entries.append((spine_path, label))
            for index, (spine_path, label) in enumerate(ncx_entries, 1):
                point = ET.SubElement(nav_map, f"{{{NCX_NS}}}navPoint", {"id": f"navPoint-{index}", "playOrder": str(index)})
                label_node = ET.SubElement(point, f"{{{NCX_NS}}}navLabel")
                ET.SubElement(label_node, f"{{{NCX_NS}}}text").text = label
                href = os.path.relpath(spine_path, ncx_path.parent).replace("\\", "/")
                ET.SubElement(point, f"{{{NCX_NS}}}content", {"src": href})
            ET.ElementTree(root).write(ncx_path, encoding="utf-8", xml_declaration=True)

    def load_text_slots(self) -> tuple[list[TextSlot], dict[Path, ET.ElementTree]]:
        slots: list[TextSlot] = []
        trees: dict[Path, ET.ElementTree] = {}
        skip = {"script", "style", "code", "pre", "svg", "math"}
        for path in self.spine_paths():
            file_slots, tree = self.load_document_slots(path)
            if tree is not None:
                trees[path] = tree
                slots.extend(file_slots)
        return slots, trees

    @staticmethod
    def _text_references(node: ET.Element) -> list[tuple[ET.Element, str]]:
        """Return visible text/tail locations in their document reading order."""
        references: list[tuple[ET.Element, str]] = []

        def visit(current: ET.Element) -> None:
            if current.text:
                references.append((current, "text"))
            for child in list(current):
                visit(child)
                if child.tail:
                    references.append((child, "tail"))

        visit(node)
        return references

    def repair_stutters(self) -> int:
        """Repair comma stutters across complete XHTML text runs.

        EPUB generators frequently split ``T, that's`` between ``span`` or
        ``em`` nodes. Processing each XML slot separately misses those cases,
        so each leaf block is reconstructed only for matching and then written
        back into its original text/tail locations.
        """
        repaired = 0
        block_names = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
        skipped = {"script", "style", "code", "pre", "svg", "math"}
        for document in self.spine_paths():
            try:
                tree = ET.parse(document)
            except (ET.ParseError, OSError):
                continue
            changed = False
            root = tree.getroot()
            blocks = [
                node for node in root.iter()
                if local_name(node.tag) in block_names
                and not any(
                    descendant is not node and local_name(descendant.tag) in block_names
                    for descendant in node.iter()
                )
                and not any(local_name(descendant.tag) in skipped for descendant in node.iter())
            ]
            for block in blocks:
                references = self._text_references(block)
                values = [getattr(node, attribute) or "" for node, attribute in references]
                updated, count = repair_stutter_comma_fragments(values)
                if not count:
                    continue
                for (node, attribute), value in zip(references, updated):
                    setattr(node, attribute, value)
                repaired += count
                changed = True
            if changed:
                tree.write(document, encoding="utf-8", xml_declaration=True)
        return repaired

    def repair_dialogue_quotes(self) -> int:
        """Restore opening dialogue quotes that were converted to commas."""
        repaired = 0
        block_names = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
        skipped = {"script", "style", "code", "pre", "svg", "math"}
        for document in self.spine_paths():
            try:
                tree = ET.parse(document)
            except (ET.ParseError, OSError):
                continue
            changed = False
            for block in tree.getroot().iter():
                if local_name(block.tag) not in block_names:
                    continue
                if any(
                    descendant is not block and local_name(descendant.tag) in block_names
                    for descendant in block.iter()
                ) or any(local_name(descendant.tag) in skipped for descendant in block.iter()):
                    continue
                references = self._text_references(block)
                values = [getattr(node, attribute) or "" for node, attribute in references]
                updated, count = repair_misplaced_dialogue_comma_fragments(values)
                if not count:
                    continue
                for (node, attribute), value in zip(references, updated):
                    setattr(node, attribute, value)
                repaired += count
                changed = True
            if changed:
                tree.write(document, encoding="utf-8", xml_declaration=True)
        return repaired

    @staticmethod
    def _is_split_paragraph(first: ET.Element, second: ET.Element) -> bool:
        """Detect obvious accidental paragraph breaks without joining real prose blocks."""
        if local_name(first.tag) != "p" or local_name(second.tag) != "p":
            return False
        blocked = {"img", "image", "svg", "math", "br", "hr"}
        if any(local_name(node.tag) in blocked for node in first.iter()) or any(
            local_name(node.tag) in blocked for node in second.iter()
        ):
            return False
        style_hint = " ".join(
            [first.attrib.get("class", ""), first.attrib.get("id", ""), second.attrib.get("class", ""), second.attrib.get("id", "")]
        ).casefold()
        if any(word in style_hint for word in ("title", "heading", "poem", "verse", "stanza", "center", "separator")):
            return False
        left = re.sub(r"\s+", " ", "".join(first.itertext())).strip()
        right = re.sub(r"\s+", " ", "".join(second.itertext())).strip()
        if len(left) < 8 or not right:
            return False
        if EpubProject._looks_like_standalone_effect(left) or EpubProject._looks_like_standalone_effect(right):
            return False
        if re.search(r"[.!?…:;][\s\"'’”»)\]]*$", left) or left.endswith(("—", "–", "-")):
            return False
        # A closing quotation mark normally marks an intentional dialogue
        # boundary. An actually interrupted quotation has no closing mark and
        # can still be repaired by the rules below.
        if re.search(r"[\"'’”»]\s*$", left):
            return False
        beginning = right.lstrip("\"'‘’“”«»([{ ")
        if not beginning:
            return False
        dangling_left = bool(re.search(
            r"\b(?:and|but|or|nor|yet|because|so|if|when|while|whereas|although|though|since|as|that|which|who|whose|whom|to|of|with|for|from|by|at|in|on)\s*$",
            left,
            re.I,
        )) or bool(re.search(r"\b(?:but|and)\s+also\s*$", left, re.I))
        first_word = re.match(r"[A-Za-z]+", beginning)
        comma_continuations = {
            "a", "an", "and", "as", "because", "but", "he", "her", "his",
            "i", "if", "it", "its", "my", "or", "our", "she", "so", "that",
            "the", "their", "they", "this", "these", "those", "though", "we",
            "when", "where", "which", "while", "who", "whose", "you", "your",
            "yet", "just", "made", "makes", "caused", "causes", "gave", "gives",
            "filled", "fills", "brought", "brings", "sent", "sends",
        }
        comma_continuation = bool(re.search(r",\s*$", left)) and bool(
            beginning[:1].islower()
            or first_word and first_word.group(0).casefold() in comma_continuations
        )
        strong_right = bool(re.match(
            r"(?:and|but|or|nor|yet|because|so|which|that|who|whose|whom)\b",
            beginning,
            re.I,
        ))
        subject_result = bool(re.match(
            r"(?:the\s+)?(?:fact|thought|sight|idea|realization|knowledge)\b",
            left,
            re.I,
        )) and bool(re.match(
            r"(?:made|makes|caused|causes|gave|gives|filled|fills|brought|brings|sent|sends|was|is)\b",
            beginning,
            re.I,
        ))
        delayed_continuation = bool(re.search(
            r"\b(?:and|but)\s+(?:in|after|before|within)\s+(?:a\s+few|several|\d+)\s+"
            r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s*$",
            left,
            re.I,
        ))
        if dangling_left or comma_continuation or strong_right or subject_result or delayed_continuation:
            return True
        if len(left) < 35:
            return False
        return bool(beginning[0].islower() or re.match(r"I(?:\s|,)", beginning))

    @staticmethod
    def _lowercase_continuation_start(node: ET.Element) -> None:
        """Lowercase an obvious continuation word after joining paragraphs."""
        continuation_words = {
            "a", "an", "and", "as", "because", "but", "he", "her", "his",
            "if", "it", "its", "my", "or", "our", "she", "so", "that",
            "the", "their", "they", "this", "these", "those", "though",
            "although", "we", "when", "where", "which", "while", "who",
            "whose", "you", "your", "yet", "just", "now", "then", "even",
            "fortunately", "unfortunately", "perhaps", "maybe", "what",
            "made", "makes", "caused", "causes", "gave", "gives",
            "filled", "fills", "brought", "brings", "sent", "sends",
            "being", "having", "hearing", "seeing", "feeling", "thinking",
            "looking", "walking", "getting", "making", "taking", "using",
            "doing", "trying", "seducing",
        }
        for current, attribute in EpubProject._text_references(node):
            value = getattr(current, attribute) or ""
            match = re.search(r"[A-Za-z]+", value)
            if match is None:
                continue
            word = match.group(0)
            if word.casefold() in continuation_words and word[:1].isupper():
                setattr(
                    current,
                    attribute,
                    value[:match.start()] + word[:1].lower() + value[match.start() + 1:],
                )
            return

    @staticmethod
    def _looks_like_standalone_effect(value: str) -> bool:
        """Recognize compact sound-effect paragraphs that must stay separate."""
        compact = re.sub(r"\s+", " ", value).strip()
        if re.search(
            r"\([^)]*\b(?:onomatopoeia|sounds?|squelch(?:ing)?|slurp|snort|squirt|"
            r"heartbeat|dripping|sliding|thrusting|moaning|mumbling|snoring)\b[^)]*\)\s*$",
            compact,
            re.I,
        ):
            return True
        bare = compact.strip(" \t\r\n.!,?:;…~—–-_\"'‘’“”«»()[]{}♥")
        if re.fullmatch(r"[A-Za-z~]{2,24}", bare):
            return True
        words = re.findall(r"[A-Za-z]+", bare)
        if len(words) >= 2:
            keys = [re.sub(r"(.)\1+", r"\1", word.casefold()) for word in words]
            if len(set(keys)) == 1:
                return True
        return False

    @staticmethod
    def _join_paragraph_nodes(first: ET.Element, second: ET.Element) -> None:
        left_text = re.sub(r"\s+", " ", "".join(first.itertext())).strip()
        right_text = re.sub(r"\s+", " ", "".join(second.itertext())).strip()
        EpubProject._lowercase_continuation_start(second)
        if len(first):
            anchor, attribute = first[-1], "tail"
        else:
            anchor, attribute = first, "text"
        existing = getattr(anchor, attribute) or ""
        incoming = second.text or ""
        # A common machine-translated layout splits a single subject/result
        # construction into three paragraphs: "..., but" / "Just being... ,"
        # / "Made me...". Once the first two pieces have been joined, the
        # comma before the predicate is no longer valid.
        if (
            re.search(r"\b(?:but|and)\s+(?:just\s+)?[a-z]+ing\b.*[,]\s*$", left_text, re.I)
            and re.match(
                r"(?:made|makes|make|caused|causes|cause|gave|gives|give|filled|fills|fill|"
                r"brought|brings|bring|sent|sends|send)\b",
                right_text,
                re.I,
            )
        ):
            existing = re.sub(r",\s*$", "", existing)
        setattr(anchor, attribute, existing.rstrip() + " " + incoming.lstrip())
        for child in list(second):
            second.remove(child)
            first.append(child)
        first.tail = second.tail

    def repair_split_paragraphs(self) -> int:
        """Join adjacent <p> elements that are clearly one interrupted sentence."""
        repaired = 0
        for document in self.spine_paths():
            try:
                tree = ET.parse(document)
            except (ET.ParseError, OSError):
                continue
            changed = False
            for parent in tree.getroot().iter():
                index = 0
                while index + 1 < len(parent):
                    first, second = parent[index], parent[index + 1]
                    if self._is_split_paragraph(first, second):
                        self._join_paragraph_nodes(first, second)
                        parent.remove(second)
                        repaired += 1
                        changed = True
                        continue
                    index += 1
            if changed:
                tree.write(document, encoding="utf-8", xml_declaration=True)
        return repaired

    @staticmethod
    def _replace_terminal_comma_with_period(node: ET.Element) -> bool:
        target: tuple[ET.Element, str] | None = None
        for current, attribute in EpubProject._text_references(node):
            value = getattr(current, attribute) or ""
            if value.strip():
                target = (current, attribute)
        if target is None:
            return False
        current, attribute = target
        value = getattr(current, attribute) or ""
        updated, count = re.subn(r",(?=\s*$)", ".", value, count=1)
        if not count:
            return False
        setattr(current, attribute, updated)
        return True

    def repair_terminal_punctuation(self) -> int:
        """Finish a narrow class of standalone sentences ending in a comma."""
        repaired = 0
        new_sentence = re.compile(
            r"(?:Now(?!\s+that\b)|However|Nevertheless|Meanwhile|Instead|Suddenly|"
            r"Fortunately|Unfortunately)\b",
            re.I,
        )
        for document in self.spine_paths():
            try:
                tree = ET.parse(document)
            except (ET.ParseError, OSError):
                continue
            changed = False
            for parent in tree.getroot().iter():
                children = list(parent)
                for first, second in zip(children, children[1:]):
                    if local_name(first.tag) != "p" or local_name(second.tag) != "p":
                        continue
                    left = re.sub(r"\s+", " ", "".join(first.itertext())).strip()
                    right = re.sub(r"\s+", " ", "".join(second.itertext())).strip()
                    beginning = right.lstrip("\"'‘’“”«»([{ ")
                    if len(left) < 20 or not left.endswith(",") or not new_sentence.match(beginning):
                        continue
                    if self._looks_like_standalone_effect(left) or self._looks_like_standalone_effect(right):
                        continue
                    if self._replace_terminal_comma_with_period(first):
                        repaired += 1
                        changed = True
            if changed:
                tree.write(document, encoding="utf-8", xml_declaration=True)
        return repaired

    @staticmethod
    def _append_terminal_period(node: ET.Element) -> None:
        """Append a period to the last visible text slot while preserving inline markup."""
        target: tuple[ET.Element, str] | None = None
        for current in node.iter():
            if current.text and current.text.strip():
                target = (current, "text")
            if current is not node and current.tail and current.tail.strip():
                target = (current, "tail")
        if target is None:
            node.text = (node.text or "").rstrip() + "."
            return
        current, attribute = target
        value = getattr(current, attribute) or ""
        setattr(current, attribute, value.rstrip() + ".")

    def review_ambiguous_paragraphs(
        self,
        reviewer: Callable[[list[dict]], list[dict]],
        limit: int = 120,
    ) -> dict:
        """Let a bounded reviewer classify ambiguous paragraph boundaries."""
        candidates: list[dict] = []
        targets: dict[str, tuple[Path, ET.ElementTree, ET.Element, ET.Element, ET.Element]] = {}
        labels = self.chapter_labels()
        label_by_path = {
            path: labels.get(str(path), path.stem)
            for path in self.spine_paths()
        }
        blocked = {"img", "image", "svg", "math", "br", "hr"}
        style_words = ("title", "heading", "poem", "verse", "stanza", "center", "separator")

        for document in self.spine_paths():
            if len(candidates) >= limit:
                break
            try:
                tree = ET.parse(document)
            except (ET.ParseError, OSError):
                continue
            for parent in tree.getroot().iter():
                index = 0
                children = list(parent)
                while index + 1 < len(children) and len(candidates) < limit:
                    first, second = children[index], children[index + 1]
                    index += 1
                    if local_name(first.tag) != "p" or local_name(second.tag) != "p":
                        continue
                    if any(local_name(node.tag) in blocked for node in first.iter()) or any(
                        local_name(node.tag) in blocked for node in second.iter()
                    ):
                        continue
                    style_hint = " ".join((
                        first.attrib.get("class", ""), first.attrib.get("id", ""),
                        second.attrib.get("class", ""), second.attrib.get("id", ""),
                    )).casefold()
                    if any(word in style_hint for word in style_words):
                        continue
                    left = re.sub(r"\s+", " ", "".join(first.itertext())).strip()
                    right = re.sub(r"\s+", " ", "".join(second.itertext())).strip()
                    if len(left) < 20 or not right:
                        continue
                    if self._looks_like_standalone_effect(left) or self._looks_like_standalone_effect(right):
                        continue
                    if re.search(r"[.!?…:;][\s\"'’”»)\]]*$", left) or left.endswith(("—", "–", "-")):
                        continue
                    if re.search(r"[\"'’”»]\s*$", left) or right.startswith(("\"", "'", "‘", "’", "“", "”", "«", "»")):
                        continue
                    beginning = right.lstrip("([{ ")
                    if not beginning or not beginning[0].isupper():
                        continue
                    if self._is_split_paragraph(first, second):
                        continue

                    siblings = list(parent)
                    position = siblings.index(first)
                    previous = ""
                    following = ""
                    if position > 0 and local_name(siblings[position - 1].tag) == "p":
                        previous = re.sub(r"\s+", " ", "".join(siblings[position - 1].itertext())).strip()
                    if position + 2 < len(siblings) and local_name(siblings[position + 2].tag) == "p":
                        following = re.sub(r"\s+", " ", "".join(siblings[position + 2].itertext())).strip()
                    candidate_id = f"G{len(candidates) + 1:04d}"
                    candidates.append({
                        "id": candidate_id,
                        "chapter": label_by_path.get(document, document.stem),
                        "path": document.relative_to(self.book_dir).as_posix(),
                        "previous": previous,
                        "left": left,
                        "right": right,
                        "next": following,
                    })
                    targets[candidate_id] = (document, tree, parent, first, second)
                    index += 1

        report = {
            "gemini_candidates": len(candidates),
            "gemini_reviewed": 0,
            "gemini_joins": 0,
            "gemini_periods_added": 0,
            "gemini_skipped": 0,
            "gemini_review_warning": "",
        }
        if not candidates:
            return report

        decisions = reviewer(candidates)
        missing_decisions = sum(
            1 for decision in decisions
            if isinstance(decision, dict)
            and str(decision.get("reason", "")).startswith("Gemini no devolvió")
        )
        if missing_decisions:
            report["gemini_review_warning"] = (
                f"Gemini no pudo clasificar {missing_decisions} de {len(candidates)} límites; "
                "se conservaron sin cambios."
            )
        changed_trees: dict[Path, ET.ElementTree] = {}
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            candidate_id = str(decision.get("id", ""))
            target = targets.get(candidate_id)
            if target is None:
                continue
            report["gemini_reviewed"] += 1
            action = str(decision.get("action", "")).casefold()
            confidence = str(decision.get("confidence", "")).casefold()
            if confidence != "high" or action not in {"join", "add_period"}:
                report["gemini_skipped"] += 1
                continue
            document, tree, parent, first, second = target
            if first not in list(parent) or second not in list(parent):
                report["gemini_skipped"] += 1
                continue
            if action == "join":
                self._join_paragraph_nodes(first, second)
                parent.remove(second)
                report["gemini_joins"] += 1
            else:
                self._append_terminal_period(first)
                report["gemini_periods_added"] += 1
            changed_trees[document] = tree
        report["gemini_skipped"] += max(0, len(candidates) - report["gemini_reviewed"])
        for document, tree in changed_trees.items():
            tree.write(document, encoding="utf-8", xml_declaration=True)
        return report

    def load_document_slots(self, path: Path) -> tuple[list[TextSlot], ET.ElementTree | None]:
        slots: list[TextSlot] = []
        skip = {"script", "style", "code", "pre", "svg", "math"}
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            return slots, None
        root = tree.getroot()
        body = next((node for node in root.iter() if local_name(node.tag) == "body"), root)
        _flatten_words_split_by_inline_markup(body)

        def visit(node: ET.Element, blocked: bool = False) -> None:
            blocked = blocked or local_name(node.tag) in skip
            if not blocked and node.text and node.text.strip():
                slots.append(TextSlot(path, node, "text", node.text))
            for child in list(node):
                visit(child, blocked)
                if not blocked and child.tail and child.tail.strip():
                    slots.append(TextSlot(path, child, "tail", child.tail))

        visit(body)
        return slots, tree

    def collect_text_slots(self) -> list[TextSlot]:
        return self.load_text_slots()[0]

    def write_slot_documents(self, document_roots: dict[Path, ET.ElementTree]) -> None:
        for path, tree in document_roots.items():
            tree.write(path, encoding="utf-8", xml_declaration=True)

    def scan_terms(self, limit: int = 160) -> list[dict]:
        counts: dict[str, int] = {}
        examples: dict[str, list[str]] = {}

        def add_example(term: str, excerpt: str, maximum: int = 3) -> None:
            values = examples.setdefault(term, [])
            if excerpt and excerpt not in values and len(values) < maximum:
                values.append(excerpt)
        # Hyphenated romanizations must be consumed as a whole. The old
        # pattern truncated Kim Mi-young to Kim Mi and Lee Ju-hyeon to Lee Ju.
        capitalized = r"[A-Z][A-Za-z]*(?:[-’'][A-Za-z]+)*"
        patterns = [
            re.compile(rf"\b{capitalized}(?:\s+{capitalized}){{1,3}}\b"),
            re.compile(r"\b[A-Z][a-z]+[A-Z][A-Za-z]*\b"),
            re.compile(r"\b[A-Z]{2,}(?:[-!?.]+)?\b"),
        ]
        for path in self.spine_paths():
            slots, _ = self.load_document_slots(path)
            slot_texts = [re.sub(r"\s+", " ", slot.original).strip() for slot in slots]
            for slot_index, slot in enumerate(slots):
                excerpt = slot_texts[slot_index]
                nearby = " ".join(
                    value for value in slot_texts[max(0, slot_index - 1):slot_index + 2] if value
                )[:700]
                honorifics = extract_honorific_terms(slot.original)
                honorific_keys = {value.casefold() for value in honorifics}
                for pattern in patterns:
                    for match in pattern.findall(slot.original):
                        term = match.strip(" .,!?:;\"'“”‘’")
                        term = re.sub(r"(?:['’]s)$", "", term, flags=re.I)
                        repeated = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+", term)
                        if len(repeated) >= 2 and len({word.casefold() for word in repeated}) == 1:
                            term = repeated[0]
                        if len(term) > 1 and term.casefold() not in honorific_keys:
                            counts[term] = counts.get(term, 0) + 1
                            role_context = contains_honorific(term) or any(
                                re.search(rf"\b{re.escape(role)}\b", term, re.I)
                                for role in ROLE_TRANSLATIONS
                            )
                            add_example(
                                term, nearby if role_context else excerpt[:260],
                                5 if role_context else 3,
                            )
                for honorific in honorifics:
                    counts[honorific] = counts.get(honorific, 0) + 1
                    add_example(honorific, nearby, 5)
        ranked = sorted(counts.items(), key=lambda pair: (
            0 if is_contextual_role_honorific(pair[0]) else
            1 if is_honorific_term(pair[0]) else 2,
            -pair[1], pair[0].lower(),
        ))[:limit]
        return [self._classify_term(term, count, examples.get(term, [])) for term, count in ranked]

    @staticmethod
    def _classify_term(term: str, count: int, examples: list[str]) -> dict:
        lower = term.lower()
        words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:[-’'][A-Za-zÀ-ÖØ-öø-ÿ]+)*", term)
        first_word = words[0].split("'", 1)[0].casefold() if words else ""
        false_sentence_fragment = (
            first_word in FALSE_CANDIDATE_LEADERS
            or any(word.casefold() in {"i", "i'm", "i'll", "i'd", "i've"} for word in words)
        ) and lower not in {"team leader", "the team leader"}
        matched_role = next((role for role in sorted(ROLE_TRANSLATIONS, key=len, reverse=True) if re.search(rf"\b{re.escape(role.lower())}\b", lower)), None)
        contextual_effect = lower in CONTEXTUAL_EFFECT_WORDS
        generic_phrase = lower in GENERIC_TRANSLATABLE_PHRASES
        romanized_effect = any(word.casefold() in ROMANIZED_EFFECT_ROOTS for word in words)
        repeated_effect = any(re.search(
            rf"(?<![A-Za-z]){re.escape(term)}(?:\s+{re.escape(term)})+(?![A-Za-z])",
            example,
            re.I,
        ) for example in examples)
        contextual_honorific = is_contextual_role_honorific(term)
        prefixed_honorific = parse_prefixed_role_honorific(term) is not None
        english_honorific = english_honorific_base(term)
        contextual_generic_role = lower in {"team leader", "the team leader"}
        stutter_honorific_fragment = is_stutter_honorific_fragment(term, examples)
        if false_sentence_fragment:
            suggestion, kind, recommended = "", "noise", False
            reason = "Fragmento de oración, no nombre ni término de glosario."
        elif stutter_honorific_fragment:
            suggestion, kind, recommended = "", "noise", False
            reason = "Fragmento extraído de un tartamudeo; no es un tratamiento independiente."
        elif contextual_generic_role:
            suggestion, kind, recommended = "Líder de equipo", "title", False
            reason = "Cargo recurrente; Gemini debe confirmar por contexto si necesita artículo y género."
        elif prefixed_honorific:
            suggestion = translate_prefixed_role_honorific(term) or term
            kind, recommended = "title", suggestion != term
            reason = "Cargo completo traducido sin recortar el nombre ni el honorífico."
        elif contextual_honorific:
            suggestion = translate_contextual_role_honorific(term) or term
            kind, recommended = "title", False
            reason = "Tratamiento compuesto que exige contexto y reordenamiento completo en español."
        elif english_honorific:
            suggestion = translate_english_honorific_base(term) or term
            kind = "honorific" if suggestion.casefold() == term.casefold() else "title"
            recommended = not is_context_sensitive_honorific(term)
            reason = (
                "Cargo con honorífico cuyo significado o género depende del contexto."
                if is_context_sensitive_honorific(term)
                else "Base inglesa traducible con el honorífico asiático conservado."
            )
        elif is_honorific_term(term):
            suggestion, kind = term, "honorific"
            recommended = count >= 2 or term.casefold() in STANDALONE_HONORIFICS
            reason = (
                "Honorífico asiático recurrente; conviene conservarlo."
                if recommended
                else "Tratamiento desconocido que aparece una sola vez; requiere revisión."
            )
        elif contains_honorific(term):
            suggestion, kind, recommended = term, "name", False
            reason = "Contiene un honorífico ya detectado por separado; no se protege la frase completa."
        elif contextual_effect or repeated_effect or romanized_effect:
            suggestion, kind, recommended = term, "effect", False
            reason = "Puede ser efecto o verbo inglés; la protección de sonidos lo resuelve por contexto."
        elif generic_phrase:
            suggestion, kind, recommended = term, "noise", False
            reason = "Expresión común que el motor puede traducir sin fijarla globalmente."
        elif matched_role:
            translated = ROLE_TRANSLATIONS[matched_role]
            role_match = re.search(rf"\b{re.escape(matched_role)}\b", term, re.I)
            assert role_match is not None
            before = term[:role_match.start()].strip()
            after = term[role_match.end():].strip()
            suggestion = (
                f"{translated} {before}" if before and not after
                else re.sub(re.escape(matched_role), translated, term, count=1, flags=re.I)
            )
            kind = "title"
            remainder = f"{before} {after}".strip()
            remainder_words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+", remainder)
            named_remainder = bool(remainder_words) and all(
                word.casefold() not in FALSE_CANDIDATE_LEADERS for word in remainder_words
            )
            worldbuilding_role = matched_role in {
                "Mage Tower Lord", "Tower Lord", "City Lord", "Sect Master", "Sect Leader",
            }
            recommended = count >= 2 and (named_remainder or worldbuilding_role)
            reason = "Contiene un título o cargo; conviene traducirlo, no protegerlo completo."
        elif re.fullmatch(r"[A-Z]{2,}", term):
            suggestion, kind, recommended = term, "name", False
            reason = "Sigla posible; se muestra para revisión, pero normalmente Google ya la conserva."
        elif re.search(r"[a-z][A-Z]", term):
            suggestion, kind, recommended = term, "name", count >= 2
            reason = "Nombre creativo con mayúsculas internas que el traductor podría separar."
        else:
            suggestion, kind, recommended = term, "name", False
            reason = "Posible nombre propio recurrente; revisar antes de protegerlo."
        return {
            "term": term, "count": count, "kind": kind,
            "suggestion": suggestion, "reason": reason, "examples": examples,
            "recommended": recommended,
            "requires_reordering": contextual_honorific,
            "preserve_full_phrase": prefixed_honorific,
            "context_sensitive": bool(
                contextual_generic_role or contextual_honorific or is_context_sensitive_honorific(term)
            ),
        }

    def mark_spanish(self) -> None:
        language = self.opf_root.find(f".//{{{DC_NS}}}language")
        if language is None:
            metadata = self.opf_root.find(f"{{{OPF_NS}}}metadata")
            if metadata is not None:
                language = ET.SubElement(metadata, f"{{{DC_NS}}}language")
        if language is not None:
            language.text = "es"
        self.save_package()

    def refresh_navigation_labels(self) -> None:
        entries = []
        for index, path in enumerate(self.spine_paths(), 1):
            if self._is_cover_document(path):
                continue
            entries.append((path.name, self._document_title(path) or f"Capítulo {index}"))
        self._rebuild_navigation(entries, self.title)

    def _is_cover_document(self, path: Path) -> bool:
        item = next((
            item for item in self.manifest.values()
            if self.resolve_item(item) == path
        ), None)
        hints = " ".join((
            path.stem,
            item.id if item else "",
            item.href if item else "",
            item.properties if item else "",
        )).casefold()
        if re.search(r"(?:^|[\W_])(?:cover|portada)(?:[\W_]|$)", hints):
            return True
        title = self._document_title(path).strip().casefold()
        return title in {"cover", "portada", "front cover", "cubierta"}

    def apply_chapter_titles(self, title_by_path: dict) -> None:
        """Apply user-edited labels to headings and both EPUB navigation formats."""
        normalized: dict[str, str] = {}
        for raw_path, raw_title in title_by_path.items():
            title = re.sub(r"\s+", " ", str(raw_title)).strip()[:240]
            if title:
                normalized[PurePosixPath(str(raw_path)).as_posix()] = title
        if not normalized:
            return self.refresh_navigation_labels()

        labels = self.chapter_labels()
        entries: list[tuple[str, str]] = []
        previous_edited_title: str | None = None
        for path in self.spine_paths():
            relative = path.relative_to(self.book_dir).as_posix()
            edited_title = normalized.get(relative)
            title = edited_title or labels[str(path)]
            entries.append((path.name, title))
            if edited_title:
                if edited_title != previous_edited_title:
                    self._set_document_title(path, edited_title)
                previous_edited_title = edited_title
            else:
                previous_edited_title = None
        self._rebuild_navigation(entries, self.title)
        self.save_package()

    @staticmethod
    def _set_document_title(path: Path, title: str) -> None:
        try:
            tree = ET.parse(path)
        except (ET.ParseError, OSError):
            return
        root = tree.getroot()
        heading_updated = False
        for node in root.iter():
            name = local_name(node.tag)
            if name == "title":
                node.text = title
            elif not heading_updated and name in {"h1", "h2"}:
                for child in list(node):
                    node.remove(child)
                node.text = title
                heading_updated = True
        tree.write(path, encoding="utf-8", xml_declaration=True)


class TranslationCache:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute("CREATE TABLE IF NOT EXISTS translations (cache_key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.connection.commit()

    def get(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM translations WHERE cache_key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, value: str) -> None:
        self.connection.execute("INSERT OR REPLACE INTO translations(cache_key, value) VALUES (?, ?)", (key, value))

    def flush(self) -> None:
        self.connection.commit()

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()
