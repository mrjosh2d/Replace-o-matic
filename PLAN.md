# Replace-o-matic: build plan

Offline pseudonymization for legal documents. Real names and numbers are swapped
for placeholders (`[PERSON_1]`, `[COMPANY_1]`, ...) before text leaves the
machine, and swapped back afterwards using a local JSON vault.

## Status

| Step | What | Status |
|---|---|---|
| 1 | Deterministic core: vault, regex detectors, `scan_text`, `apply_vault`, `rehydrate_text`, alias linking, pytest suite | **Done** |
| 2 | GLiNER (ONNX) detector plugged into `scan_text`; offline model provisioning; surname and company-name propagation | **Done** |
| 3 | Long-document handling and detection quality: labelled passages, measurement script, gap fixes | **Done** |
| 4 | Vault hardening and a CLI | Planned |

## Step 1: deterministic core (done)

`sanitizer_core.py`, standard library only.

- `scan_text(text, existing_vault, ner=None)` returns proposed mappings, vault
  entries it recognised, and warnings. It changes nothing.
- `merge_vault(vault, proposed)` accepts reviewed proposals into a new vault.
- `apply_vault(text, vault)` and `rehydrate_text(text, vault)`: single regex pass,
  longest value first, whole words only.
- `load_vault` / `save_vault`: atomic write, owner-only permissions.
- Regex detectors: SSN, EIN, keyword-anchored bank account and routing numbers,
  IBAN, email, US phone.
- NER is a plug-in point (`ner=` takes any `text -> [Detection]` callable). The
  tests use a stub, so the suite is fast and exact, and needs no model.

Run the tests:

```
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest
```

### Design decisions

1. **One placeholder per surface form.** `Acme Corporation` is `[COMPANY_1]`,
   `Acme Corp.` is `[COMPANY_1_ALIAS_1]`. Mapping both to `[COMPANY_1]` would
   make re-hydration guess which spelling was in the original. The shared
   number still shows they are the same entity.
2. **Matching is case-sensitive and exact**, for the same reason.
   `ACME CORPORATION` in a heading becomes its own alias.
3. **Alias linking is conservative.**
   - Companies link when they differ only by legal suffix, case or punctuation.
     `Acme Holdings LLC` and `Acme Inc.` stay separate.
   - A bare first or last name links to a full name only when exactly one known
     person fits. With John Smith and Mary Smith in play, `Smith` gets its own
     number.
   - Identifiers link when they differ only in formatting.
4. **Email and phone get their own types** (`[EMAIL_1]`, `[PHONE_1]`) instead of
   being folded into `financial_id`. SSN, EIN and bank numbers are `financial_id`.
5. **Overlapping detections:** the longest span wins; regex beats NER on a tie.

### Known limits

- A name split across a line break is a different string from the same name on
  one line. Each needs its own vault entry.
- Defined terms (`the "Company"`, `"Landlord"`) are not treated as sensitive.
- `apply_vault` replaces a vault value everywhere it appears as a whole word. A
  person named `Will` or `Grant` will also redact the ordinary word. Round-trip
  stays exact; the sanitized text just reads oddly. Review proposals for these.
- If an LLM rewrites a placeholder (`[person_1]`, `PERSON 1`), re-hydration will
  not recognise it.

## Step 2: GLiNER detector (done)

- `GlinerDetector` in `sanitizer_core.py`: labels `person`, `company`,
  `organization` (mapped to company), `address`; score threshold 0.4.
- Loads from `models/gliner` (or `SANITIZER_MODEL_DIR`) with
  `local_files_only=True` and `HF_HUB_OFFLINE=1`. Nothing is downloaded at runtime.
- `scan_text` now uses GLiNER by default. If the model is missing it raises
  `ModelNotFoundError` instead of quietly returning regex hits only, because a
  silent fallback would let every name through. Pass `ner=False` for regex only.
- Long texts are fed to the model in overlapping 200-word windows (40-word
  overlap), since GLiNER ignores input past its limit.
- `scripts/fetch_model.py`: the one deliberate online action. Downloads
  `onnx-community/gliner_small-v2.1` into `models/` (gitignored). Download only.
- `tests/test_gliner_detector.py`: windowing, offsets and label mapping against
  a fake model, plus one real-model test (marked `model`) that also blocks
  sockets to prove inference is offline. It skips until the model is present.

