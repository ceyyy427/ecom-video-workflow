# Isolated native acceptance, never a substitute for a customer's approval.
param([switch]$Acceptance)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not $Acceptance -or -not (Test-Path $python)) {
    Write-Host 'First launch the app and finish setup. This acceptance script requires the installed .venv.'
    exit 1
}
$workspace = Join-Path ([Environment]::GetFolderPath('MyDocuments')) ('Jianxu-Acceptance-' + [Guid]::NewGuid().ToString('N'))
& $python -X utf8 scripts/customer_smoke.py --workspace $workspace --simulate-confirmations
$result = $LASTEXITCODE
Write-Host "Evidence: $workspace"
exit $result
