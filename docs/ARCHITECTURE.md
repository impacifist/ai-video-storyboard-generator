# 초기 구현 설계

## 구성

- `server.py`: loopback 전용 HTTP 서버, 정적 화면, 생성·검수·검증·내보내기 API
- `storyboard/schema.py`: 입력, 컷, 상태, AI 검수의 공통 계약 및 형식 검증
- `storyboard/engine.py`: 연출 지시, 생성, 고정 컷 병합, 출처·이력, 연속성 검사
- `storyboard/providers.py`: Ollama / OpenAI / Claude의 서버 전용 연결부
- `storyboard/library.py`: SQLite 기반 불변 사본 저장·조회·휴지통·복원 및 변환 결과 보관
- `storyboard/conversion.py`: 선택 컷의 최대 15초 계획, 입력 가이드 기반 변환 및 대사·클립 참조 검증
- 시간 기준 분할은 source offset/continuation과 전역 시간 범위를 저장하며 대사는 한 구간만
  소유합니다. 전체 brief는 맥락으로, scope/plan은 실제 변환 대상으로 분리합니다.
- `storyboard/guides.py`: 공식 출처 기반 버전 프로필, 시스템 프롬프트 조립과 가이드 해시
- `storyboard/prompt_renderer.py`: 구조화 연출 응답 검증, 컷 순서·시간·모델 문법·원본 대사 조립.
  AI 응답에 대사/완성 prompt 필드를 허용하지 않습니다. 화자와 원문은 서버 원본에서만
  가져오며 대사 manifest를 함께 보관합니다. 새로운 외부 API나 저장 데이터 마이그레이션은 없습니다.
- `storyboard/clip_planning.py`: 분할 컷의 경계 참조, 원문 순서를 보존하는 대사 배치,
  글자 수 기반 시간 추정과 사용자가 선택한 speech 모드의 사본 재타이밍.
  부분 컷의 source에서 start_state/end_state를 제거하고 entry/exit_boundary_id를 사용합니다.
  원본 endpoint는 boundary의 original_*_context에만 전달합니다. AI의 구조화 boundaries.state를
  검증하고 양쪽 프롬프트에 동일하게 삽입합니다. 실제 가이드 충돌 warnings는 차단하고,
  추정/검토 notes는 화면·TXT에 보존합니다. 경고 문자열을 키워드로 필터링하지 않습니다.
- `storyboard/references.py`: 불변 이미지 BLOB, 보드별 참조 설정, 이미지 조회와 변환별 ZIP
- 웹 API 설정: `/api/config`는 키 등록 상태와 공개 설정만 반환하고 `/api/settings`는
  검증된 변경을 `.local-secrets/ui-settings.json`에 원자적으로 저장합니다. 키는 로컬 평문
  보관이며 프로세스 환경변수 > 웹 설정 > `.env` 순으로 적용합니다.
- `web/`: 설정, 콘티 카드, 편집, 고정, 파일 입출력 화면
- `web/translations.js`, `web/i18n.js`: 한국어·영어·일본어 UI 사전과 언어 전환.
  최초 정적 UI 및 명시적으로 지정한 UI 문구만 번역하며 사용자·모델 원문을 탐색하거나
  번역하지 않습니다. 언어 코드는 브라우저에 보관하고 날짜는 선택 언어에 맞춰 표시합니다.
- `examples/`: 사람이 읽고 수정할 수 있는 입력 예제
- `tests/`: 외부 호출 없는 계약·연결부·HTTP 검사 및 선택 브라우저 검사

## 생성 계약

입력은 brief, 생성물은 story, 저장 단위는 schema_version=1인 document입니다.
story에는 summary, beats, assumptions, shots가 있습니다. 사용자 입력은 brief에 그대로
남기고 모델이 추가한 설정은 assumptions에 구분하도록 지시합니다. 이 구분의 의미적
정확성까지 프로그램이 보장하지는 않습니다.

각 shot은 화면, 행동, 대사, 카메라, 시작·종료 상태와 연속성 메모를 가집니다.
캐릭터의 gender와 age는 선택 문자열 필드이며 구버전 콘티에서 생략해도 됩니다. 그 외 필드 검증은 유지합니다.
입력된 1~5명 캐릭터의 상태를 화면 밖에서도 모두 기록합니다. 컷은 S01부터 연속된 ID를
사용하고 모든 화자와 소품 소유자 참조는 존재하는 캐릭터 ID여야 합니다.

