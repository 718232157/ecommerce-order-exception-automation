$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    throw '尚未安装，请先双击 setup.cmd。'
}
$n8nPort = '5678'
Get-Content -LiteralPath $envPath | ForEach-Object {
    if ($_ -match '^N8N_PORT=(\d+)$') { $n8nPort = $matches[1] }
}
Push-Location $projectRoot
try {
    & docker compose --env-file $envPath up -d
    if ($LASTEXITCODE -ne 0) { throw '启动失败，请确认 Docker Desktop 已运行。' }
    Write-Host "服务已启动：http://127.0.0.1:$n8nPort" -ForegroundColor Green
    Start-Process "http://127.0.0.1:$n8nPort"
}
finally { Pop-Location }
