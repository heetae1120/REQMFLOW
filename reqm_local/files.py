from __future__ import annotations

import csv
import io
import json
import re
import subprocess
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from .profiles import PROFILE_PRESETS, merge_profile_presets
from .column_matching import find_column, match_columns


def reference_data_path(base):
    """Locate catalog CSVs in source checkouts and packaged applications."""
    base = Path(base)
    packaged = base / 'reference_data'
    return packaged if packaged.exists() else base / 'supabase' / 'ecount_migration' / 'data'

ORDER_COLUMNS = {
    'order_no': ['주문번호'], 'line_no': ['상품주문번호', '주문상세번호'],
    'source_item_code': ['상품코드', '상품번호', '업체상품코드', '협력사상품코드', 'SKU'],
    'product': ['상품명', '주문상품명'], 'option': ['옵션정보', '옵션', '옵션명'],
    'quantity': ['수량', '주문수량'], 'amount': ['최종 상품별 총 주문금액', '상품금액', '결제금액', '주문금액'],
    'recipient': ['수취인명', '수령인', '수령자명', '수령자'], 'phone': ['수취인연락처1', '연락처', '수령자전화번호', '핸드폰', '휴대폰'],
    'postcode': ['우편번호', '수취인우편번호'], 'address': ['통합배송지', '배송주소', '주소'],
    'memo': ['배송메세지', '배송메시지', '배송메모'], 'paid_at': ['결제일', '주문일', '주문일자'],
    'status': ['주문상태'], 'bundle': ['배송비 묶음번호'], 'shipping': ['배송비 합계', '배송비'],
}
REQUEST_COLUMNS = ['요청행ID', '출고요청일', '판매처', '계정', '주문번호', '상품주문번호', '수령인', '연락처', '우편번호', '주소', '배송메모', '물류품목코드', '품목명', '요청수량']
WEKEEP_REQUEST_COLUMNS = ['주문번호', '판매처', '상품명', '수량', '수령자', '핸드폰', '우편번호', '주소', '배송메세지', '송장번호', '일련번호']
RESULT_COLUMNS = ['요청행ID', '출고수량', '송장번호', '실제출고일']

COLUMN_SEARCH_TERMS = {
    'order_no': ['주문', '주문번호', '오더', 'order'],
    'line_no': ['상품주문', '상세번호', '라인', '순번', 'line'],
    'source_item_code': ['상품코드', '상품번호', '품목코드', 'sku', 'item code'],
    'product': ['상품', '상품명', '제품', '품목', 'product', 'item'],
    'option': ['옵션', '규격', '선택', 'option'],
    'quantity': ['수량', '개수', '주문수', 'qty', 'quantity'],
    'amount': ['금액', '결제', '판매가', '가격', '합계', 'amount', 'price'],
    'recipient': ['수령', '수취', '받는분', '받는사람', '이름', 'recipient'],
    'phone': ['연락처', '전화', '휴대폰', '핸드폰', 'phone', 'mobile'],
    'postcode': ['우편', '우편번호', 'zip', 'postcode'],
    'address': ['주소', '배송지', '기본주소', '상세주소', 'address'],
    'memo': ['메모', '메세지', '메시지', '배송요청', '요청사항', 'memo'],
    'paid_at': ['날짜', '일자', '주문일', '결제일', 'date'],
    'status': ['상태', '진행상태', '주문상태', 'status'],
    'bundle': ['묶음', '배송비묶음', '합포장', 'bundle'],
    'shipping': ['배송비', '운임', '택배비', 'shipping'],
}


def normalized_header(value):
    return re.sub(r'[^0-9a-z가-힣]+', '', identifier(value).casefold())


def column_choice(index, header=''):
    """Display an Excel column letter while retaining a useful header label."""
    label = identifier(header) or '(빈 열)'
    return f'{get_column_letter(index + 1)} · {label}'


