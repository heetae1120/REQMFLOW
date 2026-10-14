import unittest
import tempfile
import os
import subprocess
import sys
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

    @unittest.skipUnless(sys.platform=='win32','Windows replacement script')
    def test_script_overwrites_same_file_retries_and_restores(self):
        for fail in (False,'partial','hash'):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory(prefix='flow-replace-test-') as folder:
                root=Path(folder);source=root/'source';source.mkdir();install=root/'install';install.mkdir()
                incoming=source/'REQM_FLOW.exe';incoming.write_bytes(b'new executable')
                target=install/'My FLOW.exe';target.write_bytes(b'old executable')
                file_id=target.stat().st_ino
                with patch.dict(os.environ,{'LOCALAPPDATA':str(root/'local')}),patch('reqm_local.updater.sys.frozen',True,create=True),patch('reqm_local.updater.sys.executable',str(target)),patch('reqm_local.updater.subprocess.Popen') as popen:
                    launch_replacer(source,install,2147483647,restart_test_folder=root/'report')
                command=popen.call_args.args[0]
                self.assertEqual(command[command.index('-TargetName')+1],'My FLOW.exe')
                script=source.parent/'apply-update.ps1';text=script.read_text(encoding='utf-8-sig')
                self.assertNotIn('Move-Item',text)
                self.assertNotIn('Remove-Item -LiteralPath ${targetExe}',text)
                # Stub only process startup; execute actual filesystem and hash operations.
                text=text.replace("$env:PYINSTALLER_RESET_ENVIRONMENT = '1'", "function Start-Process { param($FilePath,$WorkingDirectory,$ArgumentList,$WindowStyle) }\n$env:PYINSTALLER_RESET_ENVIRONMENT = '1'")
                if fail=='partial':
                    text=text.replace('  Copy-Verified ${newExe} ${targetExe} $expectedHash', "  [IO.File]::WriteAllText(${targetExe}, 'partial write')\n  throw 'simulated copy failure'")
                else:
                    text=text.replace("$writeStarted = $false", r"""$writeStarted = $false
$script:copyAttempts=0
function Copy-Item {
  param($LiteralPath,$Destination,[switch]$Force)
  if($LiteralPath -eq $newExe) {
    $script:copyAttempts++
    if($script:copyAttempts -lt 3) { throw 'temporary file lock' }
  }
  Microsoft.PowerShell.Management\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Force
}""")
                if fail=='hash':
                    text=text.replace("Microsoft.PowerShell.Management\\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Force", "Microsoft.PowerShell.Management\\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Force\n  if($LiteralPath -eq $newExe) { [IO.File]::WriteAllText($Destination,'corrupt') }")
                    text=text.replace('Start-Sleep -Milliseconds 250','Start-Sleep -Milliseconds 1')
                script.write_text(text,encoding='utf-8-sig')
                result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,
                                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                logs=' '.join(p.read_text(encoding='utf-8-sig') for p in (root/'local').rglob('update.log'))
                self.assertEqual(result.returncode,4 if fail else 0,result.stderr.decode(errors='replace')+logs)
                self.assertEqual(target.read_bytes(),b'old executable' if fail else b'new executable')
                self.assertEqual(target.stat().st_ino,file_id)
                self.assertEqual([p.name for p in install.iterdir()],['My FLOW.exe'])
                backups=list((root/'local').rglob('*.exe'))
                self.assertEqual(len(backups),1,logs)
                self.assertEqual(backups[0].read_bytes(),b'old executable')

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
