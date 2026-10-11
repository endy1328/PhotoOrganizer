$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw ".venv\Scripts\python.exe 를 찾을 수 없습니다."
}

Write-Host "[1/4] Python / pip 확인"
& $venvPython -c "import sys; print(sys.executable); print(sys.version)"
& $venvPython -m pip list

Write-Host "[2/4] 단위 테스트 실행"
& $venvPython -m unittest discover -s (Join-Path $projectRoot "tests")

Write-Host "[3/4] GUI 오프스크린 스모크 테스트"
$env:QT_QPA_PLATFORM = "offscreen"
& $venvPython -c @"
from PySide6.QtWidgets import QApplication
from photo_organizer.config import ConfigManager
from photo_organizer.engine import OrganizerEngine
from photo_organizer.ui.main_window import MainWindow
from pathlib import Path
app = QApplication([])
base_dir = Path(r"$projectRoot")
window = MainWindow(OrganizerEngine(base_dir), ConfigManager(base_dir))
print(type(window).__name__)
"@
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue

Write-Host "[4/4] PyInstaller 빌드"
& $venvPython -m PyInstaller (Join-Path $projectRoot "PhotoOrganizer.spec")

Write-Host "검증 완료"
