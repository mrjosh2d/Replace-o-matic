# Network check of the installed app under Sysinternals Process Monitor, with
# the network ON. Run from the repository root, in a normal (not elevated)
# PowerShell; Windows asks twice for administrator approval (Process Monitor
# needs it to start and to stop). See README.md.
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\procmon_check.ps1 `
#       -Procmon C:\Tools\Procmon64.exe -Work C:\some\empty\folder
#
# -Work must hold the two invented documents (make_test_documents.py). The
# capture is filtered to Replace-o-matic.exe and deleted after it is summarised;
# only the summary is kept, in packaging\windows\results\.
param(
    [Parameter(Mandatory)] [string] $Procmon,
    [Parameter(Mandatory)] [string] $Work,
    [string] $Python = ".venv\Scripts\python.exe"
)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$pmc = Join-Path $here "replace_o_matic_process.pmc"
$pml = Join-Path $env:TEMP "replace-o-matic-check.pml"
$results = Join-Path $here "results"
New-Item -ItemType Directory -Force $results | Out-Null
Remove-Item $pml -ErrorAction SilentlyContinue

Write-Host "== start Process Monitor (approve the prompt)"
Start-Process $Procmon -Verb RunAs -ArgumentList "/AcceptEula", "/Quiet", "/Minimized", "/BackingFile", "`"$pml`"", "/LoadConfig", "`"$pmc`""
$deadline = (Get-Date).AddSeconds(60)
while (-not (Test-Path $pml) -and (Get-Date) -lt $deadline) { Start-Sleep 1 }
if (-not (Test-Path $pml)) { throw "Process Monitor did not start capturing" }
Start-Sleep 3

$smoke = "failed"
try {
    & powershell -ExecutionPolicy Bypass -File (Join-Path $here "gui_smoke.ps1") -Work $Work
    if ($LASTEXITCODE -eq 0) { $smoke = "passed" }
} finally {
    Write-Host "== stop Process Monitor (approve the prompt)"
    Start-Process $Procmon -Verb RunAs -ArgumentList "/Terminate" -Wait
}

$version = (Get-Item $Procmon).VersionInfo.ProductVersion
$summary = & $Python (Join-Path $here "procmon_summary.py") $pml
$code = $LASTEXITCODE
Remove-Item $pml -Force
$stamp = Get-Date -Format "yyyy-MM-dd"
$report = @(
    "Process Monitor network check, $stamp",
    "Process Monitor $version; filter replace_o_matic_process.pmc (Process Name is Replace-o-matic.exe)",
    "Windows $([Environment]::OSVersion.Version); network on",
    "Run: gui_smoke.ps1 (new matter, sanitize .docx, keys, restore, sanitize .pdf): $smoke",
    ""
) + $summary
$report | Set-Content (Join-Path $results "procmon-$stamp.txt") -Encoding utf8
$report | Write-Host
if ($code -ne 0 -or $smoke -ne "passed") { exit 1 }
