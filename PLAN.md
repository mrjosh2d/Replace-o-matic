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
| 4 | Human review, "I'm feeling lucky", encrypted vault, command-line tool, .docx/PDF input | **Done** |
| 5 | .docx in, .docx out with formatting kept; headers, footers, footnotes, endnotes, comments | **Done** |
| 6 | Labelled measurement on real documents; web addresses, middle names, bank names | **Done** |
| 7 | Key document: confidential and safe placeholder tables | **Done** |
| 8 | Altered placeholders tolerated on re-hydration; redacted PDF output | **Done** |

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
4. **Email, phone and web address get their own types** (`[EMAIL_1]`, `[PHONE_1]`,
   `[URL_1]`) instead of being folded into `financial_id`. SSN, EIN and bank numbers are `financial_id`.
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

**Real sample documents.** Five long estate-planning and LLC documents (vendor
samples with invented parties, about 206,000 words; kept out of the repo) were
run through the pipeline. They exposed what the short passages could not:
massive over-redaction. The model tags role words and defined terms as people
and companies ("trust" 534 times in one document, "my Trustee", "beneficiary",
"I"), and propagation then spread fragments such as "The" and "Agreement".

| Across the five documents | Proposed vault entries | Replacements made |
|---|---|---|
| Before the vocabulary filter | 1,074 | 19,313 |
| After | 110 | 427 |

After the filter the proposals are mostly real names, and no party name from
the documents survives in the output. One letterhead address leaked and was
fixed. These documents have no labels, so there is no recall percentage for
them: leaks were looked for by searching the redacted text for the known
names and by reading what capitalised text remained.

How the filter decides (model-found spans only; regex hits are not filtered):

