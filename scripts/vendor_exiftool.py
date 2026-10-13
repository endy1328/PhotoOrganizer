"""Install/verify the pinned official portable Windows ExifTool distribution.

Default is offline verification. --install downloads into a private temporary
directory, checks the published SHA256, and installs only into tools/exiftool.
No global installation, PATH changes, or user media changes are performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

VERSION = "13.59"
ARCHIVE = "exiftool-13.59_64.zip"
ARCHIVE_SHA256 = "44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec"
PROJECT = Path(__file__).resolve().parents[1]
DESTINATION = PROJECT / "tools" / "exiftool"
DOWNLOAD_URL = f"https://sourceforge.net/projects/exiftool/files/{ARCHIVE}/download"
MIRRORS = ("netix", "pilotfiber", "phoenixnap")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def install(archive: Path | None = None) -> None:
    if (DESTINATION / "manifest.json").exists():
        verify()
        return
    with tempfile.TemporaryDirectory(prefix="exiftool-vendor-", dir=PROJECT / ".tmp_test") as temporary:
        workspace = Path(temporary)
        downloaded = archive or workspace / ARCHIVE
        if archive is None:
            errors = []
            for mirror in MIRRORS:
                url = f"https://{mirror}.dl.sourceforge.net/project/exiftool/{ARCHIVE}"
                try:
                    request = urllib.request.Request(url, headers={"User-Agent": "PhotoOrganizer-vendor/1.0"})
                    with urllib.request.urlopen(request, timeout=30) as response, downloaded.open("wb") as stream:
                        total = 0
                        while chunk := response.read(1024 * 1024):
                            total += len(chunk)
                            if total > 20_000_000:
                                raise ValueError("ExifTool archive exceeds the download limit")
                            stream.write(chunk)
                    if digest(downloaded) != ARCHIVE_SHA256:
                        raise ValueError("Official archive SHA256 mismatch")
                    break
                except (OSError, ValueError) as exc:
                    errors.append(f"{mirror}: {exc}")
            else:
                raise ValueError("Official ExifTool download failed: " + "; ".join(errors))
        if digest(downloaded) != ARCHIVE_SHA256:
            raise ValueError("Official archive SHA256 mismatch")
        root = f"exiftool-{VERSION}_64"
        staging = workspace / "extracted"
        staging.mkdir()
        with zipfile.ZipFile(downloaded) as package:
            for entry in package.infolist():
                relative = PurePosixPath(entry.filename)
                if (relative.is_absolute() or ".." in relative.parts or "\\" in entry.filename
                        or not relative.parts or relative.parts[0] != root):
                    raise ValueError("Unexpected ExifTool archive path")
                destination = staging.joinpath(*relative.parts)
                if not destination.resolve().is_relative_to(staging.resolve()):
                    raise ValueError("ExifTool archive escapes its staging directory")
                if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("ExifTool archive contains a link")
                if entry.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(entry) as source, destination.open("xb") as target:
                        shutil.copyfileobj(source, target)
        distribution = staging / root
        (distribution / "exiftool(-k).exe").rename(distribution / "exiftool.exe")
        files = {path.relative_to(distribution).as_posix(): digest(path)
                 for path in sorted(distribution.rglob("*")) if path.is_file()}
        manifest = {"version": VERSION, "architecture": "windows-x86_64", "archive": ARCHIVE,
                    "archive_sha256": ARCHIVE_SHA256, "source": DOWNLOAD_URL,
                    "checksum_source": DOWNLOAD_URL, "files": files}
        (distribution / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        DESTINATION.mkdir(parents=True, exist_ok=True)
        # Refuse to overwrite any existing vendor files on a partial installation.
        for relative in [*files, "manifest.json"]:
            if (DESTINATION / relative).exists():
                raise ValueError(f"Existing vendor file requires manual review: {relative}")
        shutil.copytree(distribution, DESTINATION, dirs_exist_ok=True)
    verify()


def verify() -> None:
    manifest = json.loads((DESTINATION / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("version") != VERSION or manifest.get("archive_sha256") != ARCHIVE_SHA256
            or manifest.get("architecture") != "windows-x86_64"):
        raise ValueError("ExifTool pin mismatch")
    files = manifest.get("files")
    required = {"exiftool.exe", "exiftool_files/perl.exe", "exiftool_files/LICENSE",
                "exiftool_files/Licenses_Strawberry_Perl.zip", "exiftool_files/exiftool.pl"}
    if not isinstance(files, dict) or not required <= files.keys():
        raise ValueError("ExifTool runtime or license files are missing from the manifest")
    for relative, expected in files.items():
        path = DESTINATION / relative
        if not path.resolve().is_relative_to(DESTINATION.resolve()) or path.is_symlink():
            raise ValueError("ExifTool manifest path is outside the vendor directory")
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"ExifTool vendor checksum mismatch: {relative}")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}
    result = subprocess.run([str(DESTINATION / "exiftool.exe"), "-config", "", "-ver"],
                            capture_output=True, check=True, timeout=30, **options)
    if result.stdout.decode("ascii").strip() != VERSION:
        raise ValueError("ExifTool executable version mismatch")
    print(f"Verified ExifTool {VERSION} / {len(files)} vendor files / Windows x64")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--archive", type=Path, help="Use an already downloaded official ZIP (SHA256 checked)")
    arguments = parser.parse_args()
    if arguments.archive and not arguments.install:
        parser.error("--archive requires --install")
    if arguments.install:
        (PROJECT / ".tmp_test").mkdir(exist_ok=True)
        install(arguments.archive)
    else:
        verify()
