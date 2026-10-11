# 동영상 품질 프로필 6단계 계획

**Goal:** 승인된 6단계 품질과 CRF/오디오값 및 선택 설명을 환경설정에 표시한다.
**Architecture:** Qt 독립 프로필 표에서 인코딩값/이름/설명을 공유한다. 기존 키는 유지하고 새 키만 추가한다.
**Tech Stack:** Python, PySide6, TOML, unittest, PyInstaller.

- [x] sixlevels 인코딩 프로필/표시 helper와 명령값 테스트.
- [x] 환경설정 긴 드롭다운/선택 설명/공통 안내 및 전체 화면 요약.
- [x] 설정 TOML/JSON 호환과 잘못된 값 균형 fallback.
- [x] 전체 회귀, 독립 검토, 문서 갱신.
- [x] 1.0.1.8 EXE 빌드/버전/내장 코드 확인.
