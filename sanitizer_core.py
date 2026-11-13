"""Offline pseudonymization core for legal documents.

Workflow::

    proposal = scan_text(text, vault)            # detect, propose; nothing is altered
    vault = merge_vault(vault, proposal["proposed"])   # after human review
    safe = apply_vault(text, vault)              # real values -> placeholders
    original = rehydrate_text(safe, vault)       # placeholders -> real values

Vault format (JSON)::

    {"version": 1,
     "mappings": {
       "[COMPANY_1]":         {"type": "company", "value": "Acme Corporation", "entity": "COMPANY_1"},
       "[COMPANY_1_ALIAS_1]": {"type": "company", "value": "Acme Corp.",       "entity": "COMPANY_1"}}}

Every distinct surface form gets its own placeholder, so re-hydration is exact.
Aliases of one real-world entity share the entity number, so a reader (or an
LLM) can still tell that ``[COMPANY_1]`` and ``[COMPANY_1_ALIAS_1]`` co-refer.

This module makes no network calls. The vault holds the real values in
plaintext: never commit it, and never send it anywhere with the sanitized text.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Callable, Iterable

VAULT_VERSION = 1

ENTITY_TYPES = ("person", "company", "address", "financial_id", "email", "phone")

PLACEHOLDER_RE = re.compile(
    r"\[(?:" + "|".join(t.upper() for t in ENTITY_TYPES) + r")_\d+(?:_ALIAS_\d+)?\]"
)


@dataclass(frozen=True)
class Detection:
    """A sensitive span found in a text. ``text[start:end]`` is the value."""

    start: int
    end: int
    type: str
    source: str = "ner"  # "regex" or "ner"


#: An NER backend: takes the text, returns the spans it considers sensitive.
NerDetector = Callable[[str], Iterable[Detection]]


# --------------------------------------------------------------------------
# Regex detectors
# --------------------------------------------------------------------------

_B = r"(?<![\w-])"  # not preceded by a word char or hyphen
_E = r"(?![\w-])"  # not followed by one

# (entity type, pattern). If the pattern has a group named "v", only that
# group is the sensitive value; otherwise the whole match is.
REGEX_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # SSN: 123-45-6789
    ("financial_id", re.compile(_B + r"(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}" + _E)),
    # EIN: 12-3456789
    ("financial_id", re.compile(_B + r"\d{2}-\d{7}" + _E)),
    # Bank account / routing number, anchored on a keyword to limit false positives
    (
        "financial_id",
        re.compile(
            r"\b(?:account|acct\.?|a/c|routing|aba)\s*(?:number|no\.?|num\.?|#)?\s*"
            r"(?:is\s+)?[:#]?\s*(?P<v>\d(?:[ -]?\d){5,16})" + _E,
            re.IGNORECASE,
        ),
    ),
    # IBAN
    ("financial_id", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")),
    ("email", re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")),
    # US phone: (212) 555-0147, 212-555-0147, +1 212.555.0147
    (
        "phone",
        re.compile(
            r"(?<![\w+-])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}" + _E
        ),
    ),
)


def detect_regex(text: str) -> list[Detection]:
    """Find SSNs, EINs, bank account numbers, IBANs, emails and phone numbers."""
    found = []
    for etype, pattern in REGEX_PATTERNS:
        for m in pattern.finditer(text):
            group = "v" if "v" in pattern.groupindex else 0
            found.append(Detection(m.start(group), m.end(group), etype, "regex"))
    return found


# --------------------------------------------------------------------------
# Alias resolution: do two surface forms name the same real-world entity?
# --------------------------------------------------------------------------

_COMPANY_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "llc", "llp", "lp",
    "ltd", "limited", "plc", "pllc", "pc", "na", "gmbh", "ag", "sa", "bv", "nv",
}  # fmt: skip
_HONORIFICS = {"mr", "mrs", "ms", "miss", "mx", "dr", "prof", "hon", "judge", "justice"}
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "esq", "phd", "md"}


def _words(value: str) -> list[str]:
    # "L.L.C." -> "llc", "O'Brien" -> "o'brien"
    collapsed = re.sub(r"(?<=\w)\.(?=\w)", "", value.casefold())
    return re.findall(r"[\w'’-]+", collapsed)


def _company_key(value: str) -> str:
    words = _words(value)
    if words[:1] == ["the"]:
        words = words[1:]
    while len(words) > 1 and words[-1] in _COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def _person_tokens(value: str) -> tuple[str, ...]:
    words = _words(value)
    while len(words) > 1 and words[0] in _HONORIFICS:
        words = words[1:]
    while len(words) > 1 and words[-1] in _NAME_SUFFIXES:
        words.pop()
    return tuple(words)


def _person_relation(a: tuple[str, ...], b: tuple[str, ...]) -> str:
    """'strong' (same name), 'weak' (one is a bare first/last name of the other),
    'conflict' (two different full names) or 'none'."""
    if a == b:
        return "strong"
    if len(a) == 1 or len(b) == 1:
        short, full = (a, b) if len(a) == 1 else (b, a)
        if len(full) > 1 and short[0] in (full[0], full[-1]):
            return "weak"
        return "none" if len(full) == 1 else "conflict"
    # "John Q. Smith" vs "John Smith": same first and last, one has no middle name
    if a[0] == b[0] and a[-1] == b[-1] and 2 in (len(a), len(b)):
        return "strong"
    return "conflict"


def _generic_key(etype: str, value: str) -> str:
    if etype == "email":
        return value.casefold()
    if etype == "phone":
        digits = re.sub(r"\D", "", value)
        return digits[1:] if len(digits) == 11 and digits[0] == "1" else digits
    if etype == "financial_id":
        return re.sub(r"[^0-9a-z]", "", value.casefold())
    return " ".join(_words(value))  # address


def _find_entity(etype: str, value: str, entities: dict[str, dict]) -> str | None:
    """Return the id of the existing entity that ``value`` is an alias of, if any."""
    same_type = {eid: e for eid, e in entities.items() if e["type"] == etype}

    if etype != "person":
        key_of = _company_key if etype == "company" else (lambda v: _generic_key(etype, v))
        key = key_of(value)
        for eid, entity in same_type.items():
            if key and any(key_of(v) == key for v in entity["values"]):
                return eid
        return None

    tokens = _person_tokens(value)
    strong, weak = [], []
    for eid, entity in same_type.items():
        relations = {_person_relation(tokens, _person_tokens(v)) for v in entity["values"]}
        if "conflict" in relations:
            continue  # this entity is already known to be a different full name
        if "strong" in relations:
            strong.append(eid)
        elif "weak" in relations:
            weak.append(eid)
    if strong:
        return strong[0]
    # A bare "Smith" is only linked when exactly one known person fits.
    return weak[0] if len(weak) == 1 else None


# --------------------------------------------------------------------------
# Vault helpers
# --------------------------------------------------------------------------


def new_vault() -> dict:
    return {"version": VAULT_VERSION, "mappings": {}}


def _mappings(vault: dict | None) -> dict[str, dict]:
    return (vault or {}).get("mappings", {})


def _value_index(vault: dict | None) -> dict[str, str]:
    """value -> placeholder, rejecting vaults that cannot round-trip."""
    index: dict[str, str] = {}
    for placeholder, entry in _mappings(vault).items():
        if not PLACEHOLDER_RE.fullmatch(placeholder):
            raise ValueError(f"Malformed placeholder in vault: {placeholder!r}")
        value = entry["value"]
        if not value.strip():
            raise ValueError(f"Empty value for {placeholder}")
        if value in index:
            raise ValueError(f"Value mapped twice in vault: {index[value]} and {placeholder}")
        index[value] = placeholder
    return index


def merge_vault(vault: dict | None, proposed: dict[str, dict]) -> dict:
    """Return a new vault with ``proposed`` mappings added. Inputs are not modified."""
    merged = copy.deepcopy(vault) if vault else new_vault()
    for placeholder, entry in proposed.items():
        existing = merged["mappings"].get(placeholder)
        if existing is not None and existing["value"] != entry["value"]:
            raise ValueError(f"{placeholder} is already mapped to a different value")
        merged["mappings"][placeholder] = dict(entry)
    _value_index(merged)
    return merged


def load_vault(path: str | os.PathLike) -> dict:
    with open(path, encoding="utf-8") as fh:
        vault = json.load(fh)
    if vault.get("version") != VAULT_VERSION:
        raise ValueError(f"Unsupported vault version: {vault.get('version')!r}")
    _value_index(vault)
    return vault


def save_vault(vault: dict, path: str | os.PathLike) -> None:
    """Write the vault atomically, readable by the owner only."""
    _value_index(vault)
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".vault-", suffix=".tmp")  # mode 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(vault, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


# --------------------------------------------------------------------------
# Core API
# --------------------------------------------------------------------------


def _clean_spans(text: str, detections: Iterable[Detection]) -> list[Detection]:
    """Validate and trim spans, then drop overlaps (longest wins, regex beats NER)."""
    cleaned = []
    for d in detections:
        if d.type not in ENTITY_TYPES:
            raise ValueError(f"Unknown entity type: {d.type!r}")
        start, end = max(0, d.start), min(len(text), d.end)
        span = text[start:end]
        if d.type in ("person", "company"):
            span = re.sub(r"['’]s$", "", span)  # "Acme's" -> "Acme"
        end = start + len(span.rstrip())
        start += len(span) - len(span.lstrip())
        if start < end and not PLACEHOLDER_RE.search(text[start:end]):
            cleaned.append(Detection(start, end, d.type, d.source))

    kept: list[Detection] = []
    by_priority = sorted(cleaned, key=lambda d: (d.start - d.end, d.source != "regex", d.start))
    for d in by_priority:
        if all(d.end <= k.start or d.start >= k.end for k in kept):
            kept.append(d)
    return sorted(kept, key=lambda d: d.start)


def scan_text(
    text: str,
    existing_vault: dict | None = None,
    ner: NerDetector | None = None,
) -> dict:
    """Detect sensitive entities and propose placeholder mappings for the new ones.

    Neither ``text`` nor ``existing_vault`` is modified. Returns::

        {"proposed": {placeholder: {"type", "value", "entity", "source"}},  # new mappings
         "matched":  [placeholder, ...],   # existing vault entries seen in this text
         "warnings": [str, ...]}

    Numbering is deterministic: entities are numbered in order of first
    appearance, continuing from the highest number already in the vault.
    Pass the result's ``proposed`` dict to :func:`merge_vault` once reviewed.
    """
    value_to_placeholder = _value_index(existing_vault)
    entities: dict[str, dict] = {}  # entity id -> {"type", "values"}
    for entry in _mappings(existing_vault).values():
        entity = entities.setdefault(entry["entity"], {"type": entry["type"], "values": []})
        entity["values"].append(entry["value"])

    next_number = {t: 0 for t in ENTITY_TYPES}
    next_alias: dict[str, int] = {}
    for placeholder in _mappings(existing_vault):
        etype, number, alias = re.fullmatch(
            r"\[([A-Z_]+?)_(\d+)(?:_ALIAS_(\d+))?\]", placeholder
        ).groups()
        etype = etype.lower()
        next_number[etype] = max(next_number[etype], int(number))
        entity_id = f"{etype.upper()}_{number}"
        next_alias[entity_id] = max(next_alias.get(entity_id, 0), int(alias or 0))

    detections = detect_regex(text)
    if ner is not None:
        detections.extend(ner(text))

    proposed: dict[str, dict] = {}
    matched: list[str] = []
    for d in _clean_spans(text, detections):
        value = text[d.start : d.end]
        if value in value_to_placeholder:
            placeholder = value_to_placeholder[value]
            if placeholder not in proposed and placeholder not in matched:
                matched.append(placeholder)
            continue

        entity_id = _find_entity(d.type, value, entities)
        if entity_id is None:
            next_number[d.type] += 1
            entity_id = f"{d.type.upper()}_{next_number[d.type]}"
            entities[entity_id] = {"type": d.type, "values": []}
            placeholder = f"[{entity_id}]"
        else:
            next_alias[entity_id] = next_alias.get(entity_id, 0) + 1
            placeholder = f"[{entity_id}_ALIAS_{next_alias[entity_id]}]"

        entities[entity_id]["values"].append(value)
        value_to_placeholder[value] = placeholder
        proposed[placeholder] = {
            "type": d.type,
            "value": value,
            "entity": entity_id,
            "source": d.source,
        }

    warnings = []
    unknown = sorted(set(PLACEHOLDER_RE.findall(text)) - set(_mappings(existing_vault)))
    if unknown:
        warnings.append(
            "Text already contains placeholder-like tokens that are not in the vault: "
            + ", ".join(unknown)
        )
    return {"proposed": proposed, "matched": matched, "warnings": warnings}


def apply_vault(text: str, vault: dict) -> str:
    """Replace every vault value in ``text`` with its placeholder.

    One regex pass, longest value first, whole words only: "John" never fires
    inside "Johnson", and "Acme" never eats the start of "Acme Holdings LLC"
    when both are in the vault. Placeholders already present are left alone,
    so applying twice is the same as applying once.
    """
    index = _value_index(vault)
    if not index:
        return text

    def bounded(value: str) -> str:
        # Word boundaries only where the value itself starts/ends with a word char.
        left = r"(?<!\w)" if re.match(r"\w", value[0]) else ""
        right = r"(?!\w)" if re.match(r"\w", value[-1]) else ""
        return left + re.escape(value) + right

    longest_first = sorted(index, key=lambda v: (-len(v), v))
    pattern = re.compile(
        "(" + PLACEHOLDER_RE.pattern + ")|" + "|".join(bounded(v) for v in longest_first)
    )
    return pattern.sub(lambda m: m.group(1) or index[m.group(0)], text)


def rehydrate_text(text: str, vault: dict) -> str:
    """Replace placeholders with their real values. Unknown placeholders are kept.

    Single pass over placeholder tokens only, so restored values are never
    re-scanned and one placeholder can never match inside another.
    """
    mappings = _mappings(vault)
    return PLACEHOLDER_RE.sub(
        lambda m: mappings[m.group(0)]["value"] if m.group(0) in mappings else m.group(0),
        text,
    )
