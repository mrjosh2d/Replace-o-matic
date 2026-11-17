"""Write two invented test documents for the offline check of a packaged build.

    python packaging/windows/make_test_documents.py OUTPUT_FOLDER

Writes OUTPUT_FOLDER/invented-letter.docx and OUTPUT_FOLDER/invented-memo.pdf.
Every name, company, address and number below is made up. The .pdf needs
PyMuPDF (requirements-pdf.txt).
"""

import os
import sys
import zipfile
from xml.sax.saxutils import escape

LETTER = [
    "Re: Estate of Marjorie Q. Fenwhistle",
    "Dear Mr. Okonkwo-Hale,",
    "Our client, Dorian P. Velasquez-Trent, asked us to write about the trust held "
    "at Bramblecote Savings Bank, account 4417-2290-8813.",
    "Mr. Velasquez-Trent lives at 88 Larkspur Lane, Wexmoor, OH 44987, and can be "
    "reached at 555-0142 or dorian.vt@example.com.",
    "Velasquez-Trent and Fenwhistle Holdings LLC will sign the agreement on 3 March 2026.",
    "Sincerely, Imogen R. Castellano",
]

MEMO = (
    "MEMORANDUM\n\n"
    "To: Priya N. Abernathy-Low\n"
    "From: Thaddeus K. Moorcroft\n\n"
    "Quillon Freight Systems Inc. hired Moorcroft on 12 January 2026. His Social "
    "Security number on file is 900-55-1234. Ms. Abernathy-Low will review the "
    "lease for 410 Juniper Court, Halvering, OH 44911 with Quillon's counsel."
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/></Relationships>'
)


def write_docx(path: str) -> None:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{escape(p)}</w:t></w:r></w:p>' for p in LETTER)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", RELS)
        archive.writestr("word/document.xml", document)


def write_pdf(path: str) -> None:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), MEMO, fontsize=11, fontname="helv")
    document.save(path)
    document.close()


def main() -> None:
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(folder, exist_ok=True)
    write_docx(os.path.join(folder, "invented-letter.docx"))
    write_pdf(os.path.join(folder, "invented-memo.pdf"))
    print(f"wrote invented-letter.docx and invented-memo.pdf to {folder}")


if __name__ == "__main__":
    main()
