"""The Replace-o-matic workflow, with no terminal and no window in it.

Both front ends call this module: ``sanitizer_cli.py`` today, the desktop
window next (see ``GUI_PLAN.md``). Nothing here prints, prompts or imports a
GUI toolkit. Failures a user can act on are raised as :class:`ServiceError`
with a message fit to show them.

    vault = open_matter("matter.vault", passphrase)
    scan = scan_document("contract.docx", vault, progress=..., cancelled=...)
    # ... a person reviews scan.items ...
    result = commit(scan, accepted, declined, reviewed=True,
                    vault_path="matter.vault", passphrase=passphrase)
"""

from __future__ import annotations

import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Iterable

import sanitizer_core as sc  # first project import: it sets the offline switches

import docx_io
import pdf_io


class ServiceError(Exception):
    """Something the user can understand and act on. The message is for them."""


@dataclass
class Item:
    """One proposed redaction: a row of the review table."""

    type: str
    value: str
    source: str  # "ner" | "regex" | "propagated" | "manual"
    times: int = 0
    entity_hint: str = ""  # the value this would be listed under as an alias, or ""


@dataclass
class Scan:
    path: str
    text: str
    vault: dict
    items: list[Item]
    already_known: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class Result:
    output_path: str
    vault: dict
    added: int
    declined: int
    replaced: int
    reviewed: bool
    residue: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class RestoreResult:
    output_path: str
    restored: int
    altered: list[str] = field(default_factory=list)  # respelled placeholders that were recognised
    unknown: list[str] = field(default_factory=list)  # placeholders this matter does not know


@dataclass
class KeyResult:
    confidential_path: str | None
    safe_path: str | None
    count: int


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------


def _read_pdf(path: str) -> str:
    if pdf_io.available():
        return pdf_io.read_pdf(path)
    from pypdf import PdfReader

    return "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def read_document(path: str) -> str:
    """Text of a .txt, .docx or .pdf file. For a .docx that is the body, headers,
    footers, footnotes, endnotes and comments. A scanned PDF has no text to extract."""
    extension = os.path.splitext(path)[1].lower()
    if extension == ".docx":
        text = docx_io.read_docx(path)
    elif extension == ".pdf":
        text = _read_pdf(path)
    else:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    if not text.strip():
        raise ServiceError(f"No text found in {path}. If it is a scanned PDF, it needs OCR first.")
    return text


def is_docx(path: str) -> bool:
    return path.lower().endswith(".docx")


def is_pdf(path: str) -> bool:
    return path.lower().endswith(".pdf")


def default_output_path(input_path: str, label: str) -> str:
    """A .docx stays a .docx (formatting kept). A PDF being sanitized stays a
    PDF when PyMuPDF is installed. Anything else becomes .txt."""
    stem = os.path.splitext(input_path)[0]
    if is_docx(input_path):
        return f"{stem}.{label}.docx"
    if is_pdf(input_path) and label == "sanitized" and pdf_io.available():
        return f"{stem}.{label}.pdf"
    return f"{stem}.{label}.txt"



def output_formats(input_path: str, label: str) -> list[str]:
    """The extensions an output can have for this input, the default first.
    Any other extension except .docx and .pdf is written as plain text."""
    if is_docx(input_path):
        return [".docx", ".txt"]
    if is_pdf(input_path) and label == "sanitized" and pdf_io.available():
        return [".pdf", ".txt"]
    return [".txt"]


_OUTPUT_LABELS = (".key-safe", ".sanitized", ".rehydrated", ".key")  # longest match first


def successor_path(path: str) -> str:
    """The first free name beside ``path`` with a number added: ``case.sanitized.docx``
    becomes ``case (2).sanitized.docx``, so the label (and .gitignore) still match."""
    stem, extension = os.path.splitext(path)
    label = next((lab for lab in _OUTPUT_LABELS if stem.endswith(lab)), "")
    stem = stem[: len(stem) - len(label)]
    number = 2
    while os.path.exists(candidate := f"{stem} ({number}){label}{extension}"):
        number += 1
    return candidate


def key_paths(document_path: str | None, vault_path: str, fmt: str = "docx") -> tuple[str, str]:
    """The default confidential and safe key paths."""
    stem = os.path.splitext(document_path or vault_path)[0]
    return f"{stem}.key.{fmt}", f"{stem}.key-safe.{fmt}"

