# 출력 생성 용량 제한 구현 계획

**Goal:** 실제 변환 결과가 기준 이상인 사진/영상의 output_ 최종 저장 제외.
**Architecture:** 설정과 요청에 별도 생성 용량 정책을 저장한다. 엔진은 임시 변환 후 판정하며 SIZE_EXCLUDED를 실행 결과/로그로 전달한다.
**Tech Stack:** Python, PySide6, TOML, unittest, PyInstaller.

- [x] 설정/요청/결과 모델, TOML·JSON 호환, 환경설정 기본값과 크기 입력.
- [x] 엔진 임시 변환과 경계 판정, 기존 파일/수동 파일명/이동 정책 보존, 임시 정리.
- [x] UI 제외 표시/이유, 설정 변경 요청 서명 및 전파.
- [x] 실패 재현 후 회귀 테스트와 독립 검토.
- [x] README/TASKS/docs 현행화 및 1.0.1.7 EXE 빌드/리소스 확인.
