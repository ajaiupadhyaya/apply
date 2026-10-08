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
function Check-Winget($code) {
  # -1978335189 and -1978335212 mean "already installed" or "nothing to upgrade".
  if ($code -ne 0 -and $code -ne -1978335189 -and $code -ne -1978335212) {
    Write-Host "winget exited with code $code. Read the messages above; the rest of the setup continues." -ForegroundColor Yellow
  }
}

if (-not (Have git)) {
  Write-Host "Git is not installed. It is optional, because this folder is already cloned." -ForegroundColor Yellow
  if (Have winget) {
    if (Ask "Install Git?") {
      winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
      Check-Winget $LASTEXITCODE
      Refresh-Path
    }
  } else {
    Write-Host "winget is missing, so install Git by hand from https://git-scm.com/download/win if you want it." -ForegroundColor Yellow
  }
}

if (-not (Have uv)) {
  if (Ask "Install uv (the Python manager APPLY uses)?") {
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    Refresh-Path
    if (-not (Have uv)) {
      Write-Host "uv installed but not found. Close this window, open a new PowerShell, and re-run this script." -ForegroundColor Red
      exit 1
    }
  } else { Write-Host "uv is required."; exit 1 }
}

$miktexTried = $false
if (-not (Have pdflatex) -and (Ask "Install MiKTeX (typesets the PDFs; about 300 MB)?")) {
  $miktexTried = $true
  if (Have winget) {
    winget install --id MiKTeX.MiKTeX -e --accept-package-agreements --accept-source-agreements
    Check-Winget $LASTEXITCODE
    Refresh-Path
  } else {
    Write-Host "winget is missing, so MiKTeX cannot be installed here. Install it by hand from https://miktex.org/download, then re-run this script." -ForegroundColor Yellow
  }
}
if (Have initexmf) {
  # Without this MiKTeX opens a dialog for each missing package, and a
  # scheduled run waits forever for a click.
  initexmf --set-config-value=[MPM]AutoInstall=1 | Out-Null
} elseif ($miktexTried) {
  Write-Host "MiKTeX is not on PATH yet. Open a NEW PowerShell and run: initexmf --set-config-value=[MPM]AutoInstall=1" -ForegroundColor Yellow
}

uv sync
if ($LASTEXITCODE -ne 0) { Write-Host "uv sync failed (see above)." -ForegroundColor Red; exit 1 }
uv run apply setup
Write-Host ""
Write-Host "Open a new terminal before using uv directly; from this folder: uv run apply status" -ForegroundColor Green
