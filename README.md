# AI Video Storyboard Generator

English · [한국어](README.ko.md) · [日本語](README.ja.md)

A local web app for turning 1–5 character personas into an editable storyboard, then converting selected shots into video prompts for Seedance 2.0, MiniMax H3 or LTX 2.5.

**v0.5.6-beta** — a downloadable local application. It creates text storyboards and prompts; video generation and illustrated storyboard panels are not included.

## Finished animation example

https://github.com/user-attachments/assets/6b739ad2-16e0-4c44-8644-3099b755de0e

A 30-second storyboard excerpt rendered with MiniMax H3 and edited to 27.46 seconds. Character settings become dialogue, acting and camera direction; the Japanese dialogue was reviewed and corrected by the creator. This is a rendered example, separate from the mocked UI walkthrough below.

![English storyboard workspace showing character personas, dialogue, camera direction, and a locked shot](docs/screenshots/create-en.png)

Define character personalities and speaking styles, then work with shot-by-shot action, dialogue, camera direction, and continuity states. Edit individual shots and lock the ones you want to keep during regeneration.

[Download the beta](https://github.com/impacifist/ai-video-storyboard-generator/releases/tag/v0.5.6-beta) · [Release notes](docs/releases/v0.5.6-beta.md) · [Try the sample storyboard](examples/before-the-rain-stops.storyboard.json) · [Read its exported prompts](examples/before-the-rain-stops.prompts.txt)

This update adds **Copy prompt** beside every converted clip, including collapsed clips and reopened results. Each button copies only that clip's prompt, with its original dialogue and line breaks. The English, Korean and Japanese guides now show matching interfaces and authored examples. Local output budgets, diagnostics, editable clip lengths, background references and 3–60-shot generation remain available. The [75 camera techniques and Korean reference posters](docs/assets/camera-techniques-ko/README.md) are included.

Screenshots use an authored English sample and mocked conversion responses. They show the real application workflow without paid AI calls; they are not a demonstration of production model quality.

## Quick start

Install **Python 3.12 or later**, download and extract the release ZIP, and run `start.bat` on Windows. Alternatively, open a terminal in the extracted folder:

```sh
python server.py
```

Open **http://127.0.0.1:8765** in your browser. Stop the server with Ctrl+C. If the port is occupied, run `python server.py --port 8766`.

No additional Python packages are required to run the app. The template demo works without an API key; it does not interpret custom personas. AI failures are never replaced with demo output.

## Workflow

1. Open API settings and configure OpenAI, an OpenAI-compatible endpoint, Claude, Ollama, or LM Studio. Enter a model ID available through your provider. Saving settings does not call the model.
2. Add or remove character personas (1–5), then enter their relationships, location, situation, and story direction. Choose 3–60 shots for a 10–180-second storyboard; a duration-based suggestion helps with pacing. For 13+ shots, AI generation first plans the full arc, then expands batches of up to 6 shots with prior-shot context and locked anchors. This uses more API calls and costs more; all batches must validate before returning the completed storyboard. Each call retains a 16,000-token budget. Generation and regeneration failures never return a partial storyboard as complete.
3. Use Manage to search, reopen, preview, trash, or restore saved storyboards.
4. Open Convert, select shots, and choose Seedance 2.0, MiniMax H3 or LTX 2.5. Click **Suggest clip lengths**, then edit the seconds on any clip before conversion. The default plans at shot boundaries, estimates dialogue time and balances clips without forcing each to 15 seconds. Total playback time may change; the saved storyboard stays intact. Fixed 15-second windows remain under **Advanced splitting**.
5. Optionally attach multiple character and background reference images, set their roles, and arrange attachment order. Generate prompts and download TXT, JSON, or a ZIP with reference images.

The interface supports English (default), Korean, and Japanese. The globe menu saves your language choice across browser sessions. Source dialogue and user content retain their original language.

Character settings include optional gender and age alongside speaking style. For Japanese dialogue, specify pronouns, politeness and example lines in speaking style. AI generation runs one additional dialogue proofreading pass when Japanese lines are present, increasing API usage. Long dialogue lists use bounded batches of up to 12 lines. Locked shots and dialogue supplied verbatim in the inputs are excluded. If any proofreading batch fails, the generated draft remains available with the original dialogue and a review warning. This is AI assistance, not a guarantee of native-level Japanese; video conversion preserves the approved dialogue verbatim.

## See it in action

### Keep drafts organized

Search saved storyboards, preview their contents, reopen them for editing, or send a selected storyboard directly to conversion. Each save creates a separate snapshot; deleted items can be restored from Trash.

![English storyboard library with title search, collection and sort controls, and preview, open, convert, and delete actions](docs/screenshots/manage-en.png)

### Turn 30 seconds into two video prompts

In this example, Haru hesitates to ask Yuna to walk home together. Six five-second shots move from a sleeve gesture to a quiet invitation. Select the saved storyboard, keep the 15-second limit, and preview two clips: **C01, 0–15 seconds**, and **C02, 15–30 seconds**.

Choose Seedance 2.0, MiniMax H3 or LTX 2.5 to apply its bundled guide profile. Review source shots, clip planning, and conversion results side by side on a wide screen. Download all clip prompts as one TXT file, or export JSON and a reference-image ZIP. Reference mode lets each character have several images with individual roles, notes, and attachment order.

![English conversion workspace showing six source shots, a 15-second clip limit, two planned clips, Seedance prompts, and TXT, JSON, and ZIP downloads](docs/screenshots/convert-en.png)

To reproduce this example, save the [sample JSON](examples/before-the-rain-stops.storyboard.json), choose **Import JSON**, and then **Save to library**. You can inspect and edit it without an API key. Live prompt conversion requires your own configured provider; the [included TXT](examples/before-the-rain-stops.prompts.txt) is the captured mock conversion output.

### Connect your preferred AI

Configure providers from the browser. OpenAI-compatible endpoints support a custom base URL, API mode, and JSON output mode. Claude, Ollama and LM Studio have their own settings; configure only the provider you plan to use.

![English API settings dialog showing OpenAI-compatible base URL, API mode, JSON output options, and an empty API key field](docs/screenshots/api-settings-en.png)

## AI settings

**All supported local connections have a configurable output budget.** Use API settings → Ollama or LM Studio → Requested output limit; for other local servers, use OpenAI → Local connection output limit. Each connection stores its own value (default 16000, range 256–131072) for generation, review and conversion. Ollama sends [`options.num_predict`](https://docs.ollama.com/modelfile); local compatible Chat Completions/Responses send `max_tokens`/`max_output_tokens`. The compatible-server setting applies to `localhost`, `127.0.0.1` and `::1` only; cloud limits remain unchanged. Environment keys: `OLLAMA_MAX_TOKENS`, `LMSTUDIO_MAX_TOKENS`, `OPENAI_LOCAL_MAX_TOKENS`. These controls set output budgets, not model context length or reasoning mode.

**LM Studio output budget:** API settings → LM Studio → Requested output limit lets you change `max_tokens` (default 16000, range 256–131072). The value persists and applies to generation, review and conversion. Reasoning may share this budget with the response text. Keep input tokens plus this limit within the loaded model's context; increasing it does not guarantee completion. The app does not automatically retry truncated responses or send unsupported thinking controls. For a `length` finish dominated by reasoning, also check the model's reasoning settings. `LMSTUDIO_MAX_TOKENS` can be set in `.env` or the environment; environment-managed values cannot be edited in the UI. [LM Studio's supported parameters](https://lmstudio.ai/docs/developer/openai-compat/chat-completions).

Use **Diagnostics** in the header or **View diagnostics** beside an error to inspect AI request status, elapsed time, finish reason, token usage (including reasoning, when supplied), requested output limit and HTTP status. Copy the log or download it as TXT when reporting an issue. The latest 200 requests are kept in memory and disappear when the server restarts; earlier errors cannot be recovered. Request/response bodies, API keys and endpoint URLs are excluded. These are request diagnostics, not a guarantee that a whole storyboard passed validation. A `length` finish with almost all completion tokens spent on reasoning calls for checking the model's reasoning mode or budget before increasing context length.

Configure credentials in the web UI, or copy `.env.example` to `.env` and fill in only the providers you use. Settings precedence is process environment, web settings, then `.env`.

OpenAI-compatible services can use a custom base URL, Chat Completions or Responses, and the output mode supported by their endpoint. Compatibility depends on the service and model; not every endpoint supports every mode.

For **LM Studio**, load a model and start the server in its Developer tab, then choose **LM Studio** in API settings and enter the server's model ID. The default local Base URL is `http://127.0.0.1:1234/v1`. This adapter uses Chat Completions and JSON Schema by default; JSON mode and prompt JSON are optional. An API key is only needed when LM Studio authentication is enabled. LM Studio settings are independent of OpenAI credentials, and the adapter accepts only loopback server URLs. See the official [compatibility](https://lmstudio.ai/docs/developer/openai-compat), [structured output](https://lmstudio.ai/docs/developer/openai-compat/structured-output), and [authentication](https://lmstudio.ai/docs/developer/core/authentication) documentation. Actual output quality and schema support depend on the loaded model.

API keys are stored **unencrypted on your computer** in `.local-secrets/ui-settings.json` when saved through the UI. They are excluded from Git and exports. Keep the project folder private. The server listens on loopback and is intended for personal local use; it has no multi-user authentication. Do not expose it through a public proxy.

Generation, revision, review, and conversion send the relevant text to your selected provider. Generation/revision can make one additional paid call to proofread editable Japanese dialogue. Conversion sends reference metadata, not image bytes, and does not visually analyze images. Conversion can make one additional paid call to repair invalid structured output; consent is requested in the UI.

## Prompt conversion

- Bundled, attributed guide summaries and the compiler contract are in [docs/guides](docs/guides). They are snapshots, not automatically refreshed vendor documentation.
- Built-in profiles support integer clip durations from 4 to 15 seconds. Split shots retain their source offsets and share a single boundary state across adjacent clips.
- Fractional or sub-4-second clips are padded with an explicit final-frame hold to the next supported whole second (minimum 4). Source shot and dialogue timing is preserved; the plan and exported prompt disclose the added time.
- Original dialogue and speaker assignments are assembled by the application. Generated direction, state descriptions, delivery instructions, and TXT headings must use English; dialogue may remain in its source language.
- Reference mode supports up to nine character and background PNG/JPEG/WebP images in total, at most 5 MB each. Attach them to the video service in the exported manifest order.
- Background references have their own upload control in conversion. Add an overview or alternate views of the same location and describe its seating, doors, windows, aisles and character positions. Each clip receives English instructions to preserve the matching location's geometry across camera angles. Images are not visually analyzed by the conversion AI; attach them to the video service along with character references. This guides layout consistency but does not guarantee the video model's output.
- Optional dialogue timing assistance estimates speaking time and may extend the planned duration without modifying the source storyboard. It is not measured voice timing.
- Conversion now gives each spoken line an action/response onset cue and inserts a shared narrative/audio handoff on both sides of adjacent clips. Automatic mode can redistribute shot time within your chosen clip lengths using performance preferences and estimated speech floors. Fixed and shot-preserving modes retain their timing. Complete lines are assigned to the earliest fitting part instead of delaying an entire exchange. This uses the existing conversion call, preserves original dialogue and does not change your video workflow or motion-context timing. Actual rendered continuity still requires review.
- Automatic clip lengths use the original shot duration or estimated speech plus breathing room, whichever is longer. They preserve scenes and gaps in selected shots, balance whole-shot groups, and continue oversized shots across clips with dialogue assigned once. Manual seconds retime only the conversion plan and are reflected in the final prompt and TXT export. Automatic mode distributes fractional rounding over the performance rather than inserting a frozen final-frame hold. A single utterance longer than the model limit still needs editorial review; it is never shortened or duplicated to pretend it fits.
- Invalid output is not saved. Older conversions made before the English output policy must be converted again for TXT/ZIP export; their JSON remains accessible.

Review prompts before using them. Structural checks cannot guarantee the model's interpretation, natural speech timing, continuity in generated footage, or complete semantic compliance with vendor guides.

## Local data and updates

Saved storyboards, conversions, and reference images live in `storage/library/storyboards.sqlite3`. Trash is reversible. Local storage is shared by everyone with access to this project folder.

Before updating, stop the server and back up `storage/`, `.local-secrets/`, and `.env` if present. Extract the new version into a separate folder, copy those private files into it, and start the new version. Keep the previous folder and backup until you have verified the update. Never upload these files to GitHub.

## Development and validation

Run the offline unit tests:

```sh
python -m unittest discover -s tests -p "test_*.py" -q
```

Optional browser tests require Playwright and Chromium:

```sh
python -m pip install playwright
python -m playwright install chromium
python tests/browser_smoke.py
python tests/browser_settings.py
python tests/browser_library.py
python tests/browser_conversion.py
python tests/browser_i18n.py
```

Tests use temporary storage and mocked AI providers. Passing tests do not establish real-provider output quality. This beta has not been validated against paid production model calls.

To regenerate the documentation screenshots and sample exports with isolated storage and mocked AI, run `python tools/capture_showcase.py` after installing Playwright and Chromium. Add `--language ko` for the Korean screenshots and sample.

See [architecture](docs/ARCHITECTURE.md), [implementation status](docs/IMPLEMENTATION_STATUS.md), and the [Korean guide](README.ko.md) for further details.

## License

No open-source license has been selected for this beta. Public source availability does not grant a general license to redistribute or modify it. Third-party guide material remains subject to its original terms.
