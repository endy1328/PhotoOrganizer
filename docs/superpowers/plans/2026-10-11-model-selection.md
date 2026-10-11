# 모델별 처리 선택 Implementation Plan

> **For agentic workers:** Use subagent-driven-development to implement each unit and independently review results.

**Goal:** 미리보기에서 모델을 선택해 Target 정리와 output_ 생성을 제한한다.
**Architecture:** Qt 독립 engine selection API와 PreviewItem inclusion 상태. 추출 데이터는 재사용하고 UI는 체크박스 상태와 표/집계를 갱신한다.
**Tech Stack:** Python, PySide6, unittest, PyInstaller.

- [x] 코어 tests/test_model_selection.py: CAM_A/CAM_B/UNKNOWN 선택/날짜 SEQ/reset/재선택/수동명 충돌/빈 선택/복사·이동 원본보존/영상추론 유지 실패 테스트 먼저 실행.
- [x] models.py included=True, selection_applied=False, media_items=[] 추가. engine.py set_selected_models 메서드와 execute 포함 필터, 이름 충돌 재검사 추가.
- [x] UI main_window.py 미리보기 wrapper, 줄바꿈 체크 목록, 처리/제외 합계, 회색 제외 행, busy/실행후 잠금, stale선택 보호. tests/test_model_selection_ui.py 이벤트/경로/실행 검증.
- [x] 독립 검토 후 `.venv/Scripts/python.exe -m unittest discover -s tests` 전체회귀.
- [x] README.md/TASKS.md/docs/PLAN.md/docs/DECISIONS.md/docs/VALIDATION.md 현행화. 버전/date/제목 test 갱신.
- [x] `.venv/Scripts/python.exe -m PyInstaller --noconfirm --distpath dist_v1.0.1.3 --workpath build_v1.0.1.3 PhotoOrganizer.spec`, EXE 버전 및 묶인 모듈 확인.

Git의 기존 변경을 보존한다. 커밋/별도 checkout 없음. 새 의존성 없음.

구현과 전체186개 테스트 완료, 배포 검증은 docs/VALIDATION.md에서 추적한다.
