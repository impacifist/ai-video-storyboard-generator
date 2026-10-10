"""Local browser flow; isolated storage and mocked AI, no paid requests."""

import json
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import expect, sync_playwright  # noqa: E402

from server import Handler  # noqa: E402
from storyboard import library, providers  # noqa: E402
from conversion_fixtures import direction_output  # noqa: E402


def fake_compile(provider, model, system, user, schema):
    data = json.loads(user)
    return direction_output(data["plan"], data["references"])


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(library, "ROOT", Path(temporary)), \
             patch.object(providers, "load_settings", return_value={"OPENAI_API_KEY": "fake-key", "OPENAI_MODEL": "test-model"}), \
             patch.object(providers, "generate_json", side_effect=fake_compile) as upstream, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.add_init_script("localStorage.setItem('persona-storyboard.ui-language', 'ko')")
            page.goto(f"http://127.0.0.1:{server.server_port}")
            assert page.locator("#brief-form [required]").evaluate_all("nodes => nodes.every(n => n.closest('label').querySelector('.required-mark'))")
            page.locator("#try-demo").click()
            expect(page.locator("#notice")).to_contain_text("보관함에 저장했습니다")
            page.reload()
            page.locator("#nav-manage").click()
            expect(page.locator("#library-items .library-card")).to_have_count(1)
            page.locator("#library-search").fill("없는 제목")
            expect(page.locator("#library-items .library-card")).to_have_count(0)
            page.locator("#library-search").fill("")
            page.get_by_role("button", name="불러오기", exact=True).click()
            expect(page.locator("#board")).to_be_visible()
            page.locator("#library-save").click()
            expect(page.locator("#notice")).to_contain_text("새 사본")
            page.locator("#provider").select_option("openai")
            page.locator("#consent").check()
            page.locator("#nav-convert").click()
            expect(page.locator("#library-items .library-card")).to_have_count(2)
            page.get_by_role("button", name="이 콘티 선택", exact=True).first.click()
            page.locator("#video-family").select_option("custom")
            expect(page.locator("#conversion-shots input")).to_have_count(6)
            page.locator("#conversion-plan").click()
            expect(page.locator("#conversion-plan-result h3")).to_contain_text("15초 이내")
            page.locator("#conversion-run").click()
            expect(page.locator("#notice")).to_contain_text("가이드")
            upstream.assert_not_called()
            page.locator("#target-model").fill("Test Video v1")
            page.locator("#guide-source").fill("Local test guide v1")
            page.locator("#conversion-guide").fill("Use clip-local timestamps. Preserve dialogue.")
            page.locator("#conversion-consent").check()
            page.locator("#conversion-run").click()
            expect(page.locator("#conversion-results .prompt-output").first).to_be_visible()
            expect(page.locator("#notice")).to_contain_text("프롬프트를 변환해 보관")
            assert upstream.call_count == 1
            page.reload()
            page.locator("#nav-convert").click()
            page.get_by_role("button", name="이 콘티 선택", exact=True).first.click()
            expect(page.locator("#conversion-results")).to_contain_text("Test Video v1")
            page.locator("#conversion-choose").click()
            page.get_by_role("button", name="삭제", exact=True).first.click()
            expect(page.locator("#library-items .library-card")).to_have_count(1)
            expect(page.locator("#conversion-controls")).to_be_hidden()
            page.locator("#library-filter").select_option("trash")
            expect(page.locator("#library-items .library-card")).to_have_count(1)
            page.get_by_role("button", name="복원", exact=True).click()
            expect(page.locator("#library-items .library-card")).to_have_count(0)
            page.locator("#library-filter").select_option("active")
            expect(page.locator("#library-items .library-card")).to_have_count(2)
            page.locator("#conversion-picker-close").click()
            page.locator("#nav-manage").click()
            saved_key = page.evaluate("libraryItems[0].id")
            document = page.request.post(f"http://127.0.0.1:{server.server_port}/api/library/load", data={"id": saved_key}).json()["document"]
            for title in ("After the last train", "Quiet cafe / A conversation", "A very long storyboard title " * 7):
                document["brief"]["title"] = title
                response = page.request.post(f"http://127.0.0.1:{server.server_port}/api/library/save", data={"document": document})
                assert response.ok
            page.locator("#library-refresh").click()
            expect(page.locator("#library-items .library-row")).to_have_count(5)
            page.evaluate("I18n.select('en')")
            page.locator("#library-sort").select_option("title")
            expect(page.locator("#library-items h3").first).to_contain_text("A very long")
            page.locator("#library-search").fill("quiet cafe")
            expect(page.locator("#library-count")).to_have_text("1 shown / 5 total")
            expect(page.locator("#library-items h3")).to_have_text("Quiet cafe / A conversation")
            page.locator("#library-search").fill("no match")
            expect(page.locator(".library-empty")).to_contain_text("No matching storyboards")
            page.locator("#library-search").fill("")
            screenshots = Path(__file__).resolve().parent.parent / "storage/browser-check"
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshots / "library-desktop.png"), full_page=True)
            for language in ("en", "ko", "ja"):
                page.evaluate("lang => I18n.select(lang)", language)
                for width in (1920, 1440, 1024, 768, 641, 540, 390, 320):
                    page.set_viewport_size({"width": width, "height": 900})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (language, width)
            page.evaluate("I18n.select('en')")
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(screenshots / "library-mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            assert not errors, errors
            browser.close()
            print("Browser library: required markers, persisted snapshots, search/load, 15s plan, mocked conversion, restore, mobile PASS")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
