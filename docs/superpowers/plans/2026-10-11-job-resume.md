# 작업 복구 2차 구현 계획

> 작업자는 subagent-driven-development 방식으로 역할을 나누고 각 단계의 테스트와 독립 검토를 완료한다.

**Goal:** 승인된 중단 이어하기·실패 단계 재시도를 구현하고 4자리 버전 EXE를 배포한다.
**Architecture:** resume_models의 고정 계획/단계 모델, execution_journal의 SQLite 저장, resume_validation의 읽기 전용 계획, resume_engine의 검증된 단계 실행을 UI와 분리한다. 기존 저장 파일은 엄격히 판독하며 기록이 없는 실행을 추정하지 않는다.
**Tech Stack:** Python 표준 sqlite3/ctypes, PySide6, unittest, PyInstaller.

기존 미커밋 구현이 현재 작업의 기준이다. .git는 읽기 전용이므로 작업 폴더를 유지하며 기존 변경을 되돌리거나 커밋하지 않는다.

## 1. 공통 계약과 검증 (메인)

- [x] `tests/test_resume_validation.py`, `tests/test_execution_lock.py`에 성공 유지/output만 재시도/원본 변경/불확실 단계/잠금 테스트를 먼저 작성하고 실패 확인.
- [x] `src/photo_organizer/resume_models.py`: 불변 계획 정규화, plan ID, 초기 ledger, 단계 검증, ledger→ExecutionBundle 변환.
- [x] `src/photo_organizer/resume_validation.py`: `build_resume_plan(job, mode)`의 읽기 전용 처리 항목과 차단 사유. mode는 continue/retry/initial.
- [x] `src/photo_organizer/execution_lock.py`: 모든 실행 폴더에 공통인 Windows global mutex, 종료 해제.
- [x] 대상 원본/Target/output/원본 제거를 단계마다 재검증. 기존 파일·링크·성공 파일 변경을 차단하고 기준값을 갱신하지 않음.

## 2. 저장·저널 (저장 담당)

- [x] `tests/test_execution_journal.py`, `tests/test_job_schema2.py` RED→GREEN.
- [x] `job_store.JobState`에 schema_version, plan_id, plan_signature, execution_id, checkpoint, ledger, legacy_unverified를 추가. schema1 판독 및 schema2 엄격 검증.
- [x] `src/photo_organizer/execution_journal.py`: `ExecutionJournal(base_dir)`, `register(job)`, `update(job,item_id,stage,record)`, `restore(job)->bool`. ctor/restore는 DB가 없으면 파일 생성 없음.
- [x] DB plan UNIQUE/manifest 전체 검증, 이벤트 순번, checkpoint까지의 상태 재구성으로 JSON 접두부 일치 확인. 파일 수정 없는 최신 DB 채택.
- [x] DB 실패/손상/분기/오래된 READY/SaveAs 및 10만 항목의 단계별 쓰기 크기 검증.

## 3. 실행 엔진 (엔진 담당)

- [x] `tests/test_resume_engine.py`에 실패/중단 지점 테스트 작성 후 RED 확인.
- [x] `src/photo_organizer/resume_engine.py`: `execute_job(engine, job, mode='initial', progress_callback=None)`.
- [x] `OrganizerEngine.execute(...,job_state=None)`와 `resume(job,mode,progress_callback)` 연결. job_state가 없으면 기존 비저널 호출 유지.
- [x] main/output/source_remove 각각 의도·완료 저장. 시도별 임시 파일·NEW 게시 덮어쓰기 금지·검증된 Target으로 output 단독 처리.
- [x] 새 저널 move는 output 정상 종료 뒤 원본 제거. 게시 뒤 기록 실패는 UNCERTAIN 처리하고 다음 변경 중단.
- [x] 글로벌 잠금 및 읽기 전용 계획 재검증, 기존 성공·의도 제외 유지, 복구 결과/삭제 후보 중복 방지.

## 4. UI (UI 담당)

- [x] `tests/test_resume_ui.py`에 저장→실행 일부 실패→열기→이어하기/재시도 실제 엔진 통합 RED 작성.
- [x] `ui/job_controller.py`에 plan/저널 복원·고정 fingerprint 보존, 실행 시작/종료 기록 연계.
- [x] `ui/resume_dialog.py`와 기존 화면에 이어서 실행·실패 항목 재시도/읽기 전용 복구 계획/가능한 항목 실행 버튼.
- [x] schema1 실행/저널 없음은 조회 유지·재개 비활성화, 실행 중 전환/종료 잠금, SaveAs ID 유지 및 처리 설정 잠금.

## 5. 검증·배포 (메인 및 독립 검토)

- [x] 대상 테스트: `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_resume*.py' -v` 및 저장/저널/잠금 테스트.
- [x] 전체: `.venv/Scripts/python.exe -m unittest discover -s tests -v` (권한이 필요한 임시 파일 검증은 기존 승인된 방식으로 실행).
- [x] 독립 요구사항 검토 및 코드 품질 검토 후 발견 사항 수정·재검증.
- [x] README/TASKS/PLAN/DECISIONS/VALIDATION 및 설계 현행화. 버전 1.0.1.10과 수정날짜를 __init__/pyproject에 맞춤.
- [x] `.venv/Scripts/python.exe -m PyInstaller --noconfirm --distpath dist_v1.0.1.10 --workpath build_v1.0.1.10 PhotoOrganizer.spec`.
- [x] EXE 버전/수정날짜/묶인 resume·journal·lock 모듈 및 한국어 GUI 배치 확인.
