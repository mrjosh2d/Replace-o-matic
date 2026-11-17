"""Command-line tool for Replace-o-matic.

    python sanitizer_cli.py sanitize contract.docx --vault matter.vault
    python sanitizer_cli.py sanitize contract.docx --vault matter.vault --lucky
    python sanitizer_cli.py rehydrate answer.txt --vault matter.vault
    python sanitizer_cli.py vault --vault matter.vault
    python sanitizer_cli.py key contract.sanitized.docx --vault matter.vault

``sanitize`` scans the document, lets you review what it found, saves the
accepted items to the encrypted vault and writes a redacted text file.
``rehydrate`` puts the real values back into a text that contains placeholders.
``key`` writes two tables of what each placeholder stands for: a confidential
one with the real values, and a safe one without them.

Reads .txt, .docx and .pdf. A .docx is written back as a .docx with its
formatting intact; other inputs are written as plain text. Nothing here uses
the network.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from collections import Counter

import sanitizer_core as sc  # first project import: it sets the offline switches

import sanitizer_service as service
from sanitizer_service import build_key, find_residue, write_key  # noqa: F401  (used by tests and scripts)

PASSPHRASE_ENV = "REPLACE_O_MATIC_PASSPHRASE"
LUCKY_WARNING = (
    "UNREVIEWED: every item the scan found was accepted and nothing it missed was added.\n"
    "In testing on unseen text the scan missed about 1 in 10 sensitive mentions.\n"
    "Read the output before it leaves this machine."
)


class Quit(Exception):
    """The reviewer chose to stop. Nothing is saved."""


def _guard(function, *args, **kwargs):
    """Run a service call; a failure the user can act on ends the program with its message."""
    try:
        return function(*args, **kwargs)
    except service.ServiceError as error:
        raise SystemExit(str(error)) from None


def read_document(path: str) -> str:
    return _guard(service.read_document, path)


# --------------------------------------------------------------------------
# Review at the terminal
# --------------------------------------------------------------------------


def _occurrences(text: str, value: str) -> list:
    return service.occurrences(text, value)


def _context(text: str, value: str) -> str:
    return service.first_context(text, value)


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
    if service.matter_exists(path) and not sc.is_encrypted_vault(path):
        raise SystemExit(f"{path} is not an encrypted vault. Refusing to use it.")
    passphrase = _passphrase(path, not service.matter_exists(path), get)
    return _guard(service.open_matter, path, passphrase), passphrase


def cmd_sanitize(args, ask, out, get) -> int:
    text = read_document(args.input)
    vault, passphrase = _open_vault(args.vault, get)

    out(f"Scanning {args.input} ({len(text.split()):,} words)...")
    scan = _guard(service.scan_document, args.input, vault, regex_only=args.regex_only)
    for warning in scan.warnings:
        out("Warning: " + warning)
    out(f"{scan.already_known} item(s) in this document are already in the vault.")

    if args.lucky:
        accepted, declined, reviewed = list(scan.items), [], False
        out(f"I'm feeling lucky: accepting all {len(accepted)} new item(s) without review.")
    else:
        proposed = {i: {"type": item.type, "value": item.value, "source": item.source} for i, item in enumerate(scan.items)}
        try:
            accepted, declined, reviewed = review(scan.text, proposed, ask, out)
        except Quit:
            out("Stopped. Nothing was saved and no output was written.")
            return 1

    result = _guard(service.commit, scan, accepted, declined, reviewed, args.vault, passphrase, args.output)
    out(f"\nAdded {result.added} item(s) to the vault, declined {result.declined}.")
    out(f"Replaced {result.replaced} occurrence(s). Wrote {result.output_path}")
    if result.residue:
        out("Check these: vault values that still appear in a different letter case:")
        for value, hits in result.residue:
            out(f"  \"{value}\" x{hits}")
    if not reviewed:
        out("\n" + LUCKY_WARNING)
    return 0


def cmd_rehydrate(args, ask, out, get) -> int:
    read_document(args.input)  # fail early, before asking for a passphrase
    vault, _ = _open_vault(args.vault, get)
    result = _guard(service.restore, args.input, vault, args.output, tolerant=not args.strict)
    if result.altered:
        out("Restored placeholders whose spelling had been altered: " + ", ".join(result.altered))
    out(f"Wrote {result.output_path}")
    if result.unknown:
        out("Placeholders not in this vault were left as they are: " + ", ".join(result.unknown))
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


def cmd_key(args, ask, out, get) -> int:
    if not os.path.exists(args.vault):
        raise SystemExit(f"No vault at {args.vault}")
    vault, _ = _open_vault(args.vault, get)
    result = _guard(
        service.write_keys, vault, args.document, args.vault, args.format,
        args.output, args.safe_output, confidential=not args.safe_only, safe=not args.confidential_only,
    )  # fmt: skip
    if result.confidential_path:
        out(f"Confidential key: {result.confidential_path} ({result.count} placeholder(s))")
    if result.safe_path:
        out(f"Safe key: {result.safe_path} ({result.count} placeholder(s))")
    if result.confidential_path:
        out(service.CONFIDENTIAL_NOTE)
    return 0


def main(argv=None, ask=input, out=print, get=getpass.getpass) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    sanitize = commands.add_parser("sanitize", help="scan, review and redact a document")
    sanitize.add_argument("input")
    sanitize.add_argument("--vault", required=True, help="encrypted vault file (created if missing)")
    sanitize.add_argument("-o", "--output", help="default: same format as the input for .docx and .pdf, else .sanitized.txt")
    sanitize.add_argument(
        "--lucky", action="store_true", help="I'm feeling lucky: accept everything found, no review"
    )
    sanitize.add_argument("--regex-only", action="store_true", help="skip the GLiNER model")
    sanitize.set_defaults(run=cmd_sanitize)

    rehydrate = commands.add_parser("rehydrate", help="put real values back into a text")
    rehydrate.add_argument("input")
    rehydrate.add_argument("--vault", required=True)
    rehydrate.add_argument("-o", "--output", help="default: <input>.rehydrated.docx for a .docx, else .rehydrated.txt")
    rehydrate.add_argument(
        "--strict", action="store_true", help="only restore placeholders spelled exactly as written"
    )
    rehydrate.set_defaults(run=cmd_rehydrate)

    vault = commands.add_parser("vault", help="summarise a vault")
    vault.add_argument("--vault", required=True)
    vault.add_argument("--show-values", action="store_true", help="print the real values too")
    vault.set_defaults(run=cmd_vault)

    key = commands.add_parser("key", help="write a key: what each placeholder stands for")
    key.add_argument("document", nargs="?", help="sanitized (or original) document: list only its placeholders")
    key.add_argument("--vault", required=True)
    key.add_argument("--format", choices=["docx", "csv", "txt"], default="docx")
    key.add_argument("-o", "--output", help="confidential key path (default: <document>.key.<format>)")
    key.add_argument("--safe-output", help="safe key path (default: <document>.key-safe.<format>)")
    only = key.add_mutually_exclusive_group()
    only.add_argument("--confidential-only", action="store_true", help="skip the safe key")
    only.add_argument("--safe-only", action="store_true", help="write only the key without real values")
    key.set_defaults(run=cmd_key)

    args = parser.parse_args(argv)
    try:
        return args.run(args, ask, out, get)
    except (EOFError, KeyboardInterrupt):
        out("\nStopped. Nothing further was saved.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
