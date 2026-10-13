import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from selenium.common.exceptions import TimeoutException

from reqm_local.wekeep_tracking import fetch_tracking,SEARCH_URL,LOCK


class ImmediateWait:
    def __init__(self,driver,timeout):self.driver=driver
    def until(self,predicate):
        value=predicate(self.driver)
        if not value:raise TimeoutException()
        return value


class WeKeepBackgroundTests(unittest.TestCase):
    def test_saved_session_queries_without_window_or_credential_prompt(self):
        driver=MagicMock();driver.current_url=SEARCH_URL
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            with patch('reqm_local.closed_mall_browser.create_login_driver',return_value=driver) as create,patch('reqm_local.wekeep_tracking.load_credentials') as credentials,patch('reqm_local.wekeep_tracking.collect_tracking',return_value=[{'tracking':'001234567890'}]) as collect:
                result=fetch_tracking(folder,'2026-10-13','2026-10-13','b2c')
                create.assert_called_once_with(folder/'wekeep',True)
                credentials.assert_not_called()
                self.assertEqual(result,[{'tracking':'001234567890'}])
                self.assertEqual(collect.call_args.args[:4],(driver,'2026-10-13','2026-10-13','b2c'))
        driver.quit.assert_called_once();self.assertFalse(LOCK.locked())

    def login_driver(self,successful):
        driver=MagicMock();driver.current_url='https://fbw.wekeep.co.kr/fbw/login'
        username,password,submit=MagicMock(),MagicMock(),MagicMock()
        driver.find_elements.side_effect=lambda _by,selector:([username] if 'j_username' in selector else [password] if 'j_password' in selector else [submit])
        if successful:submit.click.side_effect=lambda:setattr(driver,'current_url',SEARCH_URL)
        return driver

    def test_expired_session_automatically_logs_in_headlessly(self):
        driver=self.login_driver(True);messages=[]
        with patch('reqm_local.closed_mall_browser.create_login_driver',return_value=driver) as create,patch('reqm_local.wekeep_tracking.load_credentials',return_value=('test-user','test-password')),patch('selenium.webdriver.support.ui.WebDriverWait',ImmediateWait),patch('reqm_local.wekeep_tracking.collect_tracking',return_value=[]):
            self.assertEqual(fetch_tracking(Path('test-data'),'2026-10-13','2026-10-13','b2c',messages.append),[])
            self.assertTrue(create.call_args.args[1])
        self.assertTrue(all('브라우저에서' not in text for text in messages))
        driver.quit.assert_called_once();self.assertFalse(LOCK.locked())

    def test_missing_credentials_fails_without_visible_browser_fallback(self):
        driver=self.login_driver(False)
        with patch('reqm_local.closed_mall_browser.create_login_driver',return_value=driver) as create,patch('reqm_local.wekeep_tracking.load_credentials',return_value=('','')),patch('reqm_local.wekeep_tracking.collect_tracking') as collect:
            with self.assertRaisesRegex(ValueError,'계정을 먼저 저장'):
                fetch_tracking(Path('test-data'),'2026-10-13','2026-10-13','b2c')
            create.assert_called_once();self.assertTrue(create.call_args.args[1]);collect.assert_not_called()
        driver.quit.assert_called_once();self.assertFalse(LOCK.locked())

    def test_failed_login_cleans_up_instead_of_opening_manual_window(self):
        driver=self.login_driver(False)
        with patch('reqm_local.closed_mall_browser.create_login_driver',return_value=driver) as create,patch('reqm_local.wekeep_tracking.load_credentials',return_value=('test-user','test-password')),patch('selenium.webdriver.support.ui.WebDriverWait',ImmediateWait),patch('reqm_local.wekeep_tracking.collect_tracking') as collect:
            with self.assertRaisesRegex(RuntimeError,'자동 로그인에 실패'):
                fetch_tracking(Path('test-data'),'2026-10-13','2026-10-13','b2c')
            create.assert_called_once();self.assertTrue(create.call_args.args[1]);collect.assert_not_called()
        driver.quit.assert_called_once();self.assertFalse(LOCK.locked())
