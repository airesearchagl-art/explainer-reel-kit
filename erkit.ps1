<#
.SYNOPSIS
  Run erkit from the kit's .venv without activating it.

.DESCRIPTION
  Calls .venv\Scripts\erkit.exe with all arguments and returns its exit code.
  Run install.ps1 first if .venv does not exist.
  Keep this file ASCII only (Windows PowerShell 5.1).

.EXAMPLE
  .\erkit.ps1 doctor

.EXAMPLE
  .\erkit.ps1 check samples\u-value\u-value.storyboard.md
#>
$erkit = Join-Path $PSScriptRoot ".venv\Scripts\erkit.exe"
if (-not (Test-Path $erkit)) {
    Write-Host "erkit is not installed in .venv. Run this first:" -ForegroundColor Red
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1"
    exit 2
}
& $erkit @args
exit $LASTEXITCODE
