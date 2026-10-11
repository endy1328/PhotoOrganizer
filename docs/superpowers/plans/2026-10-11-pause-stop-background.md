# 파일 완료 후 일시정지·중단 및 창 숨김 구현 계획

**Goal:** 승인된 파일 경계 제어와 Windows 영상 프로세스 무창 실행, 1.0.1.12 배포.
**Architecture:** Qt 독립 OperationControl을 엔진 경계에서 확인한다. QThread+Signal과 Qt 이벤트 루프로 UI 응답과 기존 호출 순서를 유지한다. 외부 프로세스 옵션은 공유한다.
**Tech Stack:** threading.Condition, PySide6, subprocess, unittest, PyInstaller.

기존 미커밋 작업과 읽기 전용 .git를 유지하며 현재 작업 폴더에서 구현한다.

- [x] 메인: operation_control.py 및 상태/대기/중단 테스트 RED→GREEN.
- [x] 엔진 담당: preview/scan/execute/resume 파일 경계 제어; 중단 preview 교체 금지, 실행 DONE/PENDING 보존. 실제 copy/move/중단 후 resume 테스트13개.
- [x] UI 담당: 작업 worker와 제어 mixin, 일시정지/재개·중단 버튼, busy 잠금, 진행·결과 signal, 중단 상태·오류 상태 표시. UI 응답/긴 파일 처리 중 요청/대기 중 중단/자동 저장 재예약11개 검증.
- [x] 프로세스 담당: Windows 무창 실행 공통 옵션 및 ffprobe/변환/썸네일 전파, 비Windows·stdin·인수 검증5개.
- [x] 메인: 독립 검토/전체 회귀·실제 ffmpeg·한국어 GUI 및 문서5종/설계/버전1.0.1.12 갱신.
- [x] EXE 빌드·버전/수정날짜/내장 제어·무창 옵션 검증.

공통 계약: OperationControl.request_pause()/resume()/request_stop(); checkpoint()->bool(일시정지면조건대기,중단이면False); pause_requested/paused/stop_requested/stopped 속성. preview 중단은 OperationStopped 예외, 실행/복구 중단은 최신 ExecutionBundle 반환. control은 처리 설정/계획 서명에 포함하지 않는다. UI는 _run_engine_operation(method,*args,**kwargs)에서 progress_callback=worker.progress.emit와 control을 실제 엔진에 전달하고 mock 엔진은 기존 인수만 유지한다. _operation_control과 _operation_stopped 상태로 제어/최종 표시를 갱신한다.
