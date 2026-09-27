$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m venv .venv-bot
if ($LASTEXITCODE -ne 0) { throw 'Creation environnement bot impossible' }
python -m venv .venv-self
if ($LASTEXITCODE -ne 0) { throw 'Creation environnement selfbot impossible' }
& .\.venv-bot\Scripts\python.exe -m pip install -r requirements-bot.txt
if ($LASTEXITCODE -ne 0) { throw 'Installation bot impossible' }
& .\.venv-self\Scripts\python.exe -m pip install -r requirements-self.txt
if ($LASTEXITCODE -ne 0) { throw 'Installation selfbot impossible' }
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
Write-Host 'Configure .env puis lance : .\.venv-bot\Scripts\python.exe bot.py'
