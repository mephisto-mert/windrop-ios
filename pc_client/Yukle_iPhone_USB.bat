@echo off
chcp 65001 >nul
title WinDrop iPhone USB Otomatik Kurucu
color 0b

echo ==============================================================
echo       WinDrop iPhone USB Otonom Kurulum Baslatici
echo ==============================================================
echo.
echo  iPhone'unuzu USB kablosuyla bilgisayara baglayin.
echo  Bagladiginiz anda WinDrop otomatik olarak cihaziniza yuklenecektir.
echo.
echo --------------------------------------------------------------

set "PYTHON_EXE=C:\Users\pc\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python.exe"
)

"%PYTHON_EXE%" "C:\Users\pc\Documents\projelerim\windrop_airdrop\auto_usb_installer.py"

pause
