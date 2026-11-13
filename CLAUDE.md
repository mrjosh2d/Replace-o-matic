# Replace-o-matic

Offline pseudonymization for legal documents. See `PLAN.md` for the build steps,
design decisions and known limits. Update its status table when a step lands.

## Hard rules

- **No document content leaves the machine.** `sanitizer_core.py` and anything it
  imports at runtime must make no network calls. Downloading model weights from
  huggingface.co is allowed, as a separate, deliberate setup step. Nothing is
  ever uploaded.
  - Third-party libraries can phone home on their own: `onnxruntime` did (usage
    telemetry). `sanitizer_core` sets `ORT_DISABLE_TELEMETRY=1` on import; keep
    it the first project import. After adding or upgrading any dependency, run
    `pytest -m model`: one test traces the process with `strace` and fails on
    any outbound connection.
- **Never commit a vault or real client text.** Vaults hold the real names and
  numbers (`*vault*` and `*.sanitized.txt` / `*.rehydrated.txt` are gitignored). Test fixtures use invented data only.
- **Round-trip must stay exact:** `rehydrate_text(apply_vault(t, v), v) == t`.
  Any change to matching or placeholders needs a test proving it.

## Working here

- Python 3.11. Setup and tests:
  ```
  uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
  .venv/bin/python -m pytest
  ```
- Unit tests use a stub NER and need no model. Tests that load the real GLiNER
  model are marked `model` and skip when the model is absent.
- After any change to detection, run `.venv/bin/python scripts/evaluate.py -v` and
  `-f holdout.json -v` and compare with the table in `PLAN.md`. Both sets have
  been tuned against; treat their scores as regression checks, not accuracy.
- NER backend: the `gliner` package on its ONNX backend (decided; it brings
  PyTorch as a dependency, which is accepted).

## Delegation and model choice

Goal: minimise usage. When delegating to a subagent, pick the cheapest model
that can do the task well.

- **Simple tasks: do not delegate.** A subagent starts cold and re-reads context,
  which costs more than doing a small job inline. Small edits, a single file,
  running the tests, a quick search, a short doc change: do these directly.
- **Haiku:** mechanical, well-specified work that is large enough to be worth
  handing off. Broad file searches, running a long suite and summarising
  failures, boilerplate.
- **Sonnet:** routine implementation with a clear spec. Scripts, CLI plumbing,
  additional test cases.
- **Opus:** harder delegated pieces that need judgment. Tricky algorithms (span
  merging, chunking), review passes over core logic.
- Keep design decisions, anything touching the hard rules above, and final
  review of delegated work in the main session.
