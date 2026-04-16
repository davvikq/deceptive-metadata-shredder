@echo off
REM Сначала собрать exe через PyInstaller
pyinstaller --onefile --windowed ^
  --additional-hooks-dir hooks/ ^
  --add-data "src/dms/data;dms/data" ^
  --add-binary "bin/exiftool.exe;bin" ^
  --add-data "bin/exiftool_files;bin/exiftool_files" ^
  --icon "src/dms/data/icon.ico" ^
  --name "DMS_Portable" ^
  src/dms/interfaces/gui/app.py

REM Затем собрать installer через Inno Setup
REM Стандартный путь установки Inno Setup на Windows:
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" scripts/installer.iss

echo Done! Check dist/ folder.
pause
