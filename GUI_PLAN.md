# Replace-o-matic: desktop window plan

A plan for replacing the terminal with a normal program window. Written to be
implemented by Opus 5.5 and Sonnet; each phase says which. Read `CLAUDE.md`
and `PLAN.md` first: the hard rules there apply to every line of this work.

## Decisions already made

| Question | Decision |
|---|---|
| Platforms | Windows and macOS, one codebase |
| Users | Non-technical staff: double-click install, plain wording, guard rails |
| Toolkit | PySide6 (Qt for Python, LGPL) |
| Review screen | A table of proposed items; selecting one shows its context |

Not in scope for this plan: a highlighted full-document view, batch folders,
OCR, keychain storage. They are listed at the end as follow-ons.

## What the user sees

One window, one task at a time, five screens in a fixed order. A step bar
across the top shows where they are. Nothing is written until the last step.

1. **Start.** Two large buttons: *Sanitize a document* and *Restore an
   analysis*. A smaller *Open a key* link. Recent matters listed below.
2. **Choose.** Drop a file or browse (.docx, .pdf, .txt). Pick the matter
   (vault): an existing one or *New matter*. Passphrase box; for a new matter,
   passphrase twice with a strength hint and the sentence "If you lose this
   passphrase, the names cannot be restored. Nobody can recover it."
3. **Scanning.** Progress bar with page/window count and a Cancel button.
   First run of a session also shows "Loading the model (about 10 seconds)".
4. **Review.** The main screen (below).
5. **Done.** What was written and where, with *Open folder*, *Make key*,
   *Sanitize another*. If any vault value still appears in another letter
   case, list it here under "Check these".

### Review screen

```
+----------------------------------------------------------------------------+
| 27 items found   [ Accept all ]  [ Decline selected ]   Filter: [ all v ]  |
+---+-----------+---------------------------+-------+----------+-------------+
| ✓ | Type      | Text                      | Times | Found by | Same as     |
+---+-----------+---------------------------+-------+----------+-------------+
| ☑ | Person    | John Albert Doe           |  14   | model    |             |
| ☑ | Person    | JOHN ALBERT DOE           |   4   | model    | John Albe.. |
| ☐ | Company   | American Cancer Society   |   1   | model    |             |
| ☑ | Address   | 6050 Santo Road, Ste. 240 |   3   | pattern  |             |
+---+-----------+---------------------------+-------+----------+-------------+
| Where it appears (1 of 14)                              [ < ] [ > ]        |
|  ...the name of my Spouse is Jane Dorthea Doe. I, «John Albert Doe», of... |
+----------------------------------------------------------------------------+
| [ + Add something missed ]                     [ Back ]  [ Sanitize (26) ] |
+----------------------------------------------------------------------------+
```

- Every row starts ticked. Unticking is "decline" and is remembered for the
  matter, exactly as today.
- Double-click the Text cell to edit it; the new text must occur in the
  document or the edit is refused with a message. Type is a drop-down.
- *Add something missed* opens a small dialog: type or paste the exact text,
  choose a type, see the count and first context before confirming.
- The context pane steps through every occurrence, not only the first.
- Sorting by column; filter by type; a search box. Long documents can produce
  a hundred rows.
- **"I'm feeling lucky"** is the *Accept all* button followed by *Sanitize*
  without opening any row. If no row was opened, changed or unticked, a
  confirmation says the result is unreviewed and that the scan has missed about
  1 in 10 sensitive mentions on unseen text. Those entries are saved with
  `"reviewed": false`, as now.

### Restore and key

- **Restore an analysis:** choose the file that came back (.docx or .txt),
  choose the matter, passphrase. Shows how many placeholders were restored,
  which altered spellings were recognised, and which placeholders were unknown.
- **Key:** from the Done screen or the Start screen. Two tick boxes,
  *Confidential key* (ticked) and *Safe key*. The confidential key gets a
  warning before it is written.

## Wording rules

Staff should never see: vault, placeholder syntax explained in jargon, NER,
regex, threshold, rehydrate. Use *matter file*, *stand-in* (e.g. `[PERSON_1]`),
*found by the model / by a pattern*, *restore*. Every error says what happened
and what to do next. No stack traces in the window; they go to a log file.

