"""Every sentence the window shows, in one place.

Staff never see: vault, placeholder, NER, regex, threshold, rehydrate.
Use: matter file, stand-in, found by the model / by a pattern, restore.
"""

APP_NAME = "Replace-o-matic"

STEPS = ["Start", "Choose", "Scanning", "Review", "Done"]

LOADING_MODEL = "Getting ready…"
SCANNING = "Reading the document and looking for names and numbers…"
SCAN_PROGRESS = "Part {done} of {total}"
SCAN_CANCELLED = "Scanning was stopped. Nothing was saved."

CLOSE_WHILE_BUSY_TITLE = "Stop and close?"
CLOSE_WHILE_BUSY = "Replace-o-matic is still working. If you close now, this step is abandoned and nothing is saved."
STILL_FINISHING = "Finishing the current step before closing…"

LOCK = "Lock"
LOCKED = "Locked. Enter the passphrase again to continue."

NEW_MATTER_WARNING = (
    "If you lose this passphrase, the names cannot be restored. Nobody can recover it."
)
UNREVIEWED_TITLE = "Continue without reviewing?"
UNREVIEWED = (
    "Nothing in the list was checked. In testing on new documents, the scan missed about "
    "1 in 10 sensitive mentions. The result will be marked as not reviewed."
)
CONFIDENTIAL_KEY_WARNING = (
    "This key shows the real names next to their stand-ins. Keep it on this computer "
    "and never send it with the sanitized document."
)
