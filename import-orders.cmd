@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (
  echo 请把订单 CSV 文件拖到 import-orders.cmd 上。
  echo 可先复制 samples\orders-template.csv 作为模板。
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\import-orders.ps1" -CsvPath "%~1"
pause
