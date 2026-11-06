<#
.SYNOPSIS
  Set up explainer-reel-kit on this PC (no administrator rights needed).

.DESCRIPTION
  1. Find Python 3.10 or later (py -3, then python). If missing, show how to install it and stop.
  2. Create .venv in the kit folder and install the kit (pip install -e ".[dev]").
  3. Install the browser for capture and diagrams (python -m playwright install chromium).
     If that fails, continue and show how to use Microsoft Edge instead (--channel msedge).
  4. Copy config\*.example.yaml to config\*.yaml (existing files are never overwritten).
  5. Run "erkit doctor" and show what is still missing.

  This script does NOT install ffmpeg, AivisSpeech or PowerPoint. It only prints how to install them.
  Keep this file ASCII only (Windows PowerShell 5.1 reads files without a BOM as the system code page).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -SkipBrowser -SkipDoctor
#>
[CmdletBinding()]
param(
    # Path to python.exe to use (default: py -3, then python on PATH)
    [string]$Python = "",
    # Do not install the Playwright browser
    [switch]$SkipBrowser,
    # Do not run "erkit doctor" at the end
    [switch]$SkipDoctor
)

# "Continue": pip and playwright write progress to stderr. Each step checks $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
$KitRoot = $PSScriptRoot
$MinMajor = 3
$MinMinor = 10

function Write-Step([string]$text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Write-Note([string]$text) { Write-Host "   $text" }
function Write-Warn([string]$text) { Write-Host "   $text" -ForegroundColor Yellow }

function Test-PythonCommand([string[]]$cmd) {
    # Returns "major.minor" if the command runs Python, otherwise $null
    try {
        $exe = $cmd[0]
        $rest = @()
        if ($cmd.Length -gt 1) { $rest = $cmd[1..($cmd.Length - 1)] }
        $out = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return ([string]$out).Trim() }
    } catch { }
    return $null
}

function Test-VersionOk([string]$ver) {
    if (-not $ver) { return $false }
    $parts = $ver.Split(".")
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    return ($major -gt $MinMajor) -or ($major -eq $MinMajor -and $minor -ge $MinMinor)
}

Push-Location $KitRoot
try {
    if (-not (Test-Path (Join-Path $KitRoot "pyproject.toml"))) {
        Write-Host "pyproject.toml was not found next to install.ps1. Run this script from the kit folder." -ForegroundColor Red
        exit 2
    }

    # ---- 1. Python
    Write-Step "1/5 Python $MinMajor.$MinMinor or later"
    $candidates = @()
    if ($Python) { $candidates += , @($Python) } else { $candidates += , @("py", "-3"); $candidates += , @("python") }
    $pyCmd = $null
    foreach ($c in $candidates) {
        $ver = Test-PythonCommand $c
        if ($ver) {
            if (Test-VersionOk $ver) { $pyCmd = $c; Write-Note ("found: " + ($c -join " ") + " (Python $ver)"); break }
            Write-Warn (($c -join " ") + " is Python $ver (too old)")
        }
    }
    if (-not $pyCmd) {
        Write-Host "   Python $MinMajor.$MinMinor or later was not found." -ForegroundColor Red
        Write-Note "Install it, open a new PowerShell window, and run install.ps1 again:"
        Write-Note "  winget install Python.Python.3.12"
        Write-Note "  (or download it from https://www.python.org/downloads/ )"
        exit 1
    }

    # ---- 2. .venv and the kit
    Write-Step "2/5 Virtual environment (.venv) and the kit"
    $venvPy = Join-Path $KitRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        Write-Note ".venv already exists (reused)"
    } else {
        $exe = $pyCmd[0]
        $rest = @()
        if ($pyCmd.Length -gt 1) { $rest = $pyCmd[1..($pyCmd.Length - 1)] }
        & $exe @rest -m venv (Join-Path $KitRoot ".venv")
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) {
            Write-Host "   Could not create .venv." -ForegroundColor Red
            exit 1
        }
        Write-Note "created .venv"
    }
    & $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check
    & $venvPy -m pip install -e ".[dev]" --quiet --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   pip install failed. Check the network or proxy settings, then run install.ps1 again." -ForegroundColor Red
        exit 1
    }
    Write-Note "installed explainer-reel-kit into .venv"

    # ---- 3. Browser
    Write-Step "3/5 Browser for capture and diagrams"
    if ($SkipBrowser) {
        Write-Note "skipped (-SkipBrowser)"
    } else {
        & $venvPy -m playwright install chromium
        if ($LASTEXITCODE -eq 0) {
            Write-Note "installed Chromium for Playwright"
        } else {
            Write-Warn "Could not install Chromium. You can use Microsoft Edge instead:"
            Write-Warn "  add --channel msedge to erkit diagram / capture / make / doctor"
        }
    }

    # ---- 4. Config files
    Write-Step "4/5 Config files"
    $examples = Get-ChildItem (Join-Path $KitRoot "config") -Filter "*.example.yaml" -File -ErrorAction SilentlyContinue
    foreach ($f in $examples) {
        $dest = Join-Path $f.DirectoryName ($f.Name -replace "\.example\.yaml$", ".yaml")
        if (Test-Path $dest) {
            Write-Note ("kept   config\" + (Split-Path $dest -Leaf) + " (already exists)")
        } else {
            Copy-Item $f.FullName $dest
            Write-Note ("copied config\" + $f.Name + " -> config\" + (Split-Path $dest -Leaf))
        }
    }

    # ---- 5. Doctor
    Write-Step "5/5 erkit doctor"
    $erkit = Join-Path $KitRoot ".venv\Scripts\erkit.exe"
    $doctorCode = 0
    if ($SkipDoctor) {
        Write-Note "skipped (-SkipDoctor)"
    } else {
        & $erkit doctor
        $doctorCode = $LASTEXITCODE
    }

    Write-Host ""
    Write-Host "Done." -ForegroundColor Green
    Write-Note "Not installed by this script (install them yourself if doctor shows NG):"
    Write-Note "  ffmpeg      : winget install Gyan.FFmpeg   (then open a new PowerShell window)"
    Write-Note "  AivisSpeech : install it from its official site and start it"
    Write-Note "  PowerPoint  : the desktop version is needed to export MP4"
    Write-Host ""
    Write-Note "Next time, in a new PowerShell window:"
    Write-Note "  cd `"$KitRoot`""
    Write-Note "  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass"
    Write-Note "  .\.venv\Scripts\Activate.ps1"
    Write-Note "  erkit doctor"
    Write-Note "Try the sample (needs AivisSpeech running):"
    Write-Note "  erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app"
    Write-Note "Guide: docs\guide\README.md"
    if ($doctorCode -ne 0) {
        Write-Warn "erkit doctor found missing items (see the NG lines above). Install them, then run: erkit doctor"
    }
    # The kit itself is installed, so this script succeeds even if doctor reports missing software.
    exit 0
} finally {
    Pop-Location
}