def profile_header_names(profile, fallback=None):
    """Return saved header labels keyed by their Excel column index.

    Older customized profiles can retain column positions while losing the
    corresponding header text.  A preset profile supplies display labels in
    that case without changing the user's saved positions.
    """
    profile = profile or {}
    fallback = fallback or {}
    indexes = profile.get('column_indexes', {})
    columns = profile.get('columns', {})
    fallback_columns = fallback.get('columns', {})
    result = {}
    detected = profile.get('detected_headers', {})
    if isinstance(detected, dict):
        for index, header in detected.items():
            try:
                index = int(index)
            except (TypeError, ValueError):
                continue
            header = identifier(header)
            if index >= 0 and header:
                result[index] = header
    for field, index in indexes.items():
        if not isinstance(index, int) or index < 0:
            continue
        values = columns.get(field) or fallback_columns.get(field) or []
        header = identifier(values[0]) if values else ''
        if header:
            result.setdefault(index, header)
    return result


def profile_column_choices(profile, fallback=None):
    """Build choices from real or saved header names, excluding blank columns."""
    labels = profile_header_names(profile, fallback)
    return ['미사용'] + [column_choice(index, labels[index]) for index in sorted(labels)]


def sample_header_names(rows, row_index, profile=None, fallback=None):
    """Resolve a sample's header labels, including sparse/multi-row headers."""
    row = rows[row_index]
    nearby = rows[max(0, row_index - 2):row_index + 1]
    following = rows[row_index + 1:row_index + 11]
    width = max([len(row)] + [len(value) for value in nearby + following])
    headers = [identifier(row[index]) if index < len(row) else '' for index in range(width)]

    # Spreadsheet exports sometimes use merged or two-line headers.  Only
    # borrow from rows above the selected header so order values never become
    # menu labels.
    for index, header in enumerate(headers):
        if header:
            continue
        parts = []
        for candidate_row in nearby[:-1]:
            candidate = identifier(candidate_row[index]) if index < len(candidate_row) else ''
            if candidate and candidate not in parts:
                parts.append(candidate)
        if parts:
            headers[index] = ' / '.join(parts)

    for index, header in profile_header_names(profile, fallback).items():
        if index >= len(headers):
            headers.extend([''] * (index + 1 - len(headers)))
        if not headers[index]:
            headers[index] = header
    return headers


def choice_column_index(value):
    match = re.match(r'^\s*([A-Za-z]{1,3})(?:\s*[·|:-]|\s*$)', identifier(value))
    if not match:
        return None
    result = 0
    for char in match.group(1).upper():
        result = result * 26 + ord(char) - 64
    return result - 1


def related_column_choices(field, choices, query=''):
    """Rank/filter column choices using direct and related search words."""
    choices = list(dict.fromkeys(choices))
    unused = [value for value in choices if value == '미사용']
    columns = [value for value in choices if value != '미사용']
    query_key = normalized_header(query)
    terms = {normalized_header(value) for value in COLUMN_SEARCH_TERMS.get(field, []) + ORDER_COLUMNS.get(field, [])}
    expanded = set(terms)
    if query_key:
        expanded.add(query_key)
        if not any(query_key in term or term in query_key for term in terms):
            expanded = {query_key}

    def score(value):
        key = normalized_header(value.split('·', 1)[-1])
        direct = bool(query_key and query_key in key)
        related = any(term and (term in key or key in term) for term in expanded)
        return (2 if direct else 0) + (1 if related else 0)

    ranked = sorted(enumerate(columns), key=lambda item:(-score(item[1]), item[0]))
    if query_key:
        direct = [item for item in ranked if query_key in normalized_header(item[1].split('·', 1)[-1])]
        ranked = direct or [item for item in ranked if score(item[1])]
    return unused + [value for _,value in ranked]


