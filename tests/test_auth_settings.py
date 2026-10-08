import tempfile
import unittest
from pathlib import Path

from reqm_local.auth_settings import defaults, configured_mall, load_settings, save_settings, sms_page_status
from reqm_local.closed_malls import MALLS


class AuthenticationSettingsTests(unittest.TestCase):
    def test_routing_and_disabled_sms(self):
        settings = defaults()
        ssf = next(m for m in MALLS if m.key == 'ssf')
        self.assertFalse(configured_mall(ssf, settings).automatic_code)
        settings['sms_enabled'] = True
        self.assertTrue(configured_mall(ssf, settings).automatic_code)
        settings['vendors']['ssf'] = {'automatic': False}
        self.assertFalse(configured_mall(ssf, settings).automatic_code)
        self.assertTrue(ssf.automatic_code)

    def test_mail_route_round_trip_without_passwords(self):
        settings = defaults()
        settings['vendors']['29cm'] = {'automatic': False, 'mailbox': 'orora'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            save_settings(path, settings)
            restored = load_settings(path)
            self.assertEqual(restored, settings)
            mall = configured_mall(next(m for m in MALLS if m.key == '29cm'), restored)
            self.assertEqual(mall.mailbox, 'orora')
            self.assertFalse(mall.automatic_code)

    def test_manual_vendors_cannot_enable_automatic_code(self):
        settings = defaults()
        settings['sms_enabled'] = True
        for key in ('eri', 'samsung', 'handsome'):
            self.assertFalse(configured_mall(next(m for m in MALLS if m.key == key), settings).automatic_code)

    def test_bad_settings_cannot_replace_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            save_settings(path, defaults())
            settings = defaults()
            settings['sms_phone'] = 'ABCD'
            with self.assertRaises(ValueError): save_settings(path, settings)
            self.assertEqual(load_settings(path), defaults())

    def test_page_access_does_not_claim_sms_delivery_verified(self):
        url = 'https://messages.google.com/web/conversations'
        self.assertIn('재연결', sms_page_status('https://accounts.google.com/', '', [], False, 'test@example.com'))
        self.assertIn('계정 확인', sms_page_status(url, '', ['wrong@example.com'], True, 'test@example.com'))
        self.assertIn('재연결', sms_page_status(url, 'Phone disconnected', ['test@example.com'], True, 'test@example.com'))
        status = sms_page_status(url, '', ['test@example.com'], True, 'test@example.com')
        self.assertIn('접근 확인', status)
        self.assertIn('검증 전', status)


if __name__ == '__main__': unittest.main()
