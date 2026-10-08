from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from apply.setup import extract

DOCX_XML = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Jordan Reyes</w:t></w:r></w:p>'
            '<w:p><w:r><w:t xml:space="preserve">Analyst — </w:t></w:r><w:r><w:t>Acme Capital</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Tab</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>bed</w:t></w:r></w:p></w:body></w:document>')


def make_docx(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", DOCX_XML)
    return path


def test_docx_paragraphs_become_lines(tmp_path):
    assert extract.read_document(make_docx(tmp_path / "r.docx")).splitlines() == [
        "Jordan Reyes", "Analyst — Acme Capital", "Tab\tbed"]


def test_txt_and_md(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("# Me\nThings — done.", encoding="utf-8")
    assert extract.read_document(p) == "# Me\nThings — done."


def test_pdf_goes_through_pypdf(tmp_path, monkeypatch):
    class Page:
        def extract_text(self):
            return "Page one"

    class Reader:
        def __init__(self, path):
            self.pages = [Page(), Page()]

    monkeypatch.setattr("pypdf.PdfReader", Reader)
    p = tmp_path / "r.pdf"
    p.write_bytes(b"%PDF-1.4")
    assert extract.read_document(p) == "Page one\n\nPage one"


def test_unknown_type_says_what_to_do(tmp_path):
    p = tmp_path / "r.pages"
    p.write_bytes(b"x")
    with pytest.raises(extract.Unreadable, match="PDF, DOCX"):
        extract.read_document(p)


def test_oversized_docx_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "MAX_DOCX_XML", 10)
    with pytest.raises(extract.Unreadable, match="too large"):
        extract.read_document(make_docx(tmp_path / "r.docx"))


def test_redact_phone_address_and_ssn():
    text = ("Jordan Reyes · (804) 555-0123 · +1 804.555.0199\n"
            "123 Main Street, Springfield, VA 23220\nSSN 123-45-6789\nGPA 3.9, 2025-08, 40% faster")
    out = extract.redact(text, phone="(804) 555-0123", address="123 Main Street, Springfield, VA 23220")
    assert "555" not in out and "Main Street" not in out and "6789" not in out
    assert "GPA 3.9, 2025-08, 40% faster" in out


def test_forbidden_answers():
    assert extract.contains_forbidden("my ssn is 123-45-6789")
    assert extract.contains_forbidden("DOB: 01/02/2003")
    assert extract.contains_forbidden("date of birth 2003-01-02")
    assert not extract.contains_forbidden("graduating 2027-05; 3 years of Python")
