# 실행 확인과 진행 상세 구현 계획

**Goal:** 실행 전 예상시간 확인과 안전한 진행 도킹 패널을 제공한다.

**Architecture:** Qt 없는 estimate/history 모델과 표시 전용 도킹 패널을 분리하고 기존 OperationControl polling에 결과 이벤트/진행 추정을 연결한다. 실행 확인은 checkpoint 이전에 수행한다.

**Tech Stack:** Python/PySide6/unittest/JSON/PyInstaller.

- [x] `execution_estimate.py`, `tests/test_execution_estimate.py`: 제외/DONE/영상 길이 누락/설정/이력/남은 시간 테스트 RED→GREEN. 파일 재조회 없는 추정과 bounded JSON 이력.
- [x] `ui/execution_progress.py`, `tests/test_execution_progress_panel.py`: 활성 파일/병렬 경과/최근50/숨기기 테스트 RED→GREEN, 표시 전용 native dock.
- [x] `operation_control.py`, `engine.py`, `resume_engine.py`: 성공/오류 결과 이벤트 thread-safe bounded queue와 누락 없는 전체 집계/실제 결과 기반 coordinator 전달. 기존 완료 콜백 유지.
- [x] `ui/execution_controller.py`, `main_window.py`, `operation_controller.py`, `job_controller.py`, `view_preferences.py`: 취소 전 checkpoint 미호출, 실행/재개/설정 snapshot, 도킹 재열기/저장, paused ETA/종료 유지 테스트 RED→GREEN 후 연결.
- [x] 독립 검토, 한국어 작은 창/배율, 전체567개 회귀, README/TASKS/PLAN/DECISIONS/VALIDATION 및1.0.1.17 EXE 버전/내장12개 모듈 확인. 사용자 스테이징 보존, origin push 없음.

검증 명령은 테스트 전용 mutex를 상속하는 `.venv/Scripts/python.exe .tmp_test/run_execution_suite.py`로 전체 unittest discover를 실행한다. 집중 검증은 `python -m unittest discover -s tests -p test_execution_*.py -v`를 사용한다. GUI 캡처는 offscreen 한국어 폰트에서1204×1032 및 작은 창/150·200% 배율을 검증한다. 배포는 전체 통과 후 PyInstaller를 실행한다.
