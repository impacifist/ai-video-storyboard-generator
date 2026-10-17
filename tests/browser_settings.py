"""UI settings checks in a temporary directory; never reads/writes real keys."""

import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import expect, sync_playwright  # noqa: E402

from server import Handler  # noqa: E402
from storyboard import engine, library, providers  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    clean_environment = {k: v for k, v in os.environ.items() if k not in providers.SETTING_FIELDS}
    try:
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(providers, "ROOT", Path(temporary)), \
             patch.object(library, "ROOT", Path(temporary)), \
             patch.dict(os.environ, clean_environment, clear=True), \
             patch.object(providers, "request_json") as upstream, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("localStorage.setItem('persona-storyboard.ui-language', 'ko')")
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.locator("#settings-open").click()
            expect(page.locator("#settings-openai-status")).to_contain_text("미등록")
            # Simulate an unrelated malformed/autofilled address. OpenAI must ignore it.
            page.locator("#settings-ollama-url").evaluate("node => { node.value = 'not-a-url'; }")
            page.locator("#settings-openai-key").fill("fake-openai-only-key")
            page.locator("#settings-openai-model").fill("openai-only-model")
            with page.expect_request("**/api/settings") as saved_request:
                page.locator("#settings-save").click()
            assert set(saved_request.value.post_data_json["values"]) == {
                "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL", "OPENAI_API_MODE", "OPENAI_OUTPUT_MODE", "OPENAI_LOCAL_MAX_TOKENS"}
            expect(page.locator("#settings-dialog")).not_to_be_visible()
            assert providers.load_settings()["OPENAI_API_KEY"] == "fake-openai-only-key"
            assert "ANTHROPIC_API_KEY" not in providers.load_settings()
            assert "OLLAMA_BASE_URL" not in providers.local_settings()
            for provider in ("ollama", "openai", "claude"):
                page.locator("#settings-open").click()
                page.locator("#settings-provider").select_option(provider)
                if provider != "ollama":
                    page.locator(f"#settings-{provider}-key").fill(f"fake-browser-{provider}-key")
                page.locator(f"#settings-{provider}-model").fill(f"{provider}-model")
                if provider == "ollama":
                    expect(page.locator("#settings-ollama-max-tokens")).to_have_value("16000")
                    page.locator("#settings-ollama-max-tokens").fill("32000")
                if provider == "openai":
                    expect(page.locator("#settings-openai-local-max-tokens")).to_have_value("16000")
                    page.locator("#settings-openai-local-max-tokens").fill("24000")
                page.locator("#settings-save").click()
                expect(page.locator("#settings-dialog")).not_to_be_visible()
            page.locator("#provider").select_option("openai")
            expect(page.locator("#model")).to_have_value("openai-model")
            expect(page.locator("#key-note")).not_to_contain_text("등록해주세요")
            page.reload()
            page.locator("#settings-open").click()
            expect(page.locator("#settings-openai-status")).to_contain_text("등록됨")
            expect(page.locator("#settings-openai-local-max-tokens")).to_have_value("24000")
            expect(page.locator("#settings-openai-key")).to_have_value("")
            expect(page.locator("#settings-claude-key")).to_have_value("")
            page.locator("#settings-openai-model").fill("updated-model")
            page.locator("#settings-save").click()
            expect(page.locator("#settings-dialog")).not_to_be_visible()
            assert providers.load_settings()["OPENAI_API_KEY"] == "fake-browser-openai-key"
            page.locator("#settings-open").click()
            page.locator("#settings-provider").select_option("ollama")
            expect(page.locator("#settings-ollama-max-tokens")).to_have_value("32000")
            page.locator("#settings-ollama-url").fill("http://evil.example")
            page.locator("#settings-save").click()
            expect(page.locator("#settings-error")).to_contain_text("로컬 HTTP")
            assert providers.load_settings()["OLLAMA_BASE_URL"] == "http://127.0.0.1:11434"
            # A failed Ollama edit must not block a subsequent OpenAI-only save.
            page.locator("#settings-provider").select_option("openai")
            page.locator("#settings-openai-clear").check()
            page.locator("#settings-save").click()
            expect(page.locator("#settings-dialog")).not_to_be_visible()
            assert providers.load_settings()["OPENAI_API_KEY"] == ""
            page.locator("#settings-open").click()
            expect(page.locator("#settings-openai-status")).to_contain_text("미등록")
            expect(page.locator("#settings-claude-status")).to_contain_text("등록됨")
            public = page.request.get(f"http://127.0.0.1:{server.server_port}/api/config").text()
            assert "fake-browser" not in public
            path = ROOT / "storage" / "browser-check"
            path.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(path / "settings-desktop.png"))
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(path / "settings-mobile.png"))
            page.locator("#settings-provider").select_option("claude")
            page.locator("#settings-claude-key").fill("fake-unsaved-key")
            page.locator("#settings-close").click()
            expect(page.locator("#settings-claude-key")).to_have_value("")
            assert providers.load_settings()["ANTHROPIC_API_KEY"] == "fake-browser-claude-key"
            upstream.assert_not_called()
            page.locator("#settings-open").click()
            page.locator("#settings-provider").select_option("openai")
            page.locator("#settings-openai-url").fill("https://gateway.example/v1")
            page.locator("#settings-openai-mode").select_option("chat_completions")
            page.locator("#settings-openai-output").select_option("prompt")
            page.locator("#settings-openai-key").fill("fake-gateway-key")
            page.locator("#settings-openai-model").fill("gateway-model")
            page.locator("#settings-save").click()
            expect(page.locator("#settings-dialog")).not_to_be_visible()
            page.locator("#provider").select_option("openai")
            expect(page.locator("#provider-note")).to_contain_text("https://gateway.example/v1/chat/completions")
            expect(page.locator("#model")).to_have_value("gateway-model")

            def chat_response(url, payload, headers):
                import json
                assert url == "https://gateway.example/v1/chat/completions"
                assert headers["Authorization"] == "Bearer fake-gateway-key"
                assert "response_format" not in payload
                source = json.loads(payload["messages"][-1]["content"])
                result = engine.demo_story(source["brief"]) if "revision_request" in source else {"summary": "모의 호환 API 검수", "findings": []}
                return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}

            upstream.side_effect = chat_response
            page.locator("#example").click()
            page.locator("#consent").check()
            page.locator("#generate").click()
            expect(page.locator(".shot")).to_have_count(6)
            page.locator("#ai-review").click()
            expect(page.locator("#ai-result")).to_contain_text("모의 호환 API 검수")
            assert upstream.call_count == 2
            # Dedicated LM Studio settings do not reuse cloud credentials.
            page.on("dialog", lambda dialog: dialog.accept())
            page.locator("#settings-open").click()
            page.locator("#settings-provider").select_option("lmstudio")
            expect(page.locator("#settings-lmstudio-url")).to_have_value("http://127.0.0.1:1234/v1")
            page.locator("#settings-lmstudio-url").fill("")
            page.locator("#settings-lmstudio-model").fill("local-model")
            expect(page.locator("#settings-lmstudio-max-tokens")).to_have_value("16000")
            page.locator("#settings-lmstudio-max-tokens").fill("24000")
            page.locator("#settings-save").click()
            expect(page.locator("#settings-dialog")).not_to_be_visible()
            assert providers.load_settings()["OPENAI_API_KEY"] == "fake-gateway-key"
            assert providers.load_settings()["OPENAI_BASE_URL"] == "https://gateway.example/v1"
            assert "LMSTUDIO_API_KEY" not in providers.load_settings()

            def local_response(url, payload, headers):
                import json
                assert url == "http://127.0.0.1:1234/v1/chat/completions"
                assert headers == {}
                assert payload["max_tokens"] == 24000
                assert payload["response_format"]["type"] == "json_schema"
                source = json.loads(payload["messages"][-1]["content"])
                result = engine.demo_story(source["brief"]) if "revision_request" in source else {"summary": "LM Studio 모의 검수", "findings": []}
                return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}

            upstream.side_effect = local_response
            page.locator("#provider").select_option("lmstudio")
            expect(page.locator("#model")).to_have_value("local-model")
            page.locator("#consent").check()
            page.locator("#generate").click()
            expect(page.locator("#source")).to_have_text("LMSTUDIO")
            page.locator("#ai-review").click()
            expect(page.locator("#ai-result")).to_contain_text("LM Studio 모의 검수")
            assert upstream.call_count == 4
            page.reload()
            page.locator("#provider").select_option("lmstudio")
            expect(page.locator("#model")).to_have_value("local-model")
            page.locator("#settings-open").click()
            expect(page.locator("#settings-panel-lmstudio")).to_be_visible()
            expect(page.locator("#settings-lmstudio-max-tokens")).to_have_value("24000")
            for language in ("ko", "en", "ja"):
                page.evaluate("lang => I18n.select(lang)", language)
                expect(page.locator("#settings-save")).to_contain_text("LM Studio")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
            browser.close()
            print("PASS: provider-specific settings, key preservation/delete, generic compatible API, mocked chat generation/review, URL checks, redaction, mobile. No real API calls.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
