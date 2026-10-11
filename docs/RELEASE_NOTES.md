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
