# Windows build

Builds `Replace-o-matic-Setup-<version>.exe`: a per-user installer with the
model inside. It needs no administrator rights and downloads nothing. First
built and checked on Windows 11 Home (build 26200), 17 November 2026.

## Build

PowerShell, from the repository root. Install [uv](https://docs.astral.sh/uv/)
and Inno Setup 6 (`winget install JRSoftware.InnoSetup`) once.

```
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt -r requirements-build.txt
.venv\Scripts\python.exe scripts\fetch_model.py        # once: the 611 MB model
.venv\Scripts\python.exe -m pytest                     # must pass; the strace tests skip on Windows
.venv\Scripts\pyinstaller --noconfirm packaging\replace_o_matic.spec
.venv\Scripts\python.exe scripts\check_dist.py         # fails if torch, transformers, gliner or Qt networking got in
dist\Replace-o-matic\Replace-o-matic.exe --self-test | Out-String   # "self-test: ok ..."
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\replace_o_matic.iss
```

The installer is written to `dist\installer\`. Pass `/DAppVersion=1.2.3` to
ISCC to set the version. PySide6 must stay below 6.12 (`requirements-gui.txt`
caps it).

`--self-test` prints to the console it was started from. A windowed program
does not make PowerShell wait, so the line can appear after the prompt. Pipe
the output (`| Out-String`) to make PowerShell wait and to get the exit code
in `$LASTEXITCODE`.

## Size

| | |
|---|---|
| App folder (`dist\Replace-o-matic`) | 920 MB |
| Model | 622 MB |
| PyMuPDF | 98 MB |
| Qt (PySide6) | 73 MB |
| onnxruntime | 46 MB |
| everything else | about 80 MB |
| Installer (`lzma2`, solid) | 632 MB |

The PyInstaller build takes about 1 minute and the installer about 2 minutes.

## What the Windows build needed

- On Windows the PySide6 hook also collects `plugins\generic\qtuiotouchplugin.dll`
  (touch input over UDP), which brings `Qt6Network.dll`. The spec drops both.
  `scripts\check_dist.py` lists the folder and the modules packed into the exe,
  and fails if either comes back.
- The MSVC runtime that onnxruntime and Qt need (`msvcp140*.dll`,
  `vcruntime140*.dll`) is collected automatically; no Visual C++ redistributable
  is needed.
- The exe is windowed (`console=False`), so `--self-test` borrows the parent
  console to print its result.

## Installer

`replace_o_matic.iss` sets `PrivilegesRequired=lowest` and installs into
`%LOCALAPPDATA%\Programs\Replace-o-matic`. It adds a Start-menu entry, an
optional desktop icon, and an uninstaller (Settings > Apps). It has no step
that uses the network. Uninstalling removes the program folder only. The log
and the recent-matters list in `%LOCALAPPDATA%\Replace-o-matic` stay, and so
do every matter file, key and document the user saved. Silent install:
`Replace-o-matic-Setup-0.1.0.exe /VERYSILENT /CURRENTUSER`.

### Signing (optional, not done yet)

The firm has no code-signing certificate yet. When it has one, sign the app
and then the installer:

```
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f firm.pfx /p <password> dist\Replace-o-matic\Replace-o-matic.exe
```

Then uncomment `SignTool=` and `SignedUninstaller=yes` in the .iss, and run
ISCC with `"/Ssigntool=signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f firm.pfx /p <password> $f"`.
The timestamp request is the only network use, and it happens on the build
machine, never on a user's PC.

### What staff see while it is unsigned

The installer is unsigned, so Windows SmartScreen blocks it the first time if
it arrived by download, email or Teams. Staff see a blue box, "Windows
protected your PC", with only "Don't run". To install, click **More info**,
then **Run anyway**; the publisher shows as "Unknown publisher". A copy from a
firm file share usually opens without the box. On PCs with Smart App Control
turned on, unsigned programs are blocked outright; those PCs need the signed
build. The first start after installing can take up to a minute while
antivirus scans the new files.

## Offline checks

All checks use invented documents only:
`.venv\Scripts\python.exe packaging\windows\make_test_documents.py <folder>`
writes `invented-letter.docx` and `invented-memo.pdf`. Never commit outputs,
matter files or keys (`.gitignore` covers them); delete the work folder after.

### End-to-end run through the window

`gui_smoke.ps1 -Work <folder>` drives the installed app with UI Automation. It
creates a new matter, sanitizes the .docx (and checks it for the invented
names), makes both keys, restores the sanitized .docx, and sanitizes the .pdf
in the same matter. It needs an empty folder that holds the two documents, and
it moves no mouse or keys.

**Result, 17 November 2026: passed** on the installed build. The sanitized
.docx and .pdf contained none of the invented names, and the restored .docx
matched the original exactly.

This run found a bug the unit tests could not see. Started as a program, the
app stopped at "Working…" after Continue, because `gui/app.py` was loaded
twice and background results never reached the screens. It is fixed in this
branch (`gui/app.py`), with a test.

### Network on, under Process Monitor

`procmon_check.ps1 -Procmon <path to Procmon64.exe> -Work <folder>` starts
Process Monitor with `replace_o_matic_process.pmc` (Process Name is
Replace-o-matic.exe, filtered events dropped), runs `gui_smoke.ps1`, stops
Process Monitor, and counts the events with `procmon_summary.py`. It keeps
only the summary in `results\` and deletes the capture, which lists file names.
Windows asks twice for administrator approval; approve the second prompt
promptly, or Process Monitor keeps running (stop it with `Procmon64.exe /Terminate`).
For looking by hand, load `replace_o_matic_network.pmc` (adds Operation begins
with TCP or UDP); the list must stay empty. Regenerate both filters with
`make_procmon_filter.py` (`pip install procmon-parser`).

**Result, 17 November 2026: zero network events.** There were 38,027 events
from Replace-o-matic.exe over a full run (registry, file system, local pipes,
process), and none was TCP or UDP. See `results\procmon-2026-11-17.txt`.

### Network off

`offline-check.wsb` opens Windows Sandbox with networking disabled. It maps
`C:\ReplaceOMaticCheck` read-only and runs `sandbox_check.ps1` there, which
records the network state, installs, runs `--self-test` and `gui_smoke.ps1`,
and writes `Desktop\offline-check-result.txt` inside the sandbox. Before
opening it, put the installer, `sandbox_check.ps1`, `gui_smoke.ps1` and the two
invented documents in `C:\ReplaceOMaticCheck`. Sandbox needs Windows Pro,
Enterprise or Education.

Without Sandbox, copy the same files to a clean VM or PC, switch its network
off, and run
`powershell -ExecutionPolicy Bypass -File sandbox_check.ps1 -Out <empty folder>`.

**Result: not done yet.** The build PC runs Windows 11 Home, which has no
Sandbox, and the network-off run on it is still to do.

## Open items

- **Network-off run:** on a Pro machine with the .wsb, on a clean VM, or on the
  build PC with Wi-Fi off.
- **Code-signing certificate** for the firm, then sign as above. Until then,
  staff see SmartScreen, and Smart App Control PCs cannot run the app.
- **PyMuPDF is AGPL.** That is fine inside the firm. Before the installer goes
  to anyone outside it, buy Artifex's commercial licence or build without
  PyMuPDF (PDFs then come back as plain text).
- **Vault and key file permissions:** `chmod 600` has no effect on Windows.
  Files are protected by the user profile's ACL, which usually allows only that
  user and administrators. If matters are saved on a shared drive, the share's
  permissions apply.
