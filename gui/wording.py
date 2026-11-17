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

# ---- shared
BROWSE = "Browse…"
BACK = "Back"
CONTINUE = "Continue"
WORKING = "Working…"
DOCUMENT_FILES = "Documents (*.docx *.pdf *.txt)"
RESTORE_FILES = "Documents (*.docx *.txt)"
MATTER_FILES = "Matter files (*.vault)"
ALL_TYPES = "All types"

# ---- start
START_HEADING = "What would you like to do?"
START_SANITIZE = "Sanitize a document"
START_RESTORE = "Restore an analysis"
START_KEY = "Open a key"
RECENT_MATTERS = "Recent matters"
NO_RECENT_MATTERS = "No matters used on this computer yet."

# ---- matter file and passphrase
DOCUMENT = "Document"
MATTER = "Matter file"
MATTER_NEW = "New matter…"
MATTER_OPEN = "This matter is open. Use Lock in the menu to close it."
PASSPHRASE = "Passphrase"
PASSPHRASE_AGAIN = "Passphrase again"
PASSPHRASE_HINT_SHORT = "Short. Four or more unrelated words make a strong passphrase."
PASSPHRASE_HINT_OK = "Good length."
CHOOSE_HEADING = "Choose the document and its matter"
CHOOSE_DROP = "Drop a .docx, .pdf or .txt file here, or browse."
NEED_DOCUMENT = "Choose a document first."
DOCUMENT_MISSING = "That document could not be found. Choose it again."
NEED_MATTER = "Choose a matter file, or start a new matter."
MATTER_MISSING = "That matter file could not be found. Choose it again."
NEED_PASSPHRASE = "Enter the passphrase."
PASSPHRASES_DIFFER = "The two passphrases are not the same. Type them again."

# ---- scanning
CANCEL = "Cancel"
CANCELLING = "Stopping…"

# ---- review
REVIEW_COUNT = "{total} items found, {accepted} ticked"
REVIEW_KNOWN = "{count} already in this matter will also be replaced."
ACCEPT_ALL = "Accept all"
DECLINE_SELECTED = "Decline selected"
SEARCH = "Search…"
FILTER = "Show:"
WHERE = "Where it appears ({index} of {total})"
WHERE_NONE = "Select a row to see where it appears."
WHERE_NOT_FOUND = "This text does not appear in the document."
PREVIOUS = "<"
NEXT = ">"
ADD_MISSED = "+ Add something missed"
SANITIZE_N = "Sanitize ({count})"
ADD_TITLE = "Add something missed"
ADD_PROMPT = "Type or paste the exact text as it appears in the document."
ADD_TYPE = "Type"
ADD_FOUND = "Appears {count} time(s). First: {context}"
ADD = "Add"

# ---- done
DONE_HEADING = "The sanitized document is ready"
DONE_NOT_REVIEWED = "Not reviewed: the list was accepted without checking."
DONE_OUTPUT = "Sanitized document: {path}"
DONE_MATTER = "Matter file: {path}"
DONE_COUNTS = "{replaced} replacements made. {added} new items saved to the matter, {declined} declined."
CHECK_THESE = "Check these: the text below still appears with different capital letters."
RESIDUE_ROW = "{value}  ({count} time(s))"
OPEN_FOLDER = "Open folder"
MAKE_KEY = "Make key"
SANITIZE_ANOTHER = "Sanitize another"

# ---- restore
RESTORE_HEADING = "Restore an analysis"
RESTORE_FILE = "File that came back"
RESTORE = "Restore"
RESTORE_DONE = "{count} stand-in(s) restored. Saved as: {path}"
RESTORE_ALTERED = "Recognised although they had been respelled: {items}"
RESTORE_UNKNOWN = "Not known to this matter, left as they are: {items}"

# ---- key
KEY_HEADING = "Make a key"
KEY_DOCUMENT = "Document (optional)"
KEY_DOCUMENT_HINT = "With a document, the key lists only what appears in it."
KEY_CONFIDENTIAL = "Confidential key (shows the real names)"
KEY_SAFE = "Safe key (no real names; may travel with the document)"
KEY_CONFIDENTIAL_TITLE = "Write the confidential key?"
KEY_NEED_ONE = "Tick at least one kind of key."
KEY_MAKE = "Make key"
KEY_DONE = "{count} stand-in(s) listed."
KEY_WROTE_CONFIDENTIAL = "Confidential key: {path}"
KEY_WROTE_SAFE = "Safe key: {path}"
