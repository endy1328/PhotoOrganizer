# VALIDATION

## 2026-10-12 Git ignore 및 20261012 사전 확인

- 기존 규칙은 README/AGENT/TASKS/docs/tests/scripts를 제외하면서 build_v*/dist_v*/루트 로그·작업·캡처를 허용했다. 실제 HEAD255개/index367개를 검사했다.
- 수정 규칙으로 index241개,HEAD129개 제외를 확인했다. HEAD 제외는 Python 캐시107/egg-info6/중복 로컬 설치16개다. 기존 staged 산출물을 그대로 업로드하지 않고 명시적 cached 제거로 파일을 보존한다.
- `.agents/skills/uncodixfy`와 두 중복 설치의 파일 해시 차이는0이며 canonical 공유 skill/라이선스·공개 skills-lock과 config.toml.sample은 유지한다. 신규 소스·테스트·설계 문서가 정상적인 untracked 후보로 나타난다.
- origin은 PhotoOrganizer 저장소다. remote20261012 미존재,local20261012=현재HEAD8ae2593 및 좌우0/0 확인. 직전567개 전체 회귀565통과/2skip와1.0.1.17 EXE 검증 로그 확인. 앱 코드/버전 변경 없이 추적 정책과 문서만 갱신한다.
- ignore 유지/제외43개 경로 사례 검증. index241개를 정확한 NUL manifest로 cached 제거했고 모두 로컬 크기/mtime 불변을 확인했다. 깨끗한 source index157개,ignored tracked0개,예상 밖 untracked0개다. Python source/tests 구문 및 source/test/docs의 staged diff 공백 검증 통과. vendored skill README의 기존 Markdown hard-break 공백은 그대로 유지한다.
- source commit a99beac73c9ba34d2979ae7e051cdaba0cd9f685를 origin/20261012 새 브랜치로 push했다. ls-remote의 실제 해시가 로컬HEAD와 일치하며 HEAD...origin/20261012=0/0,git status clean,ignored tracked0개를 확인했다. 로컬20261012는 origin/20261012를 추적한다. 완료 검증 기록은 후속 문서 커밋에 포함한다.

## 2026-10-12 실행 확인과 진행 상세 / 1.0.1.17

- 추정12개/진행 패널10개/통합12개/결과 제어3개 통과. 취소 전 checkpoint 미호출, 실패 이력 학습 제외, 정지시간 제외, 빠른80개 burst 완료ID/오류 보존, 패널 닫기/재열기/배치 저장·초기화, 표시 종료 예외의 cleanup을 확인했다.
- 독립 core/UI 검토 후 품질·출력폭별 이력, 첫 파일 잔여 추정/초과, lossless 집계, 동일 활동 셀 재사용, 패널 정지 상태 및 복구 건수 연결을 보완했다.
- 최종 전체 unittest567개,565통과/Windows 링크 권한2skip/실패0(69.906초). validation_execution_full.log. 사용자 실행 앱과 테스트 전용 mutex로 분리했다. 기존 실행 관련 테스트는 확인창만 자동 승인하며 취소 동작은 독립 테스트로 검증한다.
- 한국어 오프스크린 현재 파일/진행 요약 표시 시1920×1000 목록615px,1204×1032 목록521px,1024×650 목록166px,800×550 목록161px,602×516 목록147px. 150%1280×680/802×640에서196/251px,200%960×500/602×480에서162/111px 확보. ui_execution_* 캡처에서 확인창/기본 숨김/하단 전체 너비 도킹/분리 창을 직접 확인했다. 최초 기본 열기 후 넓은→좁은 창에서도 전체 너비 유지 회귀를 통과했다.
- dist_v1.0.1.17/PhotoOrganizer.exe PyInstaller 빌드 성공(25.748초). FileVersion/ProductVersion1.0.1.17, Comments 수정날짜2026-10-12 및 추정/진행/확인/복구/병렬/무창 코드 내장12개 모듈 확인. build_execution_release.log. git diff --check 통과. 사용자 스테이징과 원격은 변경하지 않았다.
- 검증 환경은 기존 Python3.13.14이며 목표3.12 및 실제 원격 EXE 수동 조작은 별도 확인 대상이다. 초기 성능 가정은 실제 장시간 미디어 벤치마크 결과가 아니며 시간 보장을 의미하지 않는다.

## 2026-10-12 작업 중 조회와 현재 파일 / 1.0.1.16

- 실제 제출 request/job 설정의 독립 복사, mapping 데이터 불변 및 예외 후 활동 표시 정리 통합3개 통과.
- core 활동5개 통과: 불변 snapshot/4개 병렬/미리보기 파일 확인/직렬 실패 정리/복구 단계와 대기 중 pause 제외. 기존 OperationControl3개도 통과.
- 집중 UI 및 통합 회귀66개 통과. 최신 선택/파일 변경·미생성/오류 안내/종료 안전, 비모달 조회 전용 설정과 실제 적용 snapshot, 제한 메타정보 캐시의 작업 후 전체 조회 복귀를 확인했다.
- 최종 전체 unittest530개 실행,528통과/Windows 링크 권한2skip/실패0(88.024초). validation_busy_full.log. 테스트 전용 mutex로 사용자 앱과 분리했다. 환경은 기존 Python3.13.14이며 목표3.12 별도 검증은 미실시다.
- 한국어 오프스크린 화면1920×1000 목록615px,1204×1032 목록521px,1024×650 목록166px,800×550 목록192px,602×516 목록147px. 150%1280×680/802×640에서196/282px,200%960×500/602×480에서162/111px를 확보했다. ui_busy_* 캡처를 직접 확인했다. 작은 창에서는 현재 파일 표시 공간 확보를 위해 출력 요약만 숨긴다.
- 독립 검토에서 지연 종료 상태 초기화, 조회 오류와 파일 변경 구분, 외부 영상 조회15초 제한, 작업 중 제한 캐시와 전체 캐시 분리를 보완하고 회귀를 통과했다. 실제 원격 화면 및 배포 EXE의 수동 조작은 별도 확인 대상이다.
- dist_v1.0.1.16/PhotoOrganizer.exe PyInstaller 빌드 성공(33.626초). FileVersion/ProductVersion1.0.1.16, Comments 수정날짜2026-10-12 및 작업 중 조회/활동 표시/설정 snapshot/병렬/무창 실행 내장8개 모듈을 확인했다. build_busy_release.log. git diff --check 통과. 사용자 스테이징을 유지하고 origin push는 수행하지 않았다.

## 2026-10-12 Git 반영 사전 확인

- 현재 소스 버전1.0.1.15/수정날짜2026-10-11, 기존 최종 전체508개 테스트506통과/2skip 로그 확인.
- origin은 PhotoOrganizer 저장소이며 요청한 refs/heads/20260112는 사전 조회에서 존재하지 않았다. 프로그램 코드 변경 없이 Git 스냅샷을 준비한다.

## 2026-10-11 독립 도킹 패널 / 1.0.1.15

- 화면 선호 focused 15개 통과: 위치/폭/독립 표시 복원, truncated Qt 상태 fallback, 정상 marker 검증, 이전 설정 호환, 화면 밖 floating 창 보정, 기존 열 설정/작업 선호.
- 집중 UI 회귀: 반응형7/도킹5/기존 상세12/실행 제어11/기본 UI17 통과. 도킹 허용영역과 기능, 사용자 배치 보호, tabbed 비활성 패널 표시 의도, busy 중 작업ID·dirty·요청서명 불변 확인.
- 한국어 Malgun Gothic 오프스크린 화면: 1920×1000 목록642px, 1204×1032 목록548px, 1024×650 목록166px, 800×550 목록192px, 602×516 목록147px. 150% 1280×680/802×640 및 200% 960×500/602×480 목록 공간 확인(최소111px). 넓은→좁은 전환 하단 균등폭을 직접 캡처로 확인했다. ui_docking_*.
- 독립 검토에 차단 이슈 없음. 최종 전체 unittest508개,506통과/Windows 링크 권한2skip/실패0(161.480초). validation_docking_full.log. 테스트 전용 mutex로 사용자 실행 앱과 분리했다. 검증 환경은 기존 Python3.13.14이며 목표3.12 별도 검증은 미실시다.
- dist_v1.0.1.15/PhotoOrganizer.exe PyInstaller 빌드 성공(59.987초), FileVersion/ProductVersion1.0.1.15 및 Comments 수정날짜2026-10-11 확인. 도킹/native 지연 크기 조정·저장/복원·반응형·모델 선택·병렬 처리·무창 실행 내장7개 모듈과 버전 상수 확인. build_docking_release.log. git diff --check 통과. 브랜치20261011의 변경은 로컬에 유지했다.
- 실제 원격 화면에서의 native 마우스 드래그와 배포 EXE 수동 조작은 별도 확인 대상이다.

## 2026-10-11 작은 화면·원격 접속 UI / 1.0.1.14

- 기존 한국어10pt Qt 화면:1024×650 요청 시 실제1024×854, minimumHint912×854, 목록viewport966×35 확인. ui_small_screen_before.png.
- origin/20261011 snapshot8ae2593 push 완료, HEAD...origin/20261011=0/0 확인 후 UI 구현 시작. 로컬 작업/빌드 중간 산출물은 snapshot에서 제외했다.
- 모델 접기/20모델 내부스크롤/선택·매핑·busy3개 RED→GREEN 및 기존 단독 매핑 테스트 통과. 화면 선호4개 RED→GREEN(열 순서/너비/표시/필수 새파일명/화면 밖 복원/손상 파일 기본값).
- 독립 검토에서 매우 큰 splitter 정수 및 깊게 중첩된 선호JSON이 앱 시작 예외를 유발함을 재현했다. 크기 상한과 RecursionError 보호를 추가하여 RED→GREEN. 숨긴 열의 너비 보존도 실패 재현 뒤 보완했다. 표시 설정은 처리 설정/작업 서명과 분리된다.
- 실제 malgun.ttf를 로드한 한국어 오프스크린 화면:1920×1000 목록664px,1204×1032 목록538px,1024×650 목록194px,800×550 목록214px,602×516 목록149px. 높이/너비가 작으면 상세를 자동 접고 사용자가 직접 펼치거나 접은 선택을 존중한다. ui_responsive_* 캡처를 직접 확인했다.
- 별도 Qt 프로세스 QT_SCALE_FACTOR=1.5에서1280×680 목록192px/802×640 목록304px, =2에서960×500 목록164px/602×480 목록113px 및 주요 버튼 접근을 확인했다. 이는 논리적 가용 창/배율의 합성 검증이며 실제 모바일 원격 프로그램 수동 조작과는 구분한다.
- 최종 전체 unittest496개,494통과/Windows 링크 권한2skip,실패0(61.494초). validation_responsive_full.log. 사용자 앱은 종료하거나 잠금을 변경하지 않았다. 소스 검증은 기존Python3.13.14이며 목표3.12 별도 검증은 미실시다.
- dist_v1.0.1.14/PhotoOrganizer.exe 빌드 성공. FileVersion/ProductVersion1.0.1.14, Comments 수정날짜2026-10-11 확인. 반응형·모델 접기·선호 설정·작업 메뉴·기존 병렬/무창 코드7개 내장 모듈을 확인했다. build_responsive_release.log. git diff --check 통과.
- 사용자 지시에 따라 사전push이후UI수정은 로컬에만 유지하고 추가originpush를 수행하지 않았다. 사전snapshot에 포함된 Python 캐시는 로컬에서만 추적 제외하고 실제 파일은 유지한다. 원격 snapshot은 변경하지 않는다.
- 배포 EXE의 실제 휴대폰 원격 조작/모니터 간 이동은 수동 검증하지 않았다. 현재 새 EXE를 실행하면 설정/로그/화면 선호는 새 배포 폴더 기준으로 저장된다.

## 2026-10-11 GPU·사진 병렬 변환 검증 / 1.0.1.13

