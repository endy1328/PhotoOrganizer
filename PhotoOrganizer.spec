# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct, VSVersionInfo
from pathlib import Path
import runpy

release = runpy.run_path(str(Path(SPECPATH) / "src" / "photo_organizer" / "__init__.py"))
app_version = release["__version__"]
version_tuple = tuple(map(int, app_version.split(".")))
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("FileDescription", "PhotoOrganizer"),
            StringStruct("FileVersion", app_version),
            StringStruct("ProductName", "PhotoOrganizer"),
            StringStruct("ProductVersion", app_version),
            StringStruct("Comments", f"수정날짜: {release['__release_date__']}"),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

hiddenimports = collect_submodules("PIL")
vendor_dir = Path(SPECPATH) / "tools" / "exiftool"
if not (vendor_dir / "exiftool.exe").is_file() or not (vendor_dir / "manifest.json").is_file():
    raise RuntimeError("Pinned ExifTool is missing. Run scripts/vendor_exiftool.py --install first.")
vendor_check = runpy.run_path(str(Path(SPECPATH) / "scripts" / "vendor_exiftool.py"))
vendor_check["verify"]()
vendor_datas = [(str(path), "tools/exiftool/" + path.relative_to(vendor_dir).parent.as_posix())
                for path in sorted(vendor_dir.rglob("*")) if path.is_file()]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[(str(Path(SPECPATH) / "src" / "photo_organizer" / "resources" / "phone_wpd.cs"), "photo_organizer/resources"), *vendor_datas],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PhotoOrganizer",
    version=version_info,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
