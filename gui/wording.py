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

# ---- Start
START_TITLE = "What would you like to do?"
BTN_SANITIZE = "Sanitize a document"
BTN_RESTORE = "Restore an analysis"
LINK_KEY = "Open a key"
RECENT_TITLE = "Recent matters"
RECENT_EMPTY = "No recent matters yet."
NOT_AVAILABLE_YET = "This part is not available yet."

# ---- Choose
CHOOSE_TITLE = "Choose a document and a matter"
DROP_HERE = "Drop a document here (.docx, .pdf or .txt)"
BROWSE = "Browse…"
BROWSE_DOCUMENT_TITLE = "Choose a document"
DOCUMENT_FILTER = "Documents (*.docx *.pdf *.txt)"
MATTER_EXISTING = "Use an existing matter"
MATTER_NEW = "Start a new matter"
MATTER_NONE_CHOSEN = "No matter file chosen"
MATTER_OPEN_TITLE = "Choose a matter file"
MATTER_SAVE_TITLE = "Save the new matter as"
MATTER_FILTER = "Matter files (*.vault);;All files (*)"
PASSPHRASE = "Passphrase"
PASSPHRASE_AGAIN = "Passphrase again"
CONTINUE = "Continue"
BACK = "Back"
STRENGTH_WEAK = "Weak: use at least 12 characters, or several words."
STRENGTH_FAIR = "Fair: a longer passphrase is safer."
STRENGTH_GOOD = "Good."
ERR_NO_DOCUMENT = "Choose a document first."
ERR_BAD_TYPE = "Only .docx, .pdf and .txt documents can be used. Choose a different file."
ERR_NOT_FOUND = "That file could not be found. Choose it again."
ERR_NO_PDF = "PDF support is not installed in this copy of Replace-o-matic. Use a .docx or .txt document."
ERR_NO_MATTER = "Choose a matter file, or start a new matter."
ERR_MATTER_MISSING = "That matter file could not be found. Choose it again."
ERR_MATTER_EXISTS = (
    "A file with that name already exists. Choose another name, or use it as an existing matter."
)
ERR_NO_PASSPHRASE = "Enter the passphrase."
ERR_MISMATCH = "The two passphrases are different. Type them again."
OPENING_MATTER = "Opening the matter…"

# ---- Scanning
SCAN_COUNT = "Part {done} of {total}"
CANCEL = "Cancel"
STOPPING = "Stopping…"
LOADING_MODEL_NOTE = "Loading the language model (about 10 seconds the first time)…"
SCAN_DONE_NO_REVIEW = "Scan finished: {count} items found. The review step is not available yet."
CHOOSE_ANOTHER = "Choose another document"

# ---- Review
REVIEW_COUNT = "{count} items found"
ACCEPT_ALL = "Accept all"
DECLINE_SELECTED = "Decline selected"
FILTER_LABEL = "Show:"
FILTER_ALL = "all"
SEARCH_PLACEHOLDER = "Search the list"
WHERE_IT_APPEARS = "Where it appears ({n} of {m})"
WHERE_NOTHING = "Select a line above to see where it appears."
WHERE_NOT_FOUND = "This text was not found in the document."
PREVIOUS = "Previous"
NEXT = "Next"
ADD_MISSED = "+ Add something missed"
SANITIZE_COUNT = "Sanitize ({n})"
SANITIZING = "Writing the sanitized document…"
SANITIZED_NO_DONE = "Finished. The sanitized document was saved as {path}"
UNREVIEWED_BUTTON_YES = "Continue anyway"
UNREVIEWED_BUTTON_NO = "Go back and review"
LEAVE_REVIEW_TITLE = "Go back?"
LEAVE_REVIEW = "Your changes to the list will be lost. Nothing has been saved."
ADD_TITLE = "Add something missed"
ADD_TEXT_LABEL = "Exact text, as it appears in the document"
ADD_TYPE_LABEL = "Type"
ADD_COUNT = "Appears {n} times. First place:"
ADD_NOT_FOUND = "Not found in the document."


def plain(message: str) -> str:
    """Service and library messages in staff wording."""
    return message.replace("vault file", "matter file").replace("vault", "matter file")
