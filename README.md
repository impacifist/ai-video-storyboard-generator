# Persona Storyboard

English · [한국어](README.ko.md)

A local web app for turning two character personas into an editable storyboard, then converting selected shots into video prompts for Seedance 2.0 or MiniMax H3.

**v0.1.0-beta** — a downloadable local application. It creates text storyboards and prompts; video generation and illustrated storyboard panels are not included.

## Quick start

Install **Python 3.12 or later**, download and extract the release ZIP, and run `start.bat` on Windows. Alternatively, open a terminal in the extracted folder:

```sh
python server.py
```

Open **http://127.0.0.1:8765** in your browser. Stop the server with Ctrl+C. If the port is occupied, run `python server.py --port 8766`.

No additional Python packages are required to run the app. The template demo works without an API key; it does not interpret custom personas. AI failures are never replaced with demo output.

## Workflow

1. Open API settings and configure OpenAI, an OpenAI-compatible endpoint, Claude, or Ollama. Enter a model ID available through your provider. Saving settings does not call the model.
2. Enter two character personas, their relationship, location, situation, and story direction. Generate, edit, lock, and regenerate shots.
3. Use Manage to search, reopen, preview, trash, or restore saved storyboards.
4. Open Convert, select shots, choose Seedance 2.0 or MiniMax H3, and review the clip plan and guide. By default, a 30-second timeline becomes two 15-second clips. Plans follow actual shot durations.
5. Optionally attach multiple character reference images, set their roles, and arrange attachment order. Generate prompts and download TXT, JSON, or a ZIP with reference images.

The interface supports English (default), Korean, and Japanese. The globe menu saves your language choice across browser sessions. Source dialogue and user content retain their original language.

## AI settings

Configure credentials in the web UI, or copy `.env.example` to `.env` and fill in only the providers you use. Settings precedence is process environment, web settings, then `.env`.

OpenAI-compatible services can use a custom base URL, Chat Completions or Responses, and the output mode supported by their endpoint. Compatibility depends on the service and model; not every endpoint supports every mode.

API keys are stored **unencrypted on your computer** in `.local-secrets/ui-settings.json` when saved through the UI. They are excluded from Git and exports. Keep the project folder private. The server listens on loopback and is intended for personal local use; it has no multi-user authentication. Do not expose it through a public proxy.

Generation, revision, review, and conversion send the relevant text to your selected provider. Conversion sends reference metadata, not image bytes, and does not visually analyze images. Conversion can make one additional paid call to repair invalid structured output; consent is requested in the UI.

## Prompt conversion

- Bundled, attributed guide summaries and the compiler contract are in [docs/guides](docs/guides). They are snapshots, not automatically refreshed vendor documentation.
- Built-in profiles support integer clip durations from 4 to 15 seconds. Split shots retain their source offsets and share a single boundary state across adjacent clips.
- Original dialogue and speaker assignments are assembled by the application. Generated direction, state descriptions, delivery instructions, and TXT headings must use English; dialogue may remain in its source language.
- Reference mode supports up to nine PNG/JPEG/WebP images in total, at most 5 MB each. Attach them to the video service in the exported manifest order.
- Optional dialogue timing assistance estimates speaking time and may extend the planned duration without modifying the source storyboard. It is not measured voice timing.
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

See [architecture](docs/ARCHITECTURE.md), [implementation status](docs/IMPLEMENTATION_STATUS.md), and the [Korean guide](README.ko.md) for further details.

## License

No open-source license has been selected for this beta. Public source availability does not grant a general license to redistribute or modify it. Third-party guide material remains subject to its original terms.
