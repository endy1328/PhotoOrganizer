import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QDockWidget, QAbstractItemView


class ExecutionProgressPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from photo_organizer.ui.execution_progress import ExecutionProgressPanel
        self.now = 100.0
        self.window = QMainWindow()
        self.panel = ExecutionProgressPanel(self.window, clock=lambda: self.now)
        self.window.addDockWidget(Qt.RightDockWidgetArea, self.panel)
        self.addCleanup(self.window.close)

    @staticmethod
    def activity(key, name, stage='output'):
        return SimpleNamespace(key=key, source_path=f'C:/source/{name}', stage=stage)

    def test_native_dock_is_independent_and_does_not_open_itself(self):
        p = self.panel
        self.assertIsInstance(p, QDockWidget)
        self.assertEqual(p.objectName(), 'photo_execution_progress_dock')
        self.assertEqual(p.allowedAreas(), Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.assertTrue(p.features() & QDockWidget.DockWidgetFloatable)
        p.begin(4, '예상 20초')
        p.update_activities((self.activity('1', 'one.jpg'),))
        self.assertTrue(p.isHidden())
        p.show()
        p.close()
        self.assertTrue(p.running)

    def test_parallel_files_have_independent_elapsed_times_and_stage_updates(self):
        p = self.panel
        p.begin(4)
        p.update_activities((self.activity('1', 'one.jpg', 'copy'),))
        self.now += 3
        p.update_activities((self.activity('1', 'one.jpg'), self.activity('2', 'two.jpg')))
        self.assertEqual(p.active_table.rowCount(), 2)
        self.assertEqual(p.active_table.item(0, 2).text(), '00:03')
        self.assertEqual(p.active_table.item(1, 2).text(), '00:00')
        self.assertIn('출력', p.active_table.item(0, 1).text())
        self.assertIn('C:/source/one.jpg', p.active_table.item(0, 0).toolTip())
        self.now += 2
        p.update_activities((self.activity('2', 'two.jpg'),))
        self.assertEqual(p.active_table.rowCount(), 1)
        self.assertEqual(p.active_table.item(0, 2).text(), '00:02')

    def test_completed_counts_eta_and_elapsed_are_separate(self):
        p = self.panel
        p.begin(8, '남은 시간 약 30초')
        self.now += 7
        p.update_progress('파일 처리 완료', 2, 8)
        self.assertIn('2 / 8', p.summary_label.text())
        self.assertIn('00:07', p.time_label.text())
        p.set_eta_text('남은 시간 약 21초')
        self.assertEqual(p.estimate_label.text(), '남은 시간 약 21초')

    def test_recent_results_are_bounded_and_latest_first(self):
        p = self.panel
        p.begin(55)
        for index in range(55):
            p.note_result(f'C:/source/{index}.jpg', 'ERROR' if index == 54 else 'SUCCESS', f'detail {index}')
        self.assertEqual(p.history_table.rowCount(), 50)
        self.assertEqual(p.history_table.item(0, 0).text(), '54.jpg')
        self.assertEqual(p.history_table.item(49, 0).text(), '5.jpg')
        self.assertIn('실패', p.history_table.item(0, 1).text())
        self.assertIn('C:/source/54.jpg', p.history_table.item(0, 0).toolTip())

    def test_finish_retains_history_and_freezes_elapsed(self):
        p = self.panel
        p.begin(3)
        p.note_result('C:/source/one.jpg', 'SUCCESS')
        self.now += 12
        p.finish(stopped=True)
        self.assertFalse(p.running)
        self.assertIn('중단', p.status_label.text())
        self.assertEqual(p.history_table.rowCount(), 1)
        text = p.time_label.text()
        self.now += 100
        p.update_activities(())
        self.assertEqual(p.time_label.text(), text)
        p.begin(1)
        self.assertEqual(p.history_table.rowCount(), 0)

    def test_error_finish_retains_reason_without_claiming_success(self):
        p = self.panel
        p.begin(1)
        p.finish(error=ValueError('journal unavailable'))
        self.assertIn('오류', p.status_label.text())
        self.assertIn('journal unavailable', p.status_label.toolTip())

    def test_empty_plan_and_long_paths_remain_readonly(self):
        p = self.panel
        p.begin(0)
        p.update_progress('대기', 0, 0)
        self.assertIn('0 / 0', p.summary_label.text())
        self.assertEqual(p.active_table.editTriggers(), QAbstractItemView.NoEditTriggers)
        self.assertEqual(p.history_table.editTriggers(), QAbstractItemView.NoEditTriggers)

    def test_recovery_counts_are_display_only(self):
        p = self.panel
        p.begin(6)
        p.set_recovery_counts(kept=2, pending=3, failed=1, blocked=0)
        self.assertIn('완료 유지 2', p.recovery_label.text())
        self.assertIn('미처리 3', p.recovery_label.text())
        self.assertEqual(p._completed, 0)
        p.set_recovery_counts()
        self.assertTrue(p.recovery_label.isHidden())

    def test_lossless_result_counts_are_independent_of_recent_history(self):
        p = self.panel
        p.begin(120)
        p.note_result('one.jpg', 'SUCCESS')
        p.set_result_counts(90, 20, 10)
        self.assertIn('완료 90 / 실패 20 / 미완료/제외 10', p.summary_label.text())
        self.assertEqual(p.history_table.rowCount(), 1)
        p.begin(1)
        self.assertIn('완료 0 / 실패 0 / 미완료/제외 0', p.summary_label.text())

    def test_unchanged_activities_preserve_cells_selection_and_scroll(self):
        p = self.panel
        p.begin(4)
        activities = (self.activity('1', 'one.jpg'), self.activity('2', 'two.jpg'))
        p.update_activities(activities)
        cell = p.active_table.item(0, 0)
        p.active_table.selectRow(0)
        self.now += 0.1
        p.update_activities(activities)
        self.assertIs(p.active_table.item(0, 0), cell)
        self.now += 1
        p.update_activities(activities)
        self.assertIs(p.active_table.item(0, 0), cell)
        self.assertEqual(p.active_table.currentRow(), 0)
        self.assertEqual(p.active_table.item(0, 2).text(), '00:01')
