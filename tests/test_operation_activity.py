import sys
from pathlib import Path
from threading import Barrier, Event, RLock, Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from photo_organizer.operation_control import OperationControl
from photo_organizer.engine import OrganizerEngine
from photo_organizer.models import OrganizeRequest, PreviewBundle
from photo_organizer import resume_engine


class OperationActivityTests(unittest.TestCase):
    def test_snapshot_is_immutable_and_clears_after_exception(self):
        control = OperationControl()
        with self.assertRaisesRegex(RuntimeError, 'error'):
            with control.file_activity('one', Path('source/one.jpg'), 'copy'):
                snapshot = control.activity_snapshot()
                self.assertIsInstance(snapshot, tuple)
                self.assertEqual(snapshot[0].source_path, str(Path('source/one.jpg')))
                control.update_file_activity('one', 'output')
                self.assertEqual(control.activity_snapshot()[0].stage, 'output')
                self.assertEqual(snapshot[0].stage, 'copy')
                with self.assertRaises((AttributeError, TypeError)):
                    snapshot[0].stage = 'changed'
                raise RuntimeError('error')
        self.assertEqual(control.activity_snapshot(), ())

    def test_parallel_active_files_are_all_reported(self):
        control, barrier, release = OperationControl(), Barrier(5), Event()
        def work(index):
            with control.file_activity(str(index), f'{index}.jpg', 'output'):
                barrier.wait(timeout=3)
                release.wait(timeout=3)
        threads = [Thread(target=work, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        try:
            barrier.wait(timeout=3)
            self.assertEqual({activity.key for activity in control.activity_snapshot()}, {'0', '1', '2', '3'})
        finally:
            release.set()
            for thread in threads:
                thread.join(timeout=3)
        self.assertEqual(control.activity_snapshot(), ())

    def test_preview_extractor_observes_path_and_error_clears_activity(self):
        control = OperationControl()
        engine = OrganizerEngine.__new__(OrganizerEngine)
        path = Path('source/current.mp4')
        engine._scan_media_files = Mock(return_value=[path])
        def extract(current):
            self.assertEqual(control.activity_snapshot()[0].source_path, str(current))
            self.assertEqual(control.activity_snapshot()[0].stage, 'metadata')
            raise RuntimeError('metadata failed')
        engine.extractor = SimpleNamespace(extract=extract)
        with self.assertRaisesRegex(RuntimeError, 'metadata failed'):
            engine.preview(OrganizeRequest(Path('source'), Path('target')), control=control)
        self.assertEqual(control.activity_snapshot(), ())

    def test_resume_worker_stage_activity_and_queued_pause(self):
        control = OperationControl()
        item = SimpleNamespace(item_id='one', source_path='one.jpg')
        job = SimpleNamespace(ledger={'one': {stage: {'state': 'PENDING'} for stage in ('main', 'output', 'source_remove')}})
        journal = SimpleNamespace(lock=RLock(), failure=None)
        observed = []
        actions = [SimpleNamespace(item_id='one', stage=stage, allowed=True, action='RUN') for stage in ('main', 'output', 'source_remove')]
        def stage(*args):
            observed.append(control.activity_snapshot()[0].stage)
            return True
        with patch.object(resume_engine, 'build_resume_plan', return_value=actions), patch.object(resume_engine, '_run_stage', side_effect=stage) as run:
            self.assertEqual(resume_engine._run_item(None, journal, job, item, None, 'initial', control, Event()), (True, False))
            self.assertEqual(observed, ['copy', 'output', 'source_remove'])
            self.assertEqual(control.activity_snapshot(), ())
            control.request_pause()
            self.assertEqual(resume_engine._run_item(None, journal, job, item, None, 'initial', control, Event()), (False, False))
            self.assertEqual(run.call_count, 3)
            self.assertEqual(control.activity_snapshot(), ())

    def test_legacy_copy_failure_clears_current_file(self):
        control = OperationControl()
        engine = OrganizerEngine.__new__(OrganizerEngine)
        engine.logger = Mock()
        row = SimpleNamespace(item_id='one', source_path='one.jpg', target_directory='target',
                              target_path='target/one.jpg', included=True, filename_edited=False,
                              write_mode='NEW', mobile_output_enabled=False, mobile_output_path='', media_type='photo')
        bundle = PreviewBundle(preview_items=[row])
        request = OrganizeRequest(Path('source'), Path('target'), mobile_output_enabled=False)
        def copy(*args):
            self.assertEqual(control.activity_snapshot()[0].source_path, 'one.jpg')
            self.assertEqual(control.activity_snapshot()[0].stage, 'copy')
            raise OSError('copy failed')
        with patch('photo_organizer.engine.shutil.copy2', side_effect=copy), patch.object(Path, 'mkdir'):
            result = engine.execute(request, preview_bundle=bundle, control=control)
        self.assertEqual(result.execution_results[0].status, 'ERROR')
        event = control.drain_file_results()[0]
        self.assertEqual((event.key, event.status, event.message), ('one', 'ERROR', 'copy failed'))
        self.assertEqual(control.activity_snapshot(), ())


if __name__ == '__main__':
    unittest.main()
