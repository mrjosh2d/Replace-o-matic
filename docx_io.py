"""Read and rewrite .docx files without disturbing their formatting.

A .docx is a zip of XML parts. Text lives in the body, headers, footers,
footnotes, endnotes and comments, and within a paragraph it is chopped into
"runs" wherever the formatting changes, so a single name can be spread over
several XML nodes. This module presents each part as plain text, takes a list
of (start, end, replacement) edits against that text, and writes them back into
the original nodes. Everything else in the file is copied untouched.
"""

from __future__ import annotations

import re
import zipfile
from typing import Callable

from lxml import etree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# Parts that carry document text, in reading order.
_TEXT_PARTS = re.compile(r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$")
_ORDER = ["document", "header", "footer", "footnotes", "endnotes", "comments"]
_TEXT_TAGS = (W + "t", W + "delText")  # delText: text deleted under Track Changes, still in the file
_BREAK_TAGS = {W + "tab": "\t", W + "br": "\n", W + "cr": "\n"}

Edit = tuple[int, int, str]


def _text_parts(archive: zipfile.ZipFile) -> list[str]:
    def order(name: str):
        kind, number = re.match(r"word/([a-z]+)(\d*)\.xml", name).groups()
        return (_ORDER.index(kind), int(number or 0))

    return sorted((n for n in archive.namelist() if _TEXT_PARTS.match(n)), key=order)


def _paragraph_of(node):
    while node is not None and node.tag != W + "p":
        node = node.getparent()
    return node


def _part_text(root) -> tuple[str, list]:
    """A part's text, and for every character the (node, index) it came from.
    Tabs, line breaks and paragraph ends map to None: they are structure, not text."""
    chars: list[str] = []
    origin: list = []
    last_paragraph = None
    for node in root.iter(*_TEXT_TAGS, *_BREAK_TAGS):
        paragraph = _paragraph_of(node)
        if chars and paragraph is not last_paragraph:
            chars.append("\n")
            origin.append(None)
        last_paragraph = paragraph
        if node.tag in _BREAK_TAGS:
            chars.append(_BREAK_TAGS[node.tag])
            origin.append(None)
        else:
            for i, ch in enumerate(node.text or ""):
                chars.append(ch)
                origin.append((node, i))
    return "".join(chars), origin


def _apply_edits(origin: list, edits: list[Edit]) -> int:
    """Write edits into the XML nodes. Returns how many were applied."""
    applied = 0
    for start, end, replacement in sorted(edits, reverse=True):  # back to front: indexes stay valid
        covered = [o for o in origin[start:end] if o is not None]
        if not covered:
            continue
        ranges: dict = {}  # node -> [first index, last index] within the span
        for node, i in covered:
            lo_hi = ranges.setdefault(node, [i, i])
            lo_hi[0], lo_hi[1] = min(lo_hi[0], i), max(lo_hi[1], i)
        first_node = covered[0][0]
        for node, (lo, hi) in ranges.items():
            insert = replacement if node is first_node else ""
            node.text = node.text[:lo] + insert + node.text[hi + 1 :]
            node.set(XML_SPACE, "preserve")
        applied += 1
    return applied


def read_docx(path: str) -> str:
    """All text in the file: body, then headers, footers, footnotes, endnotes, comments."""
    with zipfile.ZipFile(path) as archive:
        texts = [_part_text(etree.fromstring(archive.read(name)))[0] for name in _text_parts(archive)]
    return "\n\n".join(t for t in texts if t.strip())


def _scrub_metadata(name: str, data: bytes) -> bytes:
    """Blank the author, company and reviewer names Word stores outside the text."""
    if name in ("docProps/core.xml", "docProps/app.xml"):
        root = etree.fromstring(data)
        for node in root.iter():
            if etree.QName(node).localname in ("creator", "lastModifiedBy", "Company", "Manager"):
                node.text = ""
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    return data


def rewrite_docx(
    source: str, destination: str, edits_for: Callable[[str], list[Edit]], scrub: bool = False
) -> int:
    """Copy ``source`` to ``destination``, applying ``edits_for(part_text)`` to each
    text part. With ``scrub``, author metadata and comment/revision author names
    are blanked too. Returns the number of edits applied."""
    total = 0
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as out:
        text_parts = set(_text_parts(archive))
        for item in archive.infolist():
            data = archive.read(item.filename)
            if item.filename in text_parts:
                root = etree.fromstring(data)
                text, origin = _part_text(root)
                changed = _apply_edits(origin, edits_for(text))
                total += changed
                if scrub:
                    for node in root.iter():
                        for attribute in (W + "author", W + "initials"):
                            if attribute in node.attrib:
                                node.set(attribute, "Author" if attribute.endswith("author") else "A")
                                changed += 1
                if changed:  # untouched parts are copied byte for byte
                    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            elif scrub:
                data = _scrub_metadata(item.filename, data)
            out.writestr(item, data)
    return total


# --------------------------------------------------------------------------
# Writing a simple .docx from scratch (used for the key document)
# --------------------------------------------------------------------------

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType='
    '"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
    ' Target="word/document.xml"/></Relationships>'
)


