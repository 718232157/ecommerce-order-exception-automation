$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envMap = @{}
Get-Content "$projectRoot\.env" | Where-Object { $_ -match '^[A-Z0-9_]+=' } | ForEach-Object { $key,$value=$_.Split('=',2); $envMap[$key]=$value }

$health = Invoke-RestMethod 'http://127.0.0.1:8080/health'
if ($health.status -ne 'ok') { throw 'Order API 健康检查失败' }

$payload = Get-Content "$projectRoot\samples\realtime-high-risk-order.json" -Raw
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:5678/webhook/order-exception' -Headers @{'X-Internal-Key'=$envMap.INTERNAL_API_KEY} -ContentType 'application/json' -Body $payload | Out-Null

$exceptions = Invoke-RestMethod 'http://127.0.0.1:8080/exceptions'
$matches = @()
foreach ($exception in $exceptions) {
    if ($exception.order_id -eq 'ORD-TEST-HIGH-RISK-002') { $matches += $exception }
}
if ($matches.Count -ne 2) { throw "预期产生 2 类异常，实际为 $($matches.Count)" }

$risk = $matches | Where-Object exception_type -eq 'HIGH_RISK_ORDER'
$review = @{ exceptionId=$risk.id; status='APPROVED'; reviewer='自动验收'; note='smoke test' } | ConvertTo-Json
$reviewed = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:5678/webhook/exception-review' -Headers @{'X-API-Key'=$envMap.REVIEW_API_KEY} -ContentType 'application/json' -Body $review
if ($reviewed.status -ne 'APPROVED') { throw '人工复核状态更新失败' }

Write-Host "PASS：实时识别 2 类异常，异常 #$($risk.id) 已完成人工复核。" -ForegroundColor Green
