import shutil
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photo_organizer.config import ConfigManager
from photo_organizer.models import AppSettings


class ConfigTests(unittest.TestCase):
    def test_atomic_save_write_failure_keeps_existing_file_and_cleans_temp(self) -> None:
        from unittest.mock import patch
        import tempfile

        manager = ConfigManager(self.base)
        manager.save(AppSettings(source_path="keep"))
        original = manager.config_path.read_bytes()
        real_tempfile = tempfile.NamedTemporaryFile

        class FailingWriter:
            def __init__(self, *args, **kwargs):
                self.file = real_tempfile(*args, **kwargs)
                self.name = self.file.name

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.file.close()

            def write(self, text):
                self.file.write(text[:10])
                self.file.flush()
                raise OSError("write failed")

        with patch("photo_organizer.config.tempfile.NamedTemporaryFile", FailingWriter), self.assertRaises(OSError):
            manager.save(AppSettings(source_path="changed"))
        self.assertEqual(manager.config_path.read_bytes(), original)
        self.assertEqual(list(self.base.iterdir()), [manager.config_path])

    def test_atomic_save_replace_failure_keeps_existing_file_and_cleans_temp(self) -> None:
        from unittest.mock import patch

        manager = ConfigManager(self.base)
        manager.save(AppSettings(source_path="keep"))
        original = manager.config_path.read_bytes()
        with patch("photo_organizer.config.os.replace", side_effect=OSError("replace failed")), self.assertRaises(OSError):
            manager.save(AppSettings(source_path="changed"))
        self.assertEqual(manager.config_path.read_bytes(), original)
        self.assertEqual(list(self.base.iterdir()), [manager.config_path])

    def test_model_mapping_missing_keys_default(self) -> None:
        manager = ConfigManager(self.base)
        settings = manager.load()
        self.assertEqual(settings.model_name_mappings, {})
        self.assertEqual(settings.model_mapping_scope, "filename_and_folders")
        manager.config_path.write_text('[app]\nsource_path="keep"', encoding="utf-8")
        self.assertEqual(manager.load().model_name_mappings, {})
        self.assertEqual(manager.load().model_mapping_scope, "filename_and_folders")

    def test_model_mapping_unicode_round_trip_and_scope(self) -> None:
        manager = ConfigManager(self.base)
        for scope in ("filename_and_folders", "filename_only"):
            settings = AppSettings(model_name_mappings={"SM-F926N": "갤럭시 폴드6", "DJI OsmoAction4": "액션4"}, model_mapping_scope=scope)
            manager.save(settings)
            self.assertEqual(manager.load().model_name_mappings, {"SM-F926N": "갤럭시_폴드6", "DJI OsmoAction4": "액션4"})
            self.assertEqual(settings.model_name_mappings["SM-F926N"], "갤럭시 폴드6")
            self.assertEqual(manager.load().model_mapping_scope, scope)
            self.assertIn('[model_name_mappings]', manager.config_path.read_text(encoding="utf-8"))

    def test_invalid_mapping_rows_and_scope_preserve_other_settings(self) -> None:
        manager = ConfigManager(self.base)
        manager.config_path.write_text('[app]\nsource_path="keep"\nmodel_mapping_scope="bad"\n[model_name_mappings]\n"SM-F926N"="폴드6"\n"SM_F926N"="duplicate"\n"BAD"="a/b"\n"NUMERIC"=7\n"EMPTY"=""', encoding="utf-8")
        settings = manager.load()
        self.assertEqual(settings.source_path, "keep")
        self.assertEqual(settings.model_mapping_scope, "filename_and_folders")
        self.assertEqual(settings.model_name_mappings, {"SM-F926N": "폴드6"})
        manager.config_path.write_text('model_name_mappings=7\n[app]\nsource_path="keep"', encoding="utf-8")
        self.assertEqual(manager.load().source_path, "keep")
        self.assertEqual(manager.load().model_name_mappings, {})
        for value in ('7', 'true', '"bad"'):
            manager.config_path.write_text('[app]\nsource_path="keep"\n[model_name_mappings]\n"CAM"=' + value, encoding="utf-8")
            self.assertEqual(manager.load().source_path, "keep")
        manager.save(AppSettings(model_mapping_scope="bad"))
        self.assertEqual(manager.load().model_mapping_scope, "filename_and_folders")

    def test_mapping_save_validation_preserves_existing_config(self) -> None:
        manager = ConfigManager(self.base)
        manager.save(AppSettings(source_path="keep"))
        original = manager.config_path.read_bytes()
        for mapping in ({"CAM": "a/b"}, {"CAM": "line\nbreak"}, {"CAM": 'a"b'}, {"BAD\tCAM": "alias"}, {"SM-F926N": "first", "SM_F926N": "second"}, {"": "empty"}, {"": ""}, {"CAM": 7}, {"CAM": ""}, 7):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                manager.save(AppSettings(model_name_mappings=mapping))
            self.assertEqual(manager.config_path.read_bytes(), original)

    def test_model_mapping_legacy_migration_normalizes_invalid_rows(self) -> None:
        import json
        manager = ConfigManager(self.base)
        manager.legacy_config_path.write_text(json.dumps({"source_path": "legacy", "model_mapping_scope": "filename_only", "model_name_mappings": {"SM-F926N": "폴드6", "BAD": "a/b"}}), encoding="utf-8")
        settings = manager.load()
        self.assertEqual(settings.source_path, "legacy")
        self.assertEqual(settings.model_mapping_scope, "filename_only")
        self.assertEqual(settings.model_name_mappings, {"SM-F926N": "폴드6"})
        self.assertEqual(manager.load().model_name_mappings, settings.model_name_mappings)
        manager.config_path.unlink()
        manager.legacy_config_path.write_text(json.dumps({"source_path": "legacy", "model_mapping_scope": "bad", "model_name_mappings": 7}), encoding="utf-8")
        settings = manager.load()
        self.assertEqual(settings.source_path, "legacy")
        self.assertEqual(settings.model_mapping_scope, "filename_and_folders")
        self.assertEqual(settings.model_name_mappings, {})

    def test_phone_conflict_policy_default_round_trip_and_validation(self) -> None:
        manager = ConfigManager(self.base)
        self.assertTrue(hasattr(manager.load(), "phone_conflict_policy"))
        self.assertEqual(manager.load().phone_conflict_policy, "overwrite")
        for policy in ("overwrite", "skip", "rename"):
            manager.save(AppSettings(phone_conflict_policy=policy))
            self.assertEqual(manager.load().phone_conflict_policy, policy)
        for literal in ('"invalid"', 'true', '7'):
            manager.config_path.write_text('[app]\nsource_path="keep"\nphone_conflict_policy=' + literal, encoding="utf-8")
            settings = manager.load()
            self.assertEqual(settings.phone_conflict_policy, "overwrite")
            self.assertEqual(settings.source_path, "keep")

    def test_phone_conflict_policy_legacy_migration(self) -> None:
        import json
        manager = ConfigManager(self.base)
        for policy in ("skip", "invalid"):
            if manager.config_path.exists():
                manager.config_path.unlink()
            manager.legacy_config_path.write_text(json.dumps({"source_path": "legacy", "phone_conflict_policy": policy}), encoding="utf-8")
            settings = manager.load()
            self.assertTrue(hasattr(settings, "phone_conflict_policy"))
            self.assertEqual(settings.phone_conflict_policy, "skip" if policy == "skip" else "overwrite")
            self.assertEqual(manager.load().phone_conflict_policy, settings.phone_conflict_policy)

    def test_video_model_window_round_trip_and_default(self) -> None:
        manager = ConfigManager(self.base)
        self.assertEqual(manager.load().video_model_window_minutes, 5)
        manager.save(AppSettings(video_model_window_minutes=12))
        self.assertEqual(manager.load().video_model_window_minutes, 12)

    def test_invalid_video_model_window_preserves_other_settings(self) -> None:
        manager = ConfigManager(self.base)
        for value in ('-1', '1441', '1.5', 'true', '"10"'):
            with self.subTest(value=value):
                manager.config_path.write_text('[app]\nsource_path="keep"\nvideo_model_window_minutes=' + value, encoding="utf-8")
                loaded = manager.load()
                self.assertEqual(loaded.source_path, "keep")
                self.assertEqual(loaded.video_model_window_minutes, 5)
        for value in (0, 1440):
            manager.save(AppSettings(video_model_window_minutes=value))
            self.assertEqual(manager.load().video_model_window_minutes, value)

    def setUp(self) -> None:
        self.base = Path(__file__).resolve().parents[1] / ".tmp_test" / "config_case"
        if self.base.exists():
            shutil.rmtree(self.base, ignore_errors=True)
        self.base.mkdir(parents=True, exist_ok=True)

    def test_save_and_load_toml(self) -> None:
        manager = ConfigManager(self.base)
        settings = AppSettings(
            source_path="E:\\photos\\source",
            target_path="E:\\photos\\target",
            device_name_override="kidsnote",
            operation_mode="move",
        )
        manager.save(settings)
        loaded = manager.load()
        self.assertEqual(loaded.source_path, settings.source_path)
        self.assertEqual(loaded.target_path, settings.target_path)
        self.assertEqual(loaded.device_name_override, settings.device_name_override)
        self.assertEqual(loaded.operation_mode, settings.operation_mode)
        self.assertEqual(loaded.mobile_output_enabled, settings.mobile_output_enabled)
        self.assertEqual(loaded.mobile_output_max_width, settings.mobile_output_max_width)
        self.assertEqual(loaded.mobile_output_jpeg_quality, settings.mobile_output_jpeg_quality)
        self.assertEqual(loaded.mobile_output_keep_smaller_original, settings.mobile_output_keep_smaller_original)
        self.assertEqual(loaded.mobile_output_video_max_width, settings.mobile_output_video_max_width)
        self.assertEqual(loaded.mobile_output_video_quality, settings.mobile_output_video_quality)
        self.assertEqual(loaded.mobile_output_video_only_if_smaller, settings.mobile_output_video_only_if_smaller)
        self.assertTrue((self.base / "config.toml").exists())

    def test_default_mobile_output_settings(self) -> None:
        manager = ConfigManager(self.base)
        loaded = manager.load()
        self.assertTrue(loaded.mobile_output_enabled)
        self.assertEqual(loaded.mobile_output_max_width, 3000)
        self.assertEqual(loaded.mobile_output_jpeg_quality, 75)
        self.assertTrue(loaded.mobile_output_keep_smaller_original)
        self.assertEqual(loaded.mobile_output_video_max_width, 1280)
        self.assertEqual(loaded.mobile_output_video_quality, "balanced")
        self.assertTrue(loaded.mobile_output_video_only_if_smaller)


if __name__ == "__main__":
    unittest.main()