- 로컬 RTX5080 및 Ryzen7 9800X3D 확인. 실제 h264_nvenc 30프레임 인코딩 성공. GPU capability 검사64x64는 드라이버 최소 해상도 제한으로 실패하여 실제 지원되는320x240으로 보완했다.
- 합성5초1080p30 영상150프레임을 CPU/GPU로720p 및1080p 출력했다. 해상도/H.264/프레임150개 보존 확인. 720p CPU0.380초/780276bytes, GPU0.601초/2535819bytes; 1080p CPU0.675초/3368989bytes, GPU0.626초/6279021bytes. 같은 프로필 이름·CRF/CQ 숫자는 동등 화질을 뜻하지 않으며 GPU가 항상 빠르거나 더 작다는 결론을 내리지 않는다. 로그 validation_performance_benchmark.log.
- 합성1200만 화소 JPEG8장의 main/output/저널 전체 실행을 실제1/2/4worker로 비교했다. 1개1.772초, 2개1.065초, 4개0.725초. 출력1280px, 성공8개, SEQ0001..0008 및 결과 목록 계획 순서 유지. 샘플 기준 수치다. 로그 validation_parallel_benchmark.log.
- 독립 검토에서 legacy cpu/balanced/1의 manifest/저널 설정 비교 불일치를 발견하여 processing_settings 공통화 및 실제 register/update 테스트로 보완했다. publication 잠금 대기 후 baseline 재확인, 제외/실패의 인코더 보고 및 worker 이전 보고 혼입도 보완했다.
- 한국어 성능 설정 기본값/CRF·CQ 안내/사진1·2·4개 선택과 메인 요약 줄바꿈을 오프스크린으로 확인했다. performance_settings_ui.png 및 operation_paused_ui.png.
- 현재 실행 중인 사용자 앱의 전역 작업 잠금과 충돌하여 synthetic 테스트에는 별도 mutex 이름을 사용한다. 제품의 잠금 코드와 이름은 변경하지 않으며, 전체 테스트의 자식 프로세스에도 같은 테스트 이름을 전달하여 상호 배제를 검증한다. 사용자 앱이나 파일은 중단/변경하지 않는다.
- 최초 전체 회귀에서 강제 종료 후 hot rollback journal의 읽기 전용 연결 복구 오류를 발견했다. 기존 DB 전용 mode=rw로 보완하고 실제 dirty-page spill 후 자식 프로세스 종료/기존 DONE checkpoint 복구/없는 DB·미디어 경로 미생성 2개 테스트와 기존 저널 15개를 통과했다. 독립 검토에서 복원 조회에 미디어 변경 동작이 없음을 확인했다.
- 재회귀의 5초 정지/병렬 이벤트 시간 초과는 제품 변경 없는 단독 25개 실행에서 재현되지 않았다. 테스트 대기를 최대30초로 제한하고 상태/worker stack/결과 메시지 진단을 보강했다. UI 저장 횟수 실패는 이전 테스트의 다른 작업 ID 지연 자동 저장이 전역 Mock에 섞인 것으로 확인하여 현재 작업의 checkpoint/실행 상태 기준으로 검증한다.
- 최종 전체 unittest480개 실행, 478통과/Windows 링크 권한2skip, 실패0(70.312초). 로그 validation_performance_full.log. 기존 순차 복구 테스트는 photo_workers=1을 명시하여 기존 순차 전제를 유지하고 별도 병렬 테스트로 동시 처리를 검증했다.
- dist_v1.0.1.13/PhotoOrganizer.exe 최종 재빌드 성공. FileVersion/ProductVersion1.0.1.13 및 Comments 수정날짜2026-10-11 확인. 내장 설정·GPU·병렬·저널·무창·제어10개 모듈 확인. 로그 build_performance_release.log. git diff --check 통과.
- 검증 환경은 기존 .venv Python3.13.14다. 목표 Python3.12와 배포 EXE 실제 사용자 GUI/장시간 영상/다른 앱 작업 중 포커스 검증은 미실시다. 실제 GPU 인코딩 성공과 샘플 성능 수치를 일반적인 속도·동등 화질 보장으로 해석하지 않는다.

## 2026-10-11 일시정지/재개·중단·영상 창 숨김 / 1.0.1.12

- 공통 제어3개·엔진13개·UI11개·외부 프로세스5개 신규 검증. 실제 복사/이동의 main→output→원본 제거를 끝낸 후 중단, 나머지 PENDING 보존, 저장/열기 후 이어서 실행, 정지 중 중단 해제 및 마지막 파일 완료를 확인했다. 미리보기 중단은 부분 결과를 교체하지 않는다.
- QThread worker에서 UI 접근 없이 queued 진행 신호를 사용하며 UI 이벤트가 계속 처리되는 것을 확인했다. 작업 중 입력·표·탭·메타정보·이미지·자동 저장/저널 복원을 차단한다. 독립 검토에서 발견한 중단/오류 후 dirty 작업 자동 저장 예약 누락을 보완하고 외부 완료 처리가 끝난 다음 UI 이벤트에서만 재예약하는 테스트를 통과했다.
- 최종 전체 unittest445개 실행, 443통과/2skip, 실패0 (30.755초). Windows 링크 생성 권한 관련2개 skip. 로그 validation_control_full.log. 중간 회귀에서 기존 원본 변경 테스트가 같은 크기와 동일 시각 쓰기로 간헐 실패하여 다른 크기의 샘플로 결정적으로 변경했다. 앱의 파일 검증 정책은 변경하지 않았다.
- 실제 ffmpeg로 합성 MP4를 생성하고 ffprobe 촬영 일시 조회, 모바일 변환 SUCCESS(5737bytes), PNG 영상 썸네일(85139bytes)을 확인했다. Windows 자식 프로세스에서 공통 옵션 사용 시 GetConsoleWindow()==0 및 stdin EOF를 확인했다. 무창 옵션은 메타정보/변환/썸네일에 모두 적용한다.
- 한국어 Qt 오프스크린 화면 operation_paused_ui.png를 직접 확인했다. 재개/중단 버튼과 일시정지 안내, 처리 중 잠금 상태를 확인했다. 완료 시 raise_/activateWindow를 호출하지 않고 작업 오류는 상태/오류 목록으로 전달한다.
- dist_v1.0.1.12/PhotoOrganizer.exe 최종 재빌드 성공. FileVersion/ProductVersion1.0.1.12, Comments 수정날짜2026-10-11 확인. 내장 제어/worker/공통 옵션 및 실제 호출9개 모듈을 확인했다. 로그 build_control_release.log.
- 검증 환경은 기존 .venv Python3.13.14다. Python3.12 및 배포 EXE의 실제 다른 앱 작업 중 마우스 포커스 수동 검증은 미실시다. 긴 영상은 현재 파일의 모든 처리가 끝나야 실제로 정지/중단한다.

## 2026-10-11 멈춤·CMD 창 사전 확인

- 소스 확인: preview/execute/resume UI 직접 호출; progress에서 processEvents. 영상 변환/썸네일 subprocess.run은 긴 대기 동안 UI를 막을 수 있다.
- metadata/video_output/video_thumbnail은 CREATE_NO_WINDOW가 없고 phone_wpd는 이미 적용되어 있다. 사용자 환경의 창 표시를 실제 재현한 것은 아니며 코드상 창 생성 가능 경로를 확인했다.
- 독립 엔진 검토에서 파일 경계 중단과 즉시 취소의 단계 기록 차이를 확인하고 설계를 작성했다. 이번 단계 신규 코드/테스트/EXE 변경은 없다.

## 2026-10-11 미리보기 클릭별 상세 정보 사전 확인

- 소스 확인: 미리보기는 이미지column0/원본 metadata_entries 고정, 실행 결과는 itemClicked로 원본column3/대상4/모바일 출력6 전환한다.
- 클릭별 기준 파일과 대상 없음 표시 설계 초안 작성. 이번 단계에서 앱 코드·버전·EXE 변경 및 신규 기능 테스트는 수행하지 않았다.

## 2026-10-11 미리보기 클릭별 상세 정보 구현 / 1.0.1.11

- 신규12개 RED→GREEN: 같은 행 원본/대상/새 파일명 전환, 실제 QImage 대상 표시, 대상 영상 썸네일 호출 경로, 미생성/누락 및 저장 메타정보 비움, 수동 이름·다른 행 대상, 대상 생성/변경 후 메타정보 갱신, 원본 변경 재조회, 재생성 원본, 새 작업 초기화.
- 독립 검토에서 원본 메타정보와 이미지 시점 불일치/이전 작업 기준 유지 문제를 발견하고 기준값 검사 및 초기화로 보강했다.
- 독립 재검토의 저장 당시 부재한 원본이 다시 생긴 경계도 기존 스냅샷을 쓰지 않도록 보강하고 RED→GREEN을 확인했다.
- 전체413개/411통과/Windows 링크 권한2skip. 로그 validation_file_detail_full.log. 기존 실행 결과의 원본/대상/모바일 출력 경로 전환도 통과했다.
- 한국어 글꼴을 로드한 실제 Qt 소스 GUI에서 현재 기준/경로/부재 안내가 패널 위쪽에 보이고 이전 이미지·메타정보가 비워지는지 확인했다. preview_target_detail_ui.png / preview_missing_target_ui.png. 사용자 환경 EXE 수동 검증과는 구분한다.
- 실제 Python3.13.14. 목표3.12 별도 검증은 미수행.
- PyInstaller build exit0: dist_v1.0.1.11/PhotoOrganizer.exe. FileVersion/ProductVersion1.0.1.11 및 Comments 수정날짜2026-10-11 확인. 내장 main_window 코드에서 _handle_preview_item_clicked/_preview_detail_target/_file_detail_fingerprint를 확인했다. 로그 build_file_detail_release.log. git diff --check 통과.

### 2026-10-10 - 1.0.1.1 휴대폰 동일 이름 처리 선택

- 사용자 지정 기본 덮어쓰기/건너뛰기/새 이름 복사를 AppSettings, config.toml, 환경설정, 전송 창, worker/core에 연결했다. 항목 없는 기존 설정과 invalid값은 overwrite, 이전 JSON설정의 유효한값은 보존한다.
- 코어 신규 실패 확인 후 기본 overwrite/skip/rename 구현. 총23개 코어 테스트에서 실제 가상 기기 내용 교체/보존/복사 이름 순번/복수 동일 이름 객체 거부/생성 직전 경합 재평가/반복 경합20회 제한/취소/완료 응답 누락/복구 오류를 확인했다. 실제 symlink 권한 테스트1개는 skip, 경로 이탈 주입 검증은 통과했다.
- 설정6개, 휴대폰 UI9개, 기존 UI17개 검증. 환경설정 기본값 복원과 main->worker->core 전달/적용 정책 표시를 확인했다.
- backend20개: staged 교체 요청/정확한 existing ID 전달/이름·크기 검증/취소 전 생성 없음/EOF·timeout복구 이름 보존/교환 중 취소 유보 및 Windows C#실제컴파일/가짜 객체 상태 머신 테스트를 확인했다.
- C#상태 머신은 새 임시 객체 전송·확인 후 원래 객체를 backup으로 보존하며, 최종 이름/크기 확인 후 exactID/name/parent/size가 맞는 백업 파일 하나만 NO_RECURSION 삭제한다. publish실패/backup내용변경/중복이름/연결해제/삭제완료 후 확인 실패/원래 이름 대소문자 복구를 테스트했다. 삭제 이후 불확실성에서는 최종 새 파일을 임시 이름으로 되돌리지 않는다.
- 독립 검토에서 PROPVARIANT 초기화 전에 COM생성 실패시 잘못된 native 메모리 정리가 가능한 순서 문제를 발견해 COM생성 전 zero 초기화로 보완했다. 원래 크기 확인 불가와 이름 변경 미지원이면 스테이징 전에 거부한다.
- 최종 전체 unittest: 162개 실행, 161통과/1skip, 실패0. 기존 잘못된 이미지 샘플의 exifread안내 출력은 유지된다. Python3.13.14환경이며 Python3.12 검증은 미실시다.
- 연결된 Samsung USB MTP기기/내장 저장소/하위 객체57개를 읽기만 했다. backend작업 담당은 기존파일1개의 ORIGINAL_FILE_NAME_CAN_WRITE=True 속성을 읽기 전용으로 확인했다. 실제 upload/rename/delete는 수행하지 않았다.
- 실제 휴대폰 덮어쓰기/취소/케이블 분리와 기기별 rename/delete 동작 검증은 미실시다. MTP교체는 원자적이지 않고 불확실성 시 임시/백업 파일이 남을 수 있다. 선택한 휴대폰 폴더에서 오류에 표시된 복구 이름을 확인해야 한다.
- dist_v1.0.1.1/PhotoOrganizer.exe 빌드 성공. Windows FileVersion/ProductVersion=1.0.1.1, Comments 수정날짜2026-10-10 확인. 내장 C# helper는 최종 소스 바이트와 동일하며 overwrite_file/핵심 정책 인자/설정 필드 포함을 확인했다. 소스 Qt 읽기 전용 기기/폴더 탐색도 재검증했다. EXE GUI 수동 조작은 미실시다.
- 최종 독립 검토에서 PROPVARIANT 초기화 수정과 backend20개 검증 후 차단 이슈 없음 확인.

