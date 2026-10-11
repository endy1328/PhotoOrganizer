import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photo_organizer.video_output import create_mobile_video_output


class VideoOutputTests(unittest.TestCase):
    def _case_dir(self, name: str) -> Path:
        base = Path(__file__).resolve().parents[1] / ".tmp_test" / name
        if base.exists():
            shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True, exist_ok=True)
        return base

    def test_create_mobile_video_output_uses_ffmpeg_mp4_profile(self) -> None:
        base = self._case_dir("video_output_profile_case")
        source = base / "sample.mov"
        target = base / "output" / "sample.mp4"
        source.write_bytes(b"0" * 100)

        def fake_run(command, capture_output, check, **process_options):  # type: ignore[no-untyped-def]
            self.assertEqual(process_options['stdin'], subprocess.DEVNULL)
            self.assertEqual(command[0], "ffmpeg")
            self.assertIn("libx264", command)
            self.assertIn("aac", command)
            self.assertIn("scale='min(1920,iw)':-2", command)
            Path(command[-1]).write_bytes(b"1" * 40)
            return subprocess.CompletedProcess(args=command, returncode=0, stdout=b"", stderr=b"")

        with patch("photo_organizer.video_output.subprocess.run", side_effect=fake_run):
            status = create_mobile_video_output(
                source_path=source,
                target_path=target,
                max_width=1920,
                quality="high",
                only_if_smaller=False,
            )

        self.assertEqual(status, "SUCCESS")
        self.assertTrue(target.exists())
        self.assertEqual(target.read_bytes(), b"1" * 40)

    def test_create_mobile_video_output_skips_when_not_smaller(self) -> None:
        base = self._case_dir("video_output_skip_case")
        source = base / "sample.mp4"
        target = base / "output" / "sample.mp4"
        source.write_bytes(b"0" * 20)

        def fake_run(command, capture_output, check, **process_options):  # type: ignore[no-untyped-def]
            self.assertEqual(process_options['stdin'], subprocess.DEVNULL)
            Path(command[-1]).write_bytes(b"1" * 20)
            return subprocess.CompletedProcess(args=command, returncode=0, stdout=b"", stderr=b"")

        with patch("photo_organizer.video_output.subprocess.run", side_effect=fake_run):
            status = create_mobile_video_output(
                source_path=source,
                target_path=target,
                max_width=1280,
                quality="balanced",
                only_if_smaller=True,
            )

        self.assertEqual(status, "SKIPPED")
        self.assertFalse(target.exists())

    def test_create_mobile_video_output_raises_when_ffmpeg_missing(self) -> None:
        base = self._case_dir("video_output_missing_ffmpeg_case")
        source = base / "sample.mp4"
        target = base / "output" / "sample.mp4"
        source.write_bytes(b"0" * 20)

        with patch("photo_organizer.video_output.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "ffmpeg"):
                create_mobile_video_output(
                    source_path=source,
                    target_path=target,
                    max_width=1280,
                    quality="balanced",
                    only_if_smaller=True,
                )


if __name__ == "__main__":
    unittest.main()