def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def check_output_path(input_path: str, output_path: str, label: str, vault_path: str | None = None) -> str | None:
    """None if ``output_path`` is a safe place to write, else the reason it is not."""
    extension = os.path.splitext(output_path)[1].lower()
    if extension in (".docx", ".pdf") and extension not in output_formats(input_path, label):
        return f"A {extension} file cannot be written from this document. Use {' or '.join(output_formats(input_path, label))}."
    if _same_file(output_path, input_path):
        return "The output would replace the original document. Choose another name."
    if vault_path and _same_file(output_path, vault_path):
        return "The output would replace the vault file. Choose another name."
    if not os.path.isdir(os.path.dirname(os.path.abspath(output_path))):
        return f"The folder for {output_path} does not exist."
    return None

# --------------------------------------------------------------------------
# Matters (vaults)
# --------------------------------------------------------------------------


def matter_exists(path: str) -> bool:
    return os.path.exists(path)


def open_matter(path: str, passphrase: str) -> dict:
    """The vault at ``path``, or a new empty one if there is no file yet.
    Refuses a file that is not encrypted, and a wrong passphrase."""
    if not os.path.exists(path):
        return sc.new_vault()
    if not sc.is_encrypted_vault(path):
        raise ServiceError(f"{path} is not an encrypted vault. Refusing to use it.")
    try:
        return sc.load_vault(path, passphrase=passphrase)
    except sc.VaultError as error:
        raise ServiceError(str(error)) from None


# --------------------------------------------------------------------------
# Scan and review helpers
# --------------------------------------------------------------------------


def occurrences(text: str, value: str) -> list[tuple[int, int]]:
    """Every whole-word occurrence of ``value``: (start, end)."""
    if not value:
        return []
    left = r"(?<!\w)" if re.match(r"\w", value[0]) else ""
    right = r"(?!\w)" if re.match(r"\w", value[-1]) else ""
    return [(m.start(), m.end()) for m in re.finditer(left + re.escape(value) + right, text)]


def context(text: str, start: int, end: int, width: int = 45) -> str:
    """One line of surrounding text with the span marked «like this»."""
    before = text[max(0, start - width) : start]
    after = text[end : end + width]
    return " ".join(f"...{before}«{text[start:end]}»{after}...".split())


def first_context(text: str, value: str, width: int = 45) -> str:
    found = occurrences(text, value)
    if not found:
        return "(not found as a whole word in this document)"
    return context(text, *found[0], width)


def validate_edit(scan: Scan, new_text: str) -> str | None:
    """None if ``new_text`` can be redacted in this document, else why not."""
    if not new_text.strip():
        return "Enter the text to redact."
    if not occurrences(scan.text, new_text.strip()):
        return "That text does not appear in the document (check spelling and capitals)."
    return None


def make_item(scan: Scan, etype: str, value: str, source: str = "manual") -> Item:
    """An Item for text a reviewer typed in or edited."""
    return Item(etype, value, source, len(occurrences(scan.text, value)))