### 2026-10-10 - 1.0.1.0 USB 휴대폰 복사

- 전송 코어 신규13개: output_ 재귀 수집/일반 파일 제외/임시 파일 제외/빈 하위 폴더/동일 이름 보존 및 재시도/폴더 이름 충돌/취소/연결 해제/크기 불일치/중복 출력 이름/경로 변경을 확인했다. 신규모듈 부재 실패 후 구현했으며 Commit 불확실성과 조상 링크/빈 폴더 경로 테스트 실패를 재현한 뒤 수정했다.
- 실제 Windows symlink 생성 권한이 없는 테스트1개는 skip. 전체 조상 링크로 경로가 교체되는 경우는 주입 테스트로 파일 및 빈 폴더 접근 거부를 확인했다.
- WPD 계약13개: 기기 객체 ID/이름·크기 확인/취소/오류 분류/진행 응답/시간 초과/USB 목록 필터/시작·최초 송신 실패 복구/다른 스레드 소유 세션 보호를 확인했다. timeout/protocol/restart 테스트 추가 실패 후 오류 처리를 보완했다.
- 휴대폰 UI7개: 메인 버튼/busy/기기·폴더 탐색/선택/한 작업 스레드 소유/취소 응답/실패·미확인 후 대상 무효화/재조회·재시도/로그 및 로그 저장 실패 시 복사 결과 보존을 확인했다.
- 동일 시각 세션 로그 덮어쓰기를 재현하고 고유 이름+exclusive 생성으로 수정했다. 기존 AppLogger30일보관 정책을 유지한다.
- 최종 `.venv/Scripts/python.exe -m unittest discover -s tests`: 141개 실행, 140통과/1skip, 실패0. 테스트용 잘못된 이미지의 exifread 안내 출력은 기존 현상이다. 기존 .venv Python3.13.14 사용, Python3.12 검증은 미실시다.
- Windows 내장 PowerShell에서 번들 C# helper 컴파일 성공. 실제 연결된 Samsung 갤럭시 USB 기기1대만 선택 목록에 표시되며 일반 WPD 드라이브는 제외했다. 내장 저장공간/하위 객체57개를 읽기 전용으로 열거했다. helper 프로세스를 강제 종료한 뒤 첫 조회 오류/다음 조회 재시작 복구 성공을 확인했다.
- `scripts/verify_phone_transfer_ui.py`에서 실제 휴대폰 저장소/폴더 탐색, 복사 버튼 활성화, worker 정상 종료를 확인했다. 출력 파일 목록은 샘플을 주입하고 복사 버튼은 누르지 않았다. 오프스크린 스크린샷은 기존 환경 글꼴 사각형 렌더링 제약이 있어 텍스트 문자열/위젯 이벤트 기준으로 확인했다.
- 독립 검토에서 source 전체 조상 경로, 완료 불확실성, stale object ID 및 helper 최초 송신/시작 오류 정리를 지적받아 수정했다. 최종 검토에서 차단 이슈 없음 확인.
- PyInstaller `dist_v1.0.1.0/PhotoOrganizer.exe` 빌드 성공(54.5MB). Windows FileVersion/ProductVersion=1.0.1.0, 수정날짜2026-10-10 확인. 내장 phone_transfer/phone_wpd/phone_transfer_dialog 및 C# helper 리소스의 소스 바이트 일치를 확인했다.
- 실제 휴대폰 폴더 생성/파일 업로드/쓰기 중 취소/케이블 분리/이름 충돌/갤러리 표시는 미검증이다. 기기 데이터는 읽기만 했으며 기존 파일을 쓰거나 삭제하지 않았다. WPD 이름 확인과 신규 생성 사이의 동시 외부 쓰기 경쟁은 기기별 실제 검증 대상이다. EXE GUI 수동 조작은 미실시다.

### 2026-10-10 - 1.0.0.6 날짜 SEQ/범위 밖 사진/UNKNOWN 배경

- 모델 CAM/UNKNOWN/OTHER/UNKNOWN이 같은 날짜에서 0001/0002/0003/0004, 다음 날짜 UNKNOWN은 0001인 회귀 테스트 실패를 확인한 뒤 날짜 공통 카운터로 수정했다.
- 범위 밖 사진 모델 보완/앞뒤 충돌 회귀 실패 확인 후 구현. 한쪽 후보/동일 시각 충돌/다른 폴더/영상 후보 제외/UNKNOWN 제외를 포함한 fallback20개 통과.
- 기존 연쇄 추론 방지 테스트는 사진 anchor 대신 확인된 영상 anchor로 변경했다. 사진 보완은 이제 시간 제한 없이 가능하므로 기존 사진 anchor의 UNKNOWN 기대값은 정책에 맞지 않는다.
- UNKNOWN 모든 셀 배경/모델 확인 후 배경 해제 실패 테스트 확인 후 적용. 전체106개 테스트 통과.
- 독립 검토에서 유효/무일시 파일 혼합 정렬의 기존 TypeError를 재현했다. 해당 회귀 테스트 실패 확인 후 정렬 타입을 통일해 오류 파일 건너뛰기 및 연속 SEQ를 검증했다. 최종 전체107개 테스트 통과.
- 실제202405 원본 폴더281건 읽기 전용 미리보기에서 오류0. 125303 영상은 5분 범위 비교 실패 후 앞뒤 사진 보완으로 SM-F926N, 553초 차이, 파일명 20240501_125319_SM-F926N_0032.mp4 확인. 원본은 변경하지 않았다. 이전202405_test 폴더에는 이번 검증 시 해당파일이 없어 기존202405를 사용했다.
- dist_v1.0.0.6/PhotoOrganizer.exe 최종 빌드 성공. Windows FileVersion/ProductVersion=1.0.0.6, 수정날짜2026-10-10 확인. 내장 엔진의 무제한 사진 보완과 무일시 정렬 수정 포함 확인. 새 exe GUI 수동 조작은 미실시, 소스 Qt 배경/편집 이벤트 검증은 수행했다. 기존 .venv Python3.13.14 검증이며 Python3.12 검증은 미실시다.

### 2026-10-10 - 1.0.0.5 모델 조회·추론 설정·파일명 편집

- 메타데이터 신규 테스트6개 실패 후 구현, 모델 조회 tests18개 통과. 직접 확인/지원태그 미확인/조회 실패/일부 도구 실패/파일명 모델과 원본 모델 분리 검증.
- 설정 및 fallback tests: 기본/저장/invalid값/0분/시간경계/영상후보/혼합동률/UNKNOWN 후보 제외 검증.
- 파일명 편집 신규 실패 테스트 후 구현. 이름/경로/모바일 경로 일치, 잘못된 이름/확장자/기존 파일/미리보기 중복 거절, 실행 직전 생성 파일 무덮어쓰기, 부분 복사 실패/모바일 생성 중 충돌/이동 원본 보존 검증.
- Qt 오프스크린에서 편집창 입력 후 실행 버튼 mouseClick으로 편집명 캐시 실행·실제 복사 확인, 설정 변경 후 실행 차단 확인.
- 전체98개 테스트 통과. 독립 검토에서 모바일 race 지적을 받아 임시 생성+exclusive 게시로 보강 후 재검증했다.
- 실제 202405_test의 125303.mp4는 5분 설정 UNKNOWN, 10분 설정 SM-F926N 사진 추론. 두 경우 모두 영상 원본 조회는 지원 태그 모델명 미확인이다. 소스는 읽기만 수행했다.
- 환경설정 오프스크린 배치 확인(560x471, 일부 환경의 기본 글꼴 렌더링 제약 있음). .venv Python3.13.14 환경이며 Python3.12 검증은 미실시다.
- dist_v1.0.0.5/PhotoOrganizer.exe 빌드 성공. Windows FileVersion/ProductVersion=1.0.0.5, Comments 수정날짜=2026-10-10 확인. 내장 엔진에 파일명 편집 API 포함 확인. 새 exe 실제 GUI 수동 조작은 미실시이며 Qt 이벤트 검증은 소스 환경에서 수행했다.

### 2026-10-10 - 1.0.0.4 버전 체계 복원

- 사용자 요청으로 4자리 표기 복원. 소스/pyproject/창 제목/Windows 리소스를 같은 버전으로 맞춘다. 기존 1.0.1 기록은 중간 빌드의 이력이다.
- 모델명 표기는 현재 model_source(최종 출처), warnings(추출/추론 실패 안내)만으로는 정상 조회의 태그 부재와 추출 실패를 독립적으로 표시하기 어려움을 확인했다. 별도 모델 추출 상태와 최종 출처 분리 방안을 제안하며 추가 필드는 아직 구현하지 않았다.
- 전체 70개 테스트 통과, dist_v1.0.0.4/PhotoOrganizer.exe 빌드 성공. Windows FileVersion/ProductVersion=1.0.0.4, Comments 수정날짜=2026-10-10 확인. 제목 날짜 검증은 오프스크린 UI 테스트로 수행했으며 새 exe 실제 GUI 수동 조작은 미실시다.

### 2026-10-10 - 1.0.1 버전/날짜 및 UNKNOWN 안내

- 화면 Source 202405_test의 20240501_125303.mp4를 읽기 전용으로 확인했다. 생성 시각 KST 12:53:19 정상, ffprobe format/video/audio 모델 태그 없음.
- 같은 폴더 사진 60개를 확인했다. 가장 가까운 모델 사진은 20240501_130232.jpg(EXIF 13:02:32, SM-F926N)로 553초(9분13초) 차이, ±5분 후보는 없어 UNKNOWN이 정상이다.
- 전체 70개 테스트 통과. 제목 버전/날짜 및 pyproject 버전 일치, 사진 후보 없음/시간 없음/범위 밖/모델 충돌 안내 검증을 포함한다.
- 실제 Source 전체를 읽기 전용 미리보기하여 선택 영상 일시 12:53:19, UNKNOWN 및 `±5분 이내 사진 없음; 가장 가까운 사진과 553초 차이` 안내를 확인했다.
- dist_v1.0.1/PhotoOrganizer.exe 빌드 성공. Windows FileVersion/ProductVersion=1.0.1, Comments 수정날짜=2026-10-10 확인. 내장 패키지 버전/날짜도 같은 값임을 확인했다.
- 독립 검토 및 소스 UI 테스트를 수행했다. 새 배포 exe의 실제 GUI 수동 조작 검증은 아직 별도 진행 대상이다. Python 환경은 기존 .venv 3.13.14이며 3.12 검증은 수행하지 않았다.

### 2026-10-10 - 영상 메타데이터 오류 원인과 보강 검증

