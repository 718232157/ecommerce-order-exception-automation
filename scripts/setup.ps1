param([switch]$NoOpen)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot '.env'

function Write-Step([string]$message) {
    Write-Host "`n==> $message" -ForegroundColor Cyan
}

function New-Secret([int]$bytes = 32) {
    $buffer = New-Object byte[] $bytes
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($buffer) } finally { $generator.Dispose() }
    return ([BitConverter]::ToString($buffer) -replace '-', '').ToLowerInvariant()
}

function Wait-ForUrl([string]$url, [int]$seconds = 90) {
    $deadline = (Get-Date).AddSeconds($seconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return }
        }
        catch { Start-Sleep -Seconds 2 }
    } while ((Get-Date) -lt $deadline)
    throw "服务启动超时：$url。请运行 docker compose logs 查看原因。"
}

Push-Location $projectRoot
try {
    Write-Step '检查 Docker'
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw '没有找到 Docker。请先安装并启动 Docker Desktop：https://www.docker.com/products/docker-desktop/'
    }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop 尚未启动，请启动后重新双击 setup.cmd。' }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { throw '当前 Docker 缺少 Compose 插件，请更新 Docker Desktop。' }

    if (-not (Test-Path -LiteralPath $envPath)) {
        Write-Step '自动生成本地配置和安全密钥'
        $content = @(
            'GENERIC_TIMEZONE=Asia/Shanghai'
            'TZ=Asia/Shanghai'
            'FEISHU_WEBHOOK_URL='
            'FEISHU_APP_ID='
            'FEISHU_APP_SECRET='
            'FEISHU_BITABLE_APP_TOKEN='
            'FEISHU_BITABLE_TABLE_ID='
            'CONTAINER_HTTP_PROXY='
            "POSTGRES_PASSWORD=$(New-Secret 24)"
            "INBOUND_WEBHOOK_SECRET=$(New-Secret)"
            "REVIEW_API_KEY=$(New-Secret)"
            "ADMIN_API_KEY=$(New-Secret)"
            "INTERNAL_API_KEY=$(New-Secret)"
            'SEED_SAMPLE_DATA=true'
            'ENABLE_DAILY_REPORTS=false'
            'ENABLE_DEAD_LETTER_ALERTS=false'
        )
        [System.IO.File]::WriteAllLines($envPath, $content, [System.Text.UTF8Encoding]::new($false))
    }
    else {
        Write-Host '保留已有 .env 配置，不覆盖密钥。' -ForegroundColor DarkGray
    }

    Write-Step '下载镜像并启动 PostgreSQL、API 和 n8n'
    & docker compose --env-file $envPath up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'Docker 服务启动失败。' }
    Wait-ForUrl 'http://127.0.0.1:8080/health/ready'
    Wait-ForUrl 'http://127.0.0.1:5678/healthz'

    Write-Step '自动导入并发布 5 条工作流'
    $imported = $false
    foreach ($attempt in 1..3) {
        Start-Sleep -Seconds 2
        & docker compose --env-file $envPath exec -T n8n n8n import:workflow --separate --input='/workflow-templates/'
        $workflowList = (& docker compose --env-file $envPath exec -T n8n n8n list:workflow) -join "`n"
        if ($workflowList -match 'DeadLetterWatch01') {
            $imported = $true
            break
        }
        Write-Host "n8n 首次初始化尚未完成，正在重试 ($attempt/3)..."
    }
    if (-not $imported) { throw '等待 6 秒后仍未能导入全部工作流。' }
    foreach ($id in @('JUilG7xnUiQAOAYX','U8GXSUjQqCWLtI2I','PfNG53rh2exExojv','DailyOpsReport01','DeadLetterWatch01')) {
        & docker compose --env-file $envPath exec -T n8n n8n publish:workflow --id=$id
        if ($LASTEXITCODE -ne 0) { throw "发布工作流失败：$id" }
    }
    & docker compose --env-file $envPath restart n8n | Out-Null
    Wait-ForUrl 'http://127.0.0.1:5678/healthz'

    Write-Step '安装完成'
    Write-Host '首次使用只需在浏览器中创建一个 n8n 管理员账号。' -ForegroundColor Green
    Write-Host 'n8n 工作流：http://127.0.0.1:5678'
    Write-Host '接口文档：http://127.0.0.1:8080/docs'
    Write-Host '以后启动：双击 start.cmd；停止：双击 stop.cmd。'
    if (-not $NoOpen) { Start-Process 'http://127.0.0.1:5678' }
}
finally {
    Pop-Location
}