def scan_document(
    path: str,
    vault: dict,
    regex_only: bool = False,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Scan:
    """Read the document and propose what to redact. Changes nothing.
    Raises :class:`sanitizer_core.ScanCancelled` if ``cancelled()`` turns true."""
    text = read_document(path)
    proposal = sc.scan_text(
        text, vault, ner=False if regex_only else None, progress=progress, cancelled=cancelled
    )
    proposed = proposal["proposed"]
    known = {p: e["value"] for p, e in list(vault["mappings"].items()) + list(proposed.items())}
    items = []
    for placeholder, entry in proposed.items():
        main = f"[{entry['entity']}]"
        hint = known.get(main, "") if placeholder != main else ""
        items.append(
            Item(entry["type"], entry["value"], entry["source"], len(occurrences(text, entry["value"])), hint)
        )
    # Everything in the matter that occurs here, including items a reviewer added by hand.
    already_known = len({placeholder for _, _, placeholder in sc.find_vault_spans(text, vault)})
    return Scan(path, text, vault, items, already_known, proposal["warnings"])


def find_residue(safe_text: str, vault: dict) -> list[tuple[str, int]]:
    """Vault values that still show up in redacted text in a different letter
    case ("ACME" when the vault knows "Acme"). Exact matches cannot survive
    apply_vault, so anything listed here is a near miss worth a look."""
    residue = []
    for value in sorted({e["value"] for e in vault["mappings"].values()}):
        if len(value) < 4:
            continue
        hits = len(re.findall(r"(?<!\w)" + re.escape(value) + r"(?!\w)", safe_text, re.IGNORECASE))
        if hits:
            residue.append((value, hits))
    return residue


# --------------------------------------------------------------------------
# Commit: save the matter and write the sanitized document
# --------------------------------------------------------------------------


def _as_tuple(item) -> tuple:
    return (item.type, item.value, item.source) if isinstance(item, Item) else tuple(item)


def commit(
    scan: Scan,
    accepted: Iterable,
    declined: Iterable[str],
    reviewed: bool,
    vault_path: str,
    passphrase: str,
    output_path: str | None = None,
) -> Result:
    """Add the accepted items to the matter, save it, and write the sanitized
    document. ``accepted`` holds :class:`Item` objects or ``(type, value,
    source)`` tuples, in order; ``declined`` holds values not to propose again.

    All or nothing: the output is written beside its destination and checked
    before the vault is saved, and only then moved into place.
    """
    text = scan.text
    declined = list(declined)
    new_mappings, _ = sc.propose_mappings([_as_tuple(i) for i in accepted], scan.vault)
    for entry in new_mappings.values():
        entry["reviewed"] = reviewed
    vault = sc.merge_vault(scan.vault, new_mappings, declined)

    safe = sc.apply_vault(text, vault)
    if sc.rehydrate_text(safe, vault) != text:
        raise ServiceError("Internal error: round-trip check failed. No output written.")

    output = output_path or default_output_path(scan.path, "sanitized")
    problem = check_output_path(scan.path, output, "sanitized", vault_path)
    if problem:
        raise ServiceError(problem + " No output written.")
    directory = os.path.dirname(os.path.abspath(output))
    fd, pending = tempfile.mkstemp(dir=directory, prefix=".pending-", suffix=os.path.splitext(output)[1])
    os.close(fd)
    try:
        if is_docx(scan.path) and is_docx(output):
            # Same file, same formatting; only the sensitive text and author metadata change.
            docx_io.rewrite_docx(scan.path, pending, lambda part: sc.find_vault_spans(part, vault), scrub=True)
            safe = docx_io.read_docx(pending)
            if sc.find_vault_spans(safe, vault):
                raise ServiceError("Internal error: a vault value survived in the .docx. No output written.")
        elif is_pdf(scan.path) and is_pdf(output):
            if not pdf_io.available():
                raise ServiceError(
                    "Writing a redacted PDF needs PyMuPDF (pip install pymupdf). Use -o file.txt for text."
                )
            # The text is removed from the pages, the placeholder printed in its
            # place, and the file's metadata cleared.
            pdf_io.redact_pdf(scan.path, pending, lambda page: sc.find_vault_spans(page, vault))
            safe = pdf_io.read_pdf(pending)
            if sc.find_vault_spans(safe, vault):
                raise ServiceError("Internal error: a vault value survived in the PDF. No output written.")
        else:
            with open(pending, "w", encoding="utf-8") as fh:
                fh.write(safe)
        sc.save_vault(vault, vault_path, passphrase=passphrase)
        os.replace(pending, output)
    except BaseException:
        if os.path.exists(pending):
            os.unlink(pending)
        raise

    return Result(
        output_path=output,
        vault=vault,
        added=len(new_mappings),
        declined=len(declined),
        replaced=len(sc.find_vault_spans(text, vault)),
        reviewed=reviewed,
        residue=find_residue(safe, vault),
    )


# --------------------------------------------------------------------------
# Restore
# --------------------------------------------------------------------------


def _altered(text: str, found: list) -> list[str]:
    return sorted({text[start:end] for start, end, name in found if text[start:end] != name})


def _unknown(restored: str) -> list[str]:
    return sorted(set(sc.PLACEHOLDER_RE.findall(restored)))


def restore_text(text: str, vault: dict, tolerant: bool = True) -> tuple[str, RestoreResult]:
    """Put the real values back into pasted text. Nothing is written: the caller
    shows the result and saves it only if the user asks (``save_restored_text``).
    The result's ``output_path`` is empty."""
    if not text.strip():
        raise ServiceError("There is no text to restore. Paste the text that came back.")
    found = sc.find_placeholders(text, vault, tolerant)
    restored = sc.rehydrate_text(text, vault, tolerant)
    return restored, RestoreResult("", len(found), _altered(text, found), _unknown(restored))


def save_restored_text(text: str, output_path: str, vault_path: str | None = None) -> str:
    """Write restored text as plain text. Refuses the vault file, a .docx or .pdf name,
    and a folder that does not exist. Returns the path written."""
    problem = check_output_path("", output_path, "rehydrated", vault_path)
    if problem:
        raise ServiceError(problem + " Nothing was written.")
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return output_path


def restore(path: str, vault: dict, output_path: str | None = None, tolerant: bool = True) -> RestoreResult:
    """Put the real values back into a document that contains placeholders."""
    text = read_document(path)
    mappings = vault["mappings"]
    found = sc.find_placeholders(text, vault, tolerant)
    altered = _altered(text, found)
    restored = sc.rehydrate_text(text, vault, tolerant)
    output = output_path or default_output_path(path, "rehydrated")
    problem = check_output_path(path, output, "rehydrated")
    if problem:
        raise ServiceError(problem + " Nothing was written.")
    if is_docx(path) and is_docx(output):

        def edits(part: str):
            return [
                (start, end, mappings[name]["value"])
                for start, end, name in sc.find_placeholders(part, vault, tolerant)
            ]

        docx_io.rewrite_docx(path, output, edits)
        restored = docx_io.read_docx(output)
    else:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(restored)
    return RestoreResult(output, len(found), altered, _unknown(restored))


# --------------------------------------------------------------------------
# Keys
# --------------------------------------------------------------------------

CONFIDENTIAL_NOTE = (
    "CONFIDENTIAL. This key contains the real names and numbers. Keep it on this machine; "
    "never send it with the sanitized document."
)
SAFE_NOTE = (
    "Safe key: no real values. It only shows which placeholders refer to the same person, "
    "company or item, and may accompany the sanitized document."
)


def build_key(vault: dict, text: str | None = None, values: bool = True) -> tuple[list[str], list[list]]:
    """Table for a key document: one row per placeholder, aliases under their entity.

    With ``text`` (a sanitized document, or the original), only placeholders
    that occur in it are listed, in order of first appearance, with a count.
    """
    mappings = vault["mappings"]
    counts: Counter = Counter()
    first: dict[str, int] = {}
    if text is not None:
        found = [(m.start(), m.group(0)) for m in sc.PLACEHOLDER_RE.finditer(text) if m.group(0) in mappings]
        if not found:  # an original document: work out what would be replaced
            found = [(start, placeholder) for start, _, placeholder in sc.find_vault_spans(text, vault)]
        for position, placeholder in found:
            counts[placeholder] += 1
            first.setdefault(placeholder, position)

    entities: dict[str, list[str]] = {}
    for placeholder, entry in mappings.items():
        if text is None or placeholder in counts:
            entities.setdefault(entry["entity"], []).append(placeholder)
    order = sorted(entities, key=lambda e: min(first.get(p, 0) for p in entities[e])) if text is not None else list(entities)

    header = ["Placeholder", "Type"] + (["Real value"] if values else []) + ["Same as"]
    header += ["Times in document"] if text is not None else []
    rows = []
    for entity in order:
        main = f"[{entity}]"
        members = sorted(entities[entity], key=lambda p: p != main)  # stable: vault order otherwise
        for placeholder in members:
            entry = mappings[placeholder]
            row = [placeholder, entry["type"].replace("_", " ")]
            if values:
                row.append(" ".join(entry["value"].split()))
            row.append("" if placeholder == main else main)
            if text is not None:
                row.append(counts[placeholder])
            rows.append(row)
    return header, rows


def write_key(path: str, title: str, note: str, header: list[str], rows: list[list], private: bool) -> None:
    extension = os.path.splitext(path)[1].lower()
    if extension == ".docx":
        docx_io.write_table_docx(path, title, [note, f"{len(rows)} placeholder(s)."], header, rows)
    elif extension == ".csv":
        import csv

        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerows([[note], header] + rows)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"{title}\n{note}\n\n")
            for row in rows:
                cells = dict(zip(header, row))
                line = f"{cells['Placeholder']}  ({cells['Type']})"
                if "Real value" in cells:
                    line += f"  =  {cells['Real value']}"
                if cells["Same as"]:
                    line += f"  [same {cells['Type']} as {cells['Same as']}]"
                fh.write(line + "\n")
    if private:
        os.chmod(path, 0o600)


