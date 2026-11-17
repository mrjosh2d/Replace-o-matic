# End-to-end run of the installed app, driven through its window with
# Windows UI Automation. Uses invented documents only. See README.md.
#
#   powershell -ExecutionPolicy Bypass -File gui_smoke.ps1 -Work C:\some\empty\folder
#
# -Work must hold invented-letter.docx and invented-memo.pdf
# (make_test_documents.py writes them). The script makes a new matter there,
# sanitizes both documents, makes a key, restores the sanitized .docx, and
# checks each output. Outputs land in -Work: delete the folder afterwards.
param(
    [Parameter(Mandatory)] [string] $Work,
    [string] $App = "$env:LOCALAPPDATA\Programs\Replace-o-matic\Replace-o-matic.exe",
    [string] $Passphrase = "invented test passphrase only"
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$UIA = [System.Windows.Automation.AutomationElement]
$Scope = [System.Windows.Automation.TreeScope]

function Step($text) { Write-Host "== $text" }

function Find-All([int] $processId) {
    $cond = New-Object System.Windows.Automation.PropertyCondition($UIA::ProcessIdProperty, $processId)
    $UIA::RootElement.FindAll($Scope::Children, $cond) | ForEach-Object {
        $_
        $_.FindAll($Scope::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    }
}

function Wait-For([string] $name, [string] $type = "", [int] $seconds = 60, [switch] $Prefix, [switch] $Contains, [switch] $Quiet) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        foreach ($e in Find-All $script:proc.Id) {
            $c = $e.Current
            if ($c.IsOffscreen -or -not $c.IsEnabled) { continue }
            $match = if ($Prefix) { $c.Name.StartsWith($name) } elseif ($Contains) { $c.Name.Contains($name) } else { $c.Name -eq $name }
            if ($match -and ($type -eq "" -or $c.ControlType.ProgrammaticName -eq "ControlType.$type")) { return $e }
        }
        Start-Sleep -Milliseconds 250
    }
    if ($Quiet) { throw "timed out waiting for '$name'" }
    Write-Host "   visible now:"
    foreach ($e in Find-All $script:proc.Id) {
        $c = $e.Current
        if (-not $c.IsOffscreen -and $c.Name) { Write-Host "     [$($c.ControlType.ProgrammaticName)] $($c.Name) enabled=$($c.IsEnabled)" }
    }
    throw "timed out waiting for '$name' ($type)"
}

function Click([string] $name, [string] $type = "Button", [switch] $Prefix) {
    $e = Wait-For $name $type -Prefix:$Prefix
    $pattern = $null
    if ($e.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref] $pattern)) {
        $pattern.Invoke()
    } elseif ($e.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref] $pattern)) {
        $pattern.Toggle()
    } else { throw "cannot press '$name'" }
    Start-Sleep -Milliseconds 400
}

function Type-Into([string] $name, [string] $text) {
    $e = Wait-For $name "Edit"
    $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($text)
    Start-Sleep -Milliseconds 200
}

function Ensure-Ticked([string] $name) {
    $e = Wait-For $name "CheckBox"
    $toggle = $e.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
    if ($toggle.Current.ToggleState -ne "On") { $toggle.Toggle() }
}

function Assert-File([string] $path, [string[]] $mustNotContain = @(), [string[]] $mustContain = @()) {
    if (-not (Test-Path $path)) { throw "missing output: $path" }
    $text = & $script:reader $path
    foreach ($s in $mustNotContain) { if ($text.Contains($s)) { throw "$path still contains an invented real name" } }
    foreach ($s in $mustContain) { if (-not $text.Contains($s)) { throw "$path is missing expected text" } }
    Write-Host "   ok: $(Split-Path $path -Leaf)"
}

# Text of a .docx (its document.xml without tags). The sanitized PDF is only
# checked for existence here; open it to check its text by eye.
$script:reader = {
    param($path)
    if ($path.EndsWith(".docx")) {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [System.IO.Compression.ZipFile]::OpenRead($path)
        try {
            $entry = $zip.GetEntry("word/document.xml")
            $r = New-Object System.IO.StreamReader($entry.Open()); $t = $r.ReadToEnd(); $r.Close()
            return ($t -replace "<[^>]+>", "")
        } finally { $zip.Dispose() }
    }
    return [System.IO.File]::ReadAllText($path)
}

