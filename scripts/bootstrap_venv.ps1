$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$bundledPipWheel = "C:\Program Files\Blender Foundation\Blender 4.5\4.5\python\Lib\ensurepip\_bundled\pip-24.0-py3-none-any.whl"

if (-not (Test-Path $venvPython)) {
    throw ".venv\Scripts\python.exe 를 찾을 수 없습니다."
}

if (-not (Test-Path $bundledPipWheel)) {
    throw "내장 pip wheel 을 찾을 수 없습니다: $bundledPipWheel"
}

$requirements = Join-Path $projectRoot "requirements.txt"

& $venvPython -c @"
import runpy
import sys
sys.path.insert(0, r"$bundledPipWheel")
sys.argv = [
    "pip",
    "install",
    "--no-cache-dir",
    "-r",
    r"$requirements",
]
runpy.run_module("pip", run_name="__main__")
"@