def analyze_order_columns(headers, sample_rows=(), aliases=None):
    """Return conservative first-pass field-to-column matches."""
    headers = [identifier(value) for value in headers]
    normalized = [normalized_header(value) for value in headers]
    matched=match_columns(headers,aliases or ORDER_COLUMNS)
    result={field:match['index'] for field,match in matched.items()}
    used=set(result.values())

    rows = [list(row) for row in sample_rows if any(value not in (None, '') for value in row)][:20]
    values = {index:[identifier(row[index]) for row in rows if index < len(row) and identifier(row[index])]
              for index in range(len(headers))}

    def claim(field, predicate, threshold=.75):
        if field in result:
            return
        scores = []
        for index, items in values.items():
            if index in used or not items:
                continue
            score = sum(bool(predicate(value)) for value in items) / len(items)
            scores.append((score, index))
        scores.sort(reverse=True)
        if scores and scores[0][0] >= threshold and (len(scores) == 1 or scores[0][0] > scores[1][0]):
            result[field] = scores[0][1]
            used.add(scores[0][1])

    claim('phone', lambda value: bool(re.fullmatch(r'0\d{1,2}-?\d{3,4}-?\d{4}', value.replace(' ', ''))))
    claim('postcode', lambda value: bool(re.fullmatch(r'\d{5}', value)))
    claim('paid_at', lambda value: bool(re.fullmatch(r'(?:19|20)\d{2}[-./]?\d{1,2}[-./]?\d{1,2}(?:\s.*)?', value)))
    claim('quantity', lambda value: bool(re.fullmatch(r'\d{1,3}', value)) and 0 < int(value) <= 100, .9)
    return result


def filename_signature(value):
    """Return the stable words in a filename, excluding dates and changing numbers."""
    name = Path(identifier(value)).stem.casefold()
    name = re.sub(r'(?:19|20)\d{2}[._ -]?(?:0?[1-9]|1[0-2])[._ -]?(?:0?[1-9]|[12]\d|3[01])', ' ', name)
    name = re.sub(r'\d{3,}', ' ', name)
    name = re.sub(r'(?<![a-z가-힣0-9])\d+(?![a-z가-힣0-9])', ' ', name)
    return ' '.join(re.findall(r'[a-z0-9가-힣]+', name))


def filename_match_score(filename, hint):
    actual, expected = filename_signature(filename), filename_signature(hint)
    if not actual or not expected:
        return 0.0
    if actual == expected:
        return 1.0
    if expected in actual or actual in expected:
        return 0.95
    actual_words, expected_words = set(actual.split()), set(expected.split())
    coverage = len(actual_words & expected_words) / len(expected_words)
    return max(SequenceMatcher(None, actual, expected).ratio(), coverage * 0.9)


def identifier(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value if value is not None else '').strip()


DEFAULT_FILE_PASSWORDS = ['5666', '020360', '1234', 'tkdtkd8911!@@']

ADDRESS_COMBINE_GROUPS = (
    ('수령인 주소1', '수령인 주소2'),
    ('수령인주소1', '수령인주소2'),
    ('수령자 주소1', '수령자 주소2'),
    ('수령자주소1', '수령자주소2'),
    ('주소1(기본주소)', '주소2(상세주소)'),
    ('기본주소', '상세주소'),
    ('주소1', '주소2'),
    ('주소', '상세주소'),
    ('기본배송지', '상세배송지'),
    ('배송지 주소', '배송지 상세주소'),
)


def join_text_parts(values):
    """Join spreadsheet text fields with exactly one separating space."""
    parts = []
    for value in values:
        cleaned = ' '.join(identifier(value).split())
        if cleaned and cleaned not in parts:
            parts.append(cleaned)
    return ' '.join(parts)


def _decrypt_office(raw, passwords):
    if not raw.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):
        return raw
    try:
        import msoffcrypto
        office = msoffcrypto.OfficeFile(io.BytesIO(raw))
        if not office.is_encrypted():
            return raw
    except Exception:
        return raw
    for password in dict.fromkeys(passwords or DEFAULT_FILE_PASSWORDS):
        try:
            office = msoffcrypto.OfficeFile(io.BytesIO(raw))
            office.load_key(password=password, verify_password=True)
            output = io.BytesIO()
            office.decrypt(output)
            return output.getvalue()
        except Exception:
            continue
    raise ValueError('파일 비밀번호가 맞지 않습니다. 매칭 설정의 판매처 비밀번호를 확인하세요.')


