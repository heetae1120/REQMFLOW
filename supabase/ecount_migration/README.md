# 위킵 이카운트 기준정보 → Supabase 이전

이 폴더는 `위킵_이카운트_양식.xlsx`의 DB 시트를 기존 REQM Supabase 프로젝트로 이전하기 위한 패키지입니다.
기존 `items`, `item_aliases`, `product_components` 테이블은 수정하지 않고 `ecount_*` 테이블에 별도로 적재합니다.

## 실행 순서

1. Supabase Dashboard의 SQL Editor에서 `001_ecount_reference_schema.sql`을 실행합니다.
2. REQM의 `config.json`에 기존처럼 Supabase URL과 publishable/anon 키가 설정되어 있는지 확인합니다.
3. 관리자 계정으로 아래 명령을 실행합니다.

```powershell
.\.venv\Scripts\python.exe .\supabase\ecount_migration\import_ecount_reference.py
```

스크립트가 이메일과 비밀번호를 대화형으로 요청합니다. 비밀번호는 파일에 저장하지 않습니다.
가져오기는 삭제 없이 `upsert` 방식으로 동작하므로 같은 자료를 다시 실행해도 중복 행이 생기지 않습니다.

## 적재 순서

1. `ecount_item_reference`
2. `ecount_item_aliases`
3. `ecount_sales_channels`
4. `ecount_product_mappings`
5. `ecount_product_mapping_components`
6. `ecount_price_rules`
7. `ecount_price_rule_components`
8. `ecount_migration_issues`

## 검수 원칙

- `review_status = confirmed`인 행만 자동 변환에 사용합니다.
- 코드 충돌, 품목코드 누락, 세트금액 불일치, 0원 구성품은 `ecount_migration_issues`에서 확인합니다.
- 자동 변환용 조회에는 `ecount_confirmed_item_aliases`와 `ecount_confirmed_price_rules` 뷰를 사용합니다.
- 원본 행 번호는 모든 주요 테이블에 보존되어 엑셀과 역추적할 수 있습니다.

`data/validation_report.json`에는 추출 건수, 참조 무결성, 금액 검증 결과가 기록되어 있습니다.
