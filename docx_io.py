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
