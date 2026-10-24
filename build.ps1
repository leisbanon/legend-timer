$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm BossTimer.spec
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Write-Host 'Ready: dist\BossTimer.exe'
