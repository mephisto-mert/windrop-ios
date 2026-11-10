@echo off
chcp 65001 >nul
title WinDrop - Windows Guvenlik Duvari Izni

echo ========================================================
echo        WinDrop - Windows Guvenlik Duvari Izni
echo ========================================================
echo.
echo iPhone'un bilgisayariniza dosya gonderebilmesi icin
echo 8765 portuna guvenlik duvari izni tanimlaniyor...
echo.

:: Check Admin / Elevation
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Yonetici yetkisi gerekiyor. UAC onay penceresi aciliyor...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd -ArgumentList '/c `\"%~f0`\"' -Verb RunAs"
    exit /b
)

echo [*] Port 8765 TCP kurali ekleniyor...
netsh advfirewall firewall delete rule name="WinDrop P2P" >nul 2>&1
netsh advfirewall firewall add rule name="WinDrop P2P" dir=in action=allow protocol=TCP localport=8765 profile=any >nul 2>&1

echo [*] WinDrop.exe uygulama kurali ekleniyor...
netsh advfirewall firewall delete rule name="WinDrop App" >nul 2>&1
if exist "%~dp0WinDrop.exe" (
    netsh advfirewall firewall add rule name="WinDrop App" dir=in action=allow program="%~dp0WinDrop.exe" enable=yes profile=any >nul 2>&1
)

echo.
echo ========================================================
echo  [TAMAMLANDI] Guvenlik duvari engeli basariyla kaldirildi!
echo  Simdi iPhone'unuzdan QR kodu tekrar okutabilirsiniz.
echo ========================================================
echo.
pause
