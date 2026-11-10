@echo off
chcp 65001 >nul
title WinDrop — Windows <-> iPhone Kayipsiz AirDrop
cd /d "%~dp0"

:: Python 3.12 tespiti (Sistem varsayilani Python 3.14 PyQt6 barindirmaz; Python 3.12 zorunludur)
set "PY_EXE=C:\Users\pc\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY_EXE%" (
    py -3.12 --version >nul 2>&1
    if not errorlevel 1 (
        set "PY_EXE=py -3.12"
    ) else (
        set "PY_EXE=python"
    )
)

echo [WinDrop] Windows <-> iPhone Kayipsiz AirDrop Radar baslatiliyor...
%PY_EXE% "%~dp0windrop_gui.py" %*
