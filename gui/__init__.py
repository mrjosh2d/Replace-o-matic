"""Desktop window for Replace-o-matic. See GUI_PLAN.md.

Import order matters: ``sanitizer_core`` must be imported before anything that
could load onnxruntime, because it switches off that library's telemetry.
"""

import sanitizer_core  # noqa: F401  (first: sets the offline switches)
