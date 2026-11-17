"""Every sentence the window shows, in one place.

Staff never see: vault, placeholder, NER, regex, threshold, rehydrate.
Use: matter file, stand-in, found by the model / by a pattern, restore.
"""

import re

APP_NAME = "Replace-o-matic"


# ---- plurals

def plural(n: int, word: str) -> str:
    """``plural(1, "time")`` is "1 time"; ``plural(3, "time")`` is "3 times"."""
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def times(n: int) -> str:
    return plural(n, "time")


# ---- service messages in staff words

_MATTER_FILE_DAMAGED = "Wrong passphrase, or the matter file is damaged. Check the passphrase and try again."
_NOT_A_MATTER_FILE = (
    "That file is not a matter file made by Replace-o-matic, so it was not used. "
    "Choose a different matter file, or start a new matter."
)
_NO_PASSPHRASE = "This matter file is locked and needs its passphrase. Enter the passphrase and try again."
_NO_TEXT = (
    "No text could be read from this document. If it is a scanned PDF, it needs text "
    "recognition (OCR) first. Nothing was changed."
)
_NOT_WRITTEN = (
    "Something unexpected stopped the step, so as a precaution nothing was written. "
    "Your original document and matter file are unchanged. Please report this."
)
_NO_PDF_WRITER = (
    "This installation cannot write a PDF. Nothing was written. Ask your administrator "
    "to check the installation."
)

# (pattern, staff sentence). First match wins; the patterns match the messages raised in
# sanitizer_service.py and sanitizer_core.py, which the command line still shows as they are.
_SERVICE_MESSAGES = [
    (r"^Wrong passphrase, or the vault file is damaged", _MATTER_FILE_DAMAGED),
    (r"is not an encrypted vault", _NOT_A_MATTER_FILE),
    (r"^This vault is encrypted: a passphrase is required", _NO_PASSPHRASE),
    (r"^No text found in ", _NO_TEXT),
    (r"^Internal error", _NOT_WRITTEN),
    (r"needs PyMuPDF", _NO_PDF_WRITER),
]


def for_staff(message: str) -> str:
    """A message from the service or core, rewritten in staff words: what happened and
    what to do next. Unknown messages are kept, with "vault" replaced by "matter file"."""
    for pattern, sentence in _SERVICE_MESSAGES:
        if re.search(pattern, message):
            return sentence
    return re.sub(r"\bvault\b", "matter file", re.sub(r"\bVault\b", "Matter file", message))


STEPS = ["Start", "Choose", "Scanning", "Review", "Done"]

LOADING_MODEL = "Getting ready…"
SCANNING = "Reading the document and looking for names and numbers…"
SCAN_PROGRESS = "Part {done} of {total}"
SCAN_CANCELLED = "Scanning was stopped. Nothing was saved."

CLOSE_WHILE_BUSY_TITLE = "Stop and close?"
CLOSE_WHILE_BUSY = "Replace-o-matic is still working. If you close now, this step is abandoned and nothing is saved."
STILL_FINISHING = "Finishing the current step before closing…"

LOCK = "&Lock"
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
BROWSE = "Br&owse…"
BACK = "&Back"
CONTINUE = "&Continue"
WORKING = "Working…"
DOCUMENT_FILES = "Documents (*.docx *.pdf *.txt)"
RESTORE_FILES = "Documents (*.docx *.txt)"
MATTER_FILES = "Matter files (*.vault)"
ALL_TYPES = "All types"

# ---- start
START_HEADING = "What would you like to do?"
START_SANITIZE = "&Sanitize a document"
START_RESTORE = "&Restore an analysis"
START_KEY = "Open a &key"
RECENT_MATTERS = "Recent matters"
NO_RECENT_MATTERS = "No matters used on this computer yet."

# ---- matter file and passphrase
DOCUMENT = "Document"
MATTER = "Matter file"
MATTER_NEW = "&New matter…"
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
CANCEL = "Cancel"  # also Esc
CANCELLING = "Stopping…"

