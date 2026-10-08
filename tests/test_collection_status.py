import unittest
from reqm_local.collection_status import CollectionStatus, summary


class CollectionStatusTests(unittest.TestCase):
    def test_login_success_does_not_complete_collection(self):
        row = CollectionStatus()
        row.begin()
        row.login_result('성공', '업무 화면 확인', 1.2)
        self.assertEqual(row.state, 'pending')
        self.assertIsNone(row.order_count)
        self.assertEqual(row.values('TEST')[2:4], ('—', '—'))
        self.assertIn('미구현', row.result)

    def test_zero_is_confirmed_not_unknown(self):
        row = CollectionStatus()
        with self.assertRaises(ValueError): row.count_result(0)
        row.login_result('성공')
        row.count_result(0)
        self.assertEqual(row.values('TEST')[2], '0건')
        self.assertEqual(row.state, 'complete')
        self.assertEqual(row.download, '해당 없음')

    def test_failure_reason_and_summary(self):
        fail, done = CollectionStatus(), CollectionStatus()
        fail.login_result('실패', '인증 화면 미진입')
        done.login_result('성공')
        done.count_result(0)
        self.assertIn('인증 화면 미진입', fail.result)
        text = summary([fail, done])
        self.assertIn('완료 1', text)
        self.assertIn('실패 1', text)
        self.assertIn('미조회 1곳', text)

    def test_reset_clears_previous_counts(self):
        row = CollectionStatus()
        row.login_result('성공')
        row.count_result(10)
        row.begin()
        self.assertIsNone(row.order_count)
        self.assertEqual(row.state, 'running')
