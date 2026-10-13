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

Write-Host "[1/3] 프로젝트 전용 ExifTool 버전 및 파일 해시 검증"
& $venvPython (Join-Path $PSScriptRoot "vendor_exiftool.py")
if ($LASTEXITCODE -ne 0) { throw "ExifTool 검증에 실패했습니다. 빌드를 중단합니다." }

Write-Host "[2/3] 테스트 실행"
& $venvPython -m unittest discover -s (Join-Path $projectRoot "tests")
if ($LASTEXITCODE -ne 0) { throw "테스트에 실패했습니다. 빌드를 중단합니다." }

Write-Host "[3/3] PyInstaller 대체 출력 경로 빌드"
& $venvPython -m PyInstaller --distpath $distPath --workpath $buildPath $specPath
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 빌드에 실패했습니다." }

Write-Host "빌드 완료: $distPath\PhotoOrganizer.exe"
