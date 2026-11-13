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

This module makes no network calls: the GLiNER model is loaded from a local
directory only (see ``scripts/fetch_model.py`` for the one-time download) and
the Hugging Face libraries are forced into offline mode. The vault holds the real values in
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
    source: str = "ner"  # "regex", "ner" or "propagated"
    alias_of: str = ""  # propagated short forms: the full value they were derived from


#: An NER backend: takes the text, returns the spans it considers sensitive.
NerDetector = Callable[[str], Iterable[Detection]]


# --------------------------------------------------------------------------
# Regex detectors
# --------------------------------------------------------------------------

_B = r"(?<![\w-])"  # not preceded by a word char or hyphen
_E = r"(?![\w-])"  # not followed by one

# Company legal suffixes, matched in any case ("LLC", "Corporation", "INC.").
_CO_SUFFIX = (
    r"(?i:LLP|LLC|L\.L\.C\.|L\.L\.P\.|PLLC|Inc\.|Inc|Incorporated|Corp\.|Corp|Corporation"
    r"|Ltd\.|Ltd|Limited|L\.P\.|LP|PLC|P\.C\.|PC|P\.A\.|N\.A\.|GmbH)"
)
_CO_WORD = r"[A-Z][\w'’.-]*"
_STREET_WORDS = (
    "Street St Avenue Ave Road Rd Drive Dr Lane Ln Boulevard Blvd Way Place Pl Square Sq "
    "Terrace Parkway Pkwy Pike Highway Hwy Circle Cir Plaza Trail Court Ct"
).split()
# Capitalised or ALL CAPS only: "30 days later the road closed" is not an address.
_STREET_TYPE = "(?:" + "|".join(_STREET_WORDS + [w.upper() for w in _STREET_WORDS]) + ")"
_FIRM_NAME = r"(?!(?:Esq|Jr|Sr|Inc|LLC|LLP)\b)[A-Z][\w'’-]*"
# Words that end a firm's name without being a legal suffix: "Zhang & Associates".
_CO_KIND = r"(?:Associates|Partners|Holdings|Group|ASSOCIATES|PARTNERS|HOLDINGS|GROUP)"