def _html_rows(raw):
    from html.parser import HTMLParser
    class TableParser(HTMLParser):
        def __init__(self):
            super().__init__(); self.rows=[]; self.row=None; self.cell=None; self.colspan=1
        def handle_starttag(self, tag, attrs):
            if tag == 'tr': self.row=[]
            elif tag in ('td','th') and self.row is not None:
                self.cell=[]
                self.colspan=max(1,int(dict(attrs).get('colspan','1') or '1'))
        def handle_data(self, data):
            if self.cell is not None: self.cell.append(data)
        def handle_endtag(self, tag):
            if tag in ('td','th') and self.cell is not None:
                self.row.append(' '.join(''.join(self.cell).split()))
                self.row.extend(['']*(self.colspan-1)); self.cell=None; self.colspan=1
            elif tag == 'tr' and self.row is not None:
                self.rows.append(self.row); self.row=None
    text = next((raw.decode(encoding) for encoding in ('utf-8-sig','cp949','euc-kr')
                 if _can_decode(raw,encoding)), raw.decode('utf-8',errors='replace'))
    parser=TableParser(); parser.feed(text)
    return parser.rows


def _can_decode(raw, encoding):
    try:
        raw.decode(encoding); return True
    except UnicodeDecodeError:
        return False


def _excel_rows(path):
    """Let Excel recover legacy XLS files whose BIFF strings xlrd decodes incorrectly."""
    script = r'''[Console]::OutputEncoding=[Text.Encoding]::UTF8
$excel=New-Object -ComObject Excel.Application
$excel.Visible=$false;$excel.DisplayAlerts=$false;$excel.AskToUpdateLinks=$false;$excel.AutomationSecurity=3
try {
  $book=$excel.Workbooks.Open($args[0],0,$true)
  try {
    $sheet=$null;$size=-1
    foreach($candidate in $book.Worksheets){$used=$candidate.UsedRange;$current=$used.Rows.Count*$used.Columns.Count;if($current -gt $size){$sheet=$candidate;$size=$current}}
    $used=$sheet.UsedRange;$rows=@()
    for($r=1;$r -le $used.Rows.Count;$r++){$row=@();for($c=1;$c -le $used.Columns.Count;$c++){$row+= [string]$sheet.Cells.Item($r,$c).Text};$rows+=,@($row)}
    ConvertTo-Json -Compress -Depth 4 -InputObject $rows
  } finally {$book.Close($false)}
} finally {$excel.Quit();[Runtime.InteropServices.Marshal]::ReleaseComObject($excel)|Out-Null}'''
    completed = subprocess.run(
        ['powershell.exe','-NoProfile','-NonInteractive','-Command',script,str(Path(path).resolve())],
        capture_output=True, encoding='utf-8', errors='replace', timeout=45,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
    )
    if completed.returncode:
        raise ValueError('Excel 호환 판독 실패: '+(completed.stderr.strip() or 'Microsoft Excel을 확인하세요.'))
    rows=json.loads(completed.stdout.lstrip('\ufeff').strip())
    return rows if rows and isinstance(rows[0],list) else [rows]


def read_rows(path, passwords=None):
    path = Path(path)
    raw = _decrypt_office(path.read_bytes(), passwords or DEFAULT_FILE_PASSWORDS)
    if raw.startswith(b'PK'):
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            sheet = max(book.worksheets, key=lambda ws: ws.max_row * ws.max_column)
            return list(sheet.values)
        finally:
            book.close()
    if raw.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):
        import xlrd
        book = xlrd.open_workbook(file_contents=raw)
        sheet = max((book.sheet_by_index(index) for index in range(book.nsheets)), key=lambda ws:ws.nrows*ws.ncols)
        rows = [sheet.row_values(i) for i in range(sheet.nrows)]
        text = ''.join(str(value) for row in rows[:5] for value in row)
        if text and text.count('\ufffd') >= 2 and __import__('os').name == 'nt':
            return _excel_rows(path)
        return rows
    if raw.lstrip().lower().startswith((b'<html',b'<!doctype')):
        return _html_rows(raw)
    if path.suffix.lower() in ('.csv','.xls','.xlsx','.xlsm'):
        for encoding in ('utf-8-sig', 'cp949'):
            try:
                return list(csv.reader(io.StringIO(raw.decode(encoding))))
            except UnicodeDecodeError:
                continue
        raise ValueError('파일 형식 또는 문자 인코딩을 읽을 수 없습니다.')
    raise ValueError('지원 형식: xlsx, xlsm, xls, csv. PDF는 지원하지 않습니다.')


