import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.job_store import JobState, load_job, save_job
from photo_organizer.models import AppSettings, PreviewBundle, PreviewItem, ExecutionBundle, ExecutionResult
from photo_organizer.resume_models import ensure_plan, initial_ledger
from photo_organizer.execution_journal import ExecutionJournal


class JobSchema2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'job.pojob.json'

    def job(self):
        base = self.path.parent
        source = base / 'source' / '20240101_120000_X.jpg'
        directory = base / 'target' / '2024년' / '2024년 01월' / '20240101' / '20240101_X'
        name = '20240101_120000_X_0001.jpg'
        row = PreviewItem('one', 'photo', str(source), str(directory), str(directory / name), name, 'NEW', '2024-01-01T12:00:00', 'filename', 'X', 'filename', [])
        return JobState(phase='PREVIEW_READY', settings=AppSettings(source_path=str(source.parent), target_path=str(base / 'target')), preview_bundle=PreviewBundle(preview_items=[row]))

    def schema1(self, data):
        data['schema_version'] = 1
        for key in ('plan_id', 'plan_signature', 'execution_id', 'checkpoint', 'ledger', 'legacy_unverified'):
            data.pop(key, None)
        return data

    def test_new_saves_schema2_and_rejects_future(self):
        job = JobState()
        save_job(job, self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(data['schema_version'], 2)
        data['schema_version'] = 3
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_job(self.path)

    def test_schema1_draft_migrates_but_strict_stage_still_validated(self):
        save_job(JobState(), self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        for key in ('plan_id', 'plan_signature', 'execution_id', 'checkpoint', 'ledger', 'legacy_unverified'):
            data.pop(key, None)
        data['schema_version'] = 1
        self.path.write_text(json.dumps(data), encoding='utf-8')
        loaded = load_job(self.path)
        self.assertEqual(loaded.schema_version, 2)
        self.assertFalse(loaded.legacy_unverified)
        data['execution_started'] = True
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_job(self.path)

    def test_schema1_preview_gets_stable_legacy_plan_identity(self):
        save_job(self.job(), self.path)
        data = self.schema1(json.loads(self.path.read_text(encoding='utf-8')))
        self.path.write_text(json.dumps(data), encoding='utf-8')
        first = load_job(self.path)
        data['revision'] = 100
        data['job_id'] = '1196ee27-e55b-43d1-87d8-4e01f1f75043'
        self.path.write_text(json.dumps(data), encoding='utf-8')
        second = load_job(self.path)
        self.assertEqual(first.plan_id, second.plan_id)
        self.assertTrue(first.plan_id)
        self.assertFalse(first.legacy_unverified)

    def test_schema1_started_remains_unverified_even_when_resaved(self):
        job = self.job()
        row = job.preview_bundle.preview_items[0]
        job.execution_started = True
        job.phase = 'EXECUTION_FINISHED'
        job.execution_bundle = ExecutionBundle(preview_items=job.preview_bundle.preview_items, execution_results=[ExecutionResult(row.source_path, row.target_path, 'ERROR', 'copy')])
        save_job(job, self.path)
        data = self.schema1(json.loads(self.path.read_text(encoding='utf-8')))
        self.path.write_text(json.dumps(data), encoding='utf-8')
        loaded = load_job(self.path)
        self.assertTrue(loaded.legacy_unverified)
        self.assertEqual(loaded.ledger, {})
        save_job(loaded, self.path)
        self.assertTrue(load_job(self.path).legacy_unverified)

    def test_schema2_executing_partial_bundle_and_ledger_roundtrip(self):
        job = self.job()
        journal = ExecutionJournal(self.path.parent)
        journal.register(job)
        job.execution_bundle = ExecutionBundle(preview_items=job.preview_bundle.preview_items)
        save_job(job, self.path)
        loaded = load_job(self.path)
        self.assertEqual(loaded.phase, 'EXECUTING')
        self.assertEqual(loaded.execution_id, job.execution_id)
        self.assertEqual(loaded.ledger, job.ledger)
        self.assertIsNotNone(loaded.execution_bundle)

    def test_invalid_ledger_fields_and_checkpoint_types_rejected(self):
        job = self.job()
        ensure_plan(job)
        save_job(job, self.path)
        base = json.loads(self.path.read_text(encoding='utf-8'))
        for name, value in [('checkpoint', True), ('checkpoint', -1), ('execution_id', 'unsafe'), ('legacy_unverified', 1), ('ledger', {'one': {'main': {'state': 'INVALID'}}})]:
            data = dict(base, **{name: value})
            self.path.write_text(json.dumps(data), encoding='utf-8')
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_job(self.path)

    def test_schema1_cannot_carry_schema2_stage_records(self):
        save_job(JobState(), self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['schema_version'] = 1
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_job(self.path)

    def test_draft_nonempty_ledger_is_value_error(self):
        save_job(JobState(), self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['ledger'] = {'invalid': {'main': {'state': 'PENDING'}}}
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_job(self.path)

    def test_canonical_plan_signature_tamper_rejected_on_load(self):
        save_job(self.job(), self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['plan_signature'] = '0' * 64
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_job(self.path)

    def test_completed_snapshot_results_must_match_ledger(self):
        from photo_organizer.resume_models import stage_record, bundle_from_ledger
        job = self.job()
        journal = ExecutionJournal(self.path.parent)
        journal.register(job)
        attempt = stage_record('IN_PROGRESS')
        journal.update(job, 'one', 'main', attempt)
        journal.update(job, 'one', 'main', stage_record('DONE', attempt_id=attempt['attempt_id'], fingerprint={'exists': True, 'is_file': True, 'size': 3, 'mtime_ns': 4}))
        bundle_from_ledger(job)
        save_job(job, self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['execution_bundle']['execution_results'][0]['status'] = 'ERROR'
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_job(self.path)

    def test_completed_snapshot_fingerprints_must_match_ledger(self):
        from photo_organizer.resume_models import stage_record, bundle_from_ledger
        job = self.job()
        journal = ExecutionJournal(self.path.parent)
        journal.register(job)
        journal.update(job, 'one', 'main', stage_record('IN_PROGRESS'))
        journal.update(job, 'one', 'main', stage_record('DONE', attempt_id=job.ledger['one']['main']['attempt_id'], fingerprint={'exists': True, 'is_file': True, 'size': 3, 'mtime_ns': 4}))
        bundle_from_ledger(job)
        save_job(job, self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['result_fingerprints'] = {}
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_job(self.path)

    def test_forged_schema2_started_no_execution_evidence_rejected(self):
        job = self.job()
        row = job.preview_bundle.preview_items[0]
        job.execution_started = True
        job.phase = 'EXECUTION_FINISHED'
        job.execution_bundle = ExecutionBundle(preview_items=job.preview_bundle.preview_items, execution_results=[ExecutionResult(row.source_path, row.target_path, 'ERROR', 'copy')])
        save_job(job, self.path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['legacy_unverified'] = False
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_job(self.path)

    def test_saving_old_nonjournal_fixture_explicitly_marks_view_only(self):
        job = self.job()
        row = job.preview_bundle.preview_items[0]
        job.execution_started = True
        job.phase = 'EXECUTION_FINISHED'
        job.execution_bundle = ExecutionBundle(preview_items=job.preview_bundle.preview_items, execution_results=[ExecutionResult(row.source_path, row.target_path, 'ERROR', 'copy')])
        save_job(job, self.path)
        loaded = load_job(self.path)
        self.assertTrue(loaded.legacy_unverified)
        self.assertTrue(job.legacy_unverified)
        self.assertEqual(loaded.execution_id, '')
        self.assertEqual(loaded.ledger, {})
