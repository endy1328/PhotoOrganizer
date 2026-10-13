import json
import tempfile
import unittest
from pathlib import Path

from test_resume_validation import make_job
from photo_organizer.job_store import _decode, _encode, load_job, save_job
from photo_organizer.resume_models import canonical_plan, ensure_plan
from photo_organizer.resume_validation import build_resume_plan


class MetadataRefreshStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job, self.engine, self.item = make_job(self.root, mobile=False)
        self.path = self.root / 'blocked-job.json'

    def test_blocked_plan_roundtrip_retains_preview_and_cannot_register_or_preflight(self):
        original = canonical_plan(self.job)
        self.job.metadata_refresh_required = True
        save_job(self.job, self.path)
        loaded = load_job(self.path)
        self.assertTrue(loaded.metadata_refresh_required)
        self.assertEqual(loaded.preview_bundle, self.job.preview_bundle)
        self.assertEqual(canonical_plan(loaded), original)
        with self.assertRaisesRegex(ValueError, '미리보기'):
            ensure_plan(loaded)
        for mode in ('initial', 'continue', 'retry'):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, '미리보기'):
                build_resume_plan(loaded, mode)

    def test_old_job_without_flag_defaults_false(self):
        save_job(self.job, self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data.pop('metadata_refresh_required')
        self.path.write_text(json.dumps(data), encoding='utf-8')
        loaded = load_job(self.path)
        self.assertFalse(loaded.metadata_refresh_required)
        ensure_plan(loaded)

    def test_flag_requires_actual_bool(self):
        save_job(self.job, self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        for bad in (None, 0, 1, 'false', []):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                _decode(dict(data, metadata_refresh_required=bad))

    def test_refresh_required_cannot_coexist_with_execution_started(self):
        self.job.metadata_refresh_required = True
        self.job.execution_started = True
        self.job.phase = 'EXECUTING'
        self.job.legacy_unverified = True
        with self.assertRaisesRegex(ValueError, '메타'):
            _decode(_encode(self.job))

    def test_blocked_preview_without_previous_save_can_be_saved(self):
        self.job.plan_id = self.job.plan_signature = ''
        self.job.ledger = {}
        self.job.metadata_refresh_required = True
        save_job(self.job, self.path)
        loaded = load_job(self.path)
        self.assertTrue(loaded.metadata_refresh_required)
        self.assertTrue(loaded.plan_id)
        with self.assertRaises(ValueError):
            ensure_plan(loaded)


if __name__ == '__main__':
    unittest.main()
