# Project-local ExifTool

Pinned version: **13.59**, official Windows x64 portable distribution.
Verified on 2026-10-12. It is an external command-line tool, not a globally
installed dependency. No system PATH changes are required or performed.

Official release information and packaging instructions:

- https://github.com/exiftool/exiftool/blob/master/html/index.html
- https://exiftool.org/install.html
- https://sourceforge.net/projects/exiftool/files/exiftool-13.59_64.zip/download

The official release page links to SourceForge and identifies the 13.59 release
as May 27, 2026. The SourceForge download page publishes this ZIP's SHA256:

`44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec`

The netix, pilotfiber and phoenixnap HTTPS SourceForge mirrors returned the
same 11,183,675-byte archive and matched that published digest. The archive is
not trusted solely because a download succeeds: the installer rejects HTML and
any other response whose SHA256 differs.

Only the launcher was renamed from `exiftool(-k).exe` to `exiftool.exe`, as
the official instructions specify. All 510 supplied files are preserved with
SHA256 entries in `manifest.json`. The launcher SHA256 is:

`68c079c32fdae0d6c7130e9a5fb73f8ac9dabdf9ab8da312da4f6c549d6d3385`

## Installation and validation

From the project root:

```powershell
.venv/Scripts/python.exe scripts/vendor_exiftool.py --install
.venv/Scripts/python.exe scripts/vendor_exiftool.py
```

An already downloaded official ZIP can be supplied with
`--install --archive path/to/exiftool-13.59_64.zip`; the same pinned SHA256 is
mandatory. Installation refuses to overwrite existing vendor files. Verification
is offline, checks every supplied file, and runs the executable with `-ver`
using a hidden subprocess. The executable and `exiftool_files` must stay together.

`PhotoOrganizer.spec` includes the complete `tools/exiftool` tree, including
the manifest, notices and license files, at `tools/exiftool` inside the one-file
application. The application locates it beneath `sys._MEIPASS` when packaged.
The release script checks the vendor installation before tests and packaging.

## Copyright and licenses

- ExifTool: copyright 2003-2026 Phil Harvey, distributed under the same terms
  as Perl: either the Perl Artistic License or GPL. The actual Perl sources
  are included under `exiftool_files/lib/Image` and `exiftool_files/exiftool.pl`.
  Upstream notice: https://github.com/exiftool/exiftool/blob/master/README
- The supplied GPL version 3 text is preserved verbatim in
  `exiftool_files/LICENSE`.
- Strawberry Perl and bundled libraries: original license collection preserved
  in `exiftool_files/Licenses_Strawberry_Perl.zip`.
- Oliver Betz's tiny Windows launcher is CC0; its original notice and links
  are preserved in `exiftool_files/readme_windows.txt`.
  Launcher source: https://oliverbetz.de/pages/Artikel/ExifTool-for-Windows
  CC0 text: https://creativecommons.org/publicdomain/zero/1.0/legalcode

No upstream runtime files or license text were edited. Project-specific files
are `manifest.json` and this `VENDOR.md`. Validation uses synthetic copies only;
it never writes model tags to user media.
