@echo off
title WinYandexMusicRPC
cd /d "%~dp0"

echo ================================
echo   WinYandexMusicRPC
echo ================================
echo.
echo Запуск через Python 3.12...
echo.

py -3.12 main.py

echo.
echo ================================
echo   Программа завершена
echo ================================
pause
