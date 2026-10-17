# 업데이트 내역

## v0.5.4-beta · 2026-10-17

Ollama와 로컬 OpenAI 호환 연결에도 출력 토큰 한도 설정을 추가했습니다. LM Studio를 포함해 모든 지원 로컬 연결의 예산을 제공자별로 저장하고 제작·검수·변환에 적용합니다.

[v0.5.4-beta 상세 내역과 설치 안내](releases/v0.5.4-beta.md)

## v0.5.3-beta · 2026-10-17

최근 AI 요청 진단 로그와 복사·TXT 다운로드, LM Studio 출력 한도 설정, 추론 예산 소진 안내를 추가했습니다.

[v0.5.3-beta 상세 내역과 설치 안내](releases/v0.5.3-beta.md)

## v0.5.2-beta · 2026-10-17

LM Studio·Ollama·로컬 OpenAI 호환 연결의 180초 소켓 응답 대기 제한을 제거했습니다.

[v0.5.2-beta 상세 내역과 설치 안내](releases/v0.5.2-beta.md)

## v0.5.1-beta · 2026-10-17

고급 분할 설정 상시 표시, 클립 분할 적용 버튼, 자동 추천 동작 구분과 공식 문서별 링크 제목을 추가했습니다.

[v0.5.1-beta 상세 내역과 설치 안내](releases/v0.5.1-beta.md)

## v0.5.0-beta · 2026-10-17

클립 길이 자동 추천·수정, 자동 모드의 컷별 시간 배분, 인접 클립 연결 지시·발화 계기, LM Studio 지원과 권장 컷 수 안내를 포함합니다.

[v0.5.0-beta 상세 내역과 설치 안내](releases/v0.5.0-beta.md)

## v0.4.0-beta · 2026-10-16

배경 이미지 참조, 최대 60컷·권장 컷 수, 전체 설계 후 분할 생성, 구도·인과 지침과 긴 응답 처리 개선을 포함합니다.

[v0.4.0-beta 상세 내역과 설치 안내](releases/v0.4.0-beta.md)

---

# v0.3.0-beta — 콘티 연출 확장과 변환 안정성 개선

2026-10-15 · AI Video Storyboard Generator

## 주요 변경

- **캐릭터 1~5명 지원:** 캐릭터 추가·삭제, 안정적인 ID 유지, 콘티 가져오기·재생성·영상 프롬프트 변환에 반영했습니다. 한국어·영어·일본어 화면과 모바일 배치를 함께 점검했습니다.
- **카메라 기법 75선:** 제공된 자료의 001~075번을 한국어로 번역하고 콘티·영상 프롬프트 예시를 작성했습니다. 생성·재생성·AI 검수에서 장면 목적에 맞는 기법을 선택하도록 연결하고, 변환에서는 승인된 연출을 유지합니다. 카메라 프롬프트를 따로 입력하지 않아도 참고하며, 모든 기법을 강제로 사용하지 않습니다.
- **한국어 참고 이미지 3장:** 기본 움직임, 샷 크기·각도·시점, 초점·렌즈·구도를 정리한 PNG를 포함했습니다. 참고 자료이며 앱이 콘티 그림을 자동 생성하는 기능은 아닙니다. 원본 076~100번 자료는 제공되지 않아 포함하지 않았습니다.
- **소수점 클립 길이 변환 수정:** 공식 프로필에서 소수점 길이나 4초 미만의 구간 때문에 변환이 막히던 문제를 수정했습니다. 예를 들어 7.4초 구간은 마지막 화면 유지 0.6초를 추가해 8초 클립으로 변환합니다. 원본 컷·대사·분할 오프셋은 유지하고 추가 시간을 계획·검토 메모·영상 프롬프트·TXT에 명시합니다. 마지막 전환은 화면 유지 이후에 적용합니다. 직접 입력 가이드는 기존 소수점 처리를 유지합니다.
- **정수 초 기본 연출:** 새 콘티는 별도 시간 지정이 없으면 컷 길이를 정수 초로 설계하도록 지침을 보완했습니다. 기존 고정 컷의 길이는 보존합니다.
- **긴 응답 처리:** 응답 중단·불완전 종료·출력 잘림·거절·도구 호출은 성공으로 저장하지 않습니다. 자동 재시도나 모델 자동 교체는 하지 않습니다.
- **오류 안내 개선:** HTTP 502·503·504는 제공 서버 오류·시간 초과, HTTP 429는 요청·동시 실행 제한으로 구분합니다. API 키나 서버의 원문 오류 본문은 표시하지 않습니다.

## 설치·업데이트

1. Python 3.12 이상을 설치하고 `ai-video-storyboard-generator-v0.3.0-beta.zip`을 새 폴더에 압축 해제합니다.
2. 기존 설치가 있다면 **서버를 먼저 종료**하고 `storage/`, `.local-secrets/`, `.env`를 백업한 뒤 새 폴더에 복사합니다. 확인 전까지 이전 폴더와 백업을 보관하세요.
3. `start.bat` 또는 `python server.py`로 실행하고 브라우저에서 http://127.0.0.1:8765 를 엽니다. 기존 화면은 새로고침합니다.
4. 기존 콘티는 다시 생성할 필요 없이 새 변환 계획을 만들 수 있습니다. 이미 저장된 변환 결과는 자동으로 수정하지 않습니다.

다운로드 ZIP에는 소스·문서·예제·테스트와 한국어 참고 이미지가 포함됩니다. 개인 API 키·로컬 설정·저장 콘티·사용자 업로드·진단 결과는 포함하지 않습니다. `SHA256SUMS.txt`로 ZIP의 체크섬을 확인할 수 있습니다.

