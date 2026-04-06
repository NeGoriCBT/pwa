# Репозиторий: https://github.com/NeGoriCBT/pwa
# Запуск из корня проекта (папка CBTPWA), после git init и первого коммита:
#   powershell -ExecutionPolicy Bypass -File scripts/git-remote-negoricbt.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path ".git")) {
    Write-Host "Сначала: git init && git add . && git commit -m `"Initial`""
    exit 1
}
git remote remove origin 2>$null
git remote add origin "https://github.com/NeGoriCBT/pwa.git"
git branch -M main
Write-Host "Remote origin -> https://github.com/NeGoriCBT/pwa.git"
Write-Host "Дальше: git push -u origin main"
