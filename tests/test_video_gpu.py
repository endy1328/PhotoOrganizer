import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from photo_organizer import video_output


class VideoGpuTests(unittest.TestCase):
    def convert(self, encoder, speed="balanced", fail_gpu=False, fail_cpu=False, quality="balanced"):
        calls = []
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            target = Path(directory) / "target.mp4"
            source.write_bytes(b"original video")
            def run(command, **kwargs):
                calls.append(command)
                self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
                codec = command[command.index("-c:v") + 1]
                if (codec == "h264_nvenc" and fail_gpu) or (codec == "libx264" and fail_cpu):
                    Path(command[-1]).write_bytes(b"partial")
                    raise subprocess.CalledProcessError(1, command, stderr=f"{codec} original failure".encode())
                Path(command[-1]).write_bytes(b"done")
            with patch.object(video_output, "get_gpu_encoder_capability", return_value=(True, "usable")), patch.object(video_output.subprocess, "run", side_effect=run):
                result = video_output.create_mobile_video_output(source, target, 1280, quality, False, encoder=encoder, speed=speed)
            self.assertEqual(result, "SUCCESS")
            self.assertEqual(target.read_bytes(), b"done")
        return calls

    def test_cpu_speed_presets(self):
        for speed, preset in (("quality", "slow"), ("balanced", "medium"), ("fast", "fast")):
            calls = self.convert("cpu", speed)
            self.assertEqual(calls[0][calls[0].index("-preset") + 1], preset)

    def test_gpu_speed_and_quality_options_preserve_common_options(self):
        for speed, preset in (("quality", "p7"), ("balanced", "p5"), ("fast", "p3")):
            command = self.convert("gpu", speed)[0]
            for key, value in (("-c:v", "h264_nvenc"), ("-preset", preset), ("-cq", "24"), ("-rc", "vbr"), ("-b:v", "0"), ("-map_metadata", "0"), ("-pix_fmt", "yuv420p"), ("-c:a", "aac")):
                self.assertEqual(command[command.index(key) + 1], value)
            self.assertNotIn("-crf", command)

    def test_auto_gpu_failure_retries_cpu_once(self):
        calls = self.convert("auto", fail_gpu=True)
        self.assertEqual([c[c.index("-c:v") + 1] for c in calls], ["h264_nvenc", "libx264"])
        self.assertIn("CPU libx264", video_output.get_last_video_encoder_report())
        self.assertIn("h264_nvenc original failure", video_output.get_last_video_encoder_report())

    def test_actual_backend_report_resets_for_each_conversion(self):
        self.convert("gpu", "fast")
        self.assertIn("NVIDIA NVENC", video_output.get_last_video_encoder_report())
        self.assertIn("fast", video_output.get_last_video_encoder_report())
        self.convert("cpu")
        self.assertIn("CPU libx264", video_output.get_last_video_encoder_report())
        self.assertNotIn("NVIDIA NVENC", video_output.get_last_video_encoder_report())

    def test_clear_report_removes_previous_conversion_evidence(self):
        self.convert("gpu")
        self.assertTrue(video_output.get_last_video_encoder_report())
        video_output.clear_video_encoder_report()
        self.assertEqual(video_output.get_last_video_encoder_report(), "")

    def test_all_six_gpu_profiles_use_approved_cq_and_audio_values(self):
        for quality, cq, audio in (("very_high", "18", "192k"), ("high_plus", "20", "192k"),
                                   ("high", "22", "160k"), ("balanced", "24", "128k"),
                                   ("compact", "26", "128k"), ("small", "28", "96k")):
            command = self.convert("gpu", quality=quality)[0]
            self.assertEqual(command[command.index("-cq") + 1], cq)
            self.assertEqual(command[command.index("-b:a") + 1], audio)

    def test_forced_gpu_encode_failure_does_not_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "h264_nvenc original failure"):
            self.convert("gpu", fail_gpu=True)

    def test_gpu_only_smaller_preserves_existing_target(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            target = Path(directory) / "target.mp4"
            source.write_bytes(b"tiny")
            target.write_bytes(b"existing")
            def run(command, **kwargs):
                Path(command[-1]).write_bytes(b"larger than original")
            with patch.object(video_output, "get_gpu_encoder_capability", return_value=(True, "usable")), patch.object(video_output.subprocess, "run", side_effect=run):
                self.assertEqual(video_output.create_mobile_video_output(source, target, 0, "balanced", True, encoder="gpu"), "SKIPPED")
            self.assertEqual(target.read_bytes(), b"existing")
            self.assertFalse(target.with_name("target.tmp.mp4").exists())

    def test_both_failures_preserve_evidence(self):
        with self.assertRaisesRegex(RuntimeError, "h264_nvenc original failure.*libx264 original failure"):
            self.convert("auto", fail_gpu=True, fail_cpu=True)

    def test_forced_gpu_unavailable_has_clear_error(self):
        with patch.object(video_output, "get_gpu_encoder_capability", return_value=(False, "driver unavailable")), patch.object(video_output.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "NVENC.*driver unavailable"):
                video_output.create_mobile_video_output(Path("source"), Path("target"), 0, "balanced", False, encoder="gpu")
            run.assert_not_called()

    def test_auto_unavailable_uses_cpu(self):
        with patch.object(video_output, "get_gpu_encoder_capability", return_value=(False, "unavailable")):
            # convert supplies its own capability patch; exercise selection separately.
            self.assertEqual(video_output.resolve_video_encoder("auto"), "cpu")

    def test_probe_runs_actual_encode_once_hidden_with_timeout(self):
        video_output.get_gpu_encoder_capability.cache_clear()
        try:
            with patch.object(video_output.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                self.assertTrue(video_output.get_gpu_encoder_capability()[0])
                self.assertTrue(video_output.get_gpu_encoder_capability()[0])
                self.assertEqual(run.call_count, 1)
                command = run.call_args.args[0]
                self.assertIn("lavfi", command)
                self.assertIn("h264_nvenc", command)
                self.assertIn("color=c=black:s=320x240:r=30", command)
                self.assertEqual(command[-2:], ["null", "-"])
                self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
                self.assertLessEqual(run.call_args.kwargs["timeout"], 15)
        finally:
            video_output.get_gpu_encoder_capability.cache_clear()

    def test_probe_timeout_is_unavailable(self):
        video_output.get_gpu_encoder_capability.cache_clear()
        try:
            with patch.object(video_output.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffmpeg", 10)):
                usable, detail = video_output.get_gpu_encoder_capability()
                self.assertFalse(usable)
                self.assertTrue(detail)
        finally:
            video_output.get_gpu_encoder_capability.cache_clear()


if __name__ == "__main__":
    unittest.main()
