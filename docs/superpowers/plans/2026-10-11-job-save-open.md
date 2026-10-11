# 작업 저장·열기 구현 계획

**Goal:** 승인된1차 작업 저장·열기와 마지막 작업 화면 복원을 구현한다.
**Architecture:** job_store의 스키마/원자 저장, job_validation의 경로·파일상태 확인, job_controller의 화면·자동복구 상태를 분리한다. 원본 및 결과 기준값은 확인 시점에 고정한다.
**Tech Stack:** Python, PySide6, JSON/TOML, unittest, PyInstaller.

- [x] 저장 모델/strict JSON/단계 일관성/원자 저장/스키마 호환 검증.
- [x] 미리보기 원본/대상 충돌 및 경로 규칙 검증, 삭제 리뷰 확인.
- [x] 앱 복원/자동저장 기본설정 및 설정 스냅샷 분리.
- [x] UI 새 작업/열기/저장/다른이름/dirty/자동복원/체크포인트/단계별 잠금.
- [x] 정상·실패 roundtrip 및 전체 회귀/독립 검토/실제 흐름 검증.
- [x] 문서 현행화와1.0.1.9 EXE 빌드/버전/내장모듈 검증.
