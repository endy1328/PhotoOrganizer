# Model mapping Implementation Plan

**Goal:** 환경설정의 모델 별칭과 적용 범위를 출력 파일명/분류 폴더에 반영한다.
**Architecture:** Qt 독립 model_mapping.py의 공통 검증/해결 함수, 원본을 유지하는 PreviewItem 출력 모델 필드, config/UI 연결.
**Tech Stack:** Python, PySide6, TOML, unittest, PyInstaller.

- [x] model_mapping.py 및 tests/test_model_mapping.py: 검증/매칭/범위/체인 없음/원본 추론/수동명/선택 재계산/동일 별칭 병합/실제복사 테스트 RED→GREEN.
- [x] models.py 설정/요청/미리보기 필드, engine.py 출력명/폴더명 적용 및 원본 metadata 보존.
- [x] config.py/TOML sample/test_config.py: 기본값/roundtrip/이전설정/잘못된 행/legacyJSON 검증.
- [x] ui/main_window.py, ui/model_mapping.py, ui/model_selection.py 및 test_model_mapping_ui.py: 편집/범위/검증/설정 전달/서명/원본별 선택/화면 배치 검증.
- [x] 독립 검토, `.venv/Scripts/python.exe -m unittest discover -s tests` 전체 회귀 및 실제 DJI 읽기 전용 매핑 확인.
- [x] README/TASKS/docs PLAN/DECISIONS/VALIDATION 현행화와 1.0.1.5 버전 갱신.
- [x] PyInstaller `--distpath dist_v1.0.1.5 --workpath build_v1.0.1.5` 빌드, 버전 리소스/묶인 모델 매핑 코드 확인.

파일 책임은 core/main, config/agent, UI/agent로 나누며 기존 변경과 배포본을 보존한다. 커밋과 원본/휴대폰 쓰기는 수행하지 않는다.
