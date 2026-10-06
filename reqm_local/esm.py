from __future__ import annotations

import ctypes
import json
import os
import time
from ctypes import wintypes
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .files import identifier, read_rows


ESM_LOGIN_URL = "https://signin.esmplus.com/login"
ESM_DELIVERY_URL = "https://www.esmplus.com/Home/v2/smile-delivery"
ESM_DELIVERY_STATUSES = (
    "입금대기", "배송대기", "배송준비", "배송중",
    "배송완료", "미수령신고", "정산예정", "정산완료",
)


def _decimal(value) -> Decimal:
    text = identifier(value).replace(",", "") or "0"
    return Decimal(text)


def parse_esm_rows(path) -> list[dict]:
    """Read the fixed ESM PLUS full-order export.

    The marketplace file currently has 62 columns.  We intentionally use the
    positions specified by the operator because ESM's Korean headers in legacy
    XLS files are sometimes decoded incorrectly by third-party readers.
    """
    rows = read_rows(path)
    if not rows:
        raise ValueError("ESM PLUS 파일에 데이터가 없습니다.")
    header_index = next((index for index, row in enumerate(rows[:20]) if len(row) >= 61), None)
    if header_index is None:
        raise ValueError("ESM PLUS 전체주문 파일 형식이 아닙니다. 61개 이상의 열이 필요합니다.")
    result = []
    for source_index, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(identifier(value) for value in row):
            continue
        values = list(row) + [""] * max(0, 61 - len(row))
        account = identifier(values[0]).upper()
        prefix = account[:1]
        if prefix not in ("A", "G"):
            continue
        quantity = int(_decimal(values[35]))
        if quantity <= 0:
            raise ValueError(f"ESM {source_index}행의 수량(AJ)이 올바르지 않습니다.")
        total = _decimal(values[56]) - _decimal(values[60])
        unit_amount = (total / quantity).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if unit_amount < 0:
            raise ValueError(f"ESM {source_index}행의 금액(BE-BI)이 음수입니다.")
        result.append({
            "channel": "지마켓" if prefix == "G" else "옥션",
            "account": account,
            "source_product_no": identifier(values[1]),
            "order_no": identifier(values[2]),
            "product": identifier(values[27]),
            "option": identifier(values[49]),
            "order_day": identifier(values[50])[:10],
            "quantity": str(quantity),
            "unit_amount": str(unit_amount),
            # Keep the exact BE-BI total. ERP export can split a one-won
            # remainder across quantities without losing the order total.
            "amount": str(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
            "source_row": source_index,
            "source_file": Path(path).name,
        })
    if not result:
        raise ValueError("A 또는 G 아이디로 시작하는 ESM PLUS 주문을 찾지 못했습니다.")
    return result


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _dpapi():
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _protect(data: bytes, description: str = "REQM FLOW credentials") -> bytes:
    if os.name != "nt":
        raise RuntimeError("로그인 정보 보호 저장은 Windows에서만 지원합니다.")
    source, source_buffer = _blob(data)
    output = _DataBlob()
    crypt32,kernel32 = _dpapi()
    if not crypt32.CryptProtectData(
        ctypes.byref(source), description, None, None, None, 1, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("로그인 정보 보호 저장은 Windows에서만 지원합니다.")
    source, source_buffer = _blob(data)
    output = _DataBlob()
    crypt32,kernel32 = _dpapi()
    description = wintypes.LPWSTR()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), ctypes.byref(description), None, None, None, 1, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        if description:
            kernel32.LocalFree(description)


def save_credentials(path, user_id: str, password: str, account_name: str = "ESM PLUS") -> None:
    user_id, password = user_id.strip(), password.strip()
    if not user_id or not password:
        raise ValueError(f"{account_name} 아이디와 비밀번호를 모두 입력하세요.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"user_id": user_id, "password": password}, ensure_ascii=False).encode("utf-8")
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(_protect(payload, f"REQM FLOW {account_name}"))
    os.replace(temporary, target)


def load_credentials(path) -> tuple[str, str]:
    target = Path(path)
    if not target.exists():
        return "", ""
    try:
        data = json.loads(_unprotect(target.read_bytes()).decode("utf-8"))
        return identifier(data.get("user_id")), identifier(data.get("password"))
    except Exception:
        return "", ""


@dataclass
class DownloadProgress:
    status: str
    detail: str


def download_esm_orders(user_id: str, password: str, start_day: str, end_day: str,
                        download_dir, progress=None) -> list[Path]:
    """Download every non-'전체' delivery status through a visible Edge session."""
    try:
        from selenium import webdriver
        from selenium.common.exceptions import (
            ElementClickInterceptedException, StaleElementReferenceException,
            TimeoutException, UnexpectedAlertPresentException,
        )
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import Select, WebDriverWait
    except ImportError as exc:
        raise RuntimeError("자동 다운로드 구성요소(Selenium)가 설치되지 않았습니다.") from exc

    target = Path(download_dir)
    target.mkdir(parents=True, exist_ok=True)
    before = {path.name for path in target.iterdir() if path.is_file()}

    def report(status, detail=""):
        if progress:
            progress(DownloadProgress(status, detail))

    options = webdriver.EdgeOptions()
    options.add_experimental_option("prefs", {
        "download.default_directory": str(target.resolve()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    })
    options.add_argument("--disable-features=msEdgeSidebarV2")
    driver = webdriver.Edge(options=options)
    wait = WebDriverWait(driver, 45)
    stage = "브라우저 시작"
    try:
        def wait_page_idle(timeout=25):
            """Wait until ESM's Ajax request and visible loading masks have cleared."""
            masks = ".blockUI, #loadingLayer, .loading-layer, .loadingLayer, .loading_wrap"
            WebDriverWait(driver, timeout).until(lambda current: current.execute_script(
                """
                if (document.readyState !== 'complete') return false;
                if (window.jQuery && window.jQuery.active) return false;
                const nodes = Array.from(document.querySelectorAll(arguments[0]));
                return !nodes.some((node) => {
                    const style = window.getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' &&
                           Number(style.opacity || 1) !== 0 && rect.width > 0 && rect.height > 0;
                });
                """, masks
            ))

        def safe_click(element_or_locator, timeout=12):
            """Click after scrolling; retry interception and finally use DOM click."""
            deadline = time.time() + timeout
            last_error = None
            while time.time() < deadline:
                try:
                    element = (
                        driver.find_element(*element_or_locator)
                        if isinstance(element_or_locator, tuple) else element_or_locator
                    )
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center',inline:'center'});", element
                    )
                    wait_page_idle(min(4, max(1, int(deadline - time.time()))))
                    element.click()
                    return
                except (ElementClickInterceptedException, StaleElementReferenceException, TimeoutException) as exc:
                    last_error = exc
                    time.sleep(.35)
            element = (
                driver.find_element(*element_or_locator)
                if isinstance(element_or_locator, tuple) else element_or_locator
            )
            try:
                driver.execute_script("arguments[0].click();", element)
            except Exception:
                raise last_error or RuntimeError("버튼을 누르지 못했습니다.")

        stage = "로그인"
        report("로그인", "ESM PLUS에 로그인하고 있습니다.")
        driver.get(ESM_LOGIN_URL)
        wait.until(EC.presence_of_element_located((By.ID, "typeMemberInputId01"))).send_keys(user_id)
        password_box = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        password_box.send_keys(password)
        buttons = driver.find_elements(By.CSS_SELECTOR, "button")
        login = next((button for button in buttons if "로그인" in button.text), None)
        if login is None:
            raise RuntimeError("ESM PLUS 로그인 버튼을 찾지 못했습니다.")
        safe_click(login)
        wait.until(lambda current: "signin.esmplus.com/login" not in current.current_url)
        stage = "출고/배송관리 화면 열기"
        driver.get(ESM_DELIVERY_URL)
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "innerIFrame")))
        wait.until(EC.presence_of_element_located((By.ID, "searchAccount")))
        Select(driver.find_element(By.ID, "searchAccount")).select_by_visible_text("A/G 전체")
        Select(driver.find_element(By.ID, "searchDateType")).select_by_visible_text("주문일")

        def set_date(element_id, value):
            element = driver.find_element(By.ID, element_id)
            driver.execute_script(
                "arguments[0].value=arguments[1];"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                element, value,
            )

        set_date("searchSDT", start_day)
        set_date("searchEDT", end_day)
        for status in ESM_DELIVERY_STATUSES:
            stage = f"{status} 조회"
            report("조회", f"{status} 주문을 조회하고 있습니다.")
            wait_page_idle()
            Select(driver.find_element(By.ID, "searchDeliveryType")).select_by_visible_text(status)
            # Some statuses rebuild the dependent sub-status selector.
            time.sleep(.4)
            safe_click((By.ID, "btnSearch"))
            wait.until(EC.presence_of_element_located((By.ID, "excelDown")))
            time.sleep(.5)
            wait_page_idle()
            if not driver.find_elements(By.CSS_SELECTOR, "#dataGrid input[type='checkbox']"):
                report("건너뜀", f"{status}: 다운로드할 주문이 없습니다.")
                continue
            current = {path.name for path in target.iterdir() if path.is_file()}
            stage = f"{status} 엑셀 다운로드"
            safe_click((By.ID, "excelDown"))
            confirm = WebDriverWait(driver, 8).until(lambda current_driver: next((
                element for element in current_driver.find_elements(
                    By.XPATH, "//*[self::a or self::button][normalize-space()='확인']"
                ) if element.is_displayed() and element.is_enabled()
            ), False))
            safe_click(confirm)
            try:
                alert = WebDriverWait(driver, 2).until(EC.alert_is_present())
                text = alert.text
                alert.accept()
                if "없" in text:
                    report("건너뜀", f"{status}: 다운로드할 주문이 없습니다.")
                    continue
            except (TimeoutException, UnexpectedAlertPresentException):
                pass
            deadline = time.time() + 45
            while time.time() < deadline:
                files = {path.name for path in target.iterdir() if path.is_file()}
                pending = [name for name in files if name.endswith((".crdownload", ".tmp"))]
                if files - current and not pending:
                    break
                time.sleep(.5)
            report("완료", f"{status} 다운로드 확인")
        files = [path for path in target.iterdir()
                 if path.is_file() and path.name not in before and path.suffix.lower() in (".xls", ".xlsx")]
        if not files:
            raise RuntimeError("다운로드된 ESM PLUS 주문 파일이 없습니다. 조회 기간과 배송상태를 확인하세요.")
        return sorted(files, key=lambda path: path.stat().st_mtime)
    except Exception as exc:
        if isinstance(exc, RuntimeError) and not exc.__cause__:
            raise
        detail = (str(exc) or exc.__class__.__name__).splitlines()[0]
        raise RuntimeError(f"{stage} 단계에서 ESM PLUS 자동화가 중단되었습니다. {detail}") from exc
    finally:
        driver.quit()
