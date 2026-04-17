# PhotoOrganizer 1.0

PhotoOrganizer 1.0은 Source 경로 아래 여러 폴더에 흩어져 있는 사진과 영상 파일을 읽어, 메타데이터 또는 파일명 정보를 기준으로 Target 경로 아래 규칙적인 디렉토리 구조로 정리하는 Python + PySide6 데스크톱 프로그램이다.

## 현재 상태

- 현재 버전은 `1.0`이다.
- 실행 가능한 PyInstaller 산출물 `dist/PhotoOrganizer.exe`가 포함되어 있다.
- Source/Target 선택, 미리보기, 실행, 오류 확인, 삭제 리뷰 흐름을 사용할 수 있다.
- 설정은 `config.toml`, 로그는 `logs` 폴더에 저장된다.

## V1 범위

- JPG/JPEG/PNG/HEIC 사진 메타데이터 읽기
- `MP4`, `MOV`, `M4V`, `AVI`, `MKV`, `WMV` 영상 메타데이터 읽기
- 촬영일 추출
- 촬영기기 모델명 추출
- Target 디렉토리 자동 생성
- 규칙 기반 파일명 생성
- 동일 파일명 충돌 시 조건부 덮어쓰기 또는 충돌 표시
- 적용 전 미리보기
- 실행 로그 저장
- 사진 메타데이터 부재 시 파일명 fallback
- 영상 메타데이터 부재 시 파일명 fallback
- 영상 모델명 부재 시 같은 디렉토리 사진 기준 `±5분` 추론
- 복사 기본, 이동 선택 지원
- 복사 실행 후 삭제 리뷰를 통한 휴지통 이동 지원

## V1 제외

- 얼굴 인식
- 중복 이미지 해시 비교
- 클라우드 동기화
- 썸네일 갤러리
- AI 분류

## 정리 규칙

- 사진의 촬영 일시 우선순위는 `EXIF DateTimeOriginal` > `DateTimeDigitized` > `DateTime` > 파일명 fallback 이다.
- 영상의 촬영 일시 우선순위는 메타데이터의 생성/촬영 시각 > 파일명 fallback 이다.
- 파일 시스템 시간은 촬영 일시 판단 기준으로 사용하지 않는다.
- 영상 파일에 모델명 메타데이터가 없으면 같은 디렉토리의 사진 파일 중 촬영 일시가 영상 일시와 `±5분` 이내인 후보를 찾는다.
- 영상 모델명 후보가 없거나 가장 가까운 후보 판정이 충돌하면 `UNKNOWN`으로 처리한다.
- 이름 충돌 시 확장자, 용량, 실제 추출 메타데이터가 모두 같으면 기존 파일을 덮어쓴다.
- 같은 날짜 디렉토리 아래에는 `YYYYMMDD_모델명` 디렉토리를 한 단계 더 만든다.
- SEQ는 같은 모델명 디렉토리 안에서 `0001`부터 순서대로 부여한다.
- 같은 모델명 디렉토리 안의 SEQ 부여 순서는 `datetime` 오름차순 기준이다.
- 같은 날짜 기준으로 배정된 SEQ 파일명이 이미 존재하지만 덮어쓰기 조건이 맞지 않으면 번호를 건너뛰지 않고 `충돌`로 표시한다.
- 기본 파일 처리 정책은 복사다. 사용자가 선택하면 이동도 지원한다.
- 삭제는 자동 수행하지 않고 실행 후 결과 목록을 확인한 뒤 휴지통 이동 방식으로 처리한다.
- 오류 파일은 건너뛰고 로그에 기록한다.

## 목표 디렉토리 구조

```text
Target/
└── 2016년
    └── 2016년 10월
        └── 20161008
            └── 20161008_RX100M3
                ├── 20161008_010134_RX100M3_0001.JPG
                ├── 20161008_010138_RX100M3_0002.JPG
                └── ...
```

## 파일명 규칙

```text
YYYYMMDD_HHMMSS_CAMERA_MODEL_SEQ4.EXT
```

예시:

```text
20161008_010134_RX100M3_0001.JPG
```

모델명을 확정하지 못하면 `UNKNOWN`을 사용한다.

## 파일명 Fallback 패턴 우선순위

1. `YYYYMMDD_HHMMSS_MODEL`
2. `YYYYMMDD_HHMMSS`
3. `IMG_YYYYMMDD_HHMMSS`
4. `YYYY-MM-DD HH.MM.SS`
5. `YYYYMMDD`

## UI에서 할 수 있는 일

- Source 경로 선택
- Target 경로 선택
- 디바이스명(선택) 입력
- 처리 모드 `copy` 또는 `move` 선택
- 미리보기 실행
- 실제 실행
- 오류 목록 확인
- 복사 모드 실행 후 삭제 리뷰 항목 선택 및 휴지통 이동

