# REQM FLOW Web

빌드 단계가 없는 정적 웹 클라이언트다. 배포 파일은 `dist/`에 있으며 기존 FLOW Supabase의 공유 작업공간을 사용한다.

```powershell
node --test tests/core.test.mjs
python tools/qa_server.py --port 4600
```

가상 QA 서버의 로그인 값은 화면에 표시된다. QA 서버는 로컬 가상 데이터만 사용하며 실제 Supabase에는 연결하지 않는다.

배포 전에는 `docs/web-migration-handoff.md`의 남은 작업과 제한을 확인한다.
