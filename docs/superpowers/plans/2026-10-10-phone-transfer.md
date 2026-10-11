# USB 휴대폰 복사 Implementation Plan

**Goal:** 기존 output_ 폴더들을 사용자가 선택한 Android MTP 경로로 복사한다.
**Architecture:** 독립 대상 수집/전송 코어, Windows WPD adapter, PySide6 worker UI를 분리한다. 기존 정리 엔진은 변경하지 않는다.
**Tech Stack:** Python, PySide6, Windows PowerShell/C# COM WPD, unittest, PyInstaller.

## 1. 코어 (메인 담당)
- [x] tests/test_phone_transfer.py: 재귀 수집, 링크 제외, 기존 파일 보존, 폴더 충돌, 크기 불일치, 중단/재시도 테스트 먼저 작성.
- [x] `.venv/Scripts/python.exe -m unittest discover -s tests -p test_phone_transfer.py` 실패 확인.
- [x] src/photo_organizer/phone_transfer.py: RemoteEntry/OutputFolder/TransferResult, scan_outputs, transfer_outputs 구현. backend 주입으로 안전정책 검증.
- [x] 같은 명령으로 통과 확인.

## 2. WPD adapter (독립 작업 담당)
- [x] tests/test_phone_wpd.py: 프로토콜/기기탐색/전송 오류 테스트 작성 및 실패 확인.
- [x] src/photo_organizer/phone_wpd.py 및 resources helper 구현. 추가 패키지 설치 없이 Windows 내장 COM API 사용.
- [x] 기기/저장소/폴더 조회, 신규 폴더/파일, 진행률/Commit/Revert, 동일이름 충돌, COM 종료 구현.
- [x] 실제 기기 목록 read-only 확인; 사용자 파일 전송은 수행하지 않는다.

## 3. UI (독립 작업 담당)
- [x] tests/test_phone_transfer_ui.py: 버튼/대상선택/worker/취소/오류 테스트 작성 후 실패 확인.
- [x] src/photo_organizer/ui/phone_transfer_dialog.py: 기기/폴더탐색/새폴더/전송/결과 구현.
- [x] main_window.py 버튼 연결 및 busy 정책 적용.
- [x] QT_QPA_PLATFORM=offscreen UI 검증.

## 4. 통합 및 배포
- [x] 독립 검토에서 안전정책과 UI/adapter 계약 누락 확인/수정.
- [x] 전체 unittest, helper 초기화, 빌드 리소스 확인. 실제 USB 전송 미검증 여부 기록.
- [x] README.md/TASKS.md/docs/PLAN.md/DECISIONS.md/VALIDATION.md 최신화.
- [x] 새 기능 버전 1.0.1.0, 수정날짜 2026-10-10(4자리 유지).
- [x] PhotoOrganizer.spec helper 포함 후 dist_v1.0.1.0/PhotoOrganizer.exe 빌드/속성 확인.

사용자 승인에 따라 현재 작업 공간의 기존 변경을 보존한다. .git ref 권한 제한이 기록되어 있어 자동 브랜치 생성/커밋은 수행하지 않는다.
