from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from photo_organizer import video_output


class VideoQualityProfilesTests(unittest.TestCase):
    profiles = (
        ("very_high", "18", "192k", "매우 높음"),
        ("high_plus", "20", "192k", "높음+"),
        ("high", "22", "160k", "높음"),
        ("balanced", "24", "128k", "균형 (기본)"),
        ("compact", "26", "128k", "용량 절약"),
        ("small", "28", "96k", "최대 용량 절약"),
    )

    def test_profiles_are_ordered_from_quality_to_space_saving(self):
        self.assertEqual(list(video_output.VIDEO_QUALITY_PRESETS), [p[0] for p in self.profiles])

    def test_display_labels_explain_actual_encoding_values(self):
        for key, crf, bitrate, label in self.profiles:
            with self.subTest(profile=key):
                self.assertEqual(
                    video_output.video_quality_display_label(key),
                    f"{label} — CRF {crf} / 오디오 {bitrate[:-1]} kbps",
                )
                self.assertTrue(video_output.VIDEO_QUALITY_PRESETS[key]["description"])

    def test_normalization_retains_saved_keys_and_defaults_unknown_values(self):
        for key, *_ in self.profiles:
            self.assertEqual(video_output.normalize_video_quality(key), key)
        for value in ("unknown", "", None, 24):
            with self.subTest(value=value):
                self.assertEqual(video_output.normalize_video_quality(value), "balanced")
                self.assertEqual(video_output.video_quality_display_label(value),
                                 "균형 (기본) — CRF 24 / 오디오 128 kbps")

    def test_all_profiles_use_approved_encoding_values_with_medium_preset(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"original")
            for key, crf, bitrate, _ in (*self.profiles, ("invalid", "24", "128k", "")):
                with self.subTest(profile=key):
                    target = Path(directory) / f"{key}.mp4"
                    def fake_ffmpeg(command, **kwargs):
                        self.assertEqual(command[command.index("-crf") + 1], crf)
                        self.assertEqual(command[command.index("-b:a") + 1], bitrate)
                        self.assertEqual(command[command.index("-preset") + 1], "medium")
                        self.assertEqual(command[command.index("-vf") + 1], "scale='min(1280,iw)':-2")
                        Path(command[-1]).write_bytes(b"converted")
                    with patch("photo_organizer.video_output.subprocess.run", side_effect=fake_ffmpeg):
                        self.assertEqual(video_output.create_mobile_video_output(source, target, 1280, key, False), "SUCCESS")
                    self.assertEqual(target.read_bytes(), b"converted")


if __name__ == "__main__":
    unittest.main()