## Architecture

```
gui/                     new package
  app.py                 entry point, QApplication, main window, step bar
  screens/               one module per screen
  review_model.py        QAbstractTableModel over the proposal list
  workers.py             QThread workers: load model, scan, write
  wording.py             every user-facing string in one place
sanitizer_service.py     new: the workflow, with no terminal and no Qt
sanitizer_cli.py         becomes a thin layer over sanitizer_service
sanitizer_core.py        unchanged
docx_io.py, pdf_io.py    unchanged
```

### Phase 0 refactor: `sanitizer_service.py` (do this first)

Today the workflow lives inside `sanitizer_cli.py` functions that read
`argparse` namespaces and call `ask`/`out`. Move it into plain functions and
dataclasses that both front ends call. Nothing here may import Qt or print.

```python
@dataclass
class Item:            # one row of the review table
    type: str
    value: str
    source: str        # "ner" | "regex" | "propagated" | "manual"
    times: int
    entity_hint: str   # value of the entry it would be linked to, or ""

@dataclass
class Scan:
    path: str
    text: str
    vault: dict
    items: list[Item]
    already_known: int
    warnings: list[str]

def open_matter(path, passphrase) -> dict            # new or existing; raises VaultError
def scan_document(path, vault, progress=None, cancelled=None) -> Scan
def occurrences(scan, value) -> list[tuple[int, int]]   # for the context pane
def context(scan, start, end, width=60) -> str
def validate_edit(scan, new_text) -> str | None      # None if ok, else the message
def commit(scan, accepted, declined, reviewed, vault_path, passphrase, output_path) -> Result
def restore(path, vault, output_path, tolerant=True) -> RestoreResult
def write_keys(vault, document_path, confidential_path, safe_path) -> KeyResult
```

- `progress(done, total)` and `cancelled() -> bool` are plain callables. The
  GLiNER detector must call them once per window; add the two optional
  arguments to `GlinerDetector.__call__` and pass them through `scan_text`.
- `commit` contains everything after review in today's `cmd_sanitize`:
  `propose_mappings`, `merge_vault`, `save_vault`, write the output in the
  right format, read it back, verify, compute residue. It must stay
  all-or-nothing: write to temporary files and move them into place last.
- After the move, `sanitizer_cli.py` should contain only argument parsing,
  the terminal prompts and printing. **All 151 existing tests must pass
  unchanged**; that is the proof the refactor is faithful.

### Threads

Model loading takes about 8 seconds and a long document about 2 minutes, so
neither may run on the window's thread.

- One long-lived worker thread owns the detector. Load the model in the
  background as soon as the window opens, so it is usually ready by the time a
  file is chosen.
- Scan and commit run on that worker; results come back by Qt signals.
- Cancel sets a flag the detector checks between windows. Closing the window
  during a scan asks first, then cancels and waits.
- Qt objects are only touched from the main thread.

### Hard rules, as they apply here

- `sanitizer_core` must be imported before anything that could import
  `onnxruntime`. `gui/app.py` imports `sanitizer_core` on its first line.
- No Qt network modules: do not import `QtNetwork`, `QtWebEngine` or
  `QtWebSockets`, and exclude them from the packaged app. No update checker,
  no crash reporter, no analytics, no web views, no remote fonts or icons.
- Extend the `strace` test to start the window headless
  (`QT_QPA_PLATFORM=offscreen`), run a scan, and assert no outbound connection.
- The passphrase is held in memory for the session only, never written to
  settings or logs. Offer *Lock* in the menu, which forgets it.
- The log file records events and errors, never document text, values or
  passphrases. Recent-matters list stores file paths only.
- Real names appear on screen during review; that is the point. Do not put
  them in window titles, tooltips on the taskbar, or the recent-files list.

## Status

**Phase 0 is done** (`sanitizer_service.py`, `tests/test_service.py`):

- The service exposes `open_matter`, `scan_document`, `occurrences`,
  `context`, `validate_edit`, `make_item`, `commit`, `restore`, `write_keys`,
  `vault_summary`, and the dataclasses `Item`, `Scan`, `Result`,
  `RestoreResult`, `KeyResult`. Read its module docstring and tests before
  writing any screen. User-facing failures are `ServiceError`.
