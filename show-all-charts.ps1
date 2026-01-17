#!/usr/bin/env pwsh
# Nightscout CGM - Show All Charts (Last 30 Days)
# Run: .\show-all-charts.ps1

$scriptPath = "$PSScriptRoot\scripts\cgm.py"

Write-Host "`n" -NoNewline
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  NIGHTSCOUT CGM ANALYSIS - LAST 30 DAYS" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan

Write-Host "`n📈 SPARKLINE (Last 48 hours)" -ForegroundColor Yellow
Write-Host "─────────────────────────────────────────────────────────────────"
python $scriptPath chart --sparkline --hours 48 --color

Write-Host "`n🗓️  WEEKLY HEATMAP (Time-in-Range by Day/Hour)" -ForegroundColor Yellow
Write-Host "─────────────────────────────────────────────────────────────────"
python $scriptPath chart --heatmap --days 30 --color

Write-Host "`n📊 DAILY BREAKDOWN" -ForegroundColor Yellow
Write-Host "─────────────────────────────────────────────────────────────────"
foreach ($day in @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")) {
    Write-Host "`n--- $day ---" -ForegroundColor Green
    python $scriptPath chart --day $day --days 30 --color
}

Write-Host "`n🔍 PATTERN ANALYSIS" -ForegroundColor Yellow
Write-Host "─────────────────────────────────────────────────────────────────"
python $scriptPath patterns --days 30

Write-Host "`n📋 FULL STATISTICS" -ForegroundColor Yellow  
Write-Host "─────────────────────────────────────────────────────────────────"
python $scriptPath analyze --days 30

Write-Host "`n═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  END OF REPORT" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