# (entity type, pattern). If the pattern has a group named "v", only that
# group is the sensitive value; otherwise the whole match is.
REGEX_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # SSN or ITIN (ITINs start with 9): 123-45-6789
    ("financial_id", re.compile(_B + r"(?!000|666)\d{3}-(?!00)\d{2}-(?!0000)\d{4}" + _E)),
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
    # "account at First Bank, number 123456", "savings account ending in 4410"
    (
        "financial_id",
        re.compile(
            r"\baccount\b[^.;\n]{0,60}?\b(?:no\.|no\b|number|ending[ \t]+in)\s*[:#]?\s*"
            r"(?P<v>\d(?:[ -]?\d){3,16})" + _E,
            re.IGNORECASE,
        ),
    ),
    # Other labelled identifiers: medical record, member, policy, licence, passport numbers
    (
        "financial_id",
        re.compile(
            r"\b(?:MRN|(?:Member|Patient|Policy|License|Passport|Taxpayer)[ \t]+(?:ID|No\.?|Number))"
            r"\s*[:#]?\s*(?P<v>[A-Z]{1,5}[- ]?\d[\d-]{3,}\d|\d[\d-]{4,}\d)" + _E
        ),
    ),
    # IBAN
    ("financial_id", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")),
    # Capitalised words ending in a legal suffix: "Smithson & Johnson LLP", "Acme, Inc."
    (
        "company",
        re.compile(
            _B + _CO_WORD + r"(?:[ \t]+(?:&[ \t]+)?" + _CO_WORD + r"){0,5}?,?[ \t]+"
            + r"(?=[A-Z])"  # "a Delaware limited liability company" is not a name
            + _CO_SUFFIX
            # not "General Corporation Law", "Limited Liability Company", "Gifts Limited to ..."
            + r"(?!\w)(?![ \t]+(?:Law|Act|Code|Liability|Partnership|Power|Powers|to|by|in|for)\b)"
        ),
    ),
    # Law-firm lists: "Oyelaran, Schmidt & Lindqvist PC". Each listed name is one
    # word, and "Esq."/"Jr." may not be one, so a preceding person is not swallowed.
    (
        "company",
        re.compile(
            _B + _FIRM_NAME + r"(?:,[ \t]+" + _FIRM_NAME + r")+,?[ \t]+&[ \t]+" + _CO_WORD
            + r"(?:[ \t]+" + _CO_WORD + r"){0,2}?,?[ \t]+(?=[A-Z])" + _CO_SUFFIX + r"(?!\w)"
        ),
    ),
    (
        "company",
        re.compile(
            _B + _CO_WORD + r"(?:[ \t]+" + _CO_WORD + r"){0,3}?[ \t]+(?:&[ \t]+)?" + _CO_KIND + r"(?!\w)"
        ),
    ),
    # Street line: "#1 Old Capital Square", "4120 Harbor View Drive, Suite 300"
    (
        "address",
        re.compile(
            r"(?<![\w-])#?\d{1,6}[A-Za-z]?[ \t]+(?:[A-Z0-9][A-Za-z0-9.'’-]*[ \t]+){0,4}?" + _STREET_TYPE
            + r"\b\.?(?:,?[ \t]+(?i:Suite|Ste\.?|Apt\.?|Unit|Floor|Fl\.?|Room|#)[ \t]*[\w-]+)?"
        ),
    ),
    ("address", re.compile(r"\bP\.?[ \t]?O\.?[ \t]+Box[ \t]+\d+\b", re.IGNORECASE)),
    # "City, ST 12345": the half of an address the model most often drops
    (
        "address",
        re.compile(
            _B + r"(?:[A-Z][A-Za-z]+\.?[ \t]+){0,2}[A-Z][A-Za-z]+,[ \t]+"
            r"(?:[A-Z]{2}|[A-Z][A-Za-z]+(?:[ \t]+[A-Z][A-Za-z]+)?)[ \t]+"  # OH, Ohio, NEW YORK
            r"(?:\d{5}(?:-\d{4})?|[A-Z]\d[A-Z][ \t]?\d[A-Z]\d)" + _E  # US zip or Canadian code
        ),
    ),
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
    """Find SSNs, EINs, bank account numbers, IBANs, suffixed company names,
    city/state/zip lines, emails and phone numbers."""
    found = []
    for etype, pattern in REGEX_PATTERNS:
        for m in pattern.finditer(text):
            group = "v" if "v" in pattern.groupindex else 0
            found.append(Detection(m.start(group), m.end(group), etype, "regex"))
    return found


# --------------------------------------------------------------------------
# GLiNER detector (ONNX backend, local files only)
# --------------------------------------------------------------------------

DEFAULT_MODEL_DIR = os.environ.get(
    "SANITIZER_MODEL_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "gliner"),
)

#: Label given to GLiNER -> our entity type.
GLINER_LABELS = {
    "person": "person",
    "company": "company",
    "organization": "company",
    "address": "address",
}


class ModelNotFoundError(RuntimeError):
    """The local GLiNER model is missing. Nothing is ever downloaded at runtime."""


class GlinerDetector:
    """NER detector backed by a local GLiNER ONNX model.

    GLiNER only reads a few hundred words at a time and silently ignores the
    rest, so the text is fed in overlapping windows and the spans are mapped
    back to document offsets.
    """

    def __init__(
        self,
        model_dir: str | os.PathLike | None = None,
        threshold: float = 0.3,
        window_words: int = 200,
        overlap_words: int = 40,
        model=None,
    ):
        if not 0 <= overlap_words < window_words // 2:
            raise ValueError("overlap_words must be less than half of window_words")
        self.threshold = threshold
        self.window_words = window_words
        self.overlap_words = overlap_words
        self.model = model if model is not None else self._load(model_dir or DEFAULT_MODEL_DIR)

    @staticmethod
    def _load(model_dir):
        model_dir = os.fspath(model_dir)
        onnx_file = next(
            (
                rel
                for rel in ("onnx/model.onnx", "model.onnx")
                if os.path.isfile(os.path.join(model_dir, rel))
            ),
            None,
        )
        if onnx_file is None:
            raise ModelNotFoundError(
                f"No GLiNER ONNX model in {model_dir!r}. Run scripts/fetch_model.py once "
                "while online, or set SANITIZER_MODEL_DIR. To scan with regex patterns "
                "only, pass ner=False."
            )
        # Must be set before the Hugging Face libraries are imported.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        from gliner import GLiNER

        return GLiNER.from_pretrained(
            model_dir,
            local_files_only=True,
            load_onnx_model=True,
            load_tokenizer=True,
            onnx_model_file=onnx_file,
        )

    def _windows(self, text: str) -> list[tuple[int, int]]:
        """Character ranges of at most ``window_words`` words each.

        A window ends at a paragraph break if one falls in its last quarter,
        else at a sentence end, else wherever the word limit lands. Windows
        still overlap, because "sentence end" is a guess ("Mr." ends in a dot).
        """
        words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        windows = []
        i = 0
        while i < len(words):
            j = min(i + self.window_words, len(words))
            if j < len(words):
                candidates = range(j - 1, i + self.window_words * 3 // 4 - 1, -1)
                gap = lambda k: text[words[k][1] : words[k + 1][0]]
                cut = next((k for k in candidates if gap(k).count("\n") >= 2), None)
                if cut is None:
                    cut = next(
                        (k for k in candidates if text[words[k][1] - 1] in ".?!;:" or "\n" in gap(k)),
                        None,
                    )
                if cut is not None:
                    j = cut + 1
            windows.append((words[i][0], words[j - 1][1]))
            if j >= len(words):
                break
            i = j - self.overlap_words
        return windows

    def __call__(self, text: str) -> list[Detection]:
        found = []
        for start, end in self._windows(text):
            entities = self.model.predict_entities(
                text[start:end], list(GLINER_LABELS), threshold=self.threshold
            )
            for e in entities:
                etype = GLINER_LABELS.get(e["label"])
                if etype:
                    found.append(Detection(start + e["start"], start + e["end"], etype, "ner"))
        return found


_default_detector: GlinerDetector | None = None


def default_detector() -> GlinerDetector:
    """The shared GLiNER detector, loaded on first use."""
    global _default_detector
    if _default_detector is None:
        _default_detector = GlinerDetector(DEFAULT_MODEL_DIR)
    return _default_detector


# --------------------------------------------------------------------------
# Alias resolution: do two surface forms name the same real-world entity?
# --------------------------------------------------------------------------

_COMPANY_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "llc", "llp", "lp",
    "ltd", "limited", "plc", "pllc", "pc", "na", "gmbh", "ag", "sa", "bv", "nv",
}  # fmt: skip
_HONORIFICS = {"mr", "mrs", "ms", "miss", "mx", "dr", "prof", "hon", "judge", "justice"}
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "esq", "phd", "md"}
_NAME_PARTICLES = {"van", "von", "der", "den", "de", "del", "della", "di", "da", "dos", "la", "le", "bin", "ibn", "al", "el", "ter", "ten"}