- A span starting with a determiner or possessive ("my Trustee", "each
  Trustor") is never a name.
- Otherwise it must contain a capitalised word that is not legal vocabulary
  (a built-in list of roles, trust and share labels, statutes, agencies) and
  that the document never also writes in lower case. "Ulysses S Grant" passes
  in a trust that says "I grant", because of "Ulysses". "Marital Share" fails.
- A model-found address needs a digit and must start with a capital or digit.
- Regex company hits ending in a weak word (Limited, Group, Company...) are
  dropped if the rest is ordinary vocabulary ("See Group", "Survivor Limited").

Also added from these documents: street lines ("#1 Old Capital Square",
with suite or unit), PO boxes, ALL-CAPS city/state/zip lines, and joining of
overlapping address pieces.

**Risk introduced by the filter:** a person whose every name is also an
ordinary word used in lower case in the same document, or legal vocabulary
("Grant Banks" in a document that says "grant" and "banks"; "Chief Justice"),
will be dropped unless a regex catches them. Review is the backstop.

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
- Organisations that are not parties ("American Arbitration Association",
  "American Cancer Society") are redacted like any other company.
- What still gets proposed wrongly on the real documents: form labels
  ("Husband (H)", "Clergyman/Rabbi"), acronyms (RUFADAA, MMMNA), and some
  capitalised trust types ("Charitable Lead Trust"). These are for the reviewer
  to decline.

## Step 4: review, encryption and the command-line tool (done)

```
.venv/bin/python sanitizer_cli.py sanitize contract.docx --vault matter.vault
.venv/bin/python sanitizer_cli.py sanitize contract.docx --vault matter.vault --lucky
.venv/bin/python sanitizer_cli.py rehydrate answer.txt --vault matter.vault
.venv/bin/python sanitizer_cli.py vault --vault matter.vault [--show-values]
```

**Review.** `sanitize` scans, then shows each new item with its type, how often
it appears and a snippet of context. For each one: accept, decline, edit the
text to redact, change its type, or accept all the rest. Afterwards the
reviewer can type in anything the scan missed (it must appear in the document).
Quitting saves nothing. Declined values are remembered in the vault and not
proposed again for that matter.

**"I'm feeling lucky."** Offered as the second choice at the first prompt, and
as `--lucky`. It accepts everything the scan found with no review. The items
are marked `"reviewed": false` in the vault, `vault` reports how many there
are, and the run ends with a warning that the scan misses things.

**Encryption.** The vault file is AES-256-GCM, with the key derived from a
passphrase by scrypt. A wrong passphrase or a tampered file is refused. The
command-line tool will not use a plaintext vault. The passphrase is asked for
each time, or read from `REPLACE_O_MATIC_PASSPHRASE` for scripted use.
Changing to an operating-system keychain later is small: `save_vault` and
`load_vault` already accept a raw `key=` in place of a passphrase, and the
file format is the same.

**File formats.** Reads .txt, .docx and text PDFs (see step 5 for .docx).
A PDF's line breaks can fall inside a name, which then becomes a separate
vault entry.

**Checks on every run.** Round-trip is verified before the output is written.
Vault values that still appear in a different letter case are listed.

### Telemetry in onnxruntime (found and blocked)

Running the tool showed `onnxruntime` 1.31 trying to contact a Microsoft
telemetry server (`mobile.events.data.microsoft.com`) a few seconds after the
model loads. It is usage telemetry built into the library, not document text,
but it is a network call at runtime and breaks the first hard rule.

- `sanitizer_core` now sets `ORT_DISABLE_TELEMETRY=1` when it is imported, before
  any model library loads. That switch stops it; calling
  `disable_telemetry_events()` after import does not.
- If `onnxruntime` was already imported without the switch, loading the model
  raises an error.
- A test traces the whole process with `strace` during a real scan and fails on
  any outbound connection. The earlier "offline" test only patched Python's
  sockets and could not see a native library, which is why this was missed.
- In this project's sandbox every attempt was refused by the network proxy, so
  nothing was sent. Anyone who ran an earlier commit on an open network would
  have sent onnxruntime's usage telemetry.

## Step 5: .docx in, .docx out (done)

`docx_io.py`. A .docx given to `sanitize` or `rehydrate` now comes back as a
.docx (`-o something.txt` still gives plain text).

- **Everything with text is read and redacted:** body, tables, headers,
  footers, footnotes, endnotes, comments, and text deleted under Track Changes
  (it is still in the file).
- **Formatting is kept.** Word splits a paragraph into runs wherever formatting
  changes, so one name can sit across several XML nodes. Edits are written back
  into the original nodes; no run, style or layout element is added or removed.
  Parts with no change are copied byte for byte.
- **Author metadata is blanked** in the redacted file: creator, last-modified-by,
  company, manager, and the author names on comments and tracked changes.
  These are not restored by `rehydrate`.
- **Checked on every run:** the written file is read back and must contain no
  vault value, or it is deleted and the run fails.

Tried on the 21,000-word Will sample (71 parts, 54 of them headers and
footers): 85 replacements, no party name left, same 78 pages before and after
when opened in LibreOffice, 10 of 71 parts changed.

Limits:

- A value that spans a line or paragraph break (a two-line letterhead address)
  is replaced by one placeholder in the first line, and the break stays. After
  `rehydrate` the full value sits on that first line.
- Text inside embedded objects (charts, embedded spreadsheets, images) is not
  touched. Field codes and hyperlink targets are not touched, only visible text.
- Opened in LibreOffice here; the owner confirmed it looks right in Microsoft Word. With bank names caught, the reviewed-label score is 83 of
88 labels and 98.2% of sensitive characters.

## Step 6: labelled measurement on real documents (done)

Labels for the five sample documents were drafted without using the tool's own
decisions, then reviewed by the owner:

1. Candidates per document: everything the raw model flags at threshold 0.15
   (no filters), every regex hit, every capitalised phrase and every long
   number. 3,651 distinct candidates.
2. Three subagents classified them as sensitive or not, working from the
   candidate lists only.
3. Rows that merely contain a shorter sensitive row plus ordinary words
   ("John Doe's Social Security Number") were dropped, leaving 88 labels.
4. The owner reviewed the sheet: one text correction, and two notes (a firm's
   tagline being only partly caught is acceptable; a firm name inside a web
   address is hard and context-dependent).

The label sheets hold text from the sample documents, so they are kept out of
the repository. `scripts/evaluate_labels.py` scores the tool against a sheet.

| Against the reviewed labels (88) | Labels fully caught | Sensitive characters redacted |
|---|---|---|
| Before the fixes below | 79 | 97.0% |
| After | 82 | 97.7% |

Fixed from this measurement:

- **Web addresses** are now detected as their own type (`[URL_1]`), so a firm
  name inside `www.AFT.com` goes with it.
- **Middle names:** two pieces of a person's name with one or two capitalised
  words between them are joined ("Chester Alan Arthur" when "Chester" and
  "Arthur" were known), and a middle initial is matched to a middle name.
- **Trust companies** ("The Depository Trust Company") are caught by pattern.

Still not fully caught:

- The firm's tagline under its name (accepted by the owner as partial).
- "The Depository Trust Company" where a PDF line break falls inside it.
  Names broken across PDF lines are a general limit of pattern matching.
- "FAMILY WEALTH TRUST" on its own (the forms with "Doe" are caught): it is
  ordinary vocabulary to the filter.

Decided by the owner afterwards: "U.S. Bank" counts as sensitive, as the safe
call. Bank names are now matched by shape ("U.S. Bank", "First Prairie Bank",
"Bank of America, N.A."), with generic phrases ("The Bank", "Federal Reserve
Bank") filtered out. The owner also confirmed the redacted .docx looks right
in Microsoft Word.

How far to trust these figures: the documents are vendor samples with invented
parties, they contain almost no identifiers (no SSNs, account numbers or
emails), and the labels have now been used to fix things. They show the tool
handles this kind of estate-planning document well; they do not replace the
90% unseen-text figure from step 3 for documents of a new kind.

## Step 7: key document (done)

```
.venv/bin/python sanitizer_cli.py key contract.sanitized.docx --vault matter.vault
```

Writes two tables of what each placeholder stands for, with aliases listed
under their entity and a "Same as" column pointing at it:

- **Confidential key** (`<document>.key.docx`): placeholder, type, real value,
  same-as, and how many times it appears. It holds the real names, so it is as
  sensitive as the vault: marked CONFIDENTIAL at the top, written owner-only,
  gitignored. It must never be sent with the sanitized document.
- **Safe key** (`<document>.key-safe.docx`): the same table without the real
  values. It can accompany the sanitized text, so a reader or an LLM knows that
  `[PERSON_1_ALIAS_1]` is the same person as `[PERSON_1]`.

Given a document (sanitized or original), only its placeholders are listed, in
order of first appearance. With no document the whole vault is listed.
`--format csv` or `txt`, `--confidential-only`, `--safe-only`.

## Step 8: altered placeholders and redacted PDFs (done)

**Altered placeholders.** Text that has been through an LLM or a Markdown
renderer often comes back with placeholders respelled. `rehydrate` now
restores `[person_1]`, `[Person 1]`, `[PERSON-1]`, `\[PERSON\_1\]`,
`[ PERSON_1 ]` and the bare `PERSON_1`, and lists the altered forms it found.
`--strict` restores exact spellings only. In `sanitizer_core`,
`rehydrate_text(..., tolerant=True)` turns it on; the default stays exact,
because exact matching is what the round-trip guarantee rests on.

**Redacted PDFs.** With PyMuPDF installed, a PDF given to `sanitize` comes
back as a PDF (`pdf_io.py`):

- The sensitive text is deleted from the page content, not covered, and the
  placeholder is printed where it was. The raw file no longer contains it.
- Document metadata is cleared (the SCRUT sample named a real author there).
- Text is read a paragraph at a time, so a name that wraps onto the next line
  is one string. This also removes the "PDF line break inside a name" limit
  noted in steps 4 and 6.
- The written file is read back and must contain no vault value.
- PyMuPDF makes no network connection (checked with `strace` during a redaction).

With PDFs read this way, the reviewed-label score is 84 of 88 labels and 98.5%
of sensitive characters. What is left is the firm's tagline (accepted as
partial by the owner) and "FAMILY WEALTH TRUST" without a name.

Limits of PDF output:

- A placeholder is usually longer than the name it replaces, so it is printed
  in a smaller, plain font to fit the space.
- On justified lines the words after a placeholder sit slightly further left
  than in the original (PyMuPDF closes up part of the gap). Nothing overlaps,
  but the right edge of that line is no longer flush.
- Scanned pages (images of text) are not touched: they need OCR first.
  Annotations, form fields and attachments are not examined.
- `rehydrate` does not write PDFs: an analysis comes back as text.

**Licence.** PyMuPDF is AGPL (or commercial from Artifex). It is optional
(`requirements-pdf.txt`): without it PDFs are read with pypdf and written as
plain text. Internal use is unaffected; distributing the tool with PyMuPDF
bundled would bring the AGPL's terms with it.

## Later

Decided by the owner: PyMuPDF's AGPL licence is acceptable for now. Revisit it
before the tool is distributed to anyone outside the firm.

**Next: a desktop window in place of the terminal.** The plan is in
`GUI_PLAN.md` (PySide6, Windows and macOS, for non-technical staff).

Other candidates, not yet prioritised:

- **Setup for a normal computer:** a one-step installer and a plain-language
  user guide. Today the tool needs Python, a 5 GB install and a terminal.
- **A simple window** in place of the terminal: pick a file, review the items,
  save. The review logic is already separate from the prompt.
- **Batch mode:** sanitize a whole folder against one matter's vault.
- **Scanned PDFs:** OCR, then redact.
- **Measurement on other document types:** litigation, contracts,
  correspondence. Everything measured on real documents so far is estate
  planning and one LLC agreement.
- **Keychain** in place of the typed passphrase (the seam exists).
- **Original typeface** for placeholders in PDFs.
- **A smaller install:** drive the ONNX model without PyTorch.