콘티 생성·재생성과 AI 의미 검수는 `docs/guides/storyboard-direction.md`의 샷·편집 설계 기준을 공유합니다.
기존 콘티 컷 필드에 선택 이유와 연결을 기록하며 콘티 스키마나 연출 휴리스틱에 의한 저장 차단은 추가하지 않습니다.
대사 의도·상대의 반응·관계 변화별 구도 선택과 컷 사이 대비를 지침에 포함합니다. 화면의 강조 대상, 크롭·여백·깊이는 기존 purpose/visual/camera에 기록하며 기법 개수나 다양성 비율은 강제하지 않습니다.
`action-causality.md`는 생성·재생성·의미 검수·모든 변환 프로필이 공유하는 인과 설계 지침입니다. 행동의 선행 조건을 역으로 찾고 입력부터 순방향으로 공간·소지·지식·동기·시간·결과의 연결을 검토하도록 지시합니다. 기존 필드로 표현하며 별도 AI 호출이나 자동 저장 차단을 추가하지 않습니다. 변환은 승인된 인과를 보존하고 누락은 수정 의견으로 남깁니다. 실제 모델의 인과 추론 정확성은 형식 검사로 보장하지 않습니다.
`anime-direction.md`를 생성·검수·모든 변환 프로필에 공유합니다. 스타일 미지정 시 일본 2D 연출이 기본이며 명시적 다른 스타일은 유지합니다.
변환 AI 응답에는 영어 camera(size, angle, movement, transition, layout)를 요구하고 조립기 v4가 명시적으로 렌더링합니다.
기술적 클립 분할의 앞부분에는 원본 컷의 종료 전환을 넣지 않습니다. 기존 저장 결과는 재작성하지 않습니다.

12컷 이하는 기존 단일 생성 호출을 유지합니다. 13~60컷은 `batch_generation.py`에서 전체 outline(요약·beats·가정·컷별 ID/장면/길이/목적/행동)을 먼저 생성·검증하고, 최대 6컷씩 상세화합니다. 전체 brief/outline, 직전 두 컷, 해당 구간의 이전 생성본과 다음 고정 컷을 전달합니다. 고정 컷은 다시 생성하지 않으며 코드로 보존합니다. 묶음별 ID·길이·장면·상태 참조를 검증한 뒤 전체 story를 검사합니다. 개별 단계 실패에는 자동 재시도가 없고 완성본은 모두 성공한 경우만 반환합니다. 진행 중 결과의 디스크 체크포인트·중단 재개는 제공하지 않습니다. 의미 검수는 사용자가 요청하는 별도 호출입니다.
API별 출력 예산 16,000토큰은 유지합니다. SSE는 실제 content 2MB와 전송 데이터 32MB를 구분해 제한하며, 추론·이벤트 오버헤드를 생성 내용의 크기로 계산하지 않습니다. 단일 이벤트 행도 2MB로 제한합니다. 일반 JSON 응답은 기존 2MB 제한을 유지합니다. 로컬 요청과 JSON 파일 가져오기는 16MB까지 허용하고 이미지 업로드의 기존 크기 제한은 보존합니다.
일본어 대사가 있는 실제 AI 생성·재생성에는 대사 전용 교정을 한 번 적용합니다. 긴 대사 목록은 최대 12행, 합계 약 5,000자씩 분할 호출합니다(그보다 긴 단일 대사는 나누거나 축약하지 않습니다). 교정은 모든 응답이 유효할 때만 일괄 반영하며 실패하면 원래 생성 대사를 유지합니다. 행별 재교정이나 자동 재시도는 없습니다.
`character-dialogue.md`를 생성·교정·의미 검수에 공유하며, 교정은 unlocked 생성 대사의 text만 바꿉니다.
입력에 명시한 대사 원문과 고정 컷은 교정 대상에서 제외합니다. 실패하면 유효한 생성본을 유지하고 검수에 미완료 경고를 표시합니다.
교정은 사건·문법·원어민 수준을 결정적으로 검증하지 못하며 영상 변환의 원문 보존 계약과 별개입니다.

재생성에는 이전 콘티와 고정 컷을 전달합니다. 고정 컷은 모델 결과를 신뢰하지 않고
프로그램이 원본으로 치환합니다. 병합 후 다시 검증하고 모든 인접 컷을 검사합니다.
연결 경고가 있으면 사용자에게 표시합니다. 경고가 사라질 때까지 자동 생성하는 반복
루프는 없으며, 연결 경고는 생성 실패와 구분합니다.