# Role words that contracts capitalise as defined terms. NER models tag them as
# people or companies, but they identify nobody.
_DEFINED_TERMS = {
    "affiant", "agent", "assignee", "assignor", "borrower", "buyer", "claimant", "client",
    "company", "declarant", "owner", "patient", "principal", "shareholder", "shareholders",
    "contractor", "consultant", "corporation", "counsel", "court", "customer", "debtor",
    "defendant", "deponent", "discloser", "employee", "employer", "executor", "firm",
    "grantee", "grantor", "guarantor", "holder", "landlord", "lender", "lessee", "lessor",
    "licensee", "licensor", "maker", "parties", "party", "payee", "petitioner", "plaintiff",
    "purchaser", "recipient", "respondent", "seller", "settlor", "tenant", "trustee",
    "undersigned", "vendor", "witness",
}  # fmt: skip

# Vocabulary that legal drafting capitalises without naming anyone: roles,
# offices, trust and share labels, statutes and agencies. A span made only of
# these words (plus function words) is a defined term, not a name.
_LEGAL_VOCABULARY = _DEFINED_TERMS | {
    "administrator", "administrative", "advisor", "adviser", "appraiser", "attorney", "fact",
    "beneficiary", "board", "chairman", "chief", "child", "children", "co", "conservator",
    "corporate", "custodian", "deceased", "decedent", "descendant", "designated", "director",
    "doctor", "donor", "entity", "estate", "executive", "exempt", "nonexempt", "family",
    "fiduciary", "fiduciaries", "financial", "first", "second", "third", "one", "two", "fund",
    "governmental", "authority", "guardian", "heir", "husband", "wife", "spouse", "incapacitated",
    "independent", "individual", "initial", "institution", "insured", "interested", "investment",
    "legal", "living", "manager", "managing", "marital", "non", "member", "nominee", "officer",
    "operating", "partner", "person", "personal", "president", "vice", "primary", "protector",
    "qualified", "representative", "residuary", "secretary", "share", "skip", "special", "needs",
    "successor", "survivor", "surviving", "testamentary", "testator", "transferee", "transferor",
    "treasurer", "trust", "trustor", "unitrust", "revocable", "irrevocable", "charitable",
    "remainder", "heritage", "contributing", "community", "institutionalized", "protected",
    "additional", "service", "provider", "electing", "small", "business", "life", "insurance",
    "health", "care", "proxy", "program", "user", "name", "address", "location", "portfolio",
    # statutes, agencies, tax and benefit terms
    "internal", "revenue", "code", "treasury", "congress", "government", "administration",
    "social", "security", "disability", "medicaid", "medicare", "veterans", "u.s", "us",
    "irs", "ira", "qtip", "qsst", "cpa", "sep", "keogh", "gpoa", "csra", "state", "federal",
    "department", "agency", "commission", "bureau", "act", "law", "section", "article",
}  # fmt: skip

