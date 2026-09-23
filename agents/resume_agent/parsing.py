"""Turn PDF / DOCX / TXT files into lines with provenance (page + character offsets).

Every fact extracted later points back to these offsets, so the user can always see where a claim came from.
"""

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024
SUPPORTED = {".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".md": "md"}

_CID = re.compile(r"\(cid:\d+\)")
_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", " ": " ", "​": ""}


class UnsupportedDocument(ValueError):
    pass


@dataclass
class Line:
    text: str
    page: int
    start: int  # offset into ParsedDocument.text
    end: int


@dataclass
class ParsedDocument:
    format: str
    sha256: str
    text: str
    lines: list[Line]
    pages: int
    layout: str = "single_column"
    warnings: list[str] = field(default_factory=list)
    column_breaks: set[int] = field(default_factory=set)  # indexes into `lines` where a new column starts


COLUMN_BREAK = "\f"  # form feed: never produced by text extraction


def _clean(s: str) -> str:
    s = _CID.sub("", s)
    for k, v in _LIGATURES.items():
        s = s.replace(k, v)
    return re.sub(r"[ \t]+", " ", s).strip()


def _assemble(fmt: str, digest: str, pages: list[list[str]], layout: str, warnings: list[str]) -> ParsedDocument:
    lines: list[Line] = []
    buf: list[str] = []
    breaks: set[int] = set()
    offset = 0
    for page_no, page_lines in enumerate(pages, start=1):
        for raw in page_lines:
            if raw == COLUMN_BREAK:
                breaks.add(len(lines))
                continue
            text = _clean(raw)
            if not text or set(text) <= set("=-_*~ "):  # drop empty and pure decoration lines
                continue
            lines.append(Line(text, page_no, offset, offset + len(text)))
            buf.append(text)
            offset += len(text) + 1
    return ParsedDocument(fmt, digest, "\n".join(buf), lines, len(pages), layout, warnings, breaks)


# ---------------------------------------------------------------- PDF


def _pdf_page_lines(page) -> tuple[list[str], bool]:
    """Extract one page; split into header band + two columns when a vertical gutter is detected."""
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    width, height = page.width, page.height
    if len(words) < 40:
        return (page.extract_text() or "").splitlines(), False

    # Gutter = centre of the widest run of x positions crossed by the fewest words.
    xs = range(int(width * 0.2), int(width * 0.5), 2)
    crosses = [sum(1 for w in words if w["x0"] < x < w["x1"]) for x in xs]
    lowest = min(crosses)
    best_run: list[int] = []
    run: list[int] = []
    for x, c in zip(xs, crosses, strict=True):
        run = run + [x] if c == lowest else []
        if len(run) > len(best_run):
            best_run = run
    best_x = best_run[len(best_run) // 2]
    left = [w for w in words if w["x1"] <= best_x]
    right = [w for w in words if w["x0"] >= best_x]
    crossing = [w for w in words if w["x0"] < best_x < w["x1"]]
    two_col = (
        len(left) >= 0.08 * len(words)
        and len(right) >= 0.08 * len(words)
        and len({round(w["top"]) for w in left}) >= 8
        and len({round(w["top"]) for w in right}) >= 8
        and all(w["bottom"] <= height * 0.25 for w in crossing)  # only a title band may span both columns
    )
    if not two_col:
        return (page.extract_text() or "").splitlines(), False

    header_bottom = max((w["bottom"] for w in crossing), default=0) + 1
    parts: list[str] = []
    if header_bottom > 1:
        parts += (page.crop((0, 0, width, header_bottom)).extract_text() or "").splitlines()
    # Main column (usually the wider one) first, so sections read in natural order.
    left_box, right_box = (0, header_bottom, best_x, height), (best_x, header_bottom, width, height)
    boxes = [right_box, left_box] if (width - best_x) > best_x else [left_box, right_box]
    for box in boxes:
        parts.append(COLUMN_BREAK)
        parts += (page.crop(box).extract_text() or "").splitlines()
    return parts, True


def _parse_pdf(data: bytes, digest: str) -> ParsedDocument:
    import io

    import pdfplumber

    pages: list[list[str]] = []
    two_col_any = False
    warnings: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            lines, two_col = _pdf_page_lines(page)
            two_col_any |= two_col
            pages.append(lines)
    doc = _assemble("pdf", digest, pages, "two_column" if two_col_any else "single_column", warnings)
    if len(doc.text) < 200:
        doc.warnings.append("Very little text extracted; the PDF may be scanned (image-only). OCR is not enabled.")
    if two_col_any:
        doc.warnings.append("Two-column layout detected; columns were read separately. ATS parsers often fail here.")
    return doc


# ---------------------------------------------------------------- DOCX


def _parse_docx(data: bytes, digest: str) -> ParsedDocument:
    import io

    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if sum(i.file_size for i in zf.infolist()) > MAX_DOCX_UNCOMPRESSED:
            raise UnsupportedDocument("DOCX expands to more than 50 MB; refusing to parse")
    document = docx.Document(io.BytesIO(data))
    lines: list[str] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, document)
            text = p.text
            is_list = p.style is not None and "list" in (p.style.name or "").lower()
            has_num = child.pPr is not None and child.pPr.numPr is not None
            if text.strip() and (is_list or has_num) and not text.lstrip().startswith(("•", "-", "*")):
                text = "• " + text
            lines.extend(text.splitlines() or [""])
        elif tag == "tbl":
            for row in Table(child, document).rows:
                seen: set[int] = set()
                for cell in row.cells:  # merged cells repeat; skip duplicates
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    lines.extend(cell.text.splitlines())
    return _assemble("docx", digest, [lines], "single_column", [])


# ---------------------------------------------------------------- entry point


def parse_bytes(data: bytes, filename: str) -> ParsedDocument:
    if len(data) > MAX_BYTES:
        raise UnsupportedDocument("file larger than 10 MB")
    ext = Path(filename).suffix.lower()
    fmt = SUPPORTED.get(ext)
    if fmt is None:
        raise UnsupportedDocument(f"unsupported file type {ext!r}; use PDF, DOCX, TXT or MD")
    digest = hashlib.sha256(data).hexdigest()
    if fmt == "pdf":
        if not data.startswith(b"%PDF-"):
            raise UnsupportedDocument("file does not look like a PDF")
        return _parse_pdf(data, digest)
    if fmt == "docx":
        if not data.startswith(b"PK\x03\x04"):
            raise UnsupportedDocument("file does not look like a DOCX")
        return _parse_docx(data, digest)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnsupportedDocument("text file is not valid UTF-8") from exc
    return _assemble(fmt, digest, [text.splitlines()], "single_column", [])


def parse_file(path: str | Path) -> ParsedDocument:
    p = Path(path)
    return parse_bytes(p.read_bytes(), p.name)
