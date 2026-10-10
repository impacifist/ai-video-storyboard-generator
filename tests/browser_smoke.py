"""Optional end-to-end check: requires playwright + Chromium, never calls real AI."""

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
from storyboard import engine, library, providers  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BRIEF = json.loads((ROOT / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
CALLS = []


def fake_upstream(url, payload, headers):
    CALLS.append(url)
    if url.endswith("/responses"):
        source = json.loads(payload["input"])
    else:
        source = json.loads(payload["messages"][-1]["content"])
    if "revision_request" in source:
        result = engine.demo_story(source["brief"])
        result["summary"] = "브라우저 테스트용 모의 AI 응답"
    else:
        result = {"summary": "테스트용 검수 의견", "findings": []}
    content = json.dumps(result, ensure_ascii=False)
    if url.endswith("/responses"):
        return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": content}]}]}
    if url.endswith("/messages"):
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": content}]}
    return {"done": True, "message": {"content": content}}


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    screenshots = ROOT / "storage" / "browser-check"
    screenshots.mkdir(parents=True, exist_ok=True)
    settings = {"OPENAI_API_KEY": "fake-test-key", "ANTHROPIC_API_KEY": "fake-test-key"}
    try:
        with patch.object(providers, "load_settings", return_value=settings), \
             patch.object(providers, "request_json", side_effect=fake_upstream), \
             tempfile.TemporaryDirectory() as downloads, \
             patch.object(library, "ROOT", Path(downloads)), sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.add_init_script("localStorage.setItem('persona-storyboard.ui-language', 'ko')")
            page.goto(f"http://127.0.0.1:{server.server_port}")
            expect(page.locator("#provider-note")).to_contain_text("전송 없음")
            page.screenshot(path=str(screenshots / "desktop-empty.png"), full_page=True)
            page.locator("#example").click()
            page.locator("#tab-world").click()
            page.locator('[name="location"]').fill("")
            page.locator("#tab-cast").click()
            page.locator("#generate").click()
            expect(page.locator("#notice")).to_contain_text("장소 항목을 입력해주세요")
            expect(page.locator("#world-panel")).to_be_visible()
            expect(page.locator('[name="location"]')).to_be_focused()
            assert not CALLS, "Missing input must not call AI"
            page.locator('[name="location"]').fill("방과 후의 교실")
            page.locator("#tab-direction").click()
            page.locator('[name="ending"]').fill("")
            page.locator("#tab-cast").click()
            page.locator("#generate").click()
            expect(page.locator("#notice")).to_contain_text("원하는 결말 항목을 입력해주세요")
            expect(page.locator("#direction-panel")).to_be_visible()
            expect(page.locator('[name="ending"]')).to_be_focused()
            page.locator("#try-demo").click()
            expect(page.locator(".shot")).to_have_count(6)
            expect(page.locator("#source")).to_have_text("예시 템플릿")
            self_name = page.locator('[name="c0_name"]').input_value()
            assert self_name == "하루"
            page.get_by_role("button", name="S01 편집", exact=True).click()
            page.locator("#edit-visual").fill("수동 편집한 화면 <img src=x onerror=alert(1)>")
            page.locator(".line-text").first.fill("잠깐만, 기다려줘.")
            states = json.loads(page.locator("#edit-json").input_value())
            states["end_state"]["characters"][0]["position"] = "출입문"
            page.get_by_text("고급 편집 · 인물과 소품의 시작·종료 상태", exact=True).click()
            page.locator("#edit-json").fill(json.dumps(states, ensure_ascii=False))
            page.locator("#save-edit").click()
            expect(page.locator("#editor")).not_to_be_visible()
            expect(page.locator(".shot").first).to_contain_text("수동 편집한 화면")
            expect(page.locator(".shot img")).to_have_count(0)
            expect(page.locator("#review")).to_contain_text("S02 · 연속성")
            page.get_by_role("button", name="S01 고정", exact=True).click()
            expect(page.locator(".shot").first).to_have_class("shot locked")
            page.locator("#regenerate").click()
            expect(page.locator("#notice")).to_contain_text("예시 콘티입니다")
            expect(page.locator(".shot").first).to_contain_text("수동 편집한 화면")
            with page.expect_download() as download:
                page.locator("#export-json").click()
            saved = Path(downloads) / "project.json"
            download.value.save_as(saved)
            value = json.loads(saved.read_text(encoding="utf-8"))
            assert value["story"]["shots"][0]["locked"] is True
            with page.expect_download() as download:
                page.locator("#export-md").click()
            markdown_path = Path(downloads) / "storyboard.md"
            download.value.save_as(markdown_path)
            assert "수동 편집한 화면" in markdown_path.read_text(encoding="utf-8")
            page.locator("#file").set_input_files(saved)
            expect(page.locator("#notice")).to_contain_text("프로젝트를 불러왔습니다")
            for provider in ("ollama", "openai", "claude"):
                page.locator("#provider").select_option(provider)
                page.locator("#model").fill("test-model")
                page.locator("#generate").click()
                expect(page.locator("#notice")).to_contain_text("전송하는 항목을 확인")
                page.locator("#consent").check()
                page.locator("#generate").click()
                expect(page.locator("#source")).to_have_text(provider.upper())
                expect(page.locator("#summary")).to_have_text("브라우저 테스트용 모의 AI 응답")
                page.locator("#ai-review").click()
                expect(page.locator("#ai-result")).to_contain_text("테스트용 검수 의견")
                page.get_by_role("button", name="S01 고정", exact=True).click()
                page.locator("#regenerate").click()
                expect(page.locator("#notice")).to_contain_text("콘티 초안을 보관함에 저장했습니다")
                page.get_by_role("button", name="S01 고정 해제", exact=True).click()
                expect(page.locator("#ai-result")).to_contain_text("아직 실행하지 않았습니다")
            assert len(CALLS) == 9, CALLS
            page.screenshot(path=str(screenshots / "desktop-board.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "mobile overflow"
            page.screenshot(path=str(screenshots / "mobile-board.png"), full_page=True)
            assert not errors, errors
            browser.close()
            print("PASS: demo, edit, XSS escaping, lock, regenerate, import/export, three mocked providers, review invalidation, mobile overflow.")
            print("Screenshots: storage/browser-check (ignored). No real AI requests.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