_DETERMINERS = {
    "a", "an", "my", "our", "your", "his", "her", "their", "its", "each", "every", "any",
    "such", "no", "this", "that", "these", "those", "said", "another", "other",
}  # fmt: skip


def _is_vocabulary(word: str, lowercase_words: set[str] = frozenset()) -> bool:
    """Is this word (or every hyphenated part of it) ordinary or legal vocabulary?"""
    for part in word.casefold().replace("’", "'").split("-"):
        part = re.sub(r"'s$", "", part)
        singular = re.sub(r"(?<=[a-z]{3})(?:ies$)", "y", part)
        singular = re.sub(r"(?<=[a-z]{3})s$", "", singular)
        if not part or any(
            w in _LEGAL_VOCABULARY or w in _GENERIC_LEADING_WORDS or w in _FUNCTION_WORDS or w in lowercase_words
            for w in (part, singular)
        ):
            continue
        return False
    return True


# Never a name, or part of one, on their own.
_FUNCTION_WORDS = {
    "a", "an", "the", "of", "and", "or", "for", "to", "in", "on", "at", "by", "with", "from",
    "i", "me", "my", "mine", "we", "us", "our", "ours", "you", "your", "yours", "he", "him",
    "his", "she", "her", "hers", "they", "them", "their", "theirs", "it", "its", "this", "that",
    "these", "those", "any", "each", "every", "all", "no", "such", "other", "another", "said",
    "who", "whom", "whose", "which", "if", "as", "is", "are", "be", "not", "ref",
}  # fmt: skip

# First words too generic to stand for a company on their own.
_GENERIC_LEADING_WORDS = {
    "the", "first", "american", "united", "national", "general", "new", "north", "south",
    "east", "west", "international", "global", "city", "state", "bank", "law", "saint", "st",
    "old", "great", "royal", "federal", "central", "pacific", "atlantic",
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "hampshire",
    "jersey", "mexico", "york", "carolina", "dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode", "island", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "wisconsin", "wyoming", "columbia", "america", "states",
}  # fmt: skip


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
        # Keep hyphens: SSN 123-45-6789 and EIN 12-3456789 are different numbers.
        return re.sub(r"\s", "", value.casefold())
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


def _is_generic(d: Detection, span: str, lowercase_words: set[str]) -> bool:
    """True if a model-found span is ordinary vocabulary rather than a name.

    NER models tag role words and defined terms ("my Trustee", "beneficiary",
    "the Marital Trust") as people and companies. A span is kept only if it
    has a capitalised word that is not a known role word and that the document
    never also writes in lower case. So "Ulysses S Grant" survives a trust that
    says "I grant" (because of "Ulysses"); "Marital Share" does not.
    """
    if d.type not in ("person", "company"):
        return False
    words = re.findall(r"[^\W\d_][\w.'’-]*", span)
    if d.source == "propagated" and d.type == "person":
        # A bare surname or first name derived from a full name that passed. Kept
        # even if the document also uses it as an ordinary word ("Grant", "Will"),
        # but not if it is legal vocabulary ("Trustee" from "Jane Roe, Trustee").
        return all(w.rstrip(".").casefold() in _LEGAL_VOCABULARY | _FUNCTION_WORDS for w in words)
    if words and words[0].casefold() in _DETERMINERS:
        return True  # "my Trustee", "each Trustor": names do not start this way
    return not any(
        w[0].isupper() and not _is_vocabulary(w.rstrip("."), lowercase_words) for w in words
    )