$docx = Join-Path $Work "invented-letter.docx"
$pdf = Join-Path $Work "invented-memo.pdf"
$matter = Join-Path $Work "smoke-test.vault"
foreach ($f in $docx, $pdf) { if (-not (Test-Path $f)) { throw "missing $f; run make_test_documents.py first" } }
if (Test-Path $matter) { throw "$matter already exists; use an empty folder" }

Step "start the app"
$script:proc = Start-Process $App -PassThru
try {
    # The first start after installing can take a minute (antivirus scans the new
    # files). The first run shows the walkthrough over the window; later runs do not.
    $null = Wait-For "Sanitize a document" "Button" 180
    $intro = $true
    try { $null = Wait-For "Next" "Button" 5 -Quiet } catch { $intro = $false }
    if ($intro) {
        for ($i = 0; $i -lt 3; $i++) { Click "Next" }
        Click "Finish"
    }

    Step "sanitize the .docx with a new matter"
    Click "Sanitize a document"
    Type-Into "Document file" $docx
    Type-Into "Matter file" $matter
    Type-Into "Passphrase" $Passphrase
    Type-Into "Passphrase again" $Passphrase
    Click "Continue"
    $null = Wait-For "Sanitize (" "Button" 180 -Prefix   # scanning, then the Review screen
    Click "Accept all"
    Click "Sanitize (" -Prefix
    Click "Yes"                                         # "Continue without reviewing?"
    $null = Wait-For "The sanitized document is ready" "Text" 120
    $sanitizedDocx = Join-Path $Work "invented-letter.sanitized.docx"
    Assert-File $sanitizedDocx -mustNotContain @("Velasquez-Trent", "Fenwhistle", "4417-2290-8813") -mustContain @("[PERSON_")
    if (-not (Test-Path $matter)) { throw "matter file was not written" }

    Step "make a key"
    Click "Make key"
    Ensure-Ticked "Confidential key (shows the real names)"
    Ensure-Ticked "Safe key (no real names; may travel with the document)"
    Click "Make key"
    try { Click "Yes" } catch { }                       # "Write the confidential key?"
    $null = Wait-For "stand-ins listed." "Text" 60 -Contains
    Start-Sleep -Seconds 2
    $keys = Get-ChildItem $Work -Filter "*key*"
    if ($keys.Count -lt 2) { throw "expected a confidential and a safe key, found: $($keys.Name -join ', ')" }
    Write-Host "   ok: $($keys.Count) key files"
    Click "Back"

    Step "restore the sanitized .docx"
    Click "Restore an analysis"
    Type-Into "File that came back" $sanitizedDocx
    Click "Restore"
    $null = Wait-For "restored. Saved as:" "Text" 60 -Contains
    Start-Sleep -Seconds 2
    $restored = Get-ChildItem $Work -Filter "*rehydrated*" | Select-Object -First 1
    if (-not $restored) { throw "no restored file written" }
    Assert-File $restored.FullName -mustContain @("Velasquez-Trent", "Fenwhistle")
    Click "Back"

    Step "sanitize the .pdf in the same matter"
    Click "Sanitize a document"
    Type-Into "Document file" $pdf
    Type-Into "Matter file" $matter
    Click "Continue"
    $null = Wait-For "Sanitize (" "Button" 180 -Prefix
    Click "Accept all"
    Click "Sanitize (" -Prefix
    Click "Yes"
    $null = Wait-For "The sanitized document is ready" "Text" 120
    $sanitizedPdf = Get-ChildItem $Work -Filter "invented-memo.sanitized.*" | Select-Object -First 1
    if (-not $sanitizedPdf) { throw "no sanitized PDF written" }
    Write-Host "   ok: $($sanitizedPdf.Name)"

    Step "passed"
} finally {
    if (-not $script:proc.HasExited) { $script:proc.Kill() }
}
