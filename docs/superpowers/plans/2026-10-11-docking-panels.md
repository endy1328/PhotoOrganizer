# Docking panels implementation plan

**Goal:** 이미지와 상세 정보를 독립적으로 표시하고 좌우하단에 도킹하거나 분리하며 크기와 배치를 저장한다.

**Architecture:** QMainWindow의 기본 QDockWidget을 사용한다. UI 배치와 표시 선호는 작업 데이터/변환 설정과 분리한다. 기존 작은 화면 대응과 작업 잠금은 유지한다.

**Tech Stack:** Python / PySide6 / JSON / unittest / PyInstaller.

## 단계

- [x] UI: native dock, 독립 보기 메뉴, 기본 배치 복원, 경계 조절, 기본 반응형 배치 및 사용자 배치 보호. main_window.py 및 dock_panels.py, docking/responsive UI tests.
- [x] 저장: stable object names, versioned Qt state/base64, 독립 표시 상태, 이전 JSON 호환, 잘못된 입력 방어 및 화면 밖 floating panel 보정. view_preferences.py 및 dock preference tests.
- [x] 독립 검토 및 작은 창/한국어 오프스크린 UI 확인.
- [x] 4자리 버전 1.0.1.15와 수정 날짜, README/TASKS/PLAN/DECISIONS/VALIDATION 갱신.
- [x] 격리 mutex 최종 전체508개 회귀 후 EXE 빌드 및 버전/내장7개 모듈 확인. origin 반영은 하지 않았다.

## 검증 기준

좌우하단 도킹 허용, 상단 비허용, 이동/분리/닫기 가능, 두 패널 독립 표시, 재시작 시 배치 복원, 작은 창에서도 목록과 버튼 접근, 기본 배치 복원으로 회복, 파일명 편집/SEQ/변환 동작 회귀 없음.
