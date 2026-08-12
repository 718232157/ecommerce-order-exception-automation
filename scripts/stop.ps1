$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot '.env'
Push-Location $projectRoot
try {
    & docker compose --env-file $envPath down
    if ($LASTEXITCODE -ne 0) { throw '停止服务失败。' }
    Write-Host '服务已停止，订单、工作流和数据库数据均已保留。' -ForegroundColor Green
}
finally { Pop-Location }
