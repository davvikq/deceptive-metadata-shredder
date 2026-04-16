Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($env:OS -ne "Windows_NT") {
    throw "build.ps1 is intended for Windows. Use scripts/build_exe.sh on macOS/Linux."
}

$specFile = "DMS_Portable.spec"

Write-Host "Converting SVG icon to ICO..."
python scripts/convert_icon.py

if (Test-Path $specFile) {
    Write-Host "Using existing .spec file..."
    python -m PyInstaller $specFile
}
else {
    Write-Host "No .spec found, building from scratch..."
    python -m PyInstaller --onefile --windowed `
        --additional-hooks-dir hooks/ `
        --add-data "src/dms/data;dms/data" `
        --add-binary "bin/exiftool.exe;bin" `
        --add-data "bin/exiftool_files;bin/exiftool_files" `
        --icon "src/dms/data/icon.ico" `
        --exclude-module matplotlib `
        --exclude-module pandas `
        --exclude-module IPython `
        --exclude-module jupyter `
        --exclude-module notebook `
        --exclude-module PyQt5 `
        --exclude-module wx `
        --exclude-module gi `
        --name "DMS_Portable" `
        src/dms/interfaces/gui/app.py
}

$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    Write-Host "Building Windows installer via Inno Setup..."
    & $iscc "scripts/installer.iss"
    Write-Host "Done! Check dist/ folder."
}
else {
    Write-Warning "Inno Setup not found. Portable exe was built, but installer was skipped."
}