- `scan_document(progress=, cancelled=)`: `progress(done, total)` fires per
  model window; `cancelled()` is polled between windows and raises
  `sanitizer_core.ScanCancelled`. Model loading itself (about 2 seconds now)
  reports no progress: call `sanitizer_core.default_detector()` on the worker
  thread at start-up to preload it.
- `commit` is all-or-nothing and verified by a test that fails the vault save.
- `Scan.already_known` counts matter entries that occur in the document.
- The CLI is a thin layer; the 151 tests that existed before pass unchanged.

**The install-size risk is resolved.** `onnx_gliner.py` runs the model with
`onnxruntime` and `tokenizers` only, and gives results identical to the
`gliner` package on both labelled sets. A clean environment from
`requirements-dev.txt` is 323 MB with no PyTorch, and passes the whole suite.

**The window frame and the background thread are done** (`gui/app.py`,
`gui/workers.py`, `gui/wording.py`, `tests/test_gui_backend.py`). This covers
phase 2's threading and the shell part of phase 1:

- `Backend` (in `gui/workers.py`) is the only thing screens use for slow work:
  `preload_model`, `open_matter`, `scan`, `commit`, `restore`, `write_keys`,
  `cancel`, `busy`, `shutdown`. Results arrive as the signals
  `finished(job, result)`, `failed(job, message)`, `cancelled(job)` and
  `progress(done, total)`. `failed` messages are already fit to show.
- A cancel covers the running scan and any scan still queued, never a later
  one. Unexpected errors are logged by type only (no document text) and the
  worker thread survives them.
- `MainWindow` has the step bar, the screen stack, `go(name)`, `new_task()`,
  `lock()` and a close handler that asks before abandoning work. `Screen` is
  the base class: override `enter()` and the `on_finished` / `on_failed` /
  `on_cancelled` / `on_progress` handlers. Background results are routed to
  whichever screen is showing.
- `python -m gui.app` opens the frame. It looks for `gui/screens/__init__.py`
  with an `install(window)` function that adds the screens and is expected to
  define one named `"start"`.
- All user-facing sentences go in `gui/wording.py`.
- Tests run headless (`QT_QPA_PLATFORM=offscreen`, set by the test module)
  with `pytest-qt`. One `strace` test runs a real scan inside the window
  process and fails on any outbound connection.

**The review logic is done** (`ReviewState` in `sanitizer_service.py`,
`gui/review_model.py`, `tests/test_review.py`):

- `ReviewState(scan)` holds every decision: `set_accepted`, `set_type`,
  `edit_text`, `check_add` / `add`, `accept_all`, `mark_seen`, `occurrences`,
  `accepted_count`, and `result()` which returns exactly what `commit` takes.
  Refusals come back as a sentence to show. `reviewed` is False only when
  nothing was looked at or changed.
- `ReviewTableModel(state)` is the Qt model for the table, with the columns in
  the mock-up. It emits `refused(message)` and `counts_changed(accepted,
  total)`. The Review screen needs a `QTableView` on this model (inside a
  `QSortFilterProxyModel` for sorting, type filter and search), a combo-box
  delegate for the Type column, the context pane, and the buttons. Call
  `model.mark_seen(row)` when a row's context is shown.

**Packaging has been proven on Linux** (`packaging/replace_o_matic.spec`,
`requirements-build.txt`):

- `pyinstaller --noconfirm packaging/replace_o_matic.spec` builds a folder app
  of 960 MB: model 594 MB, PyMuPDF 105 MB, Qt 98 MB, the rest under 170 MB.
- `Replace-o-matic --self-test` loads the bundled model, scans a sentence and
  exits 0. Run under `strace`, the packaged app made no outbound connection,
  and it contains no PyTorch, transformers, gliner, QtNetwork or WebEngine.
- Still to do for phase 6: macOS (build, `.dmg`, sign, notarise), signing on
  Windows, and a clean-machine run on Windows.

**Windows is built and checked** (`packaging/windows/`; steps and results in
its `README.md`):

