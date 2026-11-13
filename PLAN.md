# Replace-o-matic: build plan

Offline pseudonymization for legal documents. Real names and numbers are swapped
for placeholders (`[PERSON_1]`, `[COMPANY_1]`, ...) before text leaves the
machine, and swapped back afterwards using a local JSON vault.

## Status

| Step | What | Status |
|---|---|---|
| 1 | Deterministic core: vault, regex detectors, `scan_text`, `apply_vault`, `rehydrate_text`, alias linking, pytest suite | **Done** |
| 2 | GLiNER (ONNX) detector plugged into `scan_text`; offline model provisioning | **Code done; not yet run against the real model** |
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

## Step 2: GLiNER detector (code done, real-model run pending)

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

Still to do, once huggingface.co is reachable from the dev environment:

1. Run `python scripts/fetch_model.py`, then `pytest -m model`.
2. Confirm the model repo's file layout matches what the loader expects
   (`onnx/model.onnx` plus config and tokenizer files), and adjust if not.
3. Sanity-check the 0.4 threshold on a few realistic passages.

The `gliner` package was chosen over driving `onnxruntime` directly. It brings
PyTorch along (the venv is about 5.5 GB), which is accepted.

## Step 3: long documents and quality

- Smarter chunking: break windows at paragraph or sentence boundaries.
- Propagation: once a name is detected anywhere, tag every other occurrence.
- A small labelled set of realistic legal passages to measure recall and tune
  the threshold. Missed entities are the failure that matters.

## Step 4: vault hardening and CLI

- Encrypt the vault at rest.
- CLI: `scan`, `review`, `apply`, `rehydrate`.
- Post-apply leak check: fail if any vault value is still present in the output.