def _clean_spans(text: str, detections: Iterable[Detection]) -> list[Detection]:
    """Validate and trim spans, then drop overlaps (longest wins, regex beats NER)."""
    lowercase_words = set(re.findall(r"(?<![\w'’-])[a-z][a-z'’-]+(?![\w'’-])", text))
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
        if start >= end or PLACEHOLDER_RE.search(text[start:end]):
            continue
        if d.source != "regex" and _is_generic(d, text[start:end], lowercase_words):
            continue  # "my Trustee", "trust", "Marital Share", "Employee"
        if d.source == "regex" and d.type == "company":
            # "See Group", "Survivor Limited": a heading that happens to end in a
            # word firms use. Unambiguous suffixes (LLC, Inc., N.A.) are never dropped.
            weak = re.search(r"[,\s]+(?:&\s+)?(?:Limited|LIMITED|Company|COMPANY|" + _CO_KIND + r")$", text[start:end])
            if weak and _is_generic(
                Detection(start, start + weak.start(), "company"), text[start : start + weak.start()], lowercase_words
            ):
                continue
        if d.type in ("person", "company"):
            bare = text[start:end]
            if d.type == "company" and re.search(r"\bCourt\b", bare):
                continue  # courts are public bodies, not parties
            if d.type == "company" and re.search(r"\b(?:corporation|company|partnership)$", bare):
                continue  # "Delaware corporation" describes an entity, it does not name one
        cleaned.append(Detection(start, end, d.type, d.source, d.alias_of))

    kept: list[Detection] = []
    by_priority = sorted(cleaned, key=lambda d: (d.start - d.end, d.source != "regex", d.start))
    for d in by_priority:
        if all(d.end <= k.start or d.start >= k.end for k in kept):
            kept.append(d)
    kept.sort(key=lambda d: d.start)

    # "742 Evergreen Terrace" + ", " + "Springfield, IL 62704" is one address.
    merged: list[Detection] = []
    for d in kept:
        prev = merged[-1] if merged else None
        if (
            prev
            and prev.type == d.type == "address"
            and re.fullmatch(r",?[ \t]*\n?[ \t]*", text[prev.end : d.start])
        ):
            merged[-1] = Detection(prev.start, d.end, "address", prev.source)
        else:
            merged.append(d)
    # A model-found "address" with no digit after merging is a bare place name
    # or a label ("State of Arizona", "Address"): it identifies nobody.
    return [
        d
        for d in merged
        if not (
            d.type == "address"
            and d.source != "regex"
            and not re.match(r"(?=.*\d)(?=.*[A-Za-z]{3})[#\dA-Z]", text[d.start : d.end], re.DOTALL)
        )
    ]


def _short_forms(etype: str, value: str) -> list[str]:
    """Shorter names a known entity is likely to be called by elsewhere in a text."""
    if etype == "person":
        words = re.findall(r"[\w'’-]+", value)
        while len(words) > 1 and words[-1].casefold() in _NAME_SUFFIXES:
            words.pop()
        while len(words) > 1 and words[0].casefold() in _HONORIFICS:
            words.pop(0)
        if len(words) < 2:
            return []
        # Surname and first name; initials and two-letter tokens are skipped.
        forms = [w for w in (words[-1], words[0]) if len(w) >= 3 and w[0].isupper()]
        # "Pieter van der Meer" is later "Mr. van der Meer", not "Mr. Meer".
        k = len(words) - 1
        while k > 1 and words[k - 1].casefold() in _NAME_PARTICLES:
            k -= 1
        if k < len(words) - 1:
            m = re.search(r"\b" + r"\W+".join(map(re.escape, words[k:])), value)
            if m:
                forms.insert(0, m.group(0))
        return forms
    if etype == "company":
        core = re.sub(
            r"(?:[,\s]+(?:&\s+)?(?:" + _CO_SUFFIX + "|" + _CO_KIND + r"))+$", "", value
        )
        forms = [core] if core != value else []
        # Leading words: "Cedar Ridge Properties LLC" is later just "Cedar Ridge".
        words = core.split()
        for n in range(len(words) - 1, 0, -1):
            if words[n - 1] in ("&", "of", "and") or words[n] == "&":
                continue
            forms.append(" ".join(words[:n]).rstrip(","))
        return [
            f
            for f in forms
            if len(f) >= 3 and f[0].isupper() and f.casefold() not in _GENERIC_LEADING_WORDS
        ]
    return []


def _short_forms_any_case(etype: str, value: str) -> list[str]:
    """Short forms, plus title-case versions for names given in capitals:
    "PINNACLE TITLE & ESCROW, INC." in a signature block is "Pinnacle" in the body."""
    forms = _short_forms(etype, value)
    return forms + [f.title() for f in forms if f.isupper() and f.title() != f]


