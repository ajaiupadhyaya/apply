"""A resume or a letter, as plain text — with what must never leave the machine taken out.

The text goes two places: data/context/ (which every letter request sends to
the API) and the one drafting request. Phone and street address are withheld
from the API by design, so they are removed here, before either.

The .docx parser is the standard library's. ElementTree on Python 3.11+ does
not resolve external entities, and the bundled expat caps entity expansion;
the input is the user's own resume on their own machine, and a size cap
refuses anything that is plainly not one.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_DOCX_XML = 20_000_000


class Unreadable(ValueError):
    """Not a document we can read; the message says which kinds are."""


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx(path: Path) -> str:
    """Body text only; headers and footers are not read."""
    try:
        with zipfile.ZipFile(path) as z:
            if z.getinfo("word/document.xml").file_size > MAX_DOCX_XML:
                raise Unreadable(f"{path.name}: that .docx is too large to be a resume")
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as err:
        raise Unreadable(f"{path.name}: that does not look like a Word document. "
                         "Save it as PDF, DOCX, TXT or MD and try again.") from err
    lines = []
    for para in root.iter(f"{_W}p"):
        bits = []
        for node in para.iter():
            if node.tag == f"{_W}t" and node.text:
                bits.append(node.text)
            elif node.tag == f"{_W}tab":
                bits.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                bits.append("\n")
        line = "".join(bits).rstrip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _pdf(path: Path) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        pages = [(page.extract_text() or "").strip() for page in PdfReader(str(path)).pages]
    except PyPdfError as err:
        raise Unreadable(f"{path.name}: that PDF could not be read. "
                         "Save it as PDF, DOCX, TXT or MD and try again.") from err
    return "\n\n".join(p for p in pages if p)


def read_document(path: Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _docx(path)
    if suffix == ".pdf":
        return _pdf(path)
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace").strip()
    raise Unreadable(f"{path.name}: save it as PDF, DOCX, TXT or MD and try again.")


_PHONE = re.compile(r"(?<![\d-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?![\d-])")
_INTL = re.compile(r"(?<![\w+])\+\d{1,3}(?:[\s.-]\d{2,5}){2,5}(?!\d)")
_SSN = re.compile(r"(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)")
_STREET = re.compile(
    r"(?<![\d.$%-])\b\d{1,6}\s+(?:[A-Za-z0-9][A-Za-z0-9']*\.?\s+){1,4}?"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive|Ct|Court|Way|Pl|Place|"
    r"Ter|Terrace|Pkwy|Parkway|Cir|Circle)\b"
    r"(?:,\s*[A-Za-z][A-Za-z .]*?,\s*[A-Za-z]{2}\b(?:\s+\d{5}(?:-\d{4})?)?)?", re.I)
_BOX = re.compile(r"\bP\.?\s?O\.?\s*Box\s+\d+\b", re.I)
_UNIT = re.compile(r"\b(?:Apt|Apartment|Unit|Suite|Ste)\.?\s+#?[A-Za-z]?\d+[A-Za-z]?\b|(?<!\w)#\d+[A-Za-z]?\b", re.I)
FORBIDDEN = re.compile(r"(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)|\bssn\b|social\s+security|\bd\.?o\.?b\b|"
                       r"date\s+of\s+birth|birth\s?date|birthday", re.I)


def contains_forbidden(text: str) -> bool:
    return bool(FORBIDDEN.search(text or ""))


def redact(text: str, *, phone: str | None = None, address: str | None = None) -> str:
    out = text
    if address:
        out = out.replace(address, "[address]")
    for pattern in (_STREET, _BOX, _UNIT):
        out = pattern.sub("[address]", out)
    out = _SSN.sub("[removed]", out)
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) >= 7:
        out = re.sub(r"(?<!\d)\+?\(?" + r"[\s().+-]*".join(digits) + r"(?!\d)", "[phone]", out)
    out = _INTL.sub("[phone]", out)
    return _PHONE.sub("[phone]", out)
