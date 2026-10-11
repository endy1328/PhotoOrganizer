param(
    [string]$DistDir = "dist_release",
    [string]$BuildDir = "build_release"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$distPath = Join-Path $projectRoot $DistDir
$buildPath = Join-Path $projectRoot $BuildDir
$specPath = Join-Path $projectRoot "PhotoOrganizer.spec"

if (-not (Test-Path $venvPython)) {
    throw ".venv\Scripts\python.exe 를 찾을 수 없습니다."
}

if (-not (Test-Path $specPath)) {
    throw "PhotoOrganizer.spec 를 찾을 수 없습니다."
}

Write-Host "[1/2] 테스트 실행"
& $venvPython -m unittest discover -s (Join-Path $projectRoot "tests")

Write-Host "[2/2] PyInstaller 대체 출력 경로 빌드"
& $venvPython -m PyInstaller --distpath $distPath --workpath $buildPath $specPath

Write-Host "빌드 완료: $distPath\PhotoOrganizer.exe"