def _content_rule_matches(rule, rows):
    """동일한 파일명을 쓰는 판매처를 셀 내용으로 구분한다."""
    if not rule:
        return True
    if 'not' in rule:
        return not _content_rule_matches(rule['not'], rows)

    header_sets = [
        {identifier(value).upper() for value in row if identifier(value)}
        for row in rows[:30]
    ]
    required_headers = {
        identifier(value).upper() for value in rule.get('required_headers', [])
        if identifier(value)
    }
    forbidden_headers = {
        identifier(value).upper() for value in rule.get('forbidden_headers', [])
        if identifier(value)
    }
    if required_headers and not any(required_headers.issubset(headers) for headers in header_sets):
        return False
    if forbidden_headers and any(forbidden_headers.intersection(headers) for headers in header_sets):
        return False

    index = rule.get('column_index')
    prefix = identifier(rule.get('prefix', ''))
    if not isinstance(index, int) or not prefix:
        return True
    for row in rows[:100]:
        if index < len(row) and identifier(row[index]).upper().startswith(prefix.upper()):
            return True
    return False


def _numeric_text(value):
    cleaned = re.sub(r'[^0-9.-]', '', identifier(value).replace(',', ''))
    try:
        number = Decimal(cleaned or '0')
    except InvalidOperation:
        return ''
    return str(int(number)) if number == number.to_integral_value() else format(number, 'f')


