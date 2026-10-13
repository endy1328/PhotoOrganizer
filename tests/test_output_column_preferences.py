import json
import unittest
import test_view_preferences as fixture


class OutputColumnPreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.ViewPreferencesTests.setUpClass()

    def setUp(self):
        self.fixture = fixture.ViewPreferencesTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.window = self.fixture.window
        self.window.preview_table.setColumnCount(9)
        self.window.preview_table.setHorizontalHeaderLabels(['원본', '대상', '처리', '새 파일명', '일시', '모델', '안내', '영상 조회', 'output'])
        self.prefs = self.fixture.controller()

    def restore(self, tables):
        self.fixture.path.write_text(json.dumps({'tables': tables}), encoding='utf-8')
        self.prefs.restore()

    @staticmethod
    def order(table):
        header = table.horizontalHeader()
        return [header.logicalIndex(i) for i in range(table.columnCount())]

    def test_default_preview_and_results_output_columns_are_last(self):
        self.prefs.restore()
        self.assertEqual(self.order(self.window.preview_table), [3,2,6,5,0,1,4,7,8])
        self.assertEqual(self.order(self.window.results_table), [0,1,2,3,4,5,7,6])

    def test_old_eight_column_preferences_append_output_and_keep_widths_and_hidden(self):
        old = [6,3,2,5,0,1,7,4]
        self.restore({'preview_table': {'order': old, 'widths': [200,210,220,230,240,250,260,270], 'hidden':[1,4,7]}})
        self.assertEqual(self.order(self.window.preview_table), old+[8])
        self.assertTrue(self.window.preview_table.isColumnHidden(1))
        self.assertTrue(self.window.preview_table.isColumnHidden(7))
        self.assertFalse(self.window.preview_table.isColumnHidden(8))
        self.assertTrue(self.prefs.save())
        saved = json.loads(self.fixture.path.read_text(encoding='utf-8'))['tables']['preview_table']
        self.assertEqual(saved['order'], old+[8])
        self.assertEqual(saved['widths'][:8], [200,210,220,230,240,250,260,270])
        self.assertEqual(len(saved['widths']), 9)

    def test_full_new_order_and_saved_result_order_are_respected(self):
        order = [8,7,6,5,4,3,2,1,0]
        results = [6,7,5,4,3,2,1,0]
        self.restore({'preview_table': {'order':order}, 'results_table': {'order':results}})
        self.assertEqual(self.order(self.window.preview_table), order)
        self.assertEqual(self.order(self.window.results_table), results)

    def test_malformed_eight_column_order_uses_new_default(self):
        for order in ([0]*8, [True,1,2,3,4,5,6,7], [0,1,2,3,4,5,6,9]):
            with self.subTest(order=order):
                self.restore({'preview_table': {'order':order}})
                self.assertEqual(self.order(self.window.preview_table), [3,2,6,5,0,1,4,7,8])