- 기존 dist/PhotoOrganizer.exe 내 PYZ의 영상 추출 호출은 capture_output/text/check만 사용하고 UTF-8 encoding 지정이 없음을 확인했다.
- 같은 호출을 실제 20240501_125303.mp4에 적용하면 CP949 UnicodeDecodeError가 subprocess readerthread에서 발생하고 stdout=None이 반환됨을 재현했다.
- 수정 후 실제 MP4 3개(123610/125303/130225)를 읽어 경고 없이 일시/해상도/코덱을 추출했다. 모델 태그는 없으므로 직접 모델명은 None이며 사진 추론 대상이다. 원본을 변경하지 않았다.
- 초기 추가 회귀 테스트 실패를 확인한 뒤 수정했다. 최종 메타데이터 12개 포함 전체 66개 테스트가 통과했다. UTF-8 한글 보존, 빈/잘못된 JSON, 별칭/대소문자, 스트림 모델, MediaInfo 보조 추출, stderr, timeout, unknown 설명 문자열 거절을 검증했다.
- 독립 검토에서 완료를 막는 결함은 발견되지 않았으며, unknown 설명 문자열 수용 가능성 지적은 회귀 테스트 추가 후 보수적으로 거절하도록 수정했다.
- 소스 MainWindow 오프스크린 생성 성공. PyInstaller로 dist_video_metadata/PhotoOrganizer.exe 빌드 성공, 내장 PYZ에 바이트 디코딩/timeout/모델 헬퍼 포함 확인. 새 exe의 실제 GUI 미리보기는 아직 수행하지 않았다.
- 전체 테스트 최초 실행은 기존 .tmp_test 권한 제한으로 실패했고, 승인된 샌드박스 외부 재실행에서 모두 통과했다.
- 사용 환경은 프로젝트 .venv Python 3.13.14다. 목표 Python 3.12에서의 검증은 이번에 수행하지 않았다.

## 목적

PhotoOrganizer 작업의 검증 기준과 실제 검증 결과를 기록한다.

## 현재 검증 기준

- 요구사항이 문서 또는 코드에 반영되어야 한다.
- 파일 정리 경로 규칙이 명확해야 한다.
- 파일명 생성 규칙이 문서로 고정되어야 한다.
- 메타데이터 사용과 fallback 사용 기준이 분리되어야 한다.
- 사진과 영상 파일의 처리 기준이 구분되어야 한다.
- V1 포함 기능과 제외 기능이 문서에 명확히 구분되어야 한다.
- 기본 파일 처리 정책과 충돌 처리 정책이 문서에 명확히 정의되어야 한다.
- 서브에이전트 병렬 활용 및 재사용 원칙이 운영 문서에 반영되어야 한다.
- 파일 일시 추출 우선순위가 문서에 명확히 정의되어야 한다.
- 파일 시스템 시간을 촬영 일시 기준으로 사용하지 않는 정책이 문서에 반영되어야 한다.
- 설정 저장 형식, 로그 위치/보관 정책, 메타데이터 라이브러리, fallback 패턴 우선순위가 문서에 반영되어야 한다.
- 미리보기 범위, 오류 처리 방식, 삭제 리뷰 방식이 문서에 반영되어야 한다.
- 동일 파일명 충돌 시 확장자, 용량, 실제 추출 메타데이터가 모두 같은 경우에만 덮어쓰기를 허용하는 정책이 코드와 문서에 반영되어야 한다.
- 미리보기에는 신규 생성/덮어쓰기/SEQ 증가 처리 방식이 표시되어야 한다.
- 상단 `디바이스명(선택)` 입력값이 있으면 메타데이터/파일명 대신 그 값이 모델명으로 우선 적용되어야 한다.
- 저장된 `디바이스명(선택)` 값이 있으면 override 활성 상태가 입력칸 아래 안내 문구로 즉시 보여야 한다.
- 같은 날짜 디렉토리 아래에 `YYYYMMDD_모델명` 디렉토리가 생성되어야 한다.
- SEQ는 같은 모델명 디렉토리 안에서 `0001`부터 증가해야 한다.
- 같은 모델명 디렉토리 안의 SEQ는 `datetime` 오름차순 기준으로 부여되어야 한다.
- 디바이스명/모델명은 파일명 안전 문자만 정리하고 대소문자는 보존되어야 한다.
- 공백, 밑줄, 하이픈 차이만 있는 모델명 표기는 같은 canonical key로 묶여 같은 모델 디렉토리와 SEQ 흐름을 공유해야 한다.
- 영상 메타 시각에 timezone 정보가 있으면 로컬 시간대로 변환된 값으로 사진/동영상 통합 정렬과 SEQ 부여가 이뤄져야 한다.
- `IMG_YYYYMMDDHHMMSSmmm` 형식 파일명도 `HHMMSS`를 fallback으로 읽어야 한다.
- 미리보기 직후 같은 입력값으로 실행하면 실제 대상 경로가 미리보기와 일치해야 한다.
- 미리보기/실행 결과/오류/삭제 리뷰 표의 헤더는 모두 마우스로 폭 조절이 가능해야 한다.
- 표 셀 텍스트는 줄임표(`...`)로 생략하지 않고 가로 스크롤로 전체 문자열을 확인할 수 있어야 한다.
- 하단 상세 영역은 좌우 분할로 구성되어 왼쪽에 선택한 사진의 축소 이미지 미리보기, 오른쪽에 텍스트 상세를 유지해야 한다.
- 하단 상세 영역 오른쪽은 `선택 항목 정보`와 `메타정보` 2단 구조여야 한다.
- 미리보기에서 선택한 파일의 메타정보가 `항목 | 값` 형태로 표시되어야 한다.
- 실행 결과 탭에서는 `원본`/`대상` 클릭에 따라 상세 패널 기준 파일이 바뀌어야 한다.
- 실행 결과 탭에는 모바일 출력 상태/경로가 표시되어야 하고, `모바일 출력 경로` 클릭 시 output 파일 기준 상세가 보여야 한다.
- 비사진은 placeholder로 표시하고, 영상은 `ffmpeg`가 있을 때 썸네일을 표시해야 한다.
- Windows CP949 환경에서도 `ffprobe` 호출이 `UnicodeDecodeError` 없이 동작해야 한다.
- 기존 `dist\PhotoOrganizer.exe`가 잠겨 있을 때 대체 출력 경로 빌드 절차가 문서화되어 있어야 한다.
- 영상 fallback 모델명 추출 규칙과 `UNKNOWN` 처리 기준이 문서에 반영되어야 한다.
- `1.1` 모바일 출력 경로가 `.../YYYYMMDD_MODEL/output_YYYYMMDD_MODEL` 구조로 생성되어야 한다.
- 모바일 출력 기본 설정값이 `사용`, 최대 가로 `3000`, 품질 `75`로 저장/복원되어야 한다.
- 모바일 출력 대상 포맷 `JPG/JPEG/PNG/HEIC`가 문서와 코드에 반영되어야 한다.
- 동영상 모바일 출력 기본 설정값이 최대 가로 `1280`, 품질 `balanced`, 원본보다 작을 때만 저장으로 저장/복원되어야 한다.
- 동영상 모바일 출력 경로는 `output_*` 아래 `.mp4`로 계산되어야 한다.
- 원본 가로가 기준보다 작으면 원본 크기를 유지하는 규칙이 반영되어야 한다.
- 모바일 출력 실패 시 전체 실행 실패로 처리하는 규칙이 반영되어야 한다.
- 모바일 출력 `JPG/JPEG`는 EXIF와 ICC를 보존해야 한다.
- 모바일 출력 `PNG`는 PNG 텍스트 메타데이터와 ICC, 가능한 경우 EXIF를 보존해야 한다.
- 모바일 출력 `HEIC`는 현재 `JPG`로 저장하되, 디코더가 제공한 EXIF/ICC가 있으면 보존해야 한다.
- 정리된 파일명 `YYYYMMDD_HHMMSS_MODEL_SEQ4`를 다시 읽을 때 `SEQ4`를 모델명으로 오인하지 않아야 한다.
- 일반 출력 파일의 확장자 대소문자가 소스 파일과 동일하게 유지되어야 한다.
- 영상 파일 선택 시 `ffmpeg`가 있으면 썸네일 프레임이 표시되고, 없으면 placeholder가 유지되어야 한다.
- 메인 화면 버튼 줄 오른쪽에 `환경설정` 버튼과 모바일 출력 요약 상태가 표시되어야 한다.
- 하단 상세 영역에서 모바일 출력 예정 경로를 확인할 수 있어야 한다.
- 작업 완료 시 README.md와 운영 문서가 최신 상태여야 한다.
- 작업 시작 시 남은 작업 확인과 전체 리스트업 방식이 문서에 반영되어야 한다.
- 계획 서브에이전트, 작업 서브에이전트, 검증 서브에이전트, 진행상황 서브에이전트의 역할 분리가 문서에 반영되어야 한다.
- README.md에는 운영 세부를 길게 쓰지 않고 핵심 요약만 남기도록 반영되어야 한다.
- 사용자 확인이 꼭 필요한 경우가 아니면, 문서 기준을 따라 자율적으로 진행하는 원칙이 반영되어야 한다.

## 검증 로그

### 2026-05-04 - 영상 메타 timezone 로컬 변환 반영

- 대상: `src/photo_organizer/metadata.py`, `tests/test_metadata.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 통과
- 확인 내용:
  - timezone 포함 `creation_time`은 로컬 시간대로 변환한 뒤 naive datetime으로 저장하도록 반영함
  - UTC 기준 영상 메타 시각이 사진 EXIF 현지 시각과 같은 축으로 정렬되도록 회귀 테스트를 추가함
  - `.venv\Scripts\python.exe -m unittest tests.test_metadata tests.test_fallback tests.test_engine` 38개 통과 확인
  - `.venv\Scripts\python.exe -m py_compile src\photo_organizer\metadata.py tests\test_metadata.py src\photo_organizer\fallback.py src\photo_organizer\engine.py tests\test_fallback.py tests\test_engine.py` 통과
- 비고:
  - 테스트 출력의 `File format not recognized.` 문구는 기존 텍스트 샘플을 이미지 라이브러리가 열어보는 과정의 경고이며, 테스트 자체는 통과했다

### 2026-05-04 - 모델명 canonical key 그룹핑 반영

- 대상: `src/photo_organizer/fallback.py`, `src/photo_organizer/engine.py`, `tests/test_fallback.py`, `tests/test_engine.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 통과
- 확인 내용:
  - 공백, 밑줄, 하이픈 차이만 있는 모델명 표기를 같은 canonical key로 비교하도록 반영함
  - 같은 canonical key인 사진/동영상은 같은 모델 디렉토리와 같은 SEQ 흐름을 공유하도록 반영함
  - 대표 표기는 `사용자 입력 > 사진 메타 > 영상 메타 > 파일명 fallback` 우선순위로 선택하도록 반영함
  - `.venv\Scripts\python.exe -m unittest tests.test_fallback tests.test_engine` 35개 통과 확인
  - `.venv\Scripts\python.exe -m py_compile src\photo_organizer\fallback.py src\photo_organizer\engine.py tests\test_fallback.py tests\test_engine.py` 통과
- 비고:
  - 테스트 출력의 `File format not recognized.` 문구는 기존 샘플 텍스트 파일을 확장자 기준으로 열어보는 테스트에서 발생한 라이브러리 경고이며, 테스트 자체는 통과했다

### 2026-05-04 - 디바이스명 override 상태 표시 보강

- 대상: `src/photo_organizer/ui/main_window.py`, `tests/test_ui_main_window.py`, `config.toml`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 통과
- 확인 내용:
  - 저장된 `device_name_override`가 있으면 입력칸 아래에 override 활성 안내 문구가 표시되도록 반영함
  - 입력값을 지우면 안내 문구가 자동 추출 상태로 즉시 전환되도록 반영함
  - 현재 작업 환경 `config.toml`의 `device_name_override`를 비워 `kidsnote` 고정 상태를 해제함
  - `.venv\Scripts\python.exe -m unittest tests.test_ui_main_window` 10개 통과 확인
  - `.venv\Scripts\python.exe -m py_compile src\photo_organizer\ui\main_window.py tests\test_ui_main_window.py` 통과
- 비고:
  - 모델명 우선순위 정책 자체는 유지하고, override 활성 상태 가시성만 보강했다

### 2026-04-21 - 현재 최신 검증 요약

