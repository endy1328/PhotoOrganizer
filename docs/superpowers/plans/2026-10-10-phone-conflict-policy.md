# 휴대폰 동일 이름 처리 개발 계획

사용자 승인: 환경설정에서 선택하며 기본은 덮어쓰기. 선택지는 overwrite/skip/rename이고 파일 내용 동일 비교는 수행하지 않는다.

## 요구사항
- 같은 이름의 폴더는 재사용한다. 폴더/파일 형식 충돌 또는 같은 이름 객체가 여러 개면 자동 삭제하지 않고 실패로 표시한다.
- overwrite: 새 파일을 임시 이름으로 전송·확인하고 기존 파일을 백업 이름으로 보존한 뒤 교체한다. 실패 시 가능한 범위에서 복구하고 남은 임시/백업 객체를 명시한다. 폴더는 삭제하지 않는다.
- skip: 기존 파일 유지/건너뜀.
- rename: 원래 확장자를 유지해 `_copy0001`부터 사용 가능한 이름을 찾는다. 기존 파일은 유지한다.
- config.toml에 phone_conflict_policy 저장. 항목 없음/잘못된 값은 overwrite. 실제 전송 창에 적용 정책 표시.

## 순서 및 파일
- [x] tests/test_phone_transfer.py: 기본 덮어쓰기/기존파일 내용변경/skip보존/rename충돌/전송 중 충돌/복구 실패 표시 테스트 먼저 작성 및 실패 확인.
- [x] src/photo_organizer/phone_transfer.py: 정책 검증/분기/새 이름 생성 및 기존 실패·취소·UNVERIFIED 정책 연결.
- [x] models.py/config.py/config.toml.sample/main_window.py/phone_transfer_dialog.py: 설정 저장·화면·worker전달 및 config/UI 테스트.
- [x] phone_wpd.py/resources/phone_wpd.cs: staged 교체/정확한 객체 ID 검증/백업 복구/실패 안내 및 helper 계약 테스트.
- [x] 독립 검토/전체 unittest/Windows helper 컴파일·읽기 탐색 확인. 실제 기기 데이터 쓰기는 수행하지 않는다.
- [x] 관련 문서/버전1.0.1.1 (2026-10-10) 갱신 후 EXE 빌드 및 포함 리소스/버전 검증.

확인 명령: `.venv/Scripts/python.exe -m unittest discover -s tests`. PyInstaller 명령: `.venv/Scripts/python.exe -m PyInstaller --noconfirm --distpath dist_v1.0.1.1 --workpath build_v1.0.1.1 PhotoOrganizer.spec`.
