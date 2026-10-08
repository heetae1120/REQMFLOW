"""Observed form selectors, kept separate from credentials and session state."""
from dataclasses import dataclass


@dataclass(frozen=True)
class LoginForm:
    user: str
    password: str
    submit: str = ''
    labels: tuple = ('로그인',)
    code: str = ''
    send: str = ''
    send_first: bool = False
    verify: str = ''


FORMS = {
    'eri': LoginForm('input[name=p]', 'input[name=c]', labels=('로그인',), code='input[name=o]', send='#lfBtnTr1', send_first=True),
    'samsung': LoginForm('#loginId', '#password', '#btnLogin', code='#loginSmsCtfNo', send='#btn_secon', send_first=True),
    'handsome': LoginForm('#userId', '#password', '#btnLogin', code='#smsAuthNo, #smsDrmcAuthNo'),
    'ably': LoginForm('input[name=email]', 'input[name=password]'),
    'zigzag': LoginForm('input[placeholder="이메일 주소"]', 'input[placeholder="비밀번호"]'),
    'ohou': LoginForm('input[name=email]', 'input[name=password]', labels=('로그인', '로그인 버튼')),
    'kream': LoginForm('input[name=email]', 'input[name=password]', labels=('다음',), code='input[placeholder="OTP 입력"]'),
    'hmall': LoginForm('input[id$="edt_userId:input"]', 'input[id$="edt_password:input"]', '[id$="div_dtl.form.btn_login"]'),
    'sammall': LoginForm('input[name=id]', 'input[name=passwd]', labels=('Log in',)),
    'kurly': LoginForm('input[type=text], input[type=email]', 'input[type=password]'),
    'shopby': LoginForm('#username', '#password'),
    'etbs': LoginForm('#userID', '#userPW'),
    'ssf': LoginForm('#userId', '#password', '#btnLogin'),
    'wconcept': LoginForm('#userid', '#pw', labels=('관리자 로그인',)),
    'hottracks': LoginForm('#admin-id', '#admin-pw', 'input[type=image]', code='input[name=confNum]'),
    'benepia': LoginForm('#loginId', '#password', 'a[href*="do_easy_Login"]', code='#certiNo', send='#authnumBtn', send_first=True),
    'ezwel': LoginForm('#mf_user_id', '#mf_user_pw', '#mf_btn_login', code='input[id$="authCodeEml"]', send='input[id$="startEmlCrtf"]', verify='input[id$="btn_cardAuth"]'),
    'musinsa': LoginForm('input[type=text], input[type=email]', 'input[type=password]'),
    '29cm': LoginForm('input[type=text], input[type=email]', 'input[type=password]'),
}

CODE_SELECTOR = ('input[autocomplete=one-time-code], input[placeholder*="인증"], '
                 'input[name=o], #loginSmsCtfNo, #smsAuthNo, #smsDrmcAuthNo, #certiNo, '
                 'input[id*=authNo], input[id*=AuthNo], input[id*=certNo], '
                 'input[id*=otp], input[id*=Otp], input[id*=certi], input[name*=certi], '
                 'input[id*=authNum], input[id*=AuthNum], input[id*=authCode], '
                 'input[id*=AuthCode], input[name*=authCode], input[name*=otp], input[name*=certNo], '
                 'input[name=code], input[name=verificationCode], input[maxlength="1"][inputmode=numeric]')
SEND_LABELS = ('인증번호 받기', '인증번호 발송', '인증번호 전송', '인증번호 요청', '인증요청', '인증 요청', '발송', '전송')
VERIFY_LABELS = ('인증하기', '인증', '인증확인', '인증 확인', '인증번호 확인', '확인', '로그인', '다음')


def alert_reason(text):
    """Return a fixed description; never surface raw site text containing secrets."""
    if any(x in text for x in ('비밀번호 변경', '비밀번호를 변경', '비밀번호 재설정')):
        return '사이트에서 비밀번호 변경을 요구합니다. 작업자가 사이트에서 변경 후 엑셀을 갱신하세요.'
    if any(x in text for x in ('일치하지', '올바르지', '잘못', '실패', '오류', '만료', '존재하지', '등록되지', '잠겼', '잠금')):
        return '사이트에서 로그인 또는 인증을 거절했습니다. 계정·인증번호·유효시간을 확인하세요.'
    return None
