#!/usr/bin/env sh
set -eu

OS_NAME="$(uname -s)"

case "$OS_NAME" in
  MINGW*|MSYS*|CYGWIN*)
    pyinstaller --onefile --windowed \
      --additional-hooks-dir hooks/ \
      --add-binary "bin/exiftool.exe:bin" \
      --add-data "src/dms/data:dms/data" \
      --add-data "bin/exiftool_files:bin/exiftool_files" \
      --icon=src/dms/data/icon.ico \
      --name "DMS_Portable" \
      --exclude-module matplotlib \
      --exclude-module pandas \
      --exclude-module PyQt5 \
      --exclude-module wx \
      --exclude-module gi \
      --exclude-module IPython \
      --exclude-module jupyter \
      --exclude-module notebook \
      src/dms/interfaces/gui/app.py
    ;;
  Darwin)
    pyinstaller --onefile --windowed \
      --additional-hooks-dir hooks/ \
      --add-data "src/dms/data:dms/data" \
      --icon=src/dms/data/icon.ico \
      --name "DMS" \
      --exclude-module matplotlib \
      --exclude-module pandas \
      --exclude-module PyQt5 \
      --exclude-module wx \
      --exclude-module gi \
      --exclude-module IPython \
      --exclude-module jupyter \
      --exclude-module notebook \
      src/dms/interfaces/gui/app.py
    ;;
  Linux)
    pyinstaller --onefile \
      --additional-hooks-dir hooks/ \
      --add-data "src/dms/data:dms/data" \
      --icon=src/dms/data/icon.ico \
      --name "DMS" \
      --exclude-module matplotlib \
      --exclude-module pandas \
      --exclude-module PyQt5 \
      --exclude-module wx \
      --exclude-module gi \
      --exclude-module IPython \
      --exclude-module jupyter \
      --exclude-module notebook \
      src/dms/interfaces/gui/app.py
    ;;
  *)
    echo "Unsupported platform: $OS_NAME" >&2
    exit 1
    ;;
esac