- 대상: 사용자 환경 `.venv`, 모바일 출력 메타 보존/fallback 보정
- 결과: 통과
- 확인 내용:
  - 현재 확인 환경 기준 `python -m unittest discover -s tests` 41개 통과, 6개 skip
  - 모바일 출력 JPG EXIF 재추출 시 핵심 태그 유지 확인
  - 모바일 출력 PNG 텍스트 메타데이터 유지 확인
  - `MODEL_SEQ4` fallback 오인 보정 확인
  - 미리보기 상세 메타정보 2단 표시와 메타 요약 전달이 반영됨
- 비고:
  - 현재 남은 핵심 검증은 HEIC 실제 샘플 저장 확인과 GUI 실제 화면 재확인이다

### 2026-04-18 - 일반 출력 확장자 대소문자 보존 반영

- 대상: `src/photo_organizer/metadata.py`, `src/photo_organizer/engine.py`, `tests/test_engine.py`, `tests/test_metadata.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`, `docs/HANDOFF.md`
- 결과: 통과
- 확인 내용:
  - 메타데이터 추출 시 원본 확장자 문자열을 그대로 보존하도록 반영
  - 일반 출력 파일명 생성 시 강제 대문자 변환 제거
  - 소문자/대문자/혼합 대소문자 확장자 보존 테스트 추가
  - `python -m unittest discover -s tests` 35개 통과, 4개 skip 확인
  - `python -m py_compile src\photo_organizer\metadata.py src\photo_organizer\engine.py tests\test_engine.py tests\test_metadata.py` 통과
- 비고:
  - 모바일 출력 `HEIC -> JPG`는 변환 출력이므로 `.heic -> .jpg`, `.HEIC -> .JPG`처럼 소스 케이스 패턴을 따르도록 유지한다

### 2026-04-20 - 버전 표기 `1.0.0.3` 반영

- 대상: `pyproject.toml`, `src/photo_organizer/__init__.py`, `src/photo_organizer/ui/main_window.py`, `README.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/HANDOFF.md`
- 결과: 반영
- 확인 내용:
  - 사용자 표시 버전을 `1.0.0.3`로 조정
  - 창 제목은 기존 `__version__` 기반이라 별도 코드 변경 없이 `PhotoOrganizer 1.0.0.3`로 표시됨
  - 사용자 문서와 운영 문서의 기준 버전을 `1.0.0.3`로 정리함

### 2026-04-21 - 미리보기 상세 메타정보 표시 반영

- 대상: `src/photo_organizer/models.py`, `src/photo_organizer/metadata.py`, `src/photo_organizer/engine.py`, `src/photo_organizer/ui/main_window.py`, `tests/test_engine.py`, `tests/test_ui_main_window.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`, `docs/HANDOFF.md`
- 결과: 통과
- 확인 내용:
  - `PreviewItem`에 표시용 메타 요약을 추가함
  - 사진/영상 공통 메타와 포맷별 핵심 메타를 미리보기용으로 정리함
  - 하단 상세 영역 오른쪽을 `선택 항목 정보` + `메타정보` 2단 구조로 변경함
  - 메타정보는 `항목 | 값` 2열 표로 표시하고, 선택이 없으면 `메타정보 없음`을 표시함
  - `python -m unittest tests.test_engine tests.test_ui_main_window` 30개 통과 확인
  - `py_compile`로 관련 파일 문법 확인
- 비고:
  - 실제 HEIC 샘플과 실제 GUI 수동 검증은 별도 남아 있다

### 2026-04-20 - 영상 썸네일 미리보기 반영

- 대상: `src/photo_organizer/ui/main_window.py`, `src/photo_organizer/video_thumbnail.py`, `tests/test_ui_main_window.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`, `docs/HANDOFF.md`
- 결과: 통과
- 확인 내용:
  - 영상 파일 선택 시 `ffmpeg` 기반 썸네일 추출 경로를 추가함
  - `ffmpeg`가 없거나 썸네일 추출에 실패하면 기존 placeholder를 유지하도록 방어함
  - 썸네일 추출 helper 테스트와 UI 연결 테스트를 추가함
  - `python -m unittest discover -s tests` 41개 통과, 6개 skip 확인
  - `python -m py_compile src\photo_organizer\video_thumbnail.py src\photo_organizer\ui\main_window.py tests\test_ui_main_window.py` 통과
- 비고:
  - skip 2개는 PySide6가 없는 환경에서 UI 레벨 테스트를 건너뛴 경우다
  - 실제 영상 파일 썸네일 렌더링 수동 검증은 `ffmpeg` 설치 환경에서 추가 확인이 필요하다

### 2026-04-14 - 초기 문서 세트 생성

- 대상: `AGENT.md`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 통과
- 확인 내용:
  - 운영 기준 문서 존재
  - 프로젝트 개요 문서 존재
  - 작업 목록 문서 존재
  - 계획 문서 존재
  - 결정 기록 문서 존재
  - 검증 기록 문서 존재
- 비고: 아직 구현 전 단계이므로 기능 테스트는 수행하지 않음

### 2026-04-14 - 기술 스택 문서 반영

- 대상: `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`
- 결과: 통과
- 확인 내용:
  - Python 3.12 기준 반영
  - PySide6 기준 반영
  - PyInstaller 기준 반영
  - 메타데이터 라이브러리 후보 반영
  - 설정 저장 방식 후보 반영
- 비고: 구현 라이브러리 최종 선택은 이후 결정 기록에서 확정 예정

### 2026-04-14 - V1 기능 범위 문서 반영

- 대상: `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 통과
- 확인 내용:
  - V1 포함 기능 반영
  - V1 제외 기능 반영
  - 사진 메타정보 부재 시 파일명 fallback 반영
  - 영상 메타정보 우선 및 부재 시 fallback 반영
  - 미리보기와 실행 로그 요구사항 반영
- 비고: 영상 지원 확장자와 메타데이터 처리 라이브러리는 후속 결정 필요

### 2026-04-14 - 기본 파일 처리 정책 반영

- 대상: `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`, `.codex/config.toml`
- 결과: 통과
- 확인 내용:
  - 기본 파일 처리 방식이 복사로 반영됨
  - 이동이 선택 옵션으로 반영됨
  - 덮어쓰기 금지 및 충돌 시 SEQ 증가 정책 반영됨
  - 삭제는 사용자 리뷰 후 수행 정책이 반영됨
- 비고: 실제 삭제 UI와 절차는 구현 단계에서 구체화 필요

### 2026-04-14 - 서브에이전트 효율 우선 원칙 반영

- 대상: `AGENT.md`, `README.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 통과
- 확인 내용:
  - 병렬 처리 가능 시 서브에이전트 활용 원칙 반영됨
  - 새 서브에이전트 생성과 기존 에이전트 재사용 중 효율 우선 선택 원칙 반영됨
  - 메인 에이전트가 전체 효율 기준으로 조율한다는 기준 반영됨
- 비고: 실제 작업 시 에이전트 수는 작업 규모와 병목 여부를 기준으로 조정

### 2026-04-14 - 파일 일시 추출 우선순위 반영

- 대상: `AGENT.md`, `README.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`, `.codex/config.toml`
- 결과: 통과
- 확인 내용:
  - 사진 일시 추출 우선순위 반영됨
  - 영상 일시 추출 우선순위 반영됨
  - 파일 시스템 시간을 촬영 일시 기준으로 사용하지 않음이 반영됨
- 비고: 촬영 일시를 얻지 못하면 파일명 규칙 미인식 또는 메타데이터 부재 오류로 분류할 수 있음

### 2026-04-14 - 세부 운영 기준 반영

- 대상: `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`, `.codex/config.toml`
- 결과: 통과
- 확인 내용:
  - 설정 저장 형식 JSON 반영됨
  - 로그 위치와 30일 보관 정책 반영됨
  - 영상 메타데이터 라이브러리 `ffprobe`, `pymediainfo` 반영됨
  - 사진 메타데이터 라이브러리 `exifread` 우선 검토, `Pillow + piexif` 비교 반영됨
  - 파일명 fallback 패턴 우선순위 반영됨
  - 미리보기 범위, 오류 파일 처리, 삭제 리뷰 방식 반영됨
- 비고: 지원 영상 확장자의 최종 상세 목록은 구현 단계에서 문서에 추가 확정 가능

### 2026-04-14 - 영상 확장자 및 메타데이터 우선순위 확정

