import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from reqm_local.desktop import Desktop
from reqm_local.service import Operations
from reqm_local.workspace_cloud import CloudWorkspace, WorkspaceConflict, export_workspace


REFERENCE = Path(__file__).resolve().parents[1] / 'supabase/ecount_migration/data'


class FakeClient:
    def __init__(self, state):
        self.row = {'workspace_key': 'default', 'version': 1, 'state': state, 'updated_at': 'now'}
        self.reads = []
        self.writes = []
        self.fail_reads = False

    def table(self, name):
        assert name == 'reqm_workspace_state'
        client = self

        class Query:
            def select(self, fields):
                self.fields = fields
                return self

            def eq(self, field, value):
                assert (field, value) == ('workspace_key', 'default')
                return self

            def limit(self, count):
                assert count == 1
                return self

            def execute(self):
                client.reads.append(self.fields)
                if client.fail_reads:
                    raise RuntimeError('402 quota exceeded')
                data = [{key: copy.deepcopy(client.row[key]) for key in self.fields.split(',')}] if client.row else []
                return SimpleNamespace(data=data)

        return Query()

    def rpc(self, name, values):
        assert name == 'reqm_save_workspace_state'
        client = self

        class Save:
            def execute(self):
                if values['p_expected_version'] != client.row['version']:
                    raise RuntimeError('REQM_VERSION_CONFLICT')
                client.writes.append(copy.deepcopy(values))
                client.row['state'] = copy.deepcopy(values['p_state'])
                client.row['version'] += 1
                return SimpleNamespace(data=[{'new_version': client.row['version']}])

        return Save()


class WorkspaceSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Operations(Path(self.temp.name) / 'data', REFERENCE)
        self.client = FakeClient(export_workspace(self.service))
        self.workspace = CloudWorkspace(self.client, self.service)
        self.workspace.bootstrap()
        self.client.reads.clear()

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def desktop(self):
        app = Desktop.__new__(Desktop)
        app.service = self.service
        app.root = Mock()
        app.cloud_status = Mock()
        app.refresh = Mock()
        app.load_matching_profile = Mock()
        return app

    def test_unchanged_version_never_downloads_state(self):
        for _ in range(10):
            self.assertFalse(self.workspace.pull_if_newer())
        self.assertEqual(self.client.reads, ['workspace_key,version,updated_at'] * 10)

    def test_changed_version_downloads_once_then_uses_metadata(self):
        self.client.row['version'] = 2
        self.client.row['state']['settings']['account'] = 'other PC'
        self.assertTrue(self.workspace.pull_if_newer())
        self.assertEqual(self.service.settings['account'], 'other PC')
        self.assertFalse(self.workspace.pull_if_newer())
        self.assertEqual(sum('state' in fields.split(',') for fields in self.client.reads), 1)

    def test_desktop_has_no_cloud_login_or_background_sync_entrypoints(self):
        self.assertFalse(hasattr(Desktop, '_cloud_login_success'))
        self.assertFalse(hasattr(Desktop, 'poll_cloud_workspace'))
        self.assertFalse(hasattr(Desktop, 'prepare_cloud_action'))

    def test_stale_remote_workspace_does_not_block_local_action(self):
        app = self.desktop()
        self.client.row['version'] = 2
        action = Mock()
        with patch('reqm_local.desktop.messagebox.showinfo'):
            app.safe(action)
        action.assert_called_once()
        app.refresh.assert_not_called()
        self.assertEqual(self.workspace.version, 1)

    def test_remote_read_failure_does_not_affect_local_action(self):
        app = self.desktop()
        self.client.fail_reads = True
        action = Mock()
        with patch('reqm_local.desktop.messagebox.showerror') as error:
            app.safe(action)
        action.assert_called_once()
        error.assert_not_called()
        app.root.after.assert_not_called()
        self.assertEqual(len(self.client.reads), 0)

    def test_local_change_is_saved_and_server_cas_still_blocks_race(self):
        self.service.settings['account'] = 'local change'
        self.assertTrue(self.workspace.push_if_changed())
        self.assertEqual(self.client.row['state']['settings']['account'], 'local change')
        self.service.settings['account'] = 'next local change'
        self.client.row['version'] += 1
        with self.assertRaises(WorkspaceConflict):
            self.workspace.push_if_changed()
        self.assertEqual(self.client.row['state']['settings']['account'], 'local change')

    def test_dirty_local_work_is_not_overwritten_by_refresh(self):
        self.service.settings['account'] = 'unsaved local change'
        self.client.row['version'] += 1
        with self.assertRaises(WorkspaceConflict):
            self.workspace.pull_if_newer()
        self.assertEqual(self.service.settings['account'], 'unsaved local change')

    def test_missing_or_reset_workspace_blocks_processing(self):
        self.client.row['version'] = 0
        with self.assertRaises(WorkspaceConflict):
            self.workspace.pull_if_newer()
        self.client.row = None
        with self.assertRaises(WorkspaceConflict):
            self.workspace.pull_if_newer()

    def test_export_uses_local_state_after_user_confirmation(self):
        app = self.desktop()
        app.table = Mock()
        app.rows = {'old-selection': {'data': {'channel': '오늘의집'}}}
        app.request_excluded_channels = set()
        app.request_warehouse = Mock()
        app.request_warehouse.get.return_value = '전체창고'
        app.selected = Mock(return_value=['old-selection'])
        app.preflight_review = Mock(return_value=True)
        app.confirm_request_review = Mock(return_value=True)
        app.today = Mock()
        app.today.get.return_value = '2026-10-10'
        def choose_path(_):
            self.client.row['version'] += 1
            return str(Path(self.temp.name) / 'should-not-exist.xlsx')
        app.save_path = choose_path
        with patch.object(self.service, 'request') as export, patch('reqm_local.desktop.messagebox.askyesno',return_value=False):
            app.request()
        export.assert_called_once()
        self.assertIsNone(export.call_args.args[2])


if __name__ == '__main__':
    unittest.main()
