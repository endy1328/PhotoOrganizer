# 모바일 복사 영상 용량 제한 구현 계획

**Goal:** output_ 동영상 중 설정 기준 이상인 파일을 USB 복사에서 제외한다.
**Architecture:** 설정/UI와 Qt 독립 전송 계획을 분리한다. 전송 시작 및 업로드 전 실제 파일 크기를 확인하고 제외 결과를 기록한다.
**Tech Stack:** Python, PySide6, TOML, unittest, PyInstaller.

- [x] 설정: 기본 해제/500 MB, 1..1000000 MB, 1 MB=1000000 bytes. 기존 설정과 JSON 이전 호환.
- [x] 핵심: 지원 영상 확장자, >= 판정, 사진 유지, 빈 출력/하위 폴더 생성 방지, 기존 휴대폰 파일 유지.
- [x] 복사 UI: 적용 기준, 폴더별 전송 수/용량/제외 수, 선택 합계, SIZE_EXCLUDED 결과 및 로그.
- [x] 기준 경계/사진/확장자/중첩 폴더/모든 충돌 정책/설정/UI 회귀 검증과 독립 검토.
- [x] README/TASKS/PLAN/DECISIONS/VALIDATION 현행화, 1.0.1.6 버전과 EXE 빌드 검증.