## 검증 범위

- Python 테스트 119개, Ruff, 브라우저 테스트 5종(생성·설정·보관함·변환·다국어)이 통과했습니다.
- 소수점·최소 길이·분할 경계·원본 보존·대사 보존·최종 화면 유지와 TXT 내보내기를 자동 검증했습니다. 스트림 중단·거절·도구 호출·크기 제한·오류 정보 비노출도 검사했습니다.
- 실제 예제 6컷 생성과 앱 문서 검증을 확인했습니다(약 75~80초). 이는 해당 예제·연결의 확인 결과이며 모든 모델이나 긴 입력의 성공을 보장하지 않습니다.
- 전체 영상 프롬프트 변환과 브라우저 흐름은 모의 AI로 검증했습니다. 실제 영상 생성·품질·낭독 시간은 검증하지 않았습니다. 프레임 유지 시간만큼 출력 영상 길이가 원본보다 늘어날 수 있습니다.
- 앱은 텍스트 콘티와 영상 프롬프트를 생성하며 영상 렌더링·자동 합치기를 제공하지 않습니다. 오픈소스 라이선스는 아직 지정하지 않았습니다.

## English

This beta adds 1–5 character personas, a Korean catalog of 75 camera techniques with three reference posters, response-completion checks, and clearer gateway/concurrency errors.

Official-profile conversion now pads fractional or short clips to a whole-number duration of 4–15 seconds with an explicit final-frame hold. A 7.4-second source becomes an 8-second generation clip; original shot timestamps, dialogue and split offsets are preserved, and the final transition follows the hold. Custom guides retain their fractional timing. Newly generated storyboards are instructed to use whole-second shot durations by default.

Install Python 3.12+, extract the ZIP into a new folder, stop the old server, back up and copy your private `storage/`, `.local-secrets/` and optional `.env`, then run `start.bat` or `python server.py`. Restarting the backend is required; refreshing the browser alone does not reload Python changes. Existing saved documents and conversion results are not rewritten.

Validation: 119 unit tests, Ruff and all five mocked browser suites passed. A live six-shot example was generated and validated. Full prompt conversion and video production quality were not verified against live video services. The archive excludes credentials, private projects, uploads and diagnostic artifacts.

---

# v0.2.0-beta

Updated storyboard direction and character dialogue for AI Video Storyboard Generator.

- Storyboard generation and review share purpose-driven shot planning, layout, acting and edit guidance.
- Japanese 2D animation is the default when another medium is not explicitly requested.
- Video conversion emits explicit English camera framing, angle, movement, layout and ending transitions.
- Portions of one source shot share its camera design across 15-second clip boundaries; ending transitions are deferred until the source shot ends.
- MiniMax H3 guidance incorporates the official animation workflow's relevant direction principles while retaining the approved style and application output contract.
- H3 numbered image aliases are normalized to manifest-backed `<Picture N>` tokens without altering original dialogue.
- Optional character gender and age fields work with existing storyboard files and all three UI languages.
- Generated Japanese dialogue receives one additional text-only proofreading pass. Locked shots and supplied verbatim wording are excluded. Failed proofreading keeps the generated draft and displays an advisory.

## Installation and update

Download `ai-video-storyboard-generator-v0.2.0-beta.zip`, extract it into a new folder, and run `start.bat` with Python 3.12 or later installed. Open http://127.0.0.1:8765.

For an existing installation, stop the server and back up `storage/`, `.local-secrets/`, and `.env` if present. Copy those private files into the new folder; keep the old folder and backup until the update is verified. Existing saved storyboards and conversion results are not rewritten. New direction rules apply to newly generated/revised storyboards and newly converted prompts.

The ZIP contains tracked source, documentation, examples and tests. It excludes local credentials, settings, saved projects, reference uploads and generated browser artifacts.

## Validation and limits

This update is tested with offline unit tests and browser flows using mocked AI providers. Real paid AI/video output quality is not verified. Japanese proofreading adds one provider call when editable Japanese dialogue is present and does not guarantee native-level language quality. Review speech timing and generated prompts before rendering. The application does not render videos or automatically stitch generated clips. No open-source license has been selected.

Release checks: 104 unit tests, Ruff, and all five browser suites passed (generation, settings, library, conversion, and localization). Private-path exclusion and credential-pattern checks passed; the pattern scan is not an exhaustive security audit.

---

# v0.1.0-beta

First public beta of Persona Storyboard, a Python 3.12+ local web application.

- Two-character persona input, editable shots, shot locks, and AI-assisted revisions.
- OpenAI, OpenAI-compatible endpoints, Claude, and Ollama settings in the UI.
- Saved storyboard management with search, preview, trash, and restore.
- Seedance 2.0 and MiniMax H3 prompt conversion with 15-second timeline splitting.
- Variable character reference images, attachment ordering, and TXT/JSON/ZIP exports.
- English, Korean, and Japanese interface with persistent language selection.
- English direction output with original dialogue preserved by application assembly.

## Installation

Download `persona-storyboard-v0.1.0-beta.zip`, extract it, install Python 3.12 or later, and run `start.bat` or `python server.py`. Open http://127.0.0.1:8765.

The ZIP includes source, documentation, examples, and tests. It excludes credentials, local configuration, saved storyboards, reference images, and browser-test artifacts.

## Limits

This is a personal local application, without hosted deployment or multi-user authentication. It creates text storyboards and video prompts; video generation and image panel generation are not included. Automated checks use mocked AI providers; paid production model output quality has not been verified. Review generated prompts before use. No open-source license has been selected.