def write_keys(
    vault: dict,
    document_path: str | None,
    vault_path: str,
    fmt: str = "docx",
    confidential_path: str | None = None,
    safe_path: str | None = None,
    confidential: bool = True,
    safe: bool = True,
) -> KeyResult:
    """Write the confidential key, the safe key, or both. With a document, only
    the placeholders that appear in it are listed."""
    text = read_document(document_path) if document_path else None
    about = f" for {os.path.basename(document_path)}" if document_path else ""
    default_confidential, default_safe = key_paths(document_path, vault_path, fmt)
    count = 0
    written: list[str | None] = [None, None]
    if confidential:
        written[0] = confidential_path or default_confidential
        header, rows = build_key(vault, text, values=True)
        write_key(written[0], "Key" + about, CONFIDENTIAL_NOTE, header, rows, private=True)
        count = len(rows)
    if safe:
        written[1] = safe_path or default_safe
        header, rows = build_key(vault, text, values=False)
        write_key(written[1], "Key (no real values)" + about, SAFE_NOTE, header, rows, private=False)
        count = len(rows)
    return KeyResult(written[0], written[1], count)


def vault_summary(vault: dict) -> dict:
    mappings = vault["mappings"]
    return {
        "mappings": len(mappings),
        "by_type": dict(Counter(e["type"] for e in mappings.values())),
        "unreviewed": sum(1 for e in mappings.values() if e.get("reviewed") is False),
        "declined": len(vault.get("declined", [])),
    }


