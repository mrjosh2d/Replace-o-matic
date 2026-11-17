; Inno Setup 6 script for Replace-o-matic. See packaging\windows\README.md.
;
; Build the app first (pyinstaller packaging\replace_o_matic.spec), then:
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\replace_o_matic.iss
; Output: dist\installer\Replace-o-matic-Setup-<version>.exe
;
; Per-user install, no administrator rights, nothing downloaded: the model and
; every library are inside the installer. The installer has no [Run] or [Code]
; step that touches the network.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "Replace-o-matic"
#define AppExe "Replace-o-matic.exe"

[Setup]
; Keep AppId fixed across versions so upgrades replace the old install.
AppId={{6F1C2E7A-3B0D-4D57-9E1A-5C8B2F4A7D21}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\..\dist\installer
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
CloseApplications=yes
; Code signing (optional, once the firm has a certificate). Define a sign tool
; in the Inno Setup IDE (Tools > Configure Sign Tools) or on the command line:
;   ISCC "/Ssigntool=signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f firm.pfx /p PASSWORD $f" ...
; then uncomment the next two lines. Sign dist\Replace-o-matic\Replace-o-matic.exe
; with the same command before running ISCC. The timestamp server is the only
; network use, and it happens on the build machine, never on a user's PC.
;SignTool=signtool
;SignedUninstaller=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\Replace-o-matic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; The uninstaller removes the program folder only. The log and the list of
; recent matters in %LOCALAPPDATA%\Replace-o-matic, and every matter, vault,
; key and output file the user saved, are left alone.