def _propagate(text: str, known: Iterable[tuple[str, str]]) -> list[Detection]:
    """Tag short forms of known names that the model missed.

    NER models are confident about "John A. Smith" and "Cedar Ridge Properties
    LLC" but often skip a later bare "Smith", "John" or "Cedar Ridge".
    ``known`` is (type, value) pairs from this text and from the vault.
    """
    parents: dict[tuple[str, str], set[str]] = {}
    for etype, value in known:
        for short in _short_forms_any_case(etype, value):
            parents.setdefault((etype, short), set()).add(value)

    extra = []
    for (etype, short), values in parents.items():
        # Only a company short form is tied to its parent here; for people the
        # ambiguity rules in _find_entity decide (two Smiths, one bare "Smith").
        alias_of = next(iter(values)) if etype == "company" and len(values) == 1 else ""
        for m in re.finditer(r"(?<!\w)" + re.escape(short) + r"(?!\w)", text):
            extra.append(Detection(m.start(), m.end(), etype, "propagated", alias_of))
    return extra


def scan_text(
    text: str,
    existing_vault: dict | None = None,
    ner: NerDetector | bool | None = None,
) -> dict:
    """Detect sensitive entities and propose placeholder mappings for the new ones.

    ``ner`` selects the name/company/address detector. ``None`` (default) uses
    the local GLiNER model and raises :class:`ModelNotFoundError` if it is not
    installed, rather than quietly missing every name. ``False`` runs the regex
    patterns only. Any ``text -> [Detection]`` callable can be passed instead.

    Neither ``text`` nor ``existing_vault`` is modified. Returns::

        {"proposed": {placeholder: {"type", "value", "entity", "source"}},  # new mappings
         "matched":  [placeholder, ...],   # existing vault entries seen in this text
         "warnings": [str, ...]}

    Numbering is deterministic: entities are numbered in order of first
    appearance (detected names first, then short forms derived from them),
    continuing from the highest number already in the vault.
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
    if ner is None or ner is True:
        ner = default_detector()
    if ner:
        detections.extend(ner(text))

    spans = _clean_spans(text, detections)
    known = [(e["type"], e["value"]) for e in _mappings(existing_vault).values()]
    known += [(d.type, text[d.start : d.end]) for d in spans]
    spans = _clean_spans(text, spans + _propagate(text, known))
    # Full names first, so that short forms can be linked to them.
    spans.sort(key=lambda d: (d.source == "propagated", d.start))

    proposed: dict[str, dict] = {}
    matched: list[str] = []
    for d in spans:
        value = text[d.start : d.end]
        if value in value_to_placeholder:
            placeholder = value_to_placeholder[value]
            if placeholder not in proposed and placeholder not in matched:
                matched.append(placeholder)
            continue

        entity_id = _find_entity(d.type, value, entities)
        if entity_id is None and d.alias_of:
            entity_id = next(
                (eid for eid, e in entities.items() if d.alias_of in e["values"]), None
            )
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


def find_vault_spans(text: str, vault: dict) -> list[tuple[int, int, str]]:
    """Where each vault value occurs in ``text``: (start, end, placeholder).

    One regex pass, longest value first, whole words only: "John" never fires
    inside "Johnson", and "Acme" never eats the start of "Acme Holdings LLC"
    when both are in the vault. Placeholders already in the text are skipped.
    """
    index = _value_index(vault)
    if not index:
        return []

    def bounded(value: str) -> str:
        # Word boundaries only where the value itself starts/ends with a word char.
        left = r"(?<!\w)" if re.match(r"\w", value[0]) else ""
        right = r"(?!\w)" if re.match(r"\w", value[-1]) else ""
        return left + re.escape(value) + right

    longest_first = sorted(index, key=lambda v: (-len(v), v))
    pattern = re.compile(
        "(" + PLACEHOLDER_RE.pattern + ")|" + "|".join(bounded(v) for v in longest_first)
    )
    return [
        (m.start(), m.end(), index[m.group(0)]) for m in pattern.finditer(text) if not m.group(1)
    ]


def apply_vault(text: str, vault: dict) -> str:
    """Replace every vault value in ``text`` with its placeholder.

    Matching rules are those of :func:`find_vault_spans`. Placeholders already
    present are left alone, so applying twice is the same as applying once.
    """
    out, pos = [], 0
    for start, end, placeholder in find_vault_spans(text, vault):
        out += [text[pos:start], placeholder]
        pos = end
    return "".join(out) + text[pos:]


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
