@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在安装并启动电商订单异常处理系统...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
if errorlevel 1 (
  echo.
  echo 安装未完成，请查看上方提示。
  pause
  exit /b 1
)
echo.
echo 安装完成。浏览器将打开 n8n。
pause
