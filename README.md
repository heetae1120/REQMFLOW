# REQM FLOW

판매처 주문 파일을 분석해 출고 요청과 ERP 판매전표를 만드는 Windows 데스크톱 프로그램입니다.

## 주요 기능

- 판매처별 주문 Excel 자동 판별 및 열 매칭
- 품목·세트·가격 규칙 기반 상품 매칭
- 위킵 출고요청 파일 생성과 출고 결과 반영
- ERP 판매전표 생성 및 출력 이력 관리
- 로컬 SQLite 저장과 Supabase 공유 작업공간 동기화
- Windows 패키징 및 자동 업데이트 지원

자세한 설치, 운영 및 복구 방법은 [LOCAL_PROGRAM.md](LOCAL_PROGRAM.md)를 참고하세요.

## 실행

```powershell
pip install -r requirements-local.txt
python reqm_local_app.py
```

## 빌드

```powershell
python tools/build_local.py
python tools/build_portable.py
```

`config.example.json`을 `config.json`으로 복사한 뒤 필요한 Supabase 공개 설정값을 입력합니다. 실제 비밀번호와 비밀키는 커밋하지 않습니다.
