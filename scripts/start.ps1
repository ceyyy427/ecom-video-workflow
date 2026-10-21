$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv run --locked python -m ecom_video @args
    exit $LASTEXITCODE
}
$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (Test-Path $python) {
    & $python -m ecom_video @args
    exit $LASTEXITCODE
}
Write-Error 'Install uv and run uv sync --locked first. See README.md.'
exit 1
