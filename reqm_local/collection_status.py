"""Collection progress separates unknown counts and unfinished stages."""
from dataclasses import dataclass


@dataclass
class CollectionStatus:
    login: str = '대기'
    order_count: int | None = None
    download: str = '—'
    result: str = '대기'
    state: str = 'waiting'
    reason: str = ''
    seconds: float | None = None
    file_path: str = ''

    def values(self, name):
        return (name, self.login, '—' if self.order_count is None else f'{self.order_count:,}건', self.download, self.result)

    def begin(self):
        self.login, self.order_count, self.download = '진행 중', None, '—'
        self.result, self.state, self.reason = '로그인 진행 중', 'running', ''
        self.seconds, self.file_path = None, ''

    def login_result(self, status, reason='', seconds=None):
        self.login, self.reason, self.seconds = status, reason, seconds
        if status == '성공':
            self.state = 'pending'
            self.result = '주문 조회·다운로드 미구현 · 로그인 완료'
        else:
            self.state = 'stopped' if status == '중단' else 'failed'
            self.result = f'로그인 {status} · {reason}'

    def count_result(self, count):
        if self.login != '성공' or type(count) is not int or count < 0:
            raise ValueError('로그인 성공 후 확인된 주문 수를 입력해야 합니다.')
        self.order_count = count
        if count == 0:
            self.download, self.result, self.state = '해당 없음', '완료 · 수집 대상 없음', 'complete'
        else:
            self.result, self.state = '다운로드 대기', 'running'


def summary(rows):
    items = list(rows)
    counts = {state: sum(r.state == state for r in items) for state in ('complete', 'running', 'auth', 'failed', 'pending', 'stopped')}
    total = sum(r.order_count or 0 for r in items)
    unknown = sum(r.order_count is None for r in items)
    return (f"선택 {len(items)}곳 · 완료 {counts['complete']} · 진행 중 {counts['running']} · "
            f"인증 대기 {counts['auth']} · 실패 {counts['failed']} · 후속 작업 대기 {counts['pending']} · "
            f"중단 {counts['stopped']} · 확인된 주문 합계 {total:,}건 (미조회 {unknown}곳)")
