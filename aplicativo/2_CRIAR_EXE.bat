@echo off
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name "ATS_ETS2" --icon ATS_ETS2.ico --add-data "logo.png;." --add-data "ATS_ETS2.ico;." ats_pack_manager.py
if errorlevel 1 (echo Falha ao gerar o executavel. & pause & exit /b 1)
echo Pronto! Abra dist\ATS_ETS2.exe
pause
