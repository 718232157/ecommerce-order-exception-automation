$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$docker = 'docker'

Push-Location $projectRoot
try {
    & $docker compose up -d --build
    $imported = $false
    foreach ($attempt in 1..3) {
        Start-Sleep -Seconds 2
        & $docker compose exec -T n8n n8n import:workflow --separate --input='/workflow-templates/'
        $workflowList = (& $docker compose exec -T n8n n8n list:workflow) -join "`n"
        if ($workflowList -match 'DeadLetterWatch01') {
            $imported = $true
            break
        }
        Write-Host "n8n is still completing its first-run initialization; retrying ($attempt/3)..."
    }
    if (-not $imported) { throw 'Could not import the 5 workflows after 6 seconds.' }
    foreach ($id in @('JUilG7xnUiQAOAYX','U8GXSUjQqCWLtI2I','PfNG53rh2exExojv','DailyOpsReport01','DeadLetterWatch01')) {
        & $docker compose exec -T n8n n8n publish:workflow --id=$id
    }
    & $docker compose restart n8n | Out-Null
    Write-Host '5 条工作流已导入并发布，请在 http://localhost:5678 查看。' -ForegroundColor Green
}
finally {
    Pop-Location
}
