"""Count-choice UI through real HTTP routes; all provider requests are mocked."""

import copy
import json
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright  # noqa: E402
from server import Handler  # noqa: E402
from storyboard import engine, library, providers  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main():
    state, calls = {"count": 5, "failure": False, "invalid": False}, []

    def ai(provider, model, system, user, schema):
        data = json.loads(user)
        calls.append(copy.deepcopy(data))
        if state["failure"]:
            raise providers.ProviderError("Mock retry failed")
        story = engine.demo_story(data["brief"])
        while len(story["shots"]) < state["count"]:
            story["shots"].append(copy.deepcopy(story["shots"][-1]))
        story["shots"] = story["shots"][:state["count"]]
        for i, shot in enumerate(story["shots"], 1):
            shot["id"] = f"S{i:02d}"
        if state["invalid"]:
            story["shots"][0]["dialogue"][0]["speaker"] = "unknown"
        return story

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as temporary, patch.object(library, "ROOT", Path(temporary)), \
             patch.object(providers, "load_settings", return_value={"OPENAI_API_KEY": "fake", "OPENAI_MODEL": "mock"}), \
             patch.object(providers, "generate_json", side_effect=ai), sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.add_init_script("localStorage.setItem('persona-storyboard.ui-language', 'ko')")
            base = f"http://127.0.0.1:{server.server_port}"
            page.goto(base)
            page.locator("#try-demo").click()
            expect(page.locator("#notice")).to_contain_text("보관함에 저장")
            original = page.evaluate("JSON.stringify(project)")
            old_board = library.listing()[0]["id"]
            page.locator("#provider").select_option("openai")
            page.locator("#model").fill("mock")
            page.locator("#consent").check()
            page.locator("#generate").click()
            expect(page.locator("#generation-choice")).to_be_visible()
            expect(page.locator("#generation-choice-count")).to_have_text("요청 6컷 · 생성 5컷")
            expect(page.locator("#generation-choice-preview .source-shot")).to_have_count(5)
            assert page.evaluate("JSON.stringify(project)") == original
            assert len(library.listing()) == 1 and len(calls) == 1
            with page.expect_download() as saving:
                page.locator("#generation-choice-download").click()
            saved = json.loads(Path(saving.value.path()).read_text(encoding="utf-8"))
            assert len(saved["story"]["shots"]) == saved["brief"]["shot_count"] == 5
            pending_before = page.evaluate("JSON.stringify(pendingGeneration.document)")
            for lang in ("en", "ja", "ko"):
                page.evaluate("lang => I18n.select(lang)", lang)
                assert page.evaluate("JSON.stringify(pendingGeneration.document)") == pending_before
                for width in (320, 390, 768, 1440):
                    page.set_viewport_size({"width": width, "height": 1000})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    assert page.locator("#generation-choice").evaluate("node => node.scrollWidth <= node.clientWidth + 1")
            artifacts = ROOT / "storage/browser-check"
            artifacts.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(artifacts / "generation-count-choice-ko.png"))
            state["failure"] = True
            page.locator("#generation-choice-retry").click()
            expect(page.locator("#notice")).to_contain_text("Mock retry failed")
            assert page.evaluate("JSON.stringify(project)") == original
            assert page.evaluate("pendingGeneration.actual_count") == 5
            expect(page.locator("#generation-choice-error")).to_contain_text("이전 생성 결과")
            page.locator("#generation-choice-close").click()
            page.locator("#generation-pending-open").click()
            expect(page.locator("#generation-choice-count")).to_have_text("요청 6컷 · 생성 5컷")
            state.update(failure=False, count=4)
            page.locator("#generation-choice-retry").click()
            expect(page.locator("#generation-choice-count")).to_have_text("요청 6컷 · 생성 4컷")
            assert calls[-1]["brief"]["shot_count"] == 6
            assert len(library.listing()) == 1 and len(calls) == 3
            page.locator("#generation-choice-use").click()
            expect(page.locator("#generation-choice")).not_to_be_visible()
            expect(page.locator("#notice")).to_contain_text("초안을 보관함에 저장")
            expect(page.locator('[name="shot_count"]')).to_have_value("4")
            assert page.evaluate("project.story.shots.length") == 4
            assert len(library.listing()) == 2 and len(calls) == 3
            assert json.loads(original) == library.load(old_board)
            assert "요청 6개 · 생성 4개" in page.evaluate("project.history.at(-1).event")
            page.locator('[name="shot_count"]').fill("6")
            state["count"] = 8
            page.locator("#generate").click()
            expect(page.locator("#generation-choice-count")).to_have_text("요청 6컷 · 생성 8컷")
            assert page.evaluate("project.story.shots.length") == 4
            page.locator("#generation-choice-close").click()
            expect(page.locator("#generation-pending")).to_be_visible()
            page.locator("#generation-pending-open").click()
            state["count"] = 6
            page.locator("#generation-choice-retry").click()
            expect(page.locator("#notice")).to_contain_text("초안을 보관함에 저장")
            expect(page.locator("#generation-pending")).not_to_be_visible()
            assert page.evaluate("project.story.shots.length") == 6
            assert len(library.listing()) == 3 and len(calls) == 5
            state.update(count=5, invalid=True)
            final = page.evaluate("JSON.stringify(project)")
            page.locator("#generate").click()
            expect(page.locator("#notice")).to_contain_text("화자")
            expect(page.locator("#generation-choice")).not_to_be_visible()
            assert page.evaluate("JSON.stringify(project)") == final
            assert not errors, errors
            browser.close()
        print("PASS: count preview, exact counts, draft download, explicit acceptance, failed/successful retry, previous preservation, no hidden extra AI, invalid-speaker rejection, 3 languages and mobile.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
