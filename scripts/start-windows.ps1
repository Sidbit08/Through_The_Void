param([string]$BindAddress = "127.0.0.1", [int]$Port = 8080)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
& ".\.venv\Scripts\python.exe" manage.py serve --host $BindAddress --port $Port
exit $LASTEXITCODE
