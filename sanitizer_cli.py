"""Command-line tool for Replace-o-matic.

    python sanitizer_cli.py sanitize contract.docx --vault matter.vault
    python sanitizer_cli.py sanitize contract.docx --vault matter.vault --lucky
    python sanitizer_cli.py rehydrate answer.txt --vault matter.vault
    python sanitizer_cli.py vault --vault matter.vault

``sanitize`` scans the document, lets you review what it found, saves the
accepted items to the encrypted vault and writes a redacted text file.
``rehydrate`` puts the real values back into a text that contains placeholders.

Reads .txt, .docx and .pdf. Writes plain text. Nothing here uses the network.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import zipfile
from collections import Counter
from xml.etree import ElementTree

import sanitizer_core as sc

PASSPHRASE_ENV = "REPLACE_O_MATIC_PASSPHRASE"
LUCKY_WARNING = (
    "UNREVIEWED: every item the scan found was accepted and nothing it missed was added.\n"
    "In testing on unseen text the scan missed about 1 in 10 sensitive mentions.\n"
    "Read the output before it leaves this machine."
)


class Quit(Exception):
    """The reviewer chose to stop. Nothing is saved."""


# --------------------------------------------------------------------------
# Reading documents
# --------------------------------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _read_docx(path: str) -> str:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in root.iter(_W + "p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == _W + "t":
                parts.append(node.text or "")
            elif node.tag == _W + "tab":
                parts.append("\t")
            elif node.tag in (_W + "br", _W + "cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def _read_pdf(path: str) -> str:
    from pypdf import PdfReader

    return "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def read_document(path: str) -> str:
    """Text of a .txt, .docx or .pdf file. Headers, footers and footnotes of a
    .docx are not included; a scanned PDF has no text to extract."""
    extension = os.path.splitext(path)[1].lower()
    if extension == ".docx":
        text = _read_docx(path)
    elif extension == ".pdf":
        text = _read_pdf(path)
    else:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    if not text.strip():
        raise SystemExit(f"No text found in {path}. If it is a scanned PDF, it needs OCR first.")
    return text


# --------------------------------------------------------------------------
# Review
# --------------------------------------------------------------------------


def _occurrences(text: str, value: str) -> list[re.Match]:
    left = r"(?<!\w)" if re.match(r"\w", value[0]) else ""
    right = r"(?!\w)" if re.match(r"\w", value[-1]) else ""
    return list(re.finditer(left + re.escape(value) + right, text))


def _context(text: str, value: str, width: int = 45) -> str:
    found = _occurrences(text, value)
    if not found:
        return "(not found as a whole word in this document)"
    m = found[0]
    before = text[max(0, m.start() - width) : m.start()]
    after = text[m.end() : m.end() + width]
    return " ".join(f"...{before}«{value}»{after}...".split())


def _ask_type(ask, out, default: str) -> str:
    while True:
        answer = ask(f"       type ({', '.join(sc.ENTITY_TYPES)}) [{default}] > ").strip().lower()
        if not answer:
            return default
        matches = [t for t in sc.ENTITY_TYPES if t.startswith(answer)]
        if len(matches) == 1:
            return matches[0]
        out("       Not a type I know.")


def review(text: str, proposed: dict, ask=input, out=print) -> tuple[list[tuple], list[str], bool]:
    """Walk a person through the proposals.

    Returns ``(accepted, declined, reviewed)``: accepted is a list of
    ``(type, value, source)`` in order, declined a list of values, and
    reviewed is False if the "I'm feeling lucky" shortcut was taken.
    Raises :class:`Quit` if the reviewer stops.
    """
    items = [(e["type"], e["value"], e["source"]) for e in proposed.values()]
    counts = Counter(t for t, _, _ in items)
    out(f"\nFound {len(items)} new item(s): " + (", ".join(f"{n} {t}" for t, n in counts.items()) or "nothing"))
    if items:
        out("  [r] Review each item")
        out(f"  [l] I'm feeling lucky: accept all {len(items)} without review")
        out("  [q] Quit without saving")
        while True:
            choice = ask("> ").strip().lower()
            if choice in ("l", "lucky"):
                return items, [], False
            if choice in ("q", "quit"):
                raise Quit
            if choice in ("r", "review", ""):
                break

    accepted, declined = [], []
    accept_rest = False
    for i, (etype, value, source) in enumerate(items, 1):
        if accept_rest:
            accepted.append((etype, value, source))
            continue
        while True:
            times = len(_occurrences(text, value))
            out(f"\n {i}/{len(items)}  {etype}  \"{value}\"   appears {times}x   (found by: {source})")
            out("       " + _context(text, value))
            choice = ask("       [a]ccept  [d]ecline  [e]dit text  [t]ype  [A]ccept all remaining  [q]uit > ").strip()
            if choice == "A":
                accept_rest = True
                choice = "a"
            choice = choice.lower()
            if choice in ("", "a"):
                accepted.append((etype, value, source))
                break
            if choice == "d":
                declined.append(value)
                break
            if choice == "q":
                raise Quit
            if choice == "t":
                etype = _ask_type(ask, out, etype)
            elif choice == "e":
                edited = ask("       exact text to redact instead (blank to cancel) > ").strip()
                if not edited:
                    continue
                if not _occurrences(text, edited):
                    out("       That text does not appear in the document; nothing changed.")
                    continue
                value, source = edited, "manual"

    out("\nAdd anything the scan missed. Type the exact text, or press Enter to finish.")
    while True:
        extra = ask("add > ").strip()
        if not extra:
            break
        times = len(_occurrences(text, extra))
        if not times:
            out("  That text does not appear in the document (check spelling and capitals).")
            continue
        out(f"  appears {times}x: " + _context(text, extra))
        accepted.append((_ask_type(ask, out, "person"), extra, "manual"))
    return accepted, declined, True


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
# Commands
# --------------------------------------------------------------------------


def _passphrase(path: str, new: bool, get) -> str:
    from_env = os.environ.get(PASSPHRASE_ENV)
    if from_env:
        return from_env
    if not new:
        return get(f"Passphrase for {path}: ")
    while True:
        first = get(f"Choose a passphrase for the new vault {path}: ")
        if len(first) < 8:
            print("Use at least 8 characters.")
            continue
        if get("Repeat it: ") == first:
            return first
        print("They did not match.")


def _open_vault(path: str, get) -> tuple[dict, str]:
    if not os.path.exists(path):
        return sc.new_vault(), _passphrase(path, True, get)
    if not sc.is_encrypted_vault(path):
        raise SystemExit(f"{path} is not an encrypted vault. Refusing to use it.")
    passphrase = _passphrase(path, False, get)
    try:
        return sc.load_vault(path, passphrase=passphrase), passphrase
    except sc.VaultError as error:
        raise SystemExit(str(error))


def cmd_sanitize(args, ask, out, get) -> int:
    text = read_document(args.input)
    vault, passphrase = _open_vault(args.vault, get)

    out(f"Scanning {args.input} ({len(text.split()):,} words)...")
    proposal = sc.scan_text(text, vault, ner=False if args.regex_only else None)
    for warning in proposal["warnings"]:
        out("Warning: " + warning)
    out(f"{len(proposal['matched'])} item(s) in this document are already in the vault.")

    if args.lucky:
        accepted = [(e["type"], e["value"], e["source"]) for e in proposal["proposed"].values()]
        declined, reviewed = [], False
        out(f"I'm feeling lucky: accepting all {len(accepted)} new item(s) without review.")
    else:
        try:
            accepted, declined, reviewed = review(text, proposal["proposed"], ask, out)
        except Quit:
            out("Stopped. Nothing was saved and no output was written.")
            return 1

    new_mappings, _ = sc.propose_mappings(accepted, vault)
    for entry in new_mappings.values():
        entry["reviewed"] = reviewed
    vault = sc.merge_vault(vault, new_mappings, declined)
    sc.save_vault(vault, args.vault, passphrase=passphrase)

    safe = sc.apply_vault(text, vault)
    if sc.rehydrate_text(safe, vault) != text:
        raise SystemExit("Internal error: round-trip check failed. No output written.")
    output = args.output or os.path.splitext(args.input)[0] + ".sanitized.txt"
    with open(output, "w", encoding="utf-8") as fh:
        fh.write(safe)

    out(f"\nAdded {len(new_mappings)} item(s) to the vault, declined {len(declined)}.")
    out(f"Replaced {len(sc.find_vault_spans(text, vault))} occurrence(s). Wrote {output}")
    residue = find_residue(safe, vault)
    if residue:
        out("Check these: vault values that still appear in a different letter case:")
        for value, hits in residue:
            out(f"  \"{value}\" x{hits}")
    if not reviewed:
        out("\n" + LUCKY_WARNING)
    return 0


def cmd_rehydrate(args, ask, out, get) -> int:
    text = read_document(args.input)
    vault, _ = _open_vault(args.vault, get)
    restored = sc.rehydrate_text(text, vault)
    output = args.output or os.path.splitext(args.input)[0] + ".rehydrated.txt"
    with open(output, "w", encoding="utf-8") as fh:
        fh.write(restored)
    unknown = sorted(set(sc.PLACEHOLDER_RE.findall(restored)))
    out(f"Wrote {output}")
    if unknown:
        out("Placeholders not in this vault were left as they are: " + ", ".join(unknown))
    return 0


def cmd_vault(args, ask, out, get) -> int:
    if not os.path.exists(args.vault):
        raise SystemExit(f"No vault at {args.vault}")
    vault, _ = _open_vault(args.vault, get)
    mappings = vault["mappings"]
    counts = Counter(e["type"] for e in mappings.values())
    unreviewed = sum(1 for e in mappings.values() if e.get("reviewed") is False)
    out(f"{len(mappings)} mapping(s): " + ", ".join(f"{n} {t}" for t, n in counts.items()))
    out(f"{unreviewed} accepted without review, {len(vault.get('declined', []))} declined value(s) remembered.")
    if args.show_values:
        for placeholder, entry in mappings.items():
            flag = "" if entry.get("reviewed", True) else "  (unreviewed)"
            out(f"  {placeholder:26} {entry['value']!r}{flag}")
    return 0


def main(argv=None, ask=input, out=print, get=getpass.getpass) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    sanitize = commands.add_parser("sanitize", help="scan, review and redact a document")
    sanitize.add_argument("input")
    sanitize.add_argument("--vault", required=True, help="encrypted vault file (created if missing)")
    sanitize.add_argument("-o", "--output", help="default: <input>.sanitized.txt")
    sanitize.add_argument(
        "--lucky", action="store_true", help="I'm feeling lucky: accept everything found, no review"
    )
    sanitize.add_argument("--regex-only", action="store_true", help="skip the GLiNER model")
    sanitize.set_defaults(run=cmd_sanitize)

    rehydrate = commands.add_parser("rehydrate", help="put real values back into a text")
    rehydrate.add_argument("input")
    rehydrate.add_argument("--vault", required=True)
    rehydrate.add_argument("-o", "--output", help="default: <input>.rehydrated.txt")
    rehydrate.set_defaults(run=cmd_rehydrate)

    vault = commands.add_parser("vault", help="summarise a vault")
    vault.add_argument("--vault", required=True)
    vault.add_argument("--show-values", action="store_true", help="print the real values too")
    vault.set_defaults(run=cmd_vault)

    args = parser.parse_args(argv)
    try:
        return args.run(args, ask, out, get)
    except (EOFError, KeyboardInterrupt):
        out("\nStopped. Nothing further was saved.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