Verified against the real model (`gliner_small-v2.1`, 611 MB ONNX file, about
8 s to load and 0.2 s per window on CPU): the sample agreement in the tests is
fully redacted and round-trips exactly, with sockets blocked.

That first real run showed what the model misses, and three fixes went in:

- **Bare surnames and short company names.** The model scored "John A. Smith"
  at 0.95 but a later bare "Smith" at 0.27, below the threshold. Now, once a full
  name or a suffixed company name is known (from this text or the vault), every
  whole-word occurrence of the surname or the suffix-less company name is tagged.
- **Companies with a legal suffix** ("Smithson & Johnson LLP") are also caught
  by regex, since the model missed that one entirely.
- **Address parts** the model returns separately (street; city, state, zip) are
  merged into one address when they are adjacent.

Also fixed: an SSN and an EIN with the same digits were treated as one ID.

Downloading needs these hosts: `huggingface.co` and `us.aws.cdn.hf.co` (the CDN
that serves the large files).

The `gliner` package was chosen over driving `onnxruntime` directly. It brings
PyTorch along (the venv is about 5.5 GB), which is accepted.

## Step 3: long documents and detection quality (done)

**Windowing.** A window now ends at a paragraph break if one falls in its last
quarter, else at a sentence end. Windows still overlap by 40 words.

**Measurement.** `tests/eval/` holds labelled, invented legal passages, and
`scripts/evaluate.py` reports what survives redaction:

```
.venv/bin/python scripts/evaluate.py -v                  # tuning set, list misses
.venv/bin/python scripts/evaluate.py -f holdout.json -v  # second set
.venv/bin/python scripts/evaluate.py -t 0.2 0.3 0.4 0.5  # compare thresholds
```

| Set | Passages | Labelled mentions | Sensitive characters redacted | Mentions leaked | Over-redactions |
|---|---|---|---|---|---|
| `passages.json`, before fixes (threshold 0.4) | 16 | 230 | 89.0% | 34 | 7 |
| `passages.json`, after fixes | 16 | 230 | 100% | 0 | 0 |
| `holdout.json`, first run, unseen | 10 | 184 | 90.2% | 24 | 8 |
| `holdout.json`, after a second round of fixes | 10 | 184 | 99.5% | 3 | 1 |

How to read this: **90% is the honest figure for text the rules have never
seen**, and it was measured before the second round of fixes. Both sets have
now been used for tuning, so the 99-100% rows show the fixes work on these
passages, not what to expect on a new document. A fresh held-out set is needed
to measure again. All passages were written by a model, not taken from real
filings, so real documents will be messier.

**What the fixes were.** All are general rules, none are specific to a passage:

- Threshold lowered from 0.4 to 0.3 (fewer misses, no extra false hits on the
  tuning set; 0.2 started tagging job titles and "STATE OF FLORIDA").
- Short forms of known names are tagged wherever they appear as whole words:
  surname, first name, surname with particles ("van der Meer"), a company's
  leading words ("Cedar Ridge" from "Cedar Ridge Properties LLC"), and the
  title-case form of an ALL-CAPS name.
- New regexes: "City, State 12345" lines (two-letter or spelled-out state,
  Canadian postal codes), firm names ending in Associates/Partners/Group/
  Holdings, law-firm lists ("A, B & C PC"), account numbers introduced loosely
  ("account at First Bank, number ..."; "ending in 4410"), labelled IDs (MRN,
  member, policy, licence, passport numbers), and ITINs (9xx-xx-xxxx).
- Filters: capitalised defined terms ("Employee", "the Borrower", "Claimant"),
  courts, and descriptions like "Delaware corporation" are not names.

**Still missed**

- Nicknames that are not part of the full name ("Gerry" for Gerard, "Seun" for
  Oluwaseun). Nothing ties them to the person except context.
- A country name trailing an address (", Canada").
- Anything the model misses that has no full form elsewhere to propagate from.

**Costs of the new rules**

- First-name propagation means a person named Will, Grant or Mark also redacts
  that ordinary word when capitalised. Round-trip stays exact.
- A company's first word is redacted on its own ("Orion" from "Orion Tools
  Corp."), except for a short list of generic words (First, National, United...).
- Organisations that are not parties ("American Arbitration Association") are
  redacted like any other company.

## Step 4: vault hardening and CLI

- Encrypt the vault at rest.
- CLI: `scan`, `review`, `apply`, `rehydrate`.
- Post-apply leak check: fail if any vault value is still present in the output.
