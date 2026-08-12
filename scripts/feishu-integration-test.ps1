$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envMap = @{}
Get-Content "$projectRoot\.env" | Where-Object { $_ -match '^[A-Z0-9_]+=' } | ForEach-Object { $key,$value=$_.Split('=',2); $envMap[$key]=$value }

$status = Invoke-RestMethod 'http://127.0.0.1:8080/feishu/status'
if (-not $status.webhookConfigured -or -not $status.bitableConfigured) {
    throw '飞书机器人或多维表格凭证尚未完整配置'
}

$orderId = 'ORD-FEISHU-TEST-' + (Get-Date -Format 'yyyyMMddHHmmss')
$order = @{
    orderId = $orderId
    status = 'PAID'
    paidAt = (Get-Date).AddHours(-2).ToString('o')
    shippedAt = $null
    amount = 2688
    quantity = 1
    stock = 9
    riskScore = 93
    refundRequestedAt = $null
    duplicatePayment = $false
    customer = '飞书联调用户'
} | ConvertTo-Json

$result = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:5678/webhook/order-exception' -Headers @{'X-Internal-Key'=$envMap.INTERNAL_API_KEY} -ContentType 'application/json' -Body $order
if (-not $result.accepted -or $result.exceptions.Count -ne 1) { throw '订单异常接入失败' }

Start-Sleep -Seconds 2
$exceptions = (Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8080/exceptions').Content | ConvertFrom-Json
$exception = $exceptions | Where-Object { $_.order_id -eq $orderId } | Select-Object -First 1
if (-not $exception.feishu_record_id) { throw '多维表格记录创建失败' }

$review = @{
    exceptionId = $exception.id
    status = 'APPROVED'
    reviewer = '自动验收'
    note = '飞书端到端测试通过'
} | ConvertTo-Json
$reviewed = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:5678/webhook/exception-review' -Headers @{'X-API-Key'=$envMap.REVIEW_API_KEY} -ContentType 'application/json' -Body $review
if ($reviewed.status -ne 'APPROVED' -or -not $reviewed._feishu.queued) {
    throw '人工复核结果同步多维表格失败'
}

Start-Sleep -Seconds 3
$stats = Invoke-RestMethod 'http://127.0.0.1:8080/stats'
if ($stats.outbox | Where-Object { $_.status -in @('RETRY','DEAD') }) { throw '飞书异步投递存在失败事件' }

Write-Host "PASS：机器人通知、多维表格新增及复核更新均成功，订单号 $orderId" -ForegroundColor Green
