# Replace-o-matic: build plan

Offline pseudonymization for legal documents. Real names and numbers are swapped
for placeholders (`[PERSON_1]`, `[COMPANY_1]`, ...) before text leaves the
machine, and swapped back afterwards using a local JSON vault.

## Status

| Step | What | Status |
|---|---|---|
| 1 | Deterministic core: vault, regex detectors, `scan_text`, `apply_vault`, `rehydrate_text`, alias linking, pytest suite | **Done** |
| 2 | GLiNER (ONNX) detector plugged into `scan_text`; offline model provisioning | Next |
| 3 | Long-document handling and detection quality | Planned |
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

## Step 2: GLiNER detector (next)

- `GlinerDetector` class implementing the `ner=` callable: labels `person`,
  `company`, `address`; score threshold; maps model output to `Detection`.
- Load from a local directory only, with `HF_HUB_OFFLINE=1` and
  `local_files_only=True`, and fail loudly if the model is missing.
- `scripts/fetch_model.py`: the one deliberate online action, run once on a
  connected machine, to download an ONNX GLiNER model into `models/`.
- Integration tests marked `@pytest.mark.model`, skipped when no model is present.

Two things to settle at the start of this step:

- **Model download.** This sandbox blocks huggingface.co. Either the environment
  allows it, or the model files are supplied another way.
- **`gliner` pulls in PyTorch** (about 2 GB) even when inference runs on ONNX. If
  install size matters, the alternative is to drive the ONNX file directly with
  `onnxruntime` + `tokenizers`, at the cost of reimplementing GLiNER's span
  decoding.

## Step 3: long documents and quality

- Chunk long texts with overlap (GLiNER's window is a few hundred tokens) and
  merge spans back to document offsets.
- Propagation: once a name is detected anywhere, tag every other occurrence.
- A small labelled set of realistic legal passages to measure recall and tune
  the threshold. Missed entities are the failure that matters.

## Step 4: vault hardening and CLI

- Encrypt the vault at rest.
- CLI: `scan`, `review`, `apply`, `rehydrate`.
- Post-apply leak check: fail if any vault value is still present in the output.
