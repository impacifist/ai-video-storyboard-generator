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
