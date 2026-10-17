"""Safe diagnostic UI with a blocked, synthetic LM Studio response; no real AI."""

import io
import json
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import expect, sync_playwright  # noqa: E402

from server import Handler  # noqa: E402
from storyboard import diagnostics, library, providers  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    release, started = threading.Event(), threading.Event()
    response = {"choices": [{"finish_reason": "length", "message": {
        "content": "PRIVATE BODY", "reasoning_content": "PRIVATE REASONING", "tool_calls": []}}],
        "usage": {"prompt_tokens": 14400, "completion_tokens": 16000, "total_tokens": 30400,
                  "completion_tokens_details": {"reasoning_tokens": 15933}}}

    def respond(*args, **kwargs):
        started.set()
        if not release.wait(15):
            raise TimeoutError("synthetic test wait")
        return io.BytesIO(json.dumps(response).encode())

    opener = Mock()
    opener.open.side_effect = respond
    settings = {"LMSTUDIO_MODEL": "local-model", "LMSTUDIO_API_KEY": "fake-private-key"}
    diagnostics.clear_completed()
    try:
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(library, "ROOT", Path(temporary)), \
             patch.object(providers, "load_settings", return_value=settings), \
             patch.object(providers, "build_opener", return_value=opener), sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000},
                                          permissions=["clipboard-read", "clipboard-write"])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.locator("#diagnostics-open").click()
            expect(page.locator("#diagnostics-list")).to_contain_text("No AI requests")
            page.locator("#diagnostics-close").click()
            page.locator("#example").click()
            page.locator("#provider").select_option("lmstudio")
            page.locator("#model").fill("local-model")
            page.locator("#consent").check()
            page.locator("#generate").click()
            assert started.wait(5)
            expect(page.locator("#diagnostics-open")).to_be_enabled()
            page.locator("#diagnostics-open").click()
            expect(page.locator("#diagnostics-list")).to_contain_text("Waiting for response")
            page.locator("#diagnostics-clear").click()
            expect(page.locator(".diagnostic-entry")).to_have_count(1)
            page.locator("#diagnostics-close").click()
            release.set()
            expect(page.locator("#diagnostics-error-open")).to_be_visible()
            page.locator("#diagnostics-error-open").click()
            expect(page.locator("#diagnostics-list")).to_contain_text("15933")
            expect(page.locator("#diagnostics-list")).to_contain_text("Most output tokens were spent on reasoning")
            expect(page.locator("#diagnostics-list")).to_contain_text("length")
            page.locator("#diagnostics-copy").click()
            expect(page.locator("#diagnostics-status")).to_contain_text("copied")
            copied = page.evaluate("navigator.clipboard.readText()")
            with page.expect_download() as event:
                page.locator("#diagnostics-download").click()
            report = Path(event.value.path()).read_text(encoding="utf-8")
            assert copied.replace("\r\n", "\n") == report
            assert 'reasoning_tokens: 15933' in report
            assert not any(secret in report for secret in ("PRIVATE", "fake-private-key", "127.0.0.1"))
            images = ROOT / "storage/browser-check"
            images.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(images / "diagnostics-desktop.png"))
            for language in ("ko", "ja", "en"):
                page.evaluate("language => I18n.select(language)", language)
                expect(page.locator("html")).to_have_attribute("lang", language)
                assert "15933" in page.locator("#diagnostics-list").inner_text()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator("#diagnostics-dialog").evaluate("node => node.scrollWidth <= node.clientWidth")
            page.screenshot(path=str(images / "diagnostics-mobile.png"))
            page.locator("#diagnostics-clear").click()
            expect(page.locator(".diagnostic-entry")).to_have_count(0)
            assert not errors, errors
            browser.close()
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        diagnostics.clear_completed()
    print("Diagnostic browser checks passed: running, length/reasoning, copy/TXT, clear, languages, mobile.")


if __name__ == "__main__":
    main()
