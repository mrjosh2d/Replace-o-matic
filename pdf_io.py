"""Read and redact PDFs with PyMuPDF (optional dependency).

PyMuPDF is licensed under the AGPL (or commercially from Artifex). It is not
required: without it the command-line tool reads PDFs with pypdf and writes
plain text. With it, a PDF comes back as a PDF with the sensitive text removed
from the page content (not just covered) and the placeholder printed in its
place.

Text is read paragraph by paragraph: the words of one block are joined with
single spaces, so a name that wraps onto the next line is still one string.
"""

from __future__ import annotations

from typing import Callable

Span = tuple[int, int, str]


def available() -> bool:
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        return False
    return True


def _page_text(page) -> tuple[str, list, list]:
    """Page text, the word each character belongs to (or None), and the words.
    A word is (x0, y0, x1, y1, text, block, line, number)."""
    words = page.get_text("words")
    chars: list[str] = []
    owner: list = []
    last_block = None
    for index, word in enumerate(words):
        if chars:
            chars.append(" " if word[5] == last_block else "\n")
            owner.append(None)
        last_block = word[5]
        chars.extend(word[4])
        owner.extend([index] * len(word[4]))
    return "".join(chars), owner, words


def read_pdf(path: str) -> str:
    import pymupdf

    with pymupdf.open(path) as document:
        return "\n\n".join(_page_text(page)[0] for page in document)


def redact_pdf(source: str, destination: str, spans_for: Callable[[str], list[Span]]) -> int:
    """Write ``source`` to ``destination`` with every span from
    ``spans_for(page_text)`` removed and its replacement printed there.
    Document metadata (author, title, XMP) is cleared. Returns the span count."""
    import pymupdf

    total = 0
    with pymupdf.open(source) as document:
        for page in document:
            text, owner, words = _page_text(page)
            labels = []  # (box to print in, text to print)
            for start, end, replacement in spans_for(text):
                covered = sorted({o for o in owner[start:end] if o is not None})
                if not covered:
                    continue
                total += 1
                # Characters of the first and last word that lie outside the span
                # ("Smith's" -> the "'s") are printed back around the placeholder.
                first_start = owner.index(covered[0])
                last_end = len(owner) - 1 - owner[::-1].index(covered[-1])
                label = text[first_start:start] + replacement + text[end : last_end + 1]

                lines: dict[tuple, pymupdf.Rect] = {}  # one box per line the span touches
                for index in covered:
                    word = words[index]
                    key = (word[5], word[6])
                    rect = pymupdf.Rect(word[:4])
                    lines[key] = lines[key] | rect if key in lines else rect
                for rect in lines.values():
                    # Trimmed vertically so the box cannot touch the lines above and below.
                    trim = rect.height * 0.2
                    # No fill: the text is deleted, so there is nothing to cover, and a
                    # filled box would hide neighbouring words (see below).
                    page.add_redact_annot(
                        pymupdf.Rect(rect.x0, rect.y0 + trim, rect.x1, rect.y1 - trim), fill=False
                    )
                labels.append((next(iter(lines.values())), label))

            # Removes the text under every box from the page content itself.
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
            # On justified lines MuPDF closes up part of the gap, so the words that
            # follow sit a little further left than before. Fit each placeholder
            # into the space that is really free now.
            after = page.get_text("words")
            for rect, label in labels:
                same_line = [
                    w[0] for w in after if w[0] > rect.x0 + 1 and w[1] < rect.y1 - 1 and w[3] > rect.y0 + 1
                ]
                width = min([rect.width] + [x - rect.x0 - 1.5 for x in same_line])
                size = min(11.0, rect.height * 0.8)
                while size > 2.5 and pymupdf.get_text_length(label, "helv", size) > width:
                    size -= 0.25  # a placeholder longer than the space is printed smaller
                page.insert_text(
                    (rect.x0, rect.y1 - rect.height * 0.25), label, fontname="helv", fontsize=size
                )
        document.set_metadata({})
        document.del_xml_metadata()
        document.save(destination, garbage=4, deflate=True)
    return total