def parse_orders(path, profiles, channel_override=None):
    passwords = [profile.get('password') for profile in profiles if profile.get('password')]
    rows = read_rows(path,passwords)
    candidates = []
    for profile in profiles:
        if not profile.get('enabled',True):
            continue
        if not _content_rule_matches(profile.get('content_rule'), rows):
            continue
        configured = profile.get('columns')
        cols = ({key:configured.get(key, []) for key in ORDER_COLUMNS}
                if configured is not None else ORDER_COLUMNS)
        required = profile.get('required', ['주문번호', '상품주문번호', '상품명', '수량'])
        preferred = profile.get('header_row', 1) - 1
        scan = list(range(min(len(rows), 30)))
        if 0 <= preferred < len(rows):
            scan = [preferred] + [index for index in scan if index != preferred]
        header_candidates=[]
        for index in scan:
            row = rows[index]
            headers = [identifier(x) for x in row]
            if all(find_column(headers,[name]) for name in required):
                matches=match_columns(headers,cols)
                if matches or not any(cols.values()):
                    exact=sum(m['method']=='일치' for m in matches.values())
                    header_candidates.append((exact,len(matches),index==preferred,-index,index,headers))
        if header_candidates:
            best=max(header_candidates)
            candidates.append((profile,cols,best[4],best[5]))
    if channel_override and len(candidates) > 1:
        selected = [c for c in candidates if c[0].get('channel') == channel_override]
        if len(selected) == 1:
            candidates = selected
    if len(candidates) > 1:
        scored = []
        for candidate in candidates:
            hints = candidate[0].get('filename_hints', [])
            filename_score = max((filename_match_score(path, hint) for hint in hints), default=0.0)
            names = {name for values in candidate[1].values() for name in values}
            matches=match_columns(candidate[3],candidate[1])
            schema_score=sum(1 if m['method']=='일치' else .75 for m in matches.values()) / max(1,sum(bool(v) for v in candidate[1].values()))
            scored.append((filename_score,schema_score,candidate))
        scored.sort(key=lambda item:(item[0],item[1]), reverse=True)
        if scored[0][0] >= 0.58 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08):
            candidates = [scored[0][2]]
        else:
            by_schema=sorted(scored,key=lambda item:item[1],reverse=True)
            if by_schema[0][1] >= 0.35 and (len(by_schema)==1 or by_schema[0][1]-by_schema[1][1] >= 0.08):
                candidates=[by_schema[0][2]]
    if len(candidates) != 1:
        raise ValueError(f'{Path(path).name}: 판매처 양식을 확정할 수 없습니다. 설정에서 열 구성·파일명 구분을 등록하세요.')
    profile, columns, start, headers = candidates[0]
    column_indexes = profile.get('column_indexes', {})
    resolved=match_columns(headers,columns)
    for field,index in column_indexes.items():
        if field not in resolved and columns.get(field) and isinstance(index,int) and 0<=index<len(headers):
            saved=profile.get('detected_headers',{}).get(str(index))
            if saved and normalized_header(saved)==normalized_header(headers[index]):
                resolved[field]={'index':index,'method':'저장위치','score':1.0}
    summary=' · '.join(f'{method} {sum(m["method"]==method for m in resolved.values())}개' for method in ('일치','근사'))
    result = []
    for rowno, row in enumerate(rows[start+1:], start+2):
        if not any(x not in (None, '') for x in row):
            continue
        def get(names, field=None):
            if field:
                for name in names:
                    indexes=[i for i,h in enumerate(headers) if normalized_header(h)==normalized_header(name)]
                    if len(indexes)==1 and indexes[0]<len(row) and identifier(row[indexes[0]]):
                        return identifier(row[indexes[0]])
                match=resolved.get(field)
                if match and match['index']<len(row):return identifier(row[match['index']])
                return ''
            for name in names:
                if name in headers:
                    i = headers.index(name)
                    if i < len(row) and identifier(row[i]):
                        return identifier(row[i])
            normalized_names = {normalized_header(name) for name in names if identifier(name)}
            for i, header in enumerate(headers):
                if normalized_header(header) in normalized_names and i < len(row) and identifier(row[i]):
                    return identifier(row[i])
            configured_index = column_indexes.get(field) if field and field in columns and columns.get(field) else None
            if isinstance(configured_index, int) and 0 <= configured_index < len(row):
                return identifier(row[configured_index])
            return ''
        entry = {key: get(columns.get(key, []), key) for key in ORDER_COLUMNS}
        # A previously saved custom profile can outlive a corrected built-in
        # marketplace format.  Fill missing critical values from the current
        # preset, and replace a false zero price when the canonical price is non-zero.
        preset = next((item for item in PROFILE_PRESETS if item.get('name') == profile.get('name')
                       or item.get('channel') == profile.get('channel')), {})
        for field in ORDER_COLUMNS:
            fallback = get(preset.get('columns',{}).get(field,[]))
            if fallback and not entry[field]:
                entry[field] = fallback
            if field == 'amount' and fallback:
                current_number = ''.join(re.findall(r'[0-9.-]',entry[field].replace(',','')))
                fallback_number = ''.join(re.findall(r'[0-9.-]',fallback.replace(',','')))
                try:
                    if float(current_number or 0) == 0 and float(fallback_number or 0) != 0:
                        entry[field] = fallback
                except ValueError:
                    pass
        # 일부 판매처는 헤더 바로 아래에 '주문/배송/취소' 같은 보조 제목행을 둔다.
        # 수량 칸만 채워진 보조 제목행은 주문으로 만들지 않는다.
        if not any(entry[key] for key in ('order_no','line_no','product','amount')):
            continue
        excluded = False
        for rule in profile.get('excludes',[]):
            value = get([rule.get('column','')])
            if value == identifier(rule.get('equals')):
                excluded = True; break
        if excluded:
            continue
        combined_fields = set()
        for field,names in profile.get('combine',{}).items():
            combined = join_text_parts(get([name]) for name in names)
            if combined:
                entry[field] = combined
                combined_fields.add(field)
        for field,names in profile.get('sum_columns',{}).items():
            values = [_numeric_text(get([name])) for name in names]
            if any(values):
                entry[field] = _numeric_text(sum(Decimal(value or '0') for value in values))
        if profile.get('amount_is_unit') and entry['amount'] and entry['quantity']:
            amount = _numeric_text(entry['amount'])
            qty = _numeric_text(entry['quantity'])
            if amount and qty:
                entry['amount'] = _numeric_text(Decimal(amount) * Decimal(qty))
        phone_digits = re.sub(r'\D', '', entry['phone'])
        if len(phone_digits) == 10 and not phone_digits.startswith('0'):
            entry['phone'] = f'0{phone_digits}'
        postcode_digits = re.sub(r'\D', '', entry['postcode'])
        if 1 <= len(postcode_digits) < 5:
            entry['postcode'] = postcode_digits.zfill(5)
        if 'address' not in combined_fields:
            normalized_headers = {normalized_header(header) for header in headers}
            for names in ADDRESS_COMBINE_GROUPS:
                if all(normalized_header(name) in normalized_headers for name in names):
                    entry['address'] = join_text_parts(get([name]) for name in names)
                    break
        if not entry['postcode'] and entry['address']:
            postcode_match = re.match(r'^\s*\(?\s*(\d{5})\s*\)?', entry['address'])
            if postcode_match:
                entry['postcode'] = postcode_match.group(1)
                entry['address'] = entry['address'][postcode_match.end():].strip()
        entry.update(channel=channel_override or profile['channel'], account=profile.get('account', '기본'), source_file=Path(path).name, source_row=rowno)
        entry['format_name']=profile.get('name') or profile['channel']
        entry['format_match_summary']=summary
        entry['column_matches']={field:{**match,'header':headers[match['index']]} for field,match in resolved.items()}
        # Keep missing price distinct from a legitimate zero-won gift.
        if not entry['address']:
            entry['address'] = join_text_parts([get(['기본배송지']), get(['상세배송지'])])
        else:
            entry['address'] = join_text_parts([entry['address']])
        result.append(entry)
    if not result:
        raise ValueError(f'{Path(path).name}: 주문행이 없습니다.')
    return result


