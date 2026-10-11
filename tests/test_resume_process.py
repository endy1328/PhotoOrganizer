"""Real process death between files preserves completed evidence."""
import subprocess
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.job_store import load_job, save_job
from photo_organizer.execution_journal import ExecutionJournal
from photo_organizer.job_validation import capture_file_states
from photo_organizer.models import MediaItem, OrganizeRequest
from test_resume_validation import make_job


class ProcessResumeTests(unittest.TestCase):
    def test_killed_process_recovers_database_ahead_of_json_and_only_copies_tail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job, engine, _ = make_job(root, mobile=False)
            # This regression intentionally dies at a sequential file boundary.
            job.settings.photo_workers = 1
            extra = Path(job.settings.source_path) / '20240101_120100_CAM.jpg'
            extra.write_bytes(b'second original')
            def metadata(path):
                return MediaItem(path, 'photo', '.jpg', datetime.strptime(path.stem[:15], '%Y%m%d_%H%M%S'),
                                 '사진 메타', 'CAM', '사진 메타')
            with patch.object(engine.extractor, 'extract', side_effect=metadata):
                job.preview_bundle = engine.preview(OrganizeRequest(Path(job.settings.source_path),
                                                    Path(job.settings.target_path), mobile_output_enabled=False, photo_workers=1))
            job.source_fingerprints = capture_file_states([p.source_path for p in job.preview_bundle.preview_items])
            job.ledger = {}
            ready_path = root / 'ready.pojob.json'
            save_job(job, ready_path)
            script = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from photo_organizer.job_store import load_job
from photo_organizer.engine import OrganizerEngine
from photo_organizer.resume_engine import execute_job
def progress(*args):
    print('first file done', flush=True)
    sys.stdin.read()
execute_job(OrganizerEngine(Path(sys.argv[2])), load_job(Path(sys.argv[3])), progress_callback=progress)
'''
            process = subprocess.Popen([sys.executable, '-c', script,
                                        str(Path(__file__).resolve().parents[1] / 'src'), str(root), str(ready_path)],
                                       cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'first file done')
                first, second = job.preview_bundle.preview_items
                first_baseline = capture_file_states([first.target_path])
                self.assertTrue(Path(first.target_path).is_file())
                self.assertFalse(Path(second.target_path).exists())
            finally:
                process.kill()
                process.communicate(timeout=10)
            interrupted = load_job(root / 'sessions' / 'last_session.pojob.json')
            self.assertEqual(interrupted.checkpoint, 0)
            self.assertTrue(ExecutionJournal(root).restore(interrupted))
            self.assertEqual(interrupted.ledger[first.item_id]['main']['state'], 'DONE')
            self.assertEqual(interrupted.ledger[second.item_id]['main']['state'], 'PENDING')
            with patch('photo_organizer.resume_engine.shutil.copyfileobj', wraps=shutil.copyfileobj) as copy_media:
                results = engine.resume(interrupted)
            self.assertEqual(copy_media.call_count, 1)
            self.assertEqual(Path(copy_media.call_args.args[0].name), extra)
            self.assertEqual([r.status for r in results.execution_results], ['SUCCESS', 'SUCCESS'])
            self.assertEqual(capture_file_states([first.target_path]), first_baseline)
            self.assertEqual(Path(second.target_path).read_bytes(), extra.read_bytes())


if __name__ == '__main__':
    unittest.main()