미리보기에는 변경 전 경로, 변경 후 경로, 새 파일명, 일시 근거, 모델명 근거, 오류 예상이 표시된다.
미리보기에는 추가로 `신규 생성`, `덮어쓰기`, `충돌` 같은 처리 방식 예상도 함께 표시된다.
상단 `디바이스명(선택)` 입력에 값이 있으면, 메타데이터나 파일명에서 읽은 모델명 대신 그 값이 이번 작업 전체의 디바이스명으로 우선 적용된다.
디바이스명과 모델명은 파일명 안전 문자만 정리하고, 사용자가 입력한 대소문자는 그대로 유지한다.
디바이스명을 수동 입력한 경우에도 SEQ는 같은 날짜 아래의 같은 모델명 디렉토리 안에서 `0001`부터 순서대로 증가한다.
같은 모델명 디렉토리 안의 SEQ 부여 순서는 `datetime` 오름차순 기준이다.
미리보기 직후 같은 입력값으로 `실행`하면, 실행은 방금 표시한 미리보기 결과를 그대로 사용해 실제 생성 경로와 일치하도록 유지한다.
미리보기, 실행 결과, 오류, 삭제 리뷰 표의 헤더는 모두 마우스로 가로 폭을 직접 조절할 수 있다.
표 셀 텍스트는 줄임표(`...`)로 생략하지 않되, 각 셀 영역 안에서만 그리도록 유지하고 가로 스크롤과 수동 컬럼 폭 조절을 통해 전체 문자열 기준으로 확인할 수 있다.
선택한 행의 전체 원본 경로, 대상 경로, 오류 경로, 삭제 대상 경로와 세부 내용은 표 아래 상세 영역에서 잘리지 않은 상태로 확인할 수 있다.
표 아래 상세 영역은 좌우 분할로 구성되어, 왼쪽에는 선택한 사진 파일의 축소 이미지 미리보기가 표시되고 오른쪽에는 기존 텍스트 상세가 유지된다. 비사진과 영상은 미리보기 불가 placeholder로 표시된다.
미리보기와 실행 중에는 현재 단계와 처리 건수가 상태 문구와 진행 바로 표시된다.

## 설정과 로그

- 설정 파일은 실행 폴더의 `config.toml`에 저장된다.
- `Source 경로`, `Target 경로`, `디바이스명(선택)`, `처리 모드`가 설정 파일에 함께 저장된다.
- 예전 `settings.json`이 있으면 첫 실행 시 읽어서 `config.toml`로 이전한다.
- 로그는 실행 폴더의 `logs` 폴더 아래 `jsonl` 형식으로 저장된다.
- 로그는 최근 30일 기준으로 정리된다.

## 실행 방법

### 1. 가장 쉬운 방법

아래 실행 파일을 직접 실행하면 된다.

```powershell
.\dist\PhotoOrganizer.exe
```

### 2. 소스코드로 실행

권장 순서는 아래와 같다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m photo_organizer.main
```

또는 루트 진입점 파일로 실행할 수 있다.

```powershell
.\.venv\Scripts\python.exe main.py
```

### 3. requirements 기반 설치

`requirements.txt`를 써서 설치하려면 아래처럼 진행한다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

### 4. 기존 exe가 잠겨 있을 때 대체 빌드

`dist\PhotoOrganizer.exe`가 실행 중이거나 잠겨 있어 덮어쓰기 빌드가 실패하면, 대체 출력 경로로 새 exe를 만들 수 있다.

```powershell
.\scripts\build_release.ps1
```

기본 출력은 아래 경로다.

```text
dist_release\PhotoOrganizer.exe
```

## 외부 의존성 메모

- 영상 메타데이터를 정확히 읽으려면 시스템에서 `ffprobe`를 사용할 수 있어야 한다.
- `ffprobe`가 없으면 영상 메타데이터 추출은 경고를 남기고, 가능하면 `pymediainfo`와 파일명 fallback으로 계속 진행한다.
- Windows 한글 로캘에서도 `ffprobe` JSON 출력은 UTF-8 기준으로 읽도록 처리해, 실행 시 CP949 디코딩 오류가 나지 않도록 보정했다.

## 패키징

```powershell
.\.venv\Scripts\python.exe -m PyInstaller PhotoOrganizer.spec
```

기존 `dist\PhotoOrganizer.exe`가 잠겨 있으면 아래 스크립트로 대체 출력 경로에 빌드한다.

```powershell
.\scripts\build_release.ps1
```

## 참고

- 개발용 검증 하네스와 인수인계 메모는 별도 문서와 스크립트로 관리한다.
