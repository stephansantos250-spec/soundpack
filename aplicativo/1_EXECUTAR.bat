@echo off
cd /d "%~dp0"
python ats_pack_manager.py
if errorlevel 1 (echo. & echo Instale o Python 64 bits em https://www.python.org/downloads/ marcando "Add Python to PATH". & pause)
