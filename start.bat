@echo off
chcp 65001 >nul
cd /d %~dp0backend
echo [1/3] starting backend API + scheduler (port 8000)...
start "InfoGather-API" /min ..\.venv\Scripts\python.exe -m app.serve
timeout /t 4 >nul
echo [2/3] starting cloudflare tunnel...
start "InfoGather-Tunnel" /min cmd /c "C:\Android\tools\cloudflared.exe tunnel --url http://127.0.0.1:8000 --no-autoupdate 2>>C:\Android\tools\tunnel.log"
timeout /t 12 >nul
echo [3/3] your public URL (phone browser, fill APP_KEY once):
powershell -NoProfile -Command "Select-String -Path C:\Android\tools\tunnel.log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -Last 1 | ForEach-Object { $_.Matches[0].Value }"
echo.
echo close the two minimized windows to stop services.
pause