# ---- review
REVIEW_COUNT = "{total} found, {accepted} ticked"  # total is plural(total, "item")
REVIEW_KNOWN = "{count} already in this matter will also be replaced."
ACCEPT_ALL = "Accept &all"
DECLINE_SELECTED = "&Decline selected"
SEARCH = "Search…"
FILTER = "Show:"
WHERE = "Where it appears ({index} of {total})"
WHERE_NONE = "Select a row to see where it appears."
WHERE_NOT_FOUND = "This text does not appear in the document."
PREVIOUS = "<"
NEXT = ">"
ADD_MISSED = "+ A&dd something missed"
SANITIZE_N = "&Sanitize ({count})"
ADD_TITLE = "Add something missed"
ADD_PROMPT = "Type or paste the exact text as it appears in the document."
ADD_TYPE = "Type"
ADD_FOUND = "Appears {times}. First: {context}"
ADD = "Add"

# ---- done
DONE_HEADING = "The sanitized document is ready"
DONE_NOT_REVIEWED = "Not reviewed: the list was accepted without checking."
DONE_OUTPUT = "Sanitized document: {path}"
DONE_MATTER = "Matter file: {path}"
DONE_COUNTS = "{replaced} made. {added} saved to the matter, {declined} declined."  # replaced: plural(n, REPLACEMENTS) + " made"; see done.py
REPLACEMENTS = "replacement"
NEW_ITEMS = "new item"
CHECK_THESE = "Check these: the text below still appears with different capital letters."
RESIDUE_ROW = "{value}  ({times})"
OPEN_FOLDER = "Open &folder"
MAKE_KEY = "Make &key"
SANITIZE_ANOTHER = "Sanitize a&nother"

# ---- restore
RESTORE_HEADING = "Restore an analysis"
RESTORE_FILE = "File that came back"
RESTORE = "&Restore"
RESTORE_DONE = "{standins} restored. Saved as: {path}"
RESTORE_ALTERED = "Recognised although they had been respelled: {items}"
RESTORE_UNKNOWN = "Not known to this matter, left as they are: {items}"
RESTORE_TAB_FILE = "From a &file"
RESTORE_TAB_PASTE = "&Paste text"
RESTORE_DROP = "Drop the .docx or .txt file that came back here, or browse."
RESTORE_PASTE_HINT = "Paste the text that came back here (Ctrl+V)."
RESTORE_PASTE_DONE = "{standins} restored. Copy the text below, or save it. Nothing is saved unless you choose Save as."
RESTORE_COPY = "&Copy"
RESTORE_COPIED = "Copied. Paste it where you need it."
RESTORE_COPIED_WINDOWS = RESTORE_COPIED + " It is kept out of Windows clipboard history and cloud sync."
RESTORE_SAVE_AS = "&Save as…"
RESTORE_SAVED = "Saved as: {path}"
RESTORE_PASTE_ANOTHER = "Paste &another"
NEED_PASTE = "Paste the text that came back first."
A11Y_PASTE = "Text that came back"
A11Y_RESTORED_TEXT = "Restored text"
A11Y_RESTORE_DROP = "Drop area for the file that came back"

# ---- key
KEY_HEADING = "Make a key"
KEY_DOCUMENT = "Document (optional)"
KEY_DOCUMENT_HINT = "With a document, the key lists only what appears in it."
KEY_CONFIDENTIAL = "&Confidential key (shows the real names)"
KEY_SAFE = "S&afe key (no real names; may travel with the document)"
KEY_CONFIDENTIAL_TITLE = "Write the confidential key?"
KEY_NEED_ONE = "Tick at least one kind of key."
KEY_MAKE = "Make &key"
KEY_DONE = "{standins} listed."
KEY_WROTE_CONFIDENTIAL = "Confidential key: {path}"
KEY_WROTE_SAFE = "Safe key: {path}"

