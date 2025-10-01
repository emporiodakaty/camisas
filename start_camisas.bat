@echo off
setlocal

set BASE=C:\Users\Lenovo\camisas
set VENV=%BASE%\.venv

cd /d "%BASE%"
call "%VENV%\Scripts\activate.bat"

set DJANGO_SETTINGS_MODULE=fabrica.settings
set PYTHONUNBUFFERED=1

rem Libera porta 8000 no firewall (idempotente)
netsh advfirewall firewall add rule name="Django 8000" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1

rem Descobre IP (para você abrir em outro dispositivo)
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /r /c:"IPv4 Address" /c:"Endere.* IPv4"') do set ip_raw=%%a
for /f "tokens=* delims= " %%b in ("%ip_raw%") do set LOCAL_IP=%%b

echo ============================================
echo  Abra em outro dispositivo: http://%LOCAL_IP%:8000
echo ============================================

python manage.py runserver 0.0.0.0:8000
endlocal
