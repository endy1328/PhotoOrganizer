# 변환 성능 구현 계획

승인된 GPU/사진 병렬 변환을 기존 미커밋 작업을 보존하며 현재 작업 폴더에서 구현한다. 읽기 전용 .git 때문에 커밋/작업트리 변경은 수행하지 않는다.

- [x] GPU 담당: TDD, NVENC 실제 capability 검사/CPU fallback, 속도와 품질 매핑, FFmpeg 무창 및 기존 출력 정책 보존.
- [x] 설정 담당: TDD, 모델·config·환경설정·요청·요약·strict job loading·구버전 계획 호환성.
- [x] 엔진 담당: TDD, bounded 사진 병렬 실행·SEQ 고정·저널 직렬화·정지/재개·파일 안전 및 사진 축소/저장 최적화.
- [x] 메인: 독립 코드 검토, 최종480개 회귀(478통과/2skip), 실제 CPU/GPU/사진 비교, GUI, 문서 최신화.
- [x] 메인: 1.0.1.13 (2026-10-11) EXE 재빌드 및 내장 코드/버전 확인.

공통 필드 video_encoder(auto/cpu/gpu), conversion_speed(quality/balanced/fast), photo_workers(1/2/4). create_mobile_video_output의 추가 선택 인수 encoder='cpu', speed='balanced'는 기존 호출 호환 기본값이다. 실제 앱은 요청 필드에서 전달한다. 영상 GPU 기능과 사진 병렬 기능을 분리하고 테스트 중 global 실행 mutex 사용은 엔진 담당에게 우선 배정한다.
