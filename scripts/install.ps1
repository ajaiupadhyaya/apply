# APPLY setup for Windows. From the folder you cloned into:
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
# Safe to re-run: anything already installed is skipped.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Have($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function Ask($q) { (Read-Host "$q [Y/n]") -notmatch '^[nN]' }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path", "User")
}

if (-not (Have winget)) {
  Write-Host "winget is missing. Install 'App Installer' from the Microsoft Store, then re-run." -ForegroundColor Red
  exit 1
}
if (-not (Have git) -and (Ask "Install Git?")) {
  winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
  Refresh-Path
}
if (-not (Have uv)) {
  if (Ask "Install uv (the Python manager APPLY uses)?") {
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    Refresh-Path
  } else { Write-Host "uv is required."; exit 1 }
}
if (-not (Have pdflatex) -and (Ask "Install MiKTeX (typesets the PDFs; about 300 MB)?")) {
  winget install --id MiKTeX.MiKTeX -e --accept-package-agreements --accept-source-agreements
  Refresh-Path
}
if (Have initexmf) {
  # Without this MiKTeX opens a dialog for each missing package, and a
  # scheduled run waits forever for a click.
  initexmf --set-config-value=[MPM]AutoInstall=1 | Out-Null
}

uv sync
uv run apply setup
