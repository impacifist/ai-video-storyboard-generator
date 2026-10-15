"""Three-language UI checks with isolated storage; no real AI calls."""

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

ROOT = Path(__file__).resolve().parent.parent


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(library, "ROOT", Path(temporary)), \
             patch.object(providers, "load_settings", return_value={}), \
             patch.object(providers, "generate_json") as upstream, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors, posts = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(f"http://127.0.0.1:{server.server_port}")

            def choose(language):
                page.locator("#language-toggle").click()
                expect(page.locator("#language-menu")).to_be_visible()
                page.locator(f"[data-language='{language}']").click()
                expect(page.locator("html")).to_have_attribute("lang", language)
                expect(page.locator("#language-menu")).to_be_hidden()
                expect(page.locator(".wordmark")).to_have_text("Persona Storyboard")

            expect(page.locator("html")).to_have_attribute("lang", "en")
            expect(page.locator("#nav-create")).to_have_text("Create")
            expect(page.locator(".wordmark")).to_have_text("Persona Storyboard")
            choose("ko")
            expect(page.locator(".title-field")).to_contain_text("콘티 제목")
            expect(page.locator(".provider-box summary")).to_contain_text("콘티 제작 AI")
            expect(page.locator(".provider-box")).to_contain_text("AI 서비스")
            choose("en")
            expect(page.locator("#nav-create")).to_have_text("Create")
            expect(page.locator("#language-toggle")).to_have_attribute("aria-label", "Select language")
            assert not posts, posts
            page.locator("#generate").click()
            expect(page.locator("#notice")).to_have_text("Enter Project title.")
            assert not posts, posts
            for _ in range(3):
                page.locator("#add-character").click()
            page.locator('[name="c4_name"]').fill("Keep this name 名前")
            expect(page.locator("#add-character")).to_be_disabled()
            choose("ja")
            expect(page.locator("#add-character")).to_have_text("キャラクターを追加")
            expect(page.locator("#cast-count")).to_have_text("5 / 5人")
            expect(page.locator(".remove-character").last).to_have_text("キャラクターを削除")
            choose("ko")
            expect(page.locator("#add-character")).to_have_text("캐릭터 추가")
            expect(page.locator("#cast-count")).to_have_text("5 / 5명")
            choose("en")
            expect(page.locator("#cast-count")).to_have_text("5 / 5 characters")
            expect(page.locator('[name="c4_name"]')).to_have_value("Keep this name 名前")
            assert not posts, posts
            page.locator("#settings-open").click()
            expect(page.locator("#settings-title")).to_have_text("API settings")
            expect(page.locator("#settings-openai-key")).to_have_attribute("placeholder", "Enter only to replace the key")
            page.locator("#settings-close").click()
            page.locator("#example").click()
            expect(page.locator("#notice")).to_contain_text("Example loaded")
            page.locator("[name='title']").fill("콘티 제작")
            page.locator("[name='c0_name']").fill("삭제")
            page.locator("[name='c0_personality']").fill("Do not translate this persona. 日本語も保持。絵コンテという原文も保持。")
            page.locator("[name='c0_gender']").fill("女性")
            page.locator("[name='c0_age']").fill("17歳、高校生")
            input_before = page.locator("#brief-form").evaluate("f => [...f.elements].filter(n => n.name).map(n => [n.name,n.value])")
            choose("ja")
            expect(page.locator(".title-field")).to_contain_text("ストーリーボード")
            expect(page.locator("#nav-manage")).to_have_text("管理")
            assert page.locator("#brief-form").evaluate("f => [...f.elements].filter(n => n.name).map(n => [n.name,n.value])") == input_before
            page.locator("#generate").click()
            expect(page.locator("#notice")).to_contain_text("デモストーリーボードを保存")
            document_before = page.evaluate("JSON.stringify(project)")
            assert page.evaluate("project.brief.characters[0].gender") == "女性"
            assert page.evaluate("project.brief.characters[0].age") == "17歳、高校生"
            choose("en")
            expect(page.locator("#board-title")).to_have_text("콘티 제작")
            expect(page.locator("#shots .dialogue strong").first).to_have_text("삭제")
            assert page.evaluate("JSON.stringify(project)") == document_before
            expect(page.locator("#review")).to_contain_text("demo template")
            page.get_by_role("button", name="Edit S01", exact=True).click()
            page.locator("#edit-visual").fill("Unsaved edit — 変更中")
            page.evaluate("I18n.select('ja')")
            expect(page.locator("#editor-title")).to_contain_text("カット編集")
            expect(page.locator("#edit-visual")).to_have_value("Unsaved edit — 変更中")
            expect(page.locator("#edit-dialogue")).to_contain_text("話す人物")
            page.locator("#edit-json").evaluate("node => node.closest('details').open = true")
            page.locator("#edit-json").fill("{invalid JSON}")
            page.locator("#save-edit").click()
            expect(page.locator("#edit-error")).to_have_text("JSON形式が不正です。ファイルまたは状態データを確認してください。")
            page.locator("#close-editor").click()
            choose("en")
            page.locator("#nav-convert").click()
            page.get_by_role("button", name="Select storyboard", exact=True).click()
            expect(page.locator("#conversion-source")).to_have_text("Selected storyboard: 콘티 제작")
            page.locator("#video-family").select_option("custom")
            page.locator("#conversion-guide").fill("Preserve this guide. ガイド本文。")
            for checkbox in page.locator("#conversion-shots input").all():
                checkbox.uncheck()
            page.locator("#conversion-plan").click()
            expect(page.locator("#notice")).to_have_text("Select at least one valid shot to convert.")
            choose("ja")
            expect(page.locator("#notice")).to_have_text("変換する有効なカットを1つ以上選んでください。")
            expect(page.locator("#conversion-guide")).to_have_value("Preserve this guide. ガイド本文。")
            assert page.locator("#conversion-shots input:checked").count() == 0
            assert page.evaluate("JSON.stringify(project)") == document_before
            for language in ("ko", "en", "ja"):
                choose(language)
                for width in (1440, 1024, 768, 641, 540, 390, 320):
                    page.set_viewport_size({"width": width, "height": 900})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (language, width)
                    expect(page.locator("#language-toggle")).to_be_visible()
                    page.locator("#language-toggle").click()
                    bounds = page.locator("#language-menu").bounding_box()
                    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width, (language, width, bounds)
                    page.keyboard.press("Escape")
                page.set_viewport_size({"width": 1440, "height": 900})
            page.reload()
            expect(page.locator("html")).to_have_attribute("lang", "ja")
            expect(page.locator("#nav-create")).to_have_text("制作")
            page.locator("#language-toggle").focus()
            page.keyboard.press("Enter")
            expect(page.locator("[data-language='ja']")).to_be_focused()
            page.keyboard.press("Escape")
            expect(page.locator("#language-toggle")).to_be_focused()
            expect(page.locator("#language-menu")).to_be_hidden()
            page.evaluate("I18n.select('unsupported')")
            expect(page.locator("html")).to_have_attribute("lang", "ja")
            page.locator("#settings-open").click()
            page.locator("#settings-openai-key").fill("fake-unsaved-key")
            page.evaluate("I18n.select('en')")
            expect(page.locator("#settings-openai-key")).to_have_value("fake-unsaved-key")
            expect(page.locator("#settings-title")).to_have_text("API settings")
            page.locator("#settings-close").click()

            # Only UI catalogs are checked. Stored user/model output is intentionally excluded.
            missing = page.evaluate("""() => {
              const keys = Object.keys(UI_MESSAGES);
              return keys.filter(k => UI_MESSAGES[k].length !== 2 || UI_MESSAGES[k].some(v => !v.trim()) ||
                UI_MESSAGES[k].some(v => JSON.stringify([...(k.match(/\\{\\d+\\}/g) || [])].sort()) !== JSON.stringify([...(v.match(/\\{\\d+\\}/g) || [])].sort())));
            }""")
            assert not missing, missing
            screenshots = ROOT / "storage" / "browser-check"
            screenshots.mkdir(parents=True, exist_ok=True)
            choose("en")
            untranslated = page.evaluate("""() => {
              const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
              const found = [];
              while (walker.nextNode()) {
                const node = walker.currentNode;
                if (!node.parentElement.closest('script,style,[data-language]') && /[\uac00-\ud7a3]/.test(node.nodeValue)) found.push(node.nodeValue.trim());
              }
              return found;
            }""")
            assert not untranslated, untranslated
            page.screenshot(path=str(screenshots / "language-en.png"))
            choose("ja")
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(screenshots / "language-ja-mobile.png"))
            blocked = browser.new_context()
            blocked.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new DOMException('Blocked', 'SecurityError'); }});")
            blocked_page = blocked.new_page()
            blocked_page.goto(f"http://127.0.0.1:{server.server_port}")
            expect(blocked_page.locator("html")).to_have_attribute("lang", "en")
            blocked_page.evaluate("I18n.select('en')")
            expect(blocked_page.locator("#nav-create")).to_have_text("Create")
            blocked_page.reload()
            expect(blocked_page.locator("html")).to_have_attribute("lang", "en")
            blocked.close()
            invalid = browser.new_context()
            invalid.add_init_script("localStorage.setItem('persona-storyboard.ui-language', 'unsupported')")
            invalid_page = invalid.new_page()
            invalid_page.goto(f"http://127.0.0.1:{server.server_port}")
            expect(invalid_page.locator("html")).to_have_attribute("lang", "en")
            invalid.close()
            upstream.assert_not_called()
            assert not errors, errors
            browser.close()
            print("PASS: Korean/English/Japanese UI, persistence, translated errors, unchanged persona/story/guide, keyboard, 21 responsive cases. No AI calls.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
