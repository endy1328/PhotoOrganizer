import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from test_resume_validation import make_job, finish_main
from photo_organizer.resume_models import bundle_from_ledger, stage_record


class PerformanceReportingTests(unittest.TestCase):
    def test_backend_and_fallback_reason_are_kept_in_session_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            job, _, item = make_job(directory)
            finish_main(job, item)
            report = 'CPU encoder; GPU unavailable: unsupported driver'
            job.ledger[item.item_id]['output'] = stage_record('SKIPPED', message=report)
            result = bundle_from_ledger(job)
            self.assertEqual(result.execution_results[0].mobile_output_message, report)
            self.assertIn(report, result.log_events[0].message)
