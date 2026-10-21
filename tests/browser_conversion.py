"""Official profiles, storyboard inspection and image bundle flow; mocked AI only."""

import io
import json
import sys
import tempfile
import threading
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import expect, sync_playwright  # noqa: E402

from server import Handler  # noqa: E402
from storyboard import library, providers  # noqa: E402
from conversion_fixtures import direction_output  # noqa: E402
from test_guides_references import PNG  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def fake_compile(provider, model, system, user, schema):
    data = json.loads(user)
    return direction_output(data["plan"], data["references"])


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as temporary, patch.object(library, "ROOT", Path(temporary)), \
             patch.object(providers, "load_settings", return_value={"OPENAI_API_KEY": "fake", "OPENAI_MODEL": "fake", "LMSTUDIO_MODEL": "fake"}), \
             patch.object(providers, "generate_json", side_effect=fake_compile) as upstream, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.context.grant_permissions(["clipboard-read", "clipboard-write"])
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("localStorage.setItem('persona-storyboard.ui-language', 'ko')")
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.locator("#try-demo").click()
            expect(page.locator("#notice")).to_contain_text("보관함에 저장했습니다")
            page.locator("#nav-manage").click()
            page.get_by_role("button", name="내용 미리보기", exact=True).click()
            expect(page.locator("#saved-preview")).to_be_visible()
            page.locator("#saved-preview-content details summary").first.click()
            expect(page.locator("#saved-preview-content")).to_contain_text("시작 상태")
            page.locator("#saved-preview-close").click()
            page.get_by_role("button", name="프롬프트로 변환", exact=True).click()
            expect(page.locator("#conversion-picker")).not_to_be_visible()
            expect(page.locator("#library-view")).not_to_be_visible()
            expect(page.locator("#conversion-selection")).to_contain_text("6 / 6")
            assert page.locator("#split-mode").input_value() == "auto"
            expect(page.locator("#split-mode")).to_be_visible()
            expect(page.locator("#clip-limit")).to_be_visible()
            page.locator("#split-mode").select_option("fixed")
            page.locator("#clip-limit").fill("10")
            page.locator("#conversion-split-apply").click()
            expect(page.locator("#conversion-plan-result h3")).to_contain_text("3개 클립")
            assert page.evaluate("visiblePlan.clips.map(c => c.duration)") == [10, 10, 10]
            assert page.locator("#split-mode").input_value() == "fixed"
            upstream.assert_not_called()
            page.locator("#clip-limit").fill("15")
            page.locator("#conversion-plan").click()
            assert page.locator("#split-mode").input_value() == "auto"
            expect(page.locator("[data-clip-duration]").first).to_be_visible()
            page.locator("[data-clip-duration]").first.fill("14")
            page.locator("[data-clip-duration]").first.press("Tab")
            expect(page.locator("#conversion-plan-result .library-card h4").first).to_contain_text("14초")
            assert page.evaluate("clipLengths.C01") == 14
            upstream.assert_not_called()
            # Source inspection and picker changes do not send anything to the AI.
            page.locator("#conversion-preview").click()
            expect(page.locator("#saved-preview")).to_be_visible()
            page.locator("#saved-preview-close").click()
            page.locator("#conversion-choose").click()
            expect(page.locator("#conversion-picker")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.locator("#conversion-picker")).not_to_be_visible()
            upstream.assert_not_called()
            screenshots = ROOT / "storage/browser-check"
            screenshots.mkdir(parents=True, exist_ok=True)
            page.locator("#conversion-view").scroll_into_view_if_needed()
            page.screenshot(path=str(screenshots / "conversion-desktop.png"), full_page=True)
            source_bounds = page.locator(".conversion-original").bounding_box()
            settings_bounds = page.locator(".conversion-settings").bounding_box()
            assert source_bounds["x"] + source_bounds["width"] < settings_bounds["x"]
            page.set_viewport_size({"width": 390, "height": 844})
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(path=str(screenshots / "conversion-workspace-mobile.png"), full_page=True)
            source_bounds = page.locator(".conversion-original").bounding_box()
            settings_bounds = page.locator(".conversion-settings").bounding_box()
            assert source_bounds["y"] + source_bounds["height"] < settings_bounds["y"]
            page.set_viewport_size({"width": 1440, "height": 1000})
            expect(page.locator("#target-model")).to_have_value("Seedance 2.0")
            assert page.locator("#conversion-guide").get_attribute("readonly") is not None
            page.locator("#conversion-shots details summary").first.click()
            expect(page.locator("#conversion-shots details").first).to_contain_text("카메라")
            page.locator("#video-guide").select_option("reference")
            page.locator("#conversion-plan").click()
            expect(page.locator("#notice")).to_contain_text("이미지 사용 여부")
            upstream.assert_not_called()
            files = [{"name": f"image-{i}.png", "mimeType": "image/png", "buffer": PNG} for i in range(3)]
            page.locator("#reference-characters input").first.set_input_files(files)
            expect(page.locator(".reference-card")).to_have_count(3)
            page.locator("#reference-characters input").nth(1).set_input_files(files[:1])
            expect(page.locator(".reference-card")).to_have_count(4)
            page.locator("#reference-background input").set_input_files(files[:1])
            expect(page.locator(".reference-card")).to_have_count(5)
            expect(page.locator(".reference-card strong").last).to_contain_text("배경")
            assert page.locator(".reference-card select").last.input_value() == "environment"
            assert page.locator(".reference-card select").first.input_value() == "appearance"
            expect(page.locator(".reference-extra").first).not_to_have_attribute("open", "")
            expect(page.locator("#reference-count")).to_contain_text("5/9")
            page.locator(".reference-extra summary").last.click()
            page.locator(".reference-card textarea").last.fill("Seats under the windows; doors at the end of the aisle.")
            page.locator(".reference-card select").first.select_option("body")
            page.locator(".reference-extra summary").first.click()
            page.locator(".reference-card textarea").first.fill("Only outfit. 원문 유지。")
            page.locator(".reference-card").first.get_by_role("button", name="뒤로", exact=True).click()
            page.locator("#references-save").click()
            expect(page.locator("#notice")).to_have_text("참조 설정을 저장했습니다.")
            before = page.evaluate("JSON.stringify(referenceItems)")
            page.evaluate("I18n.select('ja')")
            assert page.evaluate("JSON.stringify(referenceItems)") == before
            page.evaluate("I18n.select('ko')")
            page.locator("#video-family").select_option("minimax")
            expect(page.locator(".reference-card .reference-attachment").first).to_contain_text("<Picture 1>")
            for checkbox in page.locator("#conversion-shots input").all()[3:]:
                checkbox.uncheck()
            page.locator("#official-guide-preview > summary").click()
            links = page.locator("#official-guide-links a")
            titles = links.all_text_contents()
            assert len(titles) == 8 and len(set(titles)) == 8
            assert "공식 원문" not in titles
            expect(links.filter(has_text="텍스트 프롬프트 가이드")).to_be_visible()
            expect(links.filter(has_text="샷 구성 규격")).to_be_visible()
            page.locator("#official-guide-preview > summary").click()
            page.locator("#conversion-auto-split").click()
            expect(page.locator("#conversion-plan-result h3")).to_contain_text("2개 클립")
            assert page.locator("#conversion-shots input:checked").count() == 6
            assert page.evaluate("visiblePlan.clips.map(c => c.duration)") == [15, 15]
            assert page.evaluate("visiblePlan.clips.map(c => [c.timeline_start,c.timeline_end])") == [[0, 15], [15, 30]]
            page.locator("#conversion-consent").check()
            page.locator("#conversion-run").click()
            expect(page.locator("#conversion-results .prompt-output").first).to_be_visible()
            expect(page.locator("#conversion-results .prompt-clip").nth(1)).not_to_have_attribute("open", "")
            page.locator("#conversion-results .prompt-clip").nth(1).locator("summary").click()
            expect(page.locator("#conversion-results .prompt-clip").nth(1).locator(".prompt-output")).to_be_visible()
            assert upstream.call_count == 1
            with page.expect_download() as downloading:
                page.get_by_role("button", name="전체 프롬프트 TXT 저장", exact=True).click()
            downloaded = downloading.value
            self_text = Path(downloaded.path()).read_text(encoding="utf-8")
            assert downloaded.suggested_filename == "video-prompts.txt"
            assert "C01" in self_text and "C02" in self_text and self_text.index("C01") < self_text.index("C02")
            assert "0–15" in self_text and "15–30" in self_text and "<Picture 4>" in self_text
            assembled_lines = page.evaluate("conversionResult.dialogue_manifest.map(d => d.text)")
            assert assembled_lines and all(line in self_text for line in assembled_lines)
            directions_only = self_text
            for line in assembled_lines:
                directions_only = directions_only.replace(line, "")
            assert all(not char.isalpha() or char.isascii() for char in directions_only)
            # Export language is independent of the UI language.
            before_export = page.evaluate("promptText(conversionResult)")
            page.evaluate("I18n.select('ja')")
            assert page.evaluate("promptText(conversionResult)") == before_export
            page.evaluate("I18n.select('en')")
            assert page.evaluate("promptText(conversionResult)") == before_export
            page.evaluate("I18n.select('ko')")
            href = page.get_by_role("link", name="프롬프트와 참조 이미지 ZIP 저장").get_attribute("href")
            response = page.request.get(f"http://127.0.0.1:{server.server_port}{href}")
            assert response.status == 200
            with zipfile.ZipFile(io.BytesIO(response.body())) as archive:
                assert archive.read("video-prompts.txt").decode("utf-8").replace("\r\n", "\n") == self_text
                manifest = json.loads(archive.read("manifest.json"))
                assert len(manifest) == 5 and manifest[0]["label"] == "<Picture 1>"
                assert manifest[4]["role"] == "environment" and manifest[4]["label"] == "<Picture 5>"
                assert archive.read(manifest[0]["file"]) == PNG
            page.reload()
            page.locator("#nav-convert").click()
            page.get_by_role("button", name="이 콘티 선택", exact=True).click()
            page.locator("#video-guide").select_option("reference")
            expect(page.locator(".reference-card")).to_have_count(5)
            expect(page.locator(".reference-card textarea").nth(1)).to_have_value("Only outfit. 원문 유지。")
            page.locator("#conversion-consent").check()
            page.locator("#conversion-run").click()
            expect(page.locator("#conversion-results h3").first).to_contain_text("Seedance 2.0")
            assert page.locator("#conversion-results > details[open]").count() == 1
            assert upstream.call_count == 2
            # Reproduce a 30-second source with overfull Japanese dialogue and a split S04.
            document = page.evaluate("JSON.parse(JSON.stringify(conversionBoard))")
            for shot, duration, count in zip(document["story"]["shots"], [4, 4, 4, 5, 7, 6], [33, 39, 13, 49, 57, 32]):
                shot["duration"] = duration
                shot["dialogue"] = [{"speaker": document["brief"]["characters"][0]["id"],
                                     "text": "あ" * count, "delivery": "自然な速さ"}]
            saved = page.request.post(f"http://127.0.0.1:{server.server_port}/api/library/save", data={"document": document}).json()
            page.evaluate("id => loadSaved(id, true)", saved["saved"]["id"])
            page.locator("#video-guide").select_option("text")
            page.locator("#conversion-auto-split").click()
            expect(page.locator("#conversion-plan-result")).to_contain_text("S04: 대사 예상")
            assert page.evaluate("visiblePlan.clips.map(c => c.duration)") == [15, 15]
            # End-to-end repair: a completed draft with a missing shared character
            # must be corrected and saved by the same user action, without a second click.
            repair_calls = []

            def repair_once(provider, model, system, user, schema):
                data = json.loads(user)
                repair_calls.append(data)
                draft = direction_output(data["plan"], data["references"])
                if len(repair_calls) == 1:
                    draft["boundaries"][0]["state"]["characters"].pop()
                return draft

            upstream.side_effect = repair_once
            page.locator("#conversion-consent").check()
            page.locator("#conversion-run").click()
            expect(page.locator("#conversion-results .conversion-notes").first).to_contain_text("S04")
            assert len(repair_calls) == 2
            assert "repair" in repair_calls[1]
            assert page.evaluate("conversionResult.validation_report.repaired")
            persisted = page.request.post(f"http://127.0.0.1:{server.server_port}/api/library/load", data={"id": saved["saved"]["id"]}).json()
            assert persisted["conversions"][0]["result"]["validation_report"]["repaired"]
            upstream.side_effect = fake_compile
            assert page.evaluate("conversionResult.boundary_states.length") == 1
            page.locator("#conversion-speech-plan").click()
            expect(page.locator("#conversion-plan-result")).to_contain_text("원본 30초 → 계획 51초")
            assert page.evaluate("visiblePlan.clips.length") == 5
            assert page.evaluate("visiblePlan.notes.length") == 0
            assert page.evaluate("conversionBoard.story.shots.map(s => s.duration)") == [4, 4, 4, 5, 7, 6]
            page.locator("#conversion-consent").check()
            page.locator("#conversion-run").click()
            expect(page.locator("#notice")).to_contain_text("프롬프트를 변환해 보관")
            assert page.evaluate("conversionResult.plan.clips.length") == 5
            assert upstream.call_count == 5
            for language in ("ko", "en", "ja"):
                page.evaluate("lang => I18n.select(lang)", language)
                for width in (2560, 1920, 1440, 768, 390, 320):
                    page.set_viewport_size({"width": width, "height": 900})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (language, width)
                    if width >= 1800:
                        work = page.locator(".conversion-workspace").bounding_box()
                        results = page.locator("#conversion-results").bounding_box()
                        assert work["x"] + work["width"] < results["x"]
                        assert page.locator("#conversion-view").bounding_box()["width"] >= width - 100
            # Simple path: automatic suggestion, one numeric edit, conversion.
            page.evaluate("I18n.select('ko')")
            page.locator("#split-mode").select_option("auto")
            page.locator("#conversion-plan").click()
            expect(page.locator("[data-clip-duration]").first).to_be_visible()
            page.locator("[data-clip-duration]").first.fill("14")
            page.locator("[data-clip-duration]").first.press("Tab")
            expect(page.locator("#conversion-plan-result .library-card h4").first).to_contain_text("14초")
            edited_source = page.evaluate("JSON.stringify(conversionBoard)")
            page.locator(".conversion-advanced:has(#conversion-ai-provider) > summary").click()
            page.locator("#conversion-ai-provider").select_option("lmstudio")
            for language in ("en", "ja", "ko"):
                page.evaluate("lang => I18n.select(lang)", language)
                expect(page.locator("[data-clip-duration]").first).to_have_value("14")
                assert page.evaluate("clipLengths.C01") == 14
            page.locator("#conversion-consent").check()
            page.locator("#conversion-run").click()
            expect(page.locator("#conversion-results .prompt-output").first).to_contain_text("Timing:")
            assert page.evaluate("conversionResult.plan.clips[0].duration") == 14
            assert page.evaluate("conversionResult.provider") == "lmstudio"
            assert page.evaluate("JSON.stringify(conversionBoard)") == edited_source
            expect(page.locator("#conversion-results .prompt-output").first).to_contain_text("Timing:")
            for width in (1920, 1440, 768, 390, 320):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            screenshots = ROOT / "storage/browser-check"
            screenshots.mkdir(parents=True, exist_ok=True)
            page.evaluate("I18n.select('en')")
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.locator(".conversion-settings-section:has(#conversion-plan)").screenshot(path=str(screenshots / "clip-lengths.png"))
            page.set_viewport_size({"width": 2560, "height": 1200})
            page.evaluate("scrollTo(0, 0)")
            page.screenshot(path=str(screenshots / "conversion-wide.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 900})
            page.screenshot(path=str(screenshots / "conversion-mobile.png"))
            # LTX must ignore saved identity references and render both input modes as prose.
            page.evaluate("I18n.select('ko')")
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.locator("#video-family").select_option("ltx")
            expect(page.locator("#target-model")).to_have_value("LTX 2.5")
            expect(page.locator("#reference-panel")).not_to_be_visible()
            assert page.evaluate("conversionPayload().guide_id") == "ltx-2.5-text"
            assert page.evaluate("conversionPayload().references") == []
            for mode in ("text", "image"):
                page.locator("#video-guide").select_option(mode)
                page.locator("#conversion-consent").check()
                page.locator("#conversion-run").click()
                page.wait_for_function("guide => conversionResult?.guide_id === guide && !busy", arg=f"ltx-2.5-{mode}")
                expect(page.locator("#notice")).to_contain_text("프롬프트를 변환해 보관")
                assert page.evaluate("conversionResult.guide_id") == f"ltx-2.5-{mode}"
                prompt = page.evaluate("conversionResult.output.clips[0].prompt")
                assert "[Shot" not in prompt and "<Picture" not in prompt and "<d>" not in prompt
                page.locator("#conversion-results .prompt-copy").first.click()
                expect(page.locator("#conversion-results .prompt-copy-status").first).to_have_text("복사했습니다.")
                assert page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n") == prompt.replace("\r\n", "\n")
                with page.expect_download() as download:
                    page.get_by_role("button", name="전체 프롬프트 TXT 저장", exact=True).click()
                assert prompt in Path(download.value.path()).read_text(encoding="utf-8")
            for language in ("en", "ja", "ko"):
                page.evaluate("lang => I18n.select(lang)", language)
                expect(page.locator("#ltx-image-help")).to_be_visible()
                assert page.locator("#video-guide").input_value() == "image"
                assert page.evaluate("conversionPayload().guide_id") == "ltx-2.5-image"
            page.locator("#video-family").select_option("minimax")
            assert page.locator("#video-guide").input_value() == "text"
            expect(page.locator("#ltx-image-help")).not_to_be_visible()
            assert not errors, errors
            browser.close()
            print("PASS: saved preview, official profiles, variable references, reorder/persist, both model compilations, ZIP, languages and mobile; mocked AI only.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