- Same spec, plus a fix: on Windows the PySide6 hook pulled in the TUIO touch
  plugin and `Qt6Network.dll`; both are dropped. `scripts/check_dist.py` fails
  the build if torch, transformers, gliner or any Qt network or web library is
  bundled. App folder 920 MB, installer 632 MB.
- Inno Setup installer: per user, no administrator rights, Start-menu entry,
  uninstaller, model bundled. Unsigned until the firm has a certificate, so
  SmartScreen warns.
- `gui_smoke.ps1` drives the installed app through its window (new matter,
  .docx, keys, restore, .pdf): passed. Under Process Monitor with the network
  on: 38,027 events from the app, none TCP or UDP. With Wi-Fi off, install,
  self-test and the window run all passed. A clean-machine run (Sandbox via
  `offline-check.wsb`, or a VM) is still to do: the build PC is Windows Home.
- The window run found a bug: started as a program, `gui/app.py` was loaded
  twice, so no background result reached a screen and the app stopped at
  "Working…". Fixed, with a test.

**The screens are built and work end to end** (`gui/screens/`, `gui/settings.py`,
`tests/test_gui_screens.py`). Function first: they have had no visual polish.

- `gui/screens/__init__.py` has `install(window)`. One module per screen:
  `start`, `choose`, `scanning`, `review`, `done`, `restore`, `key`, plus
  `common.py` (`FilePicker`, `MatterForm`, and `MatterScreen`, the base class
  that opens the matter on the background thread and then calls `proceed()`).
- A matter file that does not exist yet is a new matter: passphrase twice, a
  length hint and `wording.NEW_MATTER_WARNING`. Once a matter is open in the
  session, later screens do not ask for the passphrase again; *Lock* forgets
  it and calls `Screen.forget()` on every screen (passphrase boxes, the review
  table and context pane are emptied).
- Errors and results are shown in a line on the screen (`screen.message`), not
  in pop-ups. The only pop-ups are the two confirmations: unreviewed
  (`wording.UNREVIEWED`) and the confidential key warning.
- Review: `QTableView` on `ReviewTableModel` through `ReviewFilter` (sorting,
  type filter, search), `TypeDelegate` for the Type column, context pane
  stepping through every occurrence, `AddDialog` with live count and context.
- `gui/settings.py` keeps the recent-matters list (paths only) in
  `settings.json` beside the log. `REPLACE_O_MATIC_HOME` moves that folder;
  the tests use it.
- Tests drive the real widgets headless. Set `SCREENSHOT_DIR=some/folder` when
  running `tests/test_gui_screens.py` to get a PNG of every screen.

**Phase 5 is done** (`tests/test_gui_polish.py`):

- Service and core messages are put into staff words in one place,
  `wording.for_staff`, called from `gui/workers.py`; the service and CLI keep
  their own wording. Plurals go through `wording.plural` / `wording.times`.
- Keyboard: Enter submits forms, Space ticks the selected review rows, Ctrl+F
  focuses search, Alt+Left/Right steps the context, Ctrl+L locks, Esc cancels
  a scan. Tab order and accessible names are set on every screen.
- The firm can hide *Accept all* by setting `"allow_accept_all": false` in
  `settings.json`; there is no control for it in the window.
- Review with nothing found says so and still allows adding and continuing.

**Output choices and the first-run walkthrough are done**
(`tests/test_gui_output.py`): Review and Restore have a *Save as* row
(`OutputRow`), checked by `service.check_output_path`, which also guards the
CLI: no output may replace the original document or the matter file. The Key
screen chooses .docx, .csv or .txt and remembers it. `gui/intro.py` shows four
short pages on first run; *Help > How Replace-o-matic works* reopens them.
If an output already exists (and was not picked in the Save dialog, which
asks itself), the window asks: *Save as new file* (`case (2).sanitized.docx`,
from `service.successor_path`), *Replace it*, or Cancel. Keys too.

**Left:** packaging on macOS and the Windows items above (6), and the guide (7).

## Phases

Each phase ends with tests passing and a short entry in `PLAN.md`.