- 대상: `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `.codex/config.toml`
- 결과: 통과
- 확인 내용:
  - 지원 영상 확장자 `MP4`, `MOV`, `M4V`, `AVI`, `MKV`, `WMV` 반영됨
  - 사진 메타데이터 `exifread` 우선 검토, `Pillow + piexif` 비교 반영됨
  - 영상 메타데이터 `ffprobe` 우선, `pymediainfo` 보조 반영됨
- 비고: 실제 라이브러리 통합 방식은 구현 단계에서 어댑터 구조로 구체화 가능

### 2026-04-14 - 영상 fallback 모델명 추출 규칙 반영

- 대상: `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`, `.codex/config.toml`
- 결과: 통과
- 확인 내용:
  - 같은 디렉토리 사진 기준 모델명 추론 규칙 반영됨
  - `±5분` 조건 반영됨
  - 가장 가까운 사진 우선 사용 규칙 반영됨
  - 후보 없음 또는 충돌 시 `UNKNOWN` 처리 반영됨
- 비고: 구현 시 미리보기와 로그에 추론 근거 표시를 함께 연결

### 2026-04-14 - V1 기본 구현 반영

- 대상: `pyproject.toml`, `main.py`, `PhotoOrganizer.spec`, `src/photo_organizer/*`, `tests/*`, `README.md`, `TASKS.md`, `docs/PLAN.md`
- 결과: 부분 통과
- 확인 내용:
  - 코어 정리 엔진 구현
  - 사진/영상 메타데이터 추출기 구현
  - 파일명 fallback 규칙 구현
  - 영상 fallback 모델명 추론 규칙 구현
  - 대상 디렉토리/파일명/SEQ 처리 구현
  - PySide6 UI 기본 흐름 구현
  - 설정 저장, 로그 저장, 삭제 리뷰 기본 흐름 구현
  - 대표 테스트 파일 작성
- 비고: 현재 작업 환경에서는 Python 실행 파일이 PATH에 없어 실제 테스트 실행과 GUI 실행 검증은 수행하지 못함

### 2026-04-14 - 가상환경 기반 테스트 검증

- 대상: `.venv`, `tests/test_fallback.py`, `tests/test_engine.py`
- 결과: 부분 통과
- 확인 내용:
  - `.venv` 가상환경 생성됨
  - `.venv` 내부 Python 실행 가능
  - `unittest discover -s tests` 기준 7개 테스트 통과
- 비고:
  - 초기 확인 당시 `.venv` 인터프리터 버전은 Python `3.11.11` 이었음
  - 이후 사용자 환경에서 Python `3.13.12` 기반 `.venv` 재구성 및 의존성 설치 완료

### 2026-04-14 - 의존성 설치 시도

- 대상: `.venv`, `requirements.txt`, `scripts/bootstrap_venv.ps1`
- 결과: 부분 통과
- 확인 내용:
  - Blender 내장 `pip` wheel 직접 실행 가능 확인
  - 외부 패키지 설치 명령 시도
  - `requirements.txt` 준비
  - 가상환경 부트스트랩 스크립트 준비
- 비고:
  - 현재 환경에서는 네트워크 제한으로 `pip install` 실패
  - 오류 기준: `WinError 10051`

### 2026-04-14 - 사용자 환경 가상환경 재구성 확인

- 대상: `.venv`, `pip list`, `unittest discover -s tests`
- 결과: 통과
- 확인 내용:
  - `.venv\Scripts\python.exe` 기준 Python `3.13.12` 확인
  - `PySide6`, `ExifRead`, `Pillow`, `piexif`, `pymediainfo`, `Send2Trash` 설치 확인
  - 기본 테스트 8개 통과 확인
- 비고:
  - GUI 실제 실행과 PyInstaller 빌드 검증은 후속 확인 필요

### 2026-04-14 - 검증 스크립트 실행 결과

- 대상: `scripts/run_validation.ps1`
- 결과: 부분 통과
- 확인 내용:
  - Python `3.13.12` 확인
  - 필수 런타임 패키지 설치 확인
  - 기본 테스트 8개 통과
  - 오프스크린 GUI 스모크에서 `MainWindow` 생성 확인
  - PyInstaller 빌드 성공
- 비고:
  - Qt 폰트 디렉토리 경고는 있었으나 스모크 테스트 자체는 성공
  - 실제 GUI 상호작용과 샘플 파일 검증은 후속 확인 필요

### 2026-04-14 - 설정 저장 파일 TOML 전환

- 대상: `src/photo_organizer/config.py`, `src/photo_organizer/ui/main_window.py`, `tests/test_config.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`
- 결과: 통과
- 확인 내용:
  - 설정 저장 파일이 `config.toml`로 전환됨
  - 프로그램 시작 시 저장값을 불러와 입력값에 반영하는 구조 유지
  - 경로 선택, 처리 모드 변경, 창 종료 시 설정 저장 구조 반영
  - TOML 저장/로드 테스트 추가
- 비고:
  - 테스트 통과 개수는 8개 기준으로 관리

### 2026-04-15 - 미리보기 대상 경로 표시 보강

- 대상: `src/photo_organizer/ui/main_window.py`, `README.md`
- 결과: 반영
- 확인 내용:
  - 미리보기 표의 경로 컬럼을 더 넓게 조정함
  - 각 셀에 전체 텍스트 툴팁을 추가함
  - 선택한 미리보기 행의 전체 대상 경로를 표 아래 상세 영역에 표시하도록 반영함
- 비고:
  - 현재 작업 환경에서는 GUI 수동 확인을 다시 수행하지 못했으며 코드 기준으로 반영 상태를 검토함

### 2026-04-15 - 진행상황 표시 보강

- 대상: `src/photo_organizer/engine.py`, `src/photo_organizer/ui/main_window.py`, `tests/test_engine.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`
- 결과: 반영
- 확인 내용:
  - 엔진이 미리보기와 실행 과정에서 단계명과 처리 건수를 진행 콜백으로 전달하도록 반영함
  - UI에 진행 바를 추가하고 상태 문구에 현재 단계와 건수를 표시하도록 반영함
  - 작업 중 주요 버튼을 비활성화해 중복 실행을 줄이도록 반영함
  - 엔진 진행 콜백 기본 동작을 검증하는 테스트를 추가함
- 비고:
  - 현재 작업 환경에서는 깨진 `.venv`로 인해 테스트 재실행을 수행하지 못했으며 코드 기준으로 검토함

### 2026-04-15 - 협업 운영 표준화 문서 반영

- 대상: `README.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 통과
- 확인 내용:
  - 메인 에이전트 조율, 계획/작업/검증/진행상황 역할 분리 원칙을 문서에 반영함
  - 작업 시작 시 남은 작업 확인과 전체 리스트업 원칙을 문서에 반영함
  - README에는 운영 세부 대신 핵심 요약만 남기도록 정리함
  - 운영 표준화 결정을 `docs/DECISIONS.md`에 기록함
- 비고:
  - 이번 작업은 문서 현행화 범위에 한정했으며 코드 변경은 수행하지 않음

### 2026-04-15 - 테이블 경로 가시성 및 헤더 폭 조절 보강

- 대상: `src/photo_organizer/ui/main_window.py`, `README.md`
- 결과: 반영
- 확인 내용:
  - 미리보기, 실행 결과, 오류, 삭제 리뷰 테이블의 헤더 폭을 마우스로 직접 조절할 수 있도록 반영함
  - 각 테이블에 가로 스크롤과 수동 컬럼 폭 조절 기본값을 적용함
  - 선택한 행의 전체 원본 경로, 대상 경로, 오류 경로, 삭제 대상 경로와 세부 내용을 공통 상세 영역에 표시하도록 반영함
  - 셀 툴팁을 유지해 마우스 오버로도 전체 텍스트를 확인할 수 있도록 유지함
- 비고:
  - 현재 작업 환경에서는 GUI 수동 실행과 자동 테스트를 다시 수행하지 못했으며 코드 기준으로 반영 상태를 검토함

### 2026-04-16 - 미리보기 처리 방식 표시 및 그리드 리사이즈 정책 보강

- 대상: `src/photo_organizer/ui/main_window.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`
- 결과: 반영
- 확인 내용:
  - 미리보기 표에 처리 방식 컬럼을 추가해 `신규 생성`, `덮어쓰기`, `SEQ 증가` 예상 값을 표시하도록 반영함
  - 미리보기 상세 영역에도 처리 방식이 함께 보이도록 반영함
  - 미리보기, 실행 결과, 오류, 삭제 리뷰 표가 공통 리사이즈 정책을 유지하도록 정리함
- 비고:
  - 현재 작업 환경에서는 GUI 수동 실행과 자동 테스트를 다시 수행하지 못했으며 코드 기준으로 반영 상태를 검토함

### 2026-04-16 - 동일 파일명 조건부 덮어쓰기 반영

- 대상: `src/photo_organizer/models.py`, `src/photo_organizer/metadata.py`, `src/photo_organizer/engine.py`, `src/photo_organizer/ui/main_window.py`, `tests/test_engine.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 반영
- 확인 내용:
  - 실제 메타데이터 스냅샷을 추출해 충돌 비교 기준으로 사용할 수 있도록 반영함
  - 동일 파일명 충돌 시 확장자, 용량, 실제 추출 메타데이터가 모두 같은 경우 `OVERWRITE`로 판정하도록 반영함
  - 위 조건이 맞지 않는 충돌은 기존처럼 `SEQ` 증가로 처리하도록 유지함
  - 미리보기와 실행 결과에서 처리 방식 정보를 함께 다룰 수 있도록 모델과 엔진을 확장함
  - 관련 정책과 사용자 안내 문서를 조건부 덮어쓰기 기준으로 현행화함
- 비고:
  - 현재 작업 환경에서는 깨진 `.venv`로 인해 테스트와 GUI 수동 실행을 다시 수행하지 못했으며 코드 기준으로 검토함

### 2026-04-16 - 하단 이미지 미리보기 패널 반영

- 대상: `src/photo_organizer/ui/main_window.py`, `README.md`, `docs/VALIDATION.md`
- 결과: 반영
- 확인 내용:
  - 하단 상세 영역을 좌우 분할로 바꾸어 왼쪽에 원본 파일 이미지 미리보기를 배치함
  - 선택된 사진 파일은 축소 로드해서 보여주고, 비사진/영상은 미리보기 불가 placeholder로 표시하도록 반영함
  - 오른쪽 텍스트 상세와 전체 경로 가시성은 유지하도록 반영함
- 비고:
  - 현재 작업 환경에서는 GUI 수동 실행을 다시 수행하지 못했으며 코드 기준으로 반영 상태를 검토함

### 2026-04-16 - ffprobe 디코딩 오류 수정

- 대상: `src/photo_organizer/metadata.py`, `tests/test_metadata.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 반영
- 확인 내용:
  - `ffprobe` subprocess 출력이 UTF-8 및 `errors=\"replace\"` 기준으로 디코딩되도록 반영함
  - Windows CP949 환경에서 발생하던 `UnicodeDecodeError` 재발 방지를 위한 회귀 테스트를 추가함
  - 사용자 문서와 결정 기록에 런타임 인코딩 정책을 반영함
- 비고:
  - 현재 작업 환경에서는 사용자 `.venv`를 직접 실행하지 못해 자동 테스트는 대체 인터프리터 기준으로 확인 예정

### 2026-04-16 - 잠긴 exe 우회 빌드 스크립트 추가

- 대상: `scripts/build_release.ps1`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 반영
- 확인 내용:
  - 기존 `dist\PhotoOrganizer.exe`가 잠겨 있어도 별도 출력 경로로 PyInstaller 빌드를 수행할 수 있도록 스크립트를 추가함
  - 기본 출력 경로를 `dist_release\PhotoOrganizer.exe`로 안내하도록 사용자 문서를 보강함
  - 배포 절차 결정과 검증 기준에 우회 빌드 방식을 반영함
- 비고:
  - 실제 사용자 환경에서는 `.\scripts\build_release.ps1` 실행으로 최종 확인 필요

### 2026-04-16 - 디바이스명 수동 입력 우선 적용

- 대상: `src/photo_organizer/models.py`, `src/photo_organizer/config.py`, `src/photo_organizer/engine.py`, `src/photo_organizer/ui/main_window.py`, `tests/test_config.py`, `tests/test_engine.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 반영
- 확인 내용:
  - 상단 설정 영역에 `디바이스명(선택)` 입력을 추가해 `Target 경로`와 `처리 모드` 사이에서 입력할 수 있도록 반영함
  - 입력값은 `config.toml`에 저장되고 다음 실행 시 다시 불러오도록 반영함
  - 입력값이 있으면 메타데이터/파일명 기반 모델명 대신 사용자 입력을 우선 적용하도록 엔진을 반영함
  - 미리보기에서 파일명과 모델명 근거가 사용자 입력 기준으로 바뀌는 회귀 테스트를 추가함
- 비고:
  - 모델명은 기존 규칙과 동일하게 sanitize 처리되어 파일명에 안전한 형식으로 반영됨

### 2026-04-17 - 날짜/모델명 디렉토리 구조 반영

- 대상: `src/photo_organizer/engine.py`, `tests/test_engine.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 반영
- 확인 내용:
  - 대상 경로를 `날짜/날짜_모델명/파일` 구조로 생성하도록 반영함
  - 경로 생성 테스트를 `20161008/20161008_RX100M3` 구조 기준으로 보강함
  - 디바이스명 수동 입력 및 날짜별 샘플 케이스가 모델명 디렉토리 기준으로 동작하도록 테스트를 갱신함
- 비고:
  - 모델명 디렉토리가 이미 존재하면 해당 디렉토리를 재사용한다

### 2026-04-17 - 모델명 디렉토리 기준 datetime 오름차순 SEQ 반영

- 대상: `src/photo_organizer/engine.py`, `tests/test_engine.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 반영
- 확인 내용:
  - SEQ를 같은 모델명 디렉토리 안에서만 `0001`부터 부여하도록 반영함
  - 시간이 뒤섞인 입력 순서에서도 모델명 디렉토리 단위로 `datetime` 오름차순 SEQ를 유지하도록 테스트를 유지함
- 비고:
  - 같은 `captured_at`일 때는 원본 경로 문자열 오름차순으로 tie-break 한다

### 2026-04-17 - 모델명 대소문자 보존 반영

- 대상: `src/photo_organizer/fallback.py`, `tests/test_engine.py`, `tests/test_config.py`, `README.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 반영
- 확인 내용:
  - 모델명 sanitize 과정에서 강제 대문자 변환을 제거함
  - 소문자 디바이스명 입력 시 대상 디렉토리명과 파일명도 소문자 기준으로 유지되도록 테스트를 갱신함
- 비고:
  - `UNKNOWN` sentinel만 예외적으로 대문자로 유지함

### 2026-04-17 - 그리드 셀 줄임표 비활성화

- 대상: `src/photo_organizer/ui/main_window.py`, `README.md`, `docs/VALIDATION.md`
- 결과: 반영
- 확인 내용:
  - 미리보기, 실행 결과, 오류, 삭제 리뷰 테이블에서 셀 텍스트 줄임표를 비활성화함
  - 셀 그리기를 각 셀 영역 안으로 클리핑해 옆 컬럼 텍스트와 겹치지 않도록 반영함
  - 가로 스크롤과 수동 컬럼 폭 조절로 긴 대상 경로를 전체 문자열 기준으로 확인할 수 있도록 반영함
- 비고:
  - 표 아래 상세 영역과 셀 툴팁은 기존처럼 전체 경로 확인용으로 유지함

### 2026-04-17 - `1.1` 모바일 출력 정책 문서 반영

- 대상: `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/HANDOFF.md`, `docs/VALIDATION.md`
- 결과: 통과
- 확인 내용:
  - 모바일 출력 경로를 `.../YYYYMMDD_MODEL/output_YYYYMMDD_MODEL` 구조로 반영함
  - 모바일 출력 기본값 `사용`, 최대 가로 `3000`, 품질 `75`를 운영 문서에 반영함
  - 작은 원본은 원본 크기 유지, 출력 실패 시 전체 실행 실패 정책을 운영 문서에 반영함
  - `환경설정` 버튼과 메인 화면 요약 상태 방향을 운영 문서에 반영함
- 비고:
  - 아직 구현 전 단계이므로 코드 및 GUI 검증은 수행하지 않음

### 2026-04-17 - `1.1` 모바일 출력 1차 구현 반영

- 대상: `src/photo_organizer/models.py`, `src/photo_organizer/config.py`, `src/photo_organizer/engine.py`, `src/photo_organizer/ui/main_window.py`, `tests/test_config.py`, `tests/test_engine.py`, `README.md`, `config.toml.sample`
- 결과: 부분 통과
- 확인 내용:
  - 모바일 출력 설정 필드가 `config.toml` 저장/로드에 반영됨
  - 사진 미리보기 항목에 모바일 출력 경로가 계산됨
  - 모바일 출력 경로가 `.../YYYYMMDD_MODEL/output_YYYYMMDD_MODEL` 규칙을 따름
  - 당시 기준으로 영상 파일은 모바일 출력 경로를 생성하지 않았음
  - 메인 화면 버튼 줄 오른쪽에 `환경설정` 버튼과 모바일 출력 요약 상태가 반영됨
  - 하단 상세 영역에서 모바일 출력 경로와 상태를 확인할 수 있음
  - `.venv311` 기준 `unittest discover -s tests` 26개 통과, 2개 skip
- 비고:
  - skip 2개는 대체 인터프리터 `.venv311`에 `Pillow`가 없어 실제 이미지 출력 테스트를 건너뛴 경우다.
  - 실제 사용자 `.venv` 기준 모바일 출력 GUI/샘플 파일 검증은 추가 필요

### 2026-04-17 - 모바일 출력 메타데이터 보존 및 fallback 보정 반영

- 대상: `src/photo_organizer/engine.py`, `src/photo_organizer/fallback.py`, `tests/test_engine.py`, `tests/test_fallback.py`, `README.md`, `AGENT.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/HANDOFF.md`
- 결과: 통과
- 확인 내용:
  - 모바일 출력 `JPG/JPEG` 저장 시 원본 EXIF와 ICC 프로파일이 함께 저장되도록 반영함
  - 모바일 출력 `PNG` 저장 시 PNG 텍스트 메타데이터와 ICC 프로파일, 가능한 경우 EXIF가 유지되도록 반영함
  - 모바일 출력 `HEIC`는 `JPG`로 저장되고, 디코더가 노출한 EXIF/ICC가 있으면 함께 저장되도록 반영함
  - 정리된 파일명 `YYYYMMDD_HHMMSS_MODEL_SEQ4`를 다시 읽을 때 마지막 `SEQ4`를 모델명으로 오인하지 않도록 반영함
  - 사용자 환경 `.venv` 기준 `python -m unittest discover -s tests` 31개 통과, 4개 skip 확인
  - 샘플 기준 모바일 출력 JPG EXIF 재추출 시 `DateTimeOriginal`, `Model` 등 핵심 태그가 유지되는 것을 확인함
- 비고:
  - EXIF blob 내부 오프셋 값은 다시 저장 과정에서 달라질 수 있으므로 바이트 단위 완전 동일성 대신 핵심 태그 유지 여부로 검증함
  - HEIC 메타 보존은 Pillow/코덱이 노출한 메타데이터 범위에 의존한다

### 2026-05-04 - 동영상 모바일 출력 경로 및 설정 반영

- 대상: `src/photo_organizer/models.py`, `src/photo_organizer/config.py`, `src/photo_organizer/engine.py`, `src/photo_organizer/video_output.py`, `src/photo_organizer/ui/main_window.py`, `tests/test_config.py`, `tests/test_engine.py`, `tests/test_ui_main_window.py`, `tests/test_video_output.py`
- 결과: 통과
- 확인 내용:
  - 동영상도 미리보기 시 `output_YYYYMMDD_MODEL/*.mp4` 경로가 계산됨
  - 동영상 모바일 출력 기본 설정값 `1280 / balanced / only_if_smaller=true`가 저장/복원됨
  - 동영상 모바일 출력은 `ffmpeg` 기반 `MP4(H.264/AAC)` 프로필을 사용함
  - 결과 탭에서 동영상 모바일 출력 상태 `SUCCESS/SKIPPED/ERROR`를 구분해 표시함
- 검증 메모:
  - `python -m unittest tests.test_config tests.test_engine tests.test_ui_main_window tests.test_video_output` 통과

### 2026-04-16 - 연속형 파일명 fallback 및 미리보기-실행 일치 보강

- 대상: `src/photo_organizer/fallback.py`, `src/photo_organizer/engine.py`, `src/photo_organizer/ui/main_window.py`, `tests/test_fallback.py`, `tests/test_engine.py`, `README.md`, `TASKS.md`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/VALIDATION.md`
- 결과: 반영
- 확인 내용:
  - `img_20240327170722454.jpg` 같은 파일명에서 `2024-03-27 17:07:22`를 fallback으로 읽도록 반영함
  - 입력값이 바뀌지 않은 상태의 실행은 직전 미리보기 `preview_bundle`을 재사용해 실제 대상 경로와 미리보기 경로를 일치시키도록 반영함
  - 실행 결과 표에도 `처리 방식` 컬럼을 추가해 실제 처리 결과 확인성을 높임
- 비고:
  - 입력값이 바뀌었거나 미리보기를 거치지 않은 실행은 기존처럼 실행 시점에 새 미리보기를 계산함

## 2026-10-11 출력 촬영 날짜 보존 / 1.0.1.2

- 사진·영상 출력의 변환 시각 st_mtime 문제를 실패 테스트 2개로 재현한 후 수정. Windows st_birthtime/st_mtime, EXIF 촬영 시각 보존, 수동 파일명 최종 파일 날짜, SKIPPED 기존 파일 내용/날짜 불변 검증.
- 전체 unittest 162개 실행: 161통과, Windows 링크 권한 1skip. 독립 코드 검토 차단 이슈 없음. Python 3.13 검증 환경이며 Python 3.12 별도 검증은 미수행.
- PyInstaller 1.0.1.2 빌드 성공. dist_v1.0.1.2/PhotoOrganizer.exe 생성 및 Windows 버전 리소스 1.0.1.2 / 수정날짜 2026-10-11 확인. 실제 EXE GUI 수동 확인은 미수행.

## 2026-10-11 모델별 처리 선택 / 1.0.1.3

- 모델 선택 신규 코어 테스트 RED 확인 후 구현. 복사/이동 원본 보존, 빈 선택, 날짜 SEQ/reselect, 수동명 유지/충돌 해소, 기존 파일 보호, 영상 추론 유지, 포함 모바일 출력 및 CONFLICT 이후 정상 파일 진행 검증.
- 선택 체크 변경 시 기존 Target 영상 메타데이터 재조회 없는 것을 실제 동일 크기 충돌 케이스로 검증.
- 전체 unittest 186개 실행: 185통과, Windows 링크 권한 1skip. 신규 코어 15개/UI 9개 포함. 실제 엔진 UI 선택 모델 복사 및 메타데이터 재조회 없음, 좁은/넓은 폭 실제 FlowLayout 위치, 실패 상태/전체 해제/stale 보호 검증.
- 독립 검토에서 CONFLICT 후속 파일 진행, 수동명 충돌 해소 재계산, 체크 변경 Target 메타 조회 제거, 기존 모바일 출력만 남은 경로 보호를 확인. 최종 차단 이슈 없음.
- PyInstaller 최종 1.0.1.3 빌드 성공. dist_v1.0.1.3/PhotoOrganizer.exe 버전 리소스 FileVersion/ProductVersion 1.0.1.3, 수정날짜 2026-10-11 확인. 묶인 engine/models/main_window/model_selection 모듈, set_selected_models 및 처리할 모델 제목 문구 확인. 최종 제목 반영 후 전체186개 재회귀: 185통과/1skip. UI는 오프스크린 이벤트/배치 검증이며 실제 EXE GUI 수동 검증은 별도 확인 대상.

## 2026-10-11 DJI Action4 모델명 보정 / 1.0.1.4

- 원본 DJI_20240501113332_0053_D.MP4와0054_D에서 ffprobe encoder DJI OsmoAction4 확인. 수정 전 fallback 0053_D/0054_D 오인 및 신규 실패 테스트 재현.
- 원본0016_D/0017_D/0053_D/0054_D 8개 읽기 전용 MetadataExtractor 검증: 모두 DJI_OsmoAction4, 영상 메타, 직접 모델 조회 found. 원본 파일 변경 없음.
- 전체 unittest194개 실행: 193통과, 링크 권한1skip. 신규8개 테스트: DJI파일명 처리/정리 파일명 호환/verifiedencoder/명시스트림 우선/명시MediaInfo트랙 우선/대소문자공백/다른encoder 배제/metadata없는DJI 미확인.
- 실제 Source 202405 전체 읽기 전용 preview 277개/오류0: SM-F926N248개와 DJI_OsmoAction4 29개 두 모델 그룹 확인. DJI 원본29개 모두 정상모델명. execute/변환/원본수정은 수행하지 않음.
- MediaInfo 우선순위 수정 독립검토 차단 없음, metadata24개 독립통과. PyInstaller 최종1.0.1.4 빌드 성공. dist_v1.0.1.4/PhotoOrganizer.exe의 FileVersion/ProductVersion1.0.1.4, 수정날짜2026-10-11 및 묶인 DJI fallback/Action4 코드 확인. 실제 EXE GUI 수동 확인은 미수행.

## 2026-10-11 모델명 별칭 매핑 / 1.0.1.5

- 매핑 core18개/UI7개/config13개 검증. 신규 실패 테스트 후 구현, 명시적인 source/dest 분리, Unicode·정규화·중복·reserved/blank/control 거부, 다대일/체인없음/UNKNOWN 보존/실제복사/모델 선택 재계산/원본영상추론 보존 확인.
- 일반 미리보기 매핑 변경 guard, 직접 실행 snapshot, 비정규 원본 모델 기본 호환, 수동명 batch복원 atomic/충돌/동일 Source·Target 재미리보기 UI 검증. config fault injection에서 부분 쓰기와 replace 실패 모두 기존 bytes 보존/tempcleanup 확인.
- 전체 unittest226개 실행: 225통과, Windows 링크 권한1skip. 독립 최종 검토 차단 이슈 없음.
- 실제 DJI 20240501 폴더 원본5개를 두 scope로 읽기 전용 preview. 둘 모두 추출 DJI_OsmoAction4 유지/파일명 Action4 적용, 기본은 20240501_Action4/output_20240501_Action4, filename_only는 원래 DJI 폴더 유지. 원본/휴대폰 쓰기나 기존 출력 이름 변경 미수행.
- PyInstaller 최종 빌드 성공: `dist_v1.0.1.5/PhotoOrganizer.exe`. Windows FileVersion/ProductVersion `1.0.1.5`, Comments의 수정날짜 `2026-10-11` 확인. 내장 PYZ의 model_mapping/engine/config/main_window 모듈과 기본 매핑 범위 및 UI 적용 범위 문구 포함 확인. UI 자동 검증은 통과했으며 배포 EXE의 실제 화면 수동 확인은 미수행.

## 2026-10-11 모바일 복사 영상 용량 제한 / 1.0.1.6

- 설정6개/UI2개 신규 테스트 구현 전 실패 확인 후 통과. 설정 기본/엄격한 형식과 범위/저장·JSON 이전/기본값 복원/decimal byte 전달 검증.
- 영상 기준 경계·대소문자·사진 유지·중첩 폴더 정리·모든 충돌 정책 기존 영상 보존·크기 변경과 결과/로그를 모의 백엔드로 검증. 모든 영상 제외 시 휴대폰 폴더 생성 호출 없음.
- 독립 검토 차단 이슈 없음. 실제 휴대폰 파일 쓰기 및 배포 EXE 화면 수동 확인은 이번 검증에 포함하지 않음.

- 최종 회귀: unittest 244개 실행, 243통과/Windows 링크 권한1skip. 신규 core10개/settings6개/UI2개. 전송 직전 크기 증가로 뒤늦게 제외된 파일의 계획 바이트만 진행률 합계에서 차감하는 것을 검증했다. git diff --check 통과. Python 3.13.14 환경에서 검증했으며 목표 Python 3.12 별도 검증은 미수행.

- PyInstaller 빌드 완료: dist_v1.0.1.6/PhotoOrganizer.exe. FileVersion/ProductVersion1.0.1.6, 수정날짜2026-10-11 확인. 내장 PYZ의 SIZE_EXCLUDED/제외 UI/설정 저장 코드 포함 확인.

## 2026-10-11 output_ 생성 용량 제한 / 1.0.1.7

- 신규 core15개/설정UI7개: 구현 전 실패 확인 후 통과. 정확히1,000,000바이트 경계/직전/초과, 실제 JPEG 원본>1MB이지만 결과<1MB 허용, 실제 노이즈PNG 결과>1MB 제외를 검증했다.
- 영상은 실제 변환 헬퍼를 호출하고 subprocess.run만 모의하여 작은 출력 허용/경계 제외/only_if_smaller SKIPPED 우선과 임시 정리를 검증했다. 실제 ffmpeg 인코딩 실행은 이번 검증에 포함하지 않았다.
- 기존 output_ 보존, 제외 시 신규 빈 출력 폴더 없음, 수동명/이동/삭제 리뷰 유지, 다음 파일 진행 및 INFO 로그/결과 상세 이유 확인. 설정 엄격한 형식/범위/JSON 이전/기본값 복원/요청 전파/미리보기 서명 검증.
- 독립 검토 차단 없음. 별도 fault injection에서 수동 파일명 최종 경로 경합과 최종 os.replace 실패 모두 기존 파일 보존/임시 정리 확인.
- 전체 unittest266개 실행: 265통과/Windows 링크 권한1skip. Python3.13.14 환경이며 목표3.12 별도 확인은 미수행. 배포 EXE 실제 화면 수동 확인은 미수행.

- PyInstaller 1.0.1.7 빌드 성공. dist_v1.0.1.7/PhotoOrganizer.exe FileVersion/ProductVersion1.0.1.7 및 수정날짜2026-10-11 확인. 내장 엔진 SIZE_EXCLUDED/출력 제한 UI/설정 저장 코드 포함 확인. git diff --check 통과.

## 2026-10-11 동영상 품질 프로필 6단계 / 1.0.1.8

- 신규core4개/UI설정4개 실패 재현 후 통과. 모든 프로필의 실제 ffmpeg 명령 CRF/오디오/medium, 기존 키/unknown fallback, 6항목 표시/동적 설명/기본값/설정 roundtrip/화면 요약 검증.
- 전체274개 실행: 273통과/Windows 링크 권한1skip. 변경된 small 표시 명칭에 맞춰 기존 요약 테스트 기대값 갱신.
- 한국어 폰트를 지정한 오프스크린 캡처에서 드롭다운/설명/공통 안내 배치 확인. 6개 항목 문자열 너비와 화살표 여백이 드롭다운534px 안에 들어감. 캡처 quality_profiles_settings.png.
- 실제 영상 화질 비교 및 배포 EXE 화면 수동 확인은 미수행. Python3.13.14 환경이며 목표3.12 별도 확인은 미수행.

- 독립 검토 차단 없음. 신규8개 독립 통과 및 별도 잘못된 값 저장/JSON 이관 확인. PyInstaller dist_v1.0.1.8/PhotoOrganizer.exe 빌드 성공, FileVersion/ProductVersion1.0.1.8/수정날짜2026-10-11 확인. 내장 sixkeys/공통 CRF UI 안내 포함 확인. git diff --check 통과.

## 2026-10-11 작업 저장·열기 설계 검토

- 현재 모델/UI/엔진을 읽기 전용 확인. 미리보기·결과 메모리 보관, 종료 시 입력 설정만 저장 확인. 일반 copy/move 이후 모바일 오류 시 전체ERROR 및 루프 중단, 결과 없는 후속 항목 확인.
- 저장/UI/재실행 관점3개 판단 에이전트 검토를 취합해 설계 초안 작성. 원자 저장, 기본 설정 분리, 경로/파일 상태 재검증, 완료/부분 결과 재실행 잠금, 삭제 체크 해제 정책 제안.
- 코드 변경/기능 테스트/EXE 빌드는 수행하지 않음. 현재 배포 버전1.0.1.8 유지.

## 2026-10-11 작업 저장·열기 / 1.0.1.9

- 설계 승인 후 신규 49개: 저장15개/경로·삭제14개/전역 설정2개/UI18개. 저장 실패 replace/fsync와 이전 파일 보존, 손상/미래/중복 키/누락 JSON·목록 제한·단계 불일치, raw EXIF 객체 제외를 검증했다.
- 실제 엔진 저장→열기→미리보기 실행→완료 복구, 원본 변경 시 쓰기 전 차단, 다른 이름 독립 작업 ID, 실행 기록 실패 시 차단, 실행 예외 시 체크포인트 유지/재실행 잠금, 삭제 체크 해제 및 재검증을 확인했다.
- 새 작업 DRAFT의 최근 복구 교체, 완료 입력/매핑/출력 잠금·허용 휴대폰 설정·기본값 복원·새 작업 잠금 해제, 과거 SUCCESS와 현재 누락 파일 별도 표시를 확인했다.
- 전체 unittest323개: 321통과/Windows 링크 생성 권한2skip. 링크된 상위 경로 차단은 별도 모의 링크 검사로 통과했다. Python3.13.14 환경이며 목표3.12 별도 검증은 미수행.
- 구형 UI 모의 테스트는 작업 저장 확인과 분리했다. Qt 클래스 메서드 MagicMock 패치에서 발생한 네이티브 접근 위반을 실제 함수 패치로 해소하고 전체 회귀 통과를 확인했다. 이전 직접 실행 테스트는 실행 전 미리보기/체크포인트 보장 흐름에 맞게 갱신했다.
- 실제 휴대폰 전송, 강제 종료 파일별 재개, 배포 EXE 사용자 환경 수동 조작은 이번 자동 검증에 포함하지 않았다.
- 최종 독립 검토에서 실제 엔진 완료→설정 기본값 복원→저장/열기→새 작업의 최근 DRAFT 복구를 재현했다. 완료 처리 설정 변경으로 저장이 실패하던 검토 결함은 잠금으로 해결했다.
- PyInstaller dist_v1.0.1.9/PhotoOrganizer.exe 빌드 완료. FileVersion/ProductVersion1.0.1.9, Comments 수정날짜2026-10-11 및 내장 job_store/job_validation/ui.job_controller/main_window 확인. git diff --check 통과.
- 한국어 폰트 파일을 직접 로드한 소스 GUI 오프스크린 캡처에서 작업 버튼 줄과 스크롤 하단 작업 복원 설정의 배치를 확인했다. 캡처: job_save_open_ui.png / job_recovery_settings.png. 배포 EXE 수동 조작 검증과는 구분한다.

## 2026-10-11 작업 복구 2차 설계 검토

- engine.execute의 main/output 오류 통합, 일반 move의 원본 선제 이동, 수동명 move의 출력 후 원본 제거, 출력 생성·임시 파일 경로와 schema1 완료 증거 부족을 읽기 전용으로 확인했다.
- 엔진/저장/UI 관점 세 독립 판단을 취합하고 schema2·SQLite 저널·단계별 복구 계획을 작성했다. 정책 선택은 구현 전 검토안이다.
- 이번 작업은 문서만 변경했다. 기능 테스트·버전 변경·EXE 재빌드를 수행하지 않았으며 1.0.1.9 검증 기록은 유지한다.
- 독립 설계 검토에서 정상적으로 뒤처진 JSON/분기 충돌 구분, schema1 안정적 plan ID, 배포 폴더 간 실행 잠금 범위의 보강을 요청받았다. 이벤트 순번까지의 상태 전체 비교, UUID5 구형 계획 식별, PC 공통 Windows 실행 mutex를 설계에 반영했다. DB 없는 다른 환경의 실행 시작 작업은 조회만 허용하는 범위로 명확히 했다.
- 보강 후 최종 독립 설계 검토 통과. 추가 차단 사항 없음. 이동 원본 제거 시점 변경은 구현 전 사용자 확인 정책으로 유지한다.

## 2026-10-11 작업 복구 2차 / 1.0.1.10

- 새 단계 검증14개/Windows 잠금3개/실제 프로세스 복구1개/저널15개/schema2 13개/엔진18개/UI14개의 요구사항과 독립 코드 검토를 수행했다.
- 일반 정리 완료/output 실패 후 검증된 Target만 사용한 출력 재시도, 수동 이름·촬영 날짜·완료 Target의 기준값 유지, 이동 출력 실패 시 원본 보존과 성공 후 제거, 출력 건너뜀/용량 제외 종료를 확인했다.
- 실제 child 프로세스에서 첫 파일 완료 후 파일 사이 대기 지점에서 강제 종료했다. checkpoint0 JSON보다 앞선 SQLite 기록을 복원하여 첫 파일 DONE/둘째 PENDING을 채택하고 남은 파일을 처리했다. 서로 다른 cwd의 프로세스 충돌과 강제 종료 후 Windows mutex 해제도 별도 확인했다.
- 게시 경합, 파일 게시/원본 제거 후 완료 기록 실패, 최초/복구 시작 JSON 실패, 손상·분기 DB, 완료 파일 변경, active attempt와 전이/형제 단계 조작은 오류 주입으로 검증했다. 영상 인코딩 중 특정 프레임·게시 순간의 실제 강제 종료 검증과는 구분한다.
- 오래된 READY 저장본의 최신 진행 채택·처리 잠금·저장 필요 표시, SaveAs 계획/실행 ID 유지, 구형 실행 및 다른 폴더의 DB 없는 작업 조회 유지, 복구 계획 취소, 파일마다 전체 JSON을 저장하지 않는 동작을 확인했다.
- 독립 검토로 완료 ledger/결과/기준값/삭제 후보 일치, schema2 계획 서명, IN_PROGRESS 전이·시도 ID, 저장 실패 후 처리 입력 잠금, 종료 후 debounce 재시작을 보강했다. 초기 파일명 충돌은 파일을 변경하지 않고 ERROR 결과를 남긴다.
- 10만 항목 저널 초기 등록3.373초, 한 단계 이벤트0.0076초/84자(측정 당시 환경). 단계별 쓰기는 현재 항목만 검증한다. 계획 식별 서명은 JSON에만 적용하고 사진 내용 해시 비교를 추가하지 않았다.
- 한국어 글꼴을 직접 로드한 실제 Qt 소스 화면 캡처에서 새 버튼/복구 계획 표와 WAIT 전체 문구/취소 버튼 배치를 확인했다. 캡처: job_resume_ui.png / job_resume_plan.png.
- 최종 전체 `python -m unittest discover -s tests -v`: 401개/399통과/Windows 링크 생성 권한2skip. 로그 validation_resume_full.log. 실제 프로세스 복구 테스트에는 복사 호출1회/둘째 원본만 입력됨을 추가 검증했고 단독 재검증 통과했다.
- 회귀 중 일회성 Windows 파일 교체 접근 오류1회가 발생했다. 해당 엔진18개 단독 재검증과 최종 전체401개에서 재현되지 않았으며 저장 실패 시 파일 처리를 시작하지 않는 정책은 유지한다.
- PyInstaller 빌드 exit0, dist_v1.0.1.10/PhotoOrganizer.exe의 FileVersion/ProductVersion1.0.1.10, Comments 수정날짜2026-10-11 확인. PYZ 안의 execution_journal/execution_lock/resume_models/resume_validation/resume_engine/ui.resume_dialog/ui.job_controller 포함을 확인했다. 로그 build_resume_release.log.
- 실제 확인 Python3.13.14. 목표 Python3.12, 실제 사용자 EXE 수동 조작, 실제 Android 전송은 별도 환경 확인 대상으로 유지한다. 기존 배포 폴더/설정/사용자 데이터는 보존했다.
