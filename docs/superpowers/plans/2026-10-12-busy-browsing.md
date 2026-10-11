# 작업 중 조회 구현 계획

**Goal:** 안전한 조회 UI와 현재 처리 파일 표시를 제공한다.

**Architecture:** 변환 상태와 조회 worker를 분리하고 OperationControl 활동 snapshot을 GUI에서 읽는다. 제출 설정은 복사하여 조회 전용으로 표시한다.

**Tech Stack:** Python/PySide6/JSON/unittest/PyInstaller.

- [x] Core: operation_control.py/engine.py/resume_engine.py, 실제 파일 활동 lifecycle 및 병렬/중단 테스트.
- [x] UI: main_window.py 및 busy_detail_worker.py, 읽기 UI/비모달 readonly settings/현재 파일 label/조회worker와 테스트.
- [x] 통합: operation_controller.py, 실행 설정 snapshot, 활동 polling과 cleanup 및 worker GUI 통합 테스트.
- [x] 독립 검토, 작은 창/배율, 전체530개 회귀, 관련5개 문서/4자리버전 및 EXE 빌드. push하지 않았다.