| # | Work | Model | Why |
|---|---|---|---|
| 0 | Extract `sanitizer_service.py`; CLI becomes a thin layer; progress and cancel hooks in the detector | **Done** | See "Status" below |
| 1 | Start and Choose screens, passphrase handling, recent-matters settings (shell, step bar and log are done) | **Done** | See "Status" |
| 2 | Scanning screen with progress bar and Cancel (worker thread, preload and cancel are done) | **Done** | See "Status" |
| 3 | Review screen: table model, edit, add, filter, context stepping, unreviewed confirmation | **Done** | See "Status" |
| 4 | Done screen, Restore flow, Key flow | **Done** | See "Status" |
| 5 | Wording pass, keyboard access, error messages, empty and failure states | **Done** | Mechanical once `wording.py` exists |
| 6 | Packaging: Windows installer and macOS app, model bundled, offline check of the packaged app | **Opus** | Hardest to get right; see below |
| 7 | User guide (two pages with screenshots) and a first-run walkthrough | Sonnet | |

Suggested order of pull requests: 0, then 1+2, then 3, then 4+5, then 6+7.
Phase 0 is worth merging on its own before any Qt code exists.

## Tests

- **Service layer:** plain pytest, no Qt. Port the scenarios in
  `tests/test_cli_and_vault.py` to call the service directly: accept, decline,
  edit, retype, add, quit-saves-nothing, unreviewed flag, second document
  reuses the matter, wrong passphrase, .docx and .pdf in and out.
- **Window:** `pytest-qt` with `QT_QPA_PLATFORM=offscreen` and the stub
  detector already used in the tests. One test per screen for the main path,
  plus: cancel mid-scan leaves no files; closing during a scan; editing a row
  to text that is not in the document is refused; unticked rows become
  declines; *Accept all* then *Sanitize* triggers the unreviewed confirmation.
- **Offline:** the extended `strace` test above.
- **By hand, each release:** install on a clean Windows machine and a clean
  Mac with networking switched off, run one .docx and one .pdf end to end.

## Packaging (phase 6)

PyTorch is no longer needed (see "Status"): the runtime is `onnxruntime`,
`tokenizers`, `numpy`, `cryptography`, `lxml`, `pypdf`, optionally PyMuPDF, plus
PySide6. Expect roughly 0.3 GB of libraries, 0.2 GB of Qt and the 0.6 GB model.

- Package with PyInstaller or Briefcase. Exclude `torch`, `transformers` and
  `gliner` explicitly so a developer machine that has them cannot pull them in.
- Bundle the model (611 MB) inside the installer so nothing is downloaded on
  the user's machine. `scripts/fetch_model.py` stays a build-time step.
- Windows: an installer that needs no administrator rights if possible.
  macOS: a signed and notarised `.app` in a `.dmg`; unsigned apps are blocked
  by default and staff will not know how to get past that. Both need
  certificates the firm has to obtain.
- Run the `strace`-style offline check against the packaged app, not only the
  source tree. On Windows and macOS, where `strace` does not exist, run the
  packaged app with the network disabled and with a firewall log, and record
  the result.
- PyMuPDF's AGPL licence matters once the app is distributed. Inside the firm
  it is fine. Revisit before giving the installer to anyone else.

## Risks

- **Model file size.** The 611 MB model is now most of the install. A
  quantised ONNX file would be much smaller but changes results; it would need
  the labelled sets re-run before adopting it.
- **Long documents.** A 120,000-word document takes about two minutes to scan
  and produces a long table. Progress, cancel and filtering are not optional.
- **Lost passphrase.** There is no recovery. Say so when a matter is created.
- **Staff trusting "Accept all".** The unreviewed confirmation and the
  `reviewed` flag are the guard. Consider a firm setting that disables the
  shortcut entirely.
- **Two front ends drifting apart.** All behaviour lives in the service; the
  CLI and the window stay thin. A change that touches both is a smell.

## Follow-ons, after this plan

- Highlighted full-document view beside the table.
- Batch: sanitize a folder against one matter.
- Keychain in place of the typed passphrase (`save_vault(key=...)` exists).
- OCR for scanned PDFs.
- A firm-wide "never redact" list shared between matters.