def write_table_docx(path: str, title: str, notes: list[str], header: list[str], rows: list[list]) -> None:
    """A landscape .docx with a title, a few note lines and one bordered table."""
    w = W[1:-1]

    def run(text, bold=False, size=None, color=None):
        r = etree.Element(W + "r")
        if bold or size or color:
            props = etree.SubElement(r, W + "rPr")
            if bold:
                etree.SubElement(props, W + "b")
            if color:
                etree.SubElement(props, W + "color").set(W + "val", color)
            if size:
                etree.SubElement(props, W + "sz").set(W + "val", str(size * 2))
        t = etree.SubElement(r, W + "t")
        t.text = str(text)
        t.set(XML_SPACE, "preserve")
        return r

    def paragraph(text, **style):
        p = etree.Element(W + "p")
        p.append(run(text, **style))
        return p

    document = etree.Element(W + "document", nsmap={"w": w})
    body = etree.SubElement(document, W + "body")
    body.append(paragraph(title, bold=True, size=16))
    for i, note in enumerate(notes):
        body.append(paragraph(note, bold=i == 0, color="C00000" if i == 0 else None))
    body.append(paragraph(""))

    table = etree.SubElement(body, W + "tbl")
    props = etree.SubElement(table, W + "tblPr")
    etree.SubElement(props, W + "tblW").attrib.update({W + "w": "5000", W + "type": "pct"})
    borders = etree.SubElement(props, W + "tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        etree.SubElement(borders, W + side).attrib.update(
            {W + "val": "single", W + "sz": "4", W + "space": "0", W + "color": "808080"}
        )
    for n, cells in enumerate([header] + rows):
        tr = etree.SubElement(table, W + "tr")
        if n == 0:
            etree.SubElement(etree.SubElement(tr, W + "trPr"), W + "tblHeader")  # repeat on each page
        for cell in cells:
            tc = etree.SubElement(tr, W + "tc")
            tc.append(paragraph(cell, bold=n == 0))

    section = etree.SubElement(body, W + "sectPr")
    etree.SubElement(section, W + "pgSz").attrib.update(
        {W + "w": "15840", W + "h": "12240", W + "orient": "landscape"}
    )
    etree.SubElement(section, W + "pgMar").attrib.update(
        {W + k: "1080" for k in ("top", "right", "bottom", "left")} | {W + "header": "720", W + "footer": "720", W + "gutter": "0"}
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("[Content_Types].xml", _CONTENT_TYPES)
        out.writestr("_rels/.rels", _RELS)
        out.writestr("word/document.xml", etree.tostring(document, xml_declaration=True, encoding="UTF-8", standalone=True))