# --------------------------------------------------------------------------
# Review state: what a reviewer has decided so far (no GUI in here)
# --------------------------------------------------------------------------

SOURCE_LABELS = {"ner": "model", "regex": "pattern", "propagated": "short form", "manual": "added by you"}


@dataclass
class Row:
    item: Item
    accepted: bool = True
    detected_value: str = ""  # what the scan proposed, before any edit; "" for added rows


class ReviewState:
    """The decisions behind the review table. Every row starts accepted.

    ``result()`` gives what :func:`commit` needs. ``reviewed`` is False only if
    the reviewer changed nothing and looked at nothing: the "accept all" path.
    """

    def __init__(self, scan: Scan):
        self.scan = scan
        self.rows = [Row(item, True, item.value) for item in scan.items]
        self.touched = False

    # ---- looking

    def mark_seen(self, index: int) -> None:
        """The reviewer opened this row's context."""
        self.touched = True

    def occurrences(self, index: int) -> list[tuple[int, int]]:
        return occurrences(self.scan.text, self.rows[index].item.value)

    # ---- deciding

    def set_accepted(self, index: int, accepted: bool) -> None:
        self.rows[index].accepted = accepted
        self.touched = True

    def accept_all(self) -> None:
        """Tick every row. Does not count as reviewing."""
        for row in self.rows:
            row.accepted = True

    def set_type(self, index: int, etype: str) -> str | None:
        if etype not in sc.ENTITY_TYPES:
            return "Choose one of the listed types."
        self.rows[index].item.type = etype
        self.touched = True
        return None

    def _taken(self, value: str, skip: int | None = None) -> bool:
        in_rows = any(r.item.value == value for i, r in enumerate(self.rows) if i != skip)
        in_matter = any(e["value"] == value for e in self.scan.vault["mappings"].values())
        return in_rows or in_matter

    def edit_text(self, index: int, new_text: str) -> str | None:
        """Change the text a row redacts. Returns None, or why it was refused."""
        new_text = new_text.strip()
        problem = validate_edit(self.scan, new_text)
        if problem:
            return problem
        if self._taken(new_text, skip=index):
            return "That text is already in the list or in this matter."
        item = self.rows[index].item
        if new_text != item.value:
            item.value, item.source, item.entity_hint = new_text, "manual", ""
            item.times = len(occurrences(self.scan.text, new_text))
            self.touched = True
        return None

    def check_add(self, etype: str, text: str) -> str | None:
        """Why this could not be added, or None. Changes nothing."""
        text = text.strip()
        problem = validate_edit(self.scan, text)
        if problem:
            return problem
        if etype not in sc.ENTITY_TYPES:
            return "Choose one of the listed types."
        if self._taken(text):
            return "That text is already in the list or in this matter."
        return None

    def add(self, etype: str, text: str) -> str | None:
        """Add something the scan missed. Returns None, or why it was refused."""
        problem = self.check_add(etype, text)
        if problem is None:
            self.rows.append(Row(make_item(self.scan, etype, text.strip()), True, ""))
            self.touched = True
        return problem

    # ---- outcome

    @property
    def accepted_count(self) -> int:
        return sum(row.accepted for row in self.rows)

    def result(self) -> tuple[list[Item], list[str], bool]:
        """(accepted items, declined values, reviewed) for :func:`commit`.

        A declined row is remembered under the text the scan proposed, so it is
        not proposed again. A row the reviewer added and then unticked is simply
        dropped.
        """
        accepted = [row.item for row in self.rows if row.accepted]
        kept = {item.value for item in accepted}
        declined = [
            row.detected_value
            for row in self.rows
            if not row.accepted and row.detected_value and row.detected_value not in kept
        ]
        return accepted, declined, self.touched
