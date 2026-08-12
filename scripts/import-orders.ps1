param([Parameter(Mandatory=$true)][string]$CsvPath)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) { throw '请先双击 setup.cmd 完成安装。' }
if (-not (Test-Path -LiteralPath $CsvPath)) { throw "找不到 CSV：$CsvPath" }

$secretLine = Get-Content -LiteralPath $envPath | Where-Object { $_.StartsWith('INBOUND_WEBHOOK_SECRET=') } | Select-Object -First 1
$secret = $secretLine.Split('=', 2)[1]
$accepted = 0; $duplicates = 0; $exceptions = 0

foreach ($row in (Import-Csv -LiteralPath $CsvPath)) {
    if (-not $row.orderId -or -not $row.status) { throw 'CSV 中 orderId 和 status 不能为空。' }
    $fingerprintText = ($row | ConvertTo-Json -Compress)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $fingerprint = (([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($fingerprintText))) -replace '-', '').ToLowerInvariant()).Substring(0,16)
    $payload = [ordered]@{
        eventId = "csv:$($row.orderId):$fingerprint"
        orderId = $row.orderId
        status = $row.status.ToUpperInvariant()
        paidAt = if ($row.paidAt) { $row.paidAt } else { $null }
        shippedAt = if ($row.shippedAt) { $row.shippedAt } else { $null }
        refundRequestedAt = if ($row.refundRequestedAt) { $row.refundRequestedAt } else { $null }
        amount = if ($row.amount) { [double]$row.amount } else { 0 }
        quantity = if ($row.quantity) { [int]$row.quantity } else { 1 }
        stock = if ($row.stock) { [int]$row.stock } else { 0 }
        riskScore = if ($row.riskScore) { [int]$row.riskScore } else { 0 }
        duplicatePayment = $row.duplicatePayment -match '^(1|true|yes|y)$'
        customer = if ($row.customer) { $row.customer } else { $null }
    }
    $body = $payload | ConvertTo-Json -Compress
    $timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds().ToString()
    $hmac = [System.Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($secret))
    $signature = ([BitConverter]::ToString($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes("$timestamp.$body"))) -replace '-', '').ToLowerInvariant()
    $result = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8080/v1/orders/ingest' -Headers @{'X-Timestamp'=$timestamp;'X-Signature'=$signature} -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
    $accepted++; if ($result.duplicate) { $duplicates++ }; $exceptions += @($result.exceptions).Count
}

Write-Host "导入完成：订单 $accepted 条，重复 $duplicates 条，识别异常 $exceptions 个。" -ForegroundColor Green
Write-Host '查看异常：http://127.0.0.1:8080/exceptions'
