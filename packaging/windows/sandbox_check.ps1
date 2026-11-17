# Offline check on a machine with no network: install, self-test, then the
# window-driven run. Started by offline-check.wsb inside Windows Sandbox; on a
# clean VM or PC with the network off, run it by hand from the folder that
# holds the installer, gui_smoke.ps1 and the two invented documents.
param(
    [string] $From = $PSScriptRoot,
    [string] $Out = [Environment]::GetFolderPath("Desktop")  # where the result and outputs go
)
$ErrorActionPreference = "Stop"
$result = Join-Path $Out "offline-check-result.txt"
$work = Join-Path $Out "work"
function Note($text) { $text | Tee-Object -FilePath $result -Append | Write-Host }

Note "Offline check, $(Get-Date -Format 's'), Windows $([Environment]::OSVersion.Version)"
$up = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object Status -eq "Up" | ForEach-Object Name)
Note "network adapters up: $($up.Count) $($up -join ', ')"
$profiles = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)
$internet = @($profiles | Where-Object { $_.IPv4Connectivity -eq "Internet" -or $_.IPv6Connectivity -eq "Internet" })
$local = @($profiles | Where-Object { $_ -notin $internet -and ($_.IPv4Connectivity -eq "LocalNetwork" -or $_.IPv6Connectivity -eq "LocalNetwork") })
if ($internet.Count) { Note "WARNING: internet connectivity on: $($internet.InterfaceAlias -join ', '); the network is not off" }
else { Note "internet connectivity: none" }
# A VPN adapter (Tailscale, for example) can stay Up with no physical link under it.
if ($local.Count) { Note "local-only networks still listed: $($local.InterfaceAlias -join ', ')" }

$setup = Get-ChildItem $From -Filter "Replace-o-matic-Setup-*.exe" | Select-Object -First 1
$p = Start-Process $setup.FullName -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER" -Wait -PassThru
Note "install ($($setup.Name)): exit $($p.ExitCode)"
$app = "$env:LOCALAPPDATA\Programs\Replace-o-matic\Replace-o-matic.exe"
Note ("self-test: " + ((& $app --self-test | Out-String).Trim()) + " (exit $LASTEXITCODE)")

New-Item -ItemType Directory -Force $work | Out-Null
Copy-Item (Join-Path $From "invented-*.*") $work
& powershell -ExecutionPolicy Bypass -File (Join-Path $From "gui_smoke.ps1") -Work $work *>&1 | ForEach-Object { Note "$_" }
Note "window run: exit $LASTEXITCODE"
