$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) { throw '请先双击 setup.cmd 完成安装。' }

Write-Host '飞书连接向导' -ForegroundColor Cyan
Write-Host "请从飞书开放平台和多维表格地址中复制以下信息。直接回车会保留原值。`n"
$inputValues = [ordered]@{
    FEISHU_WEBHOOK_URL = Read-Host '群自定义机器人 Webhook URL'
    FEISHU_APP_ID = Read-Host '企业自建应用 App ID'
    FEISHU_APP_SECRET = Read-Host '企业自建应用 App Secret'
    FEISHU_BITABLE_APP_TOKEN = Read-Host '多维表格 App Token'
    FEISHU_BITABLE_TABLE_ID = Read-Host '数据表 Table ID'
}

$lines = [System.Collections.Generic.List[string]](Get-Content -LiteralPath $envPath)
foreach ($entry in $inputValues.GetEnumerator()) {
    if ([string]::IsNullOrWhiteSpace($entry.Value)) { continue }
    $found = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index].StartsWith("$($entry.Key)=")) {
            $lines[$index] = "$($entry.Key)=$($entry.Value.Trim())"
            $found = $true
            break
        }
    }
    if (-not $found) { $lines.Add("$($entry.Key)=$($entry.Value.Trim())") }
}
[System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))

Push-Location $projectRoot
try {
    Write-Host "`n正在重启服务并初始化飞书台账..." -ForegroundColor Cyan
    & docker compose --env-file $envPath up -d --force-recreate order-api
    if ($LASTEXITCODE -ne 0) { throw '服务重启失败。' }
    Start-Sleep -Seconds 6
    $adminLine = $lines | Where-Object { $_.StartsWith('ADMIN_API_KEY=') } | Select-Object -First 1
    $adminKey = $adminLine.Split('=', 2)[1]
    $result = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8080/feishu/bootstrap' -Headers @{'X-API-Key'=$adminKey}
    if (-not $result.configured) { throw '飞书参数不完整，请重新运行配置向导。' }
    Write-Host '飞书连接成功，多维表格字段已初始化。' -ForegroundColor Green
    Write-Host '日报和死信告警仍保持关闭，可在 .env 确认目标群后手动开启。'
}
finally { Pop-Location }