## 제공자 연결

2026-10-10에 다음 공식 문서를 확인했습니다.

- [Ollama Chat](https://docs.ollama.com/api/chat): `/api/chat`, stream=false, JSON Schema format
- [Ollama Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses): Responses의 text.format에 strict JSON Schema
- [Claude Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs): Messages의 output_config.format
- [Claude Messages](https://platform.claude.com/docs/en/api/messages/create)

모든 제공자에 동일한 콘티 계약을 지시하고 응답을 로컬에서 다시 검증합니다.
OpenAI 설정에는 사용자 지정 Base URL과 Responses / Chat Completions를 지원합니다.
JSON Schema는 형식 옵션으로 스키마를 전달하고 JSON 모드·프롬프트 JSON은 시스템
지시에 같은 스키마를 포함합니다. 프롬프트 JSON은 공급자의 스키마 강제가 없으므로
로컬 검증 실패 가능성이 더 높습니다. 출력 형식의 자동 fallback은 하지 않습니다.
특정 서비스의 전용 프리셋 없이 Base URL, API 방식, 출력 방식, 키와 모델을 사용자가
입력합니다. 실제 endpoint를 화면에 공개하고 대상 호스트
변경 시 새 키 입력 또는 기존 키 삭제를 요구합니다.
형식 검증은 사용 중인 작은 JSON Schema 부분집합만 구현하며 범용 JSON Schema 엔진은
아닙니다. 제공자의 구조화 출력 지원 여부·모델 접근 권한은 실제 계정에서 확인해야 합니다.
모델 버전·출력 한도 차이로 거절되는 요청은 오류로 표시합니다. 자동 fallback은 없습니다.

OpenAI는 store=false를 지정합니다. 이것은 제공자의 전체 데이터 보존 정책에 대한
보증이 아닙니다. 프록시 환경변수와 리다이렉트는 상속하지 않아 자격증명을 의도치 않은
주소로 보내지 않습니다. 회사 프록시 전용 환경에서는 추가 구현이 필요할 수 있습니다.

## 첫 버전의 제한

- 콘티는 텍스트 카드이며 그림 패널은 아직 생성하지 않습니다.
- 대사·컷 단위의 세부 잠금 대신 전체 컷 잠금을 지원합니다.
- JSON 전체 입력과 프로젝트 임포트를 지원하며 PDF·이미지 임포트는 지원하지 않습니다.
- 장면 ID가 같은 인접 컷의 상태를 비교합니다. 장면 간 이동의 의미적 타당성은 AI와
  사람이 확인해야 합니다.
- 콘티·수정 이력·변환 결과를 로컬 보관함에 저장합니다. 저장 시 새 사본을 만들며,
  미생성 입력은 기존처럼 JSON으로 따로 다운로드합니다. 보관함은 개인용이며 계정 격리는 없습니다.
- Seedance 2.0/MiniMax H3의 텍스트/이미지 참조 프로필을 내장합니다. 서버가 가이드를
  적용하고 원문 대사·클립 대응·정수 4~15초·이미지 라벨·H3 섹션 순서를 검사합니다.
  가이드의 모든 의미적 조건, 실제 영상 품질과 연결은 사람 검토가 필요합니다.
- 참조 이미지는 별도 SQLite 테이블에 BLOB으로 저장합니다. 참조 설정은 수정할 수 있지만
  이미지 바이트와 변환 당시 manifest는 불변입니다. 요청은 UUID만 받고 경로를 받지 않으며
  다른 보드의 자산 사용·중복 ID·9장 초과·텍스트 방식의 이미지 사용을 거부합니다.
  ZIP 파일명은 서버가 생성합니다. 이미지/ZIP 조회에도 Host·Origin 검사를 적용합니다.
  원본이 휴지통이면 이미지와 ZIP 조회도 차단하며 복원하면 다시 접근할 수 있습니다.
- 이미지 업로드 경로만 JSON 본문 상한을 6.8MB로 확장합니다. 이미지 바이트는 5MB 이하,
  PNG/JPEG/WebP MIME와 헤더를 검사합니다. 변환 AI는 이미지 메타데이터만 받습니다.
- 실제 AI 호출과 창작 품질은 키 및 모델 준비 후 확인해야 합니다. 모의 테스트를 실제
  제공자 연결 성공이나 작품 품질 증거로 간주하지 않습니다.