def workbook_bytes(headers, rows, title='자료'):
    book = Workbook()
    sheet = book.active
    sheet.title = title
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    from openpyxl.styles import Font, PatternFill
    for row in sheet:
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = 's'  # Untrusted spreadsheet strings must never become formulas.
    for cell in sheet[1]:
        cell.font = Font(color='FFFFFF', bold=True)
        cell.fill = PatternFill('solid', fgColor='173C4A')
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    from openpyxl.utils import get_column_letter
    for i, head in enumerate(headers, 1):
        sheet.column_dimensions[get_column_letter(i)].width = 24 if head != '주소' else 55
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def wekeep_workbook_bytes(rows):
    """Create the verified WeKeep layout while leaving serial-number values blank."""
    book = Workbook()
    sheet = book.active
    sheet.title = '택배출고'
    sheet.append(WEKEEP_REQUEST_COLUMNS)
    for row in rows:
        sheet.append(row)
    for row in sheet:
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = 's'
    fill = PatternFill('solid', fgColor='D9EAF7')
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(horizontal='center')
    widths = [22, 14, 45, 9, 14, 18, 11, 55, 35, 18, 14]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


DEFAULT_SETTINGS = {
    'profiles': PROFILE_PRESETS,
    'request_headers': REQUEST_COLUMNS,
    'request_format': 'wekeep',
    'allow_duplicate_orders': True,
    'cloud_email': '',
    'result_columns': {x: x for x in RESULT_COLUMNS},
    'warehouse': '300', 'manager_code': '00109',
}


def settings_at(folder):
    path = Path(folder) / 'settings.json'
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_SETTINGS, ensure_ascii=False, indent=2), encoding='utf-8')
    settings = json.loads(path.read_text(encoding='utf-8-sig'))
    before = json.dumps(settings,ensure_ascii=False,sort_keys=True)
    merge_profile_presets(settings)
    settings.setdefault('request_format', 'wekeep')
    settings.setdefault('allow_duplicate_orders', True)
    settings.setdefault('channel_customer_codes', {})
    for profile in settings.get('profiles', []):
        profile['required'] = []
    if json.dumps(settings,ensure_ascii=False,sort_keys=True) != before:
        temporary=path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path)
    return settings
