import unittest
from unittest.mock import patch
from reqm_local.updater import GITHUB_LATEST_URL,latest_release


class UpdateChannelTests(unittest.TestCase):
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

    def test_missing_github_hash_falls_back_to_existing_supabase_channel(self):
        mirror={'version':'1.9.31','file':'1.9.31/REQM_FLOW.exe','sha256':'b'*64}
        with patch('reqm_local.updater._read_json',side_effect=[{'tag_name':'v1.9.31','assets':[]},mirror]):
            result=latest_release('1.9.30',config={'supabase_url':'https://demo.supabase.co'})
        self.assertEqual(result['sha256'],'b'*64)
        self.assertEqual(result['exe_url'],'https://demo.supabase.co/storage/v1/object/public/reqm-updates/desktop/1.9.31/REQM_FLOW.exe')