# ---- review: columns, empty state, keyboard
REVIEW_COLUMNS = ["", "Type", "Text", "Times", "Found by", "Same as"]
REVIEW_EMPTY = (
    "Nothing sensitive was found in this document. If you can see something that should be "
    "replaced, use \"Add something missed\". Otherwise continue."
)
PREVIOUS_TIP = "Previous place it appears (Alt+Left)"
NEXT_TIP = "Next place it appears (Alt+Right)"
SEARCH_TIP = "Search the list (Ctrl+F)"
TABLE_TIP = "Space ticks or unticks the selected rows. Double-click a Text or Type cell to change it."
LOCK_SHORTCUT = "Ctrl+L"

# ---- names read out by screen readers where the visible text is not enough
A11Y_TABLE = "Items found"
A11Y_SEARCH = "Search the items"
A11Y_FILTER = "Show only one type"
A11Y_PREVIOUS = "Previous place it appears"
A11Y_NEXT = "Next place it appears"
A11Y_CONTEXT = "Where it appears"
A11Y_DOCUMENT = "Document file"
A11Y_MATTER = "Matter file"
A11Y_BROWSE_DOCUMENT = "Browse for the document"
A11Y_BROWSE_MATTER = "Browse for the matter file"
A11Y_DROP = "Drop area for the document"
A11Y_RECENT = "Recent matters"
A11Y_PROGRESS = "Scanning progress"
A11Y_RESIDUE = "Text to check"
A11Y_STEP = "Step {n} of {total}: {name}"


# ---- output file (Review and Restore)
OUTPUT_SANITIZED = "Save the sanitized document as:"
OUTPUT_RESTORED = "Save the restored file as:"
CHANGE = "Chan&ge…"
A11Y_OUTPUT_PATH = "Where the file will be saved"
A11Y_OUTPUT_CHANGE = "Choose where to save the file"
OUTPUT_FILTERS = {
    ".docx": "Word document (*.docx)",
    ".pdf": "PDF (*.pdf)",
    ".txt": "Plain text (*.txt)",
}

# ---- key format
KEY_FORMAT = "File type"
KEY_FORMATS = [
    ("docx", "Word document (.docx)"),
    ("csv", "Spreadsheet (.csv)"),
    ("txt", "Plain text (.txt)"),
]

# ---- first-run walkthrough
HELP_MENU = "&Help"
HELP_INTRO = "&How Replace-o-matic works"
INTRO_TITLE = "How Replace-o-matic works"
INTRO_PAGE = "{n} of {total}"
INTRO_NEXT = "&Next"
INTRO_FINISH = "&Finish"
INTRO_PAGES = [
    (
        "What it does",
        "Replace-o-matic swaps the names and numbers in a document for stand-ins such as "
        "[PERSON_1], so the document can be sent for analysis. When the analysis comes back, "
        "it puts the real names and numbers back.\n\n"
        "Everything happens on this computer. Nothing is sent anywhere.",
    ),
    (
        "The matter file and passphrase",
        "Each client matter has its own matter file. It keeps the real names locked, so the "
        "same name gets the same stand-in every time.\n\n"
        "You choose a passphrase when you start a matter. If you lose it, the names cannot be "
        "restored. Nobody can recover it, so keep it somewhere safe.",
    ),
    (
        "Review the list",
        "The scan is not perfect. In testing on new documents it missed about 1 in 10 "
        "sensitive mentions.\n\n"
        "Before you send anything, read the list of what was found and look through the "
        "document. If something was missed, use \"Add something missed\".",
    ),
    (
        "What to send and what to keep",
        "Send only the sanitized document.\n\n"
        "Never send the matter file, and never send the confidential key. Both hold the real "
        "names. Keep them on this computer.",
    ),
]

# ---- a file that is already there
REPLACE_TITLE = "The file already exists"
REPLACE_TEXT = "This file is already there:\n{existing}\n\nSave a new file beside it, or replace it?"
REPLACE_NEW_NAMES = "The new file would be:\n{names}"
REPLACE_SAVE_NEW = "Save as &new file"
REPLACE_REPLACE = "&Replace it"
