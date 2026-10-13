import unittest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch
from reqm_local.updater import GITHUB_LATEST_URL,latest_release,launch_replacer,cleanup_legacy_install,update_backup_directory


class UpdateChannelTests(unittest.TestCase):
    def test_existing_desktop_backup_is_migrated_without_touching_application(self):
        with tempfile.TemporaryDirectory() as folder:
            install=Path(folder)/'desktop';install.mkdir()
            (install/'REQM_FLOW.exe').write_bytes(b'current')
            previous=install/'REQM_FLOW.previous.exe';previous.write_bytes(b'previous')
            with patch.dict(os.environ,{'LOCALAPPDATA':str(Path(folder)/'local')}),patch('reqm_local.updater.sys.frozen',True,create=True),patch('reqm_local.updater.install_directory',return_value=install):
                self.assertTrue(cleanup_legacy_install())
                self.assertFalse(previous.exists())
                self.assertEqual((update_backup_directory(install)/previous.name).read_bytes(),b'previous')
                self.assertFalse(cleanup_legacy_install())
            self.assertEqual((install/'REQM_FLOW.exe').read_bytes(),b'current')

    def test_failed_backup_copy_keeps_original(self):
        with tempfile.TemporaryDirectory() as folder:
            previous=Path(folder)/'REQM_FLOW.previous.exe';previous.write_bytes(b'previous')
            with patch.dict(os.environ,{'LOCALAPPDATA':folder}),patch('reqm_local.updater.sys.frozen',True,create=True),patch('reqm_local.updater.install_directory',return_value=Path(folder)),patch('reqm_local.updater.shutil.copy2',side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    cleanup_legacy_install()
            self.assertEqual(previous.read_bytes(),b'previous')

    def test_replacer_starts_with_fresh_pyinstaller_environment(self):
        with tempfile.TemporaryDirectory(prefix='REQM-FLOW-update-') as folder:
            source=Path(folder)/'REQM_FLOW';source.mkdir()
            with patch.dict(os.environ,{'_PYI_APPLICATION_HOME_DIR':'deleted-runtime'}),patch('reqm_local.updater.subprocess.Popen') as popen:
                launch_replacer(source,Path(folder)/'install',123,restart_test_folder=Path(folder)/'report')
            self.assertEqual(popen.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'],'1')
            script=(Path(folder)/'apply-update.ps1').read_text(encoding='utf-8-sig')
            self.assertIn("$env:PYINSTALLER_RESET_ENVIRONMENT = '1'",script)
            self.assertIn('-RestartTestFolder',popen.call_args.args[0])
            self.assertIn('-BackupDirectory',popen.call_args.args[0])
            self.assertIn("Join-Path $BackupDirectory 'REQM_FLOW.previous.exe'",script)
            self.assertNotIn("Join-Path $Target 'REQM_FLOW.previous.exe'",script)

    def test_official_github_release_is_preferred_and_hash_is_returned(self):
        url='https://github.com/heetae1120/REQMFLOW/releases/download/v1.9.31/REQM_FLOW.exe'
        release={'tag_name':'v1.9.31','assets':[{'name':'REQM_FLOW.exe',
            'digest':'sha256:'+'a'*64,'browser_download_url':url}]}
        with patch('reqm_local.updater._read_json',return_value=release) as read:
            self.assertEqual(latest_release('1.9.30'),{'version':'1.9.31','exe_url':url,'sha256':'a'*64})
            read.assert_called_once_with(GITHUB_LATEST_URL,8)

    def test_installed_latest_version_does_not_download_or_query_mirror(self):
        with patch('reqm_local.updater._read_json',return_value={'tag_name':'v1.9.31'}) as read:
            self.assertIsNone(latest_release('1.9.31'))
            self.assertEqual(read.call_count,1)

    def test_missing_github_hash_falls_back_to_github_manifest(self):
        mirror={'version':'1.9.31','file':'1.9.31/REQM_FLOW.exe','sha256':'b'*64}
        with patch('reqm_local.updater._read_json',side_effect=[{'tag_name':'v1.9.31','assets':[]},mirror]):
            result=latest_release('1.9.30',config={'supabase_url':'https://demo.supabase.co'})
        self.assertEqual(result['sha256'],'b'*64)
        self.assertEqual(result['exe_url'],'https://github.com/heetae1120/REQMFLOW/releases/latest/download/1.9.31/REQM_FLOW.exe')
