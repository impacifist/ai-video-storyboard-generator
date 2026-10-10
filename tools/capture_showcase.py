"""Capture public English documentation using authored samples and mocked AI.

Requires Playwright + Chromium. Never reads user settings or saved storyboards.
Run from the repository root: python tools/capture_showcase.py
"""

import copy
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
IMAGES = ROOT / "docs/screenshots"
SAMPLE = ROOT / "examples/before-the-rain-stops.storyboard.json"


def sample_document():
    brief = {
        "title": "Before the rain stops",
        "characters": [
            {"id": "haru", "name": "Haru", "personality": "Reserved, thoughtful, and playful with close friends.",
             "speech": "Short, hesitant sentences; a soft voice.", "desire": "Walk home with Yuna.",
             "fear": "Making their friendship awkward.", "habit": "Touches her sleeve when nervous.",
             "fixed": "Short dark hair, navy school uniform, no umbrella."},
            {"id": "yuna", "name": "Yuna", "personality": "Observant and considerate; never puts others on the spot.",
             "speech": "Warm and direct, leaving room for a reply.", "desire": "Get closer to Haru.",
             "fear": "Making Haru uncomfortable.", "habit": "Pauses what she is doing to listen.",
             "fixed": "Long dark hair, navy school uniform, one clear umbrella."},
        ],
        "relationship": "Classmates who care about each other but have not said so aloud.",
        "location": "A classroom after school", "time": "Late afternoon",
        "atmosphere": "Gentle rain, warm window light, comfortable silence.",
        "situation": "Haru stands by the window. Yuna is packing her bag at the next desk.",
        "intent": "Show Haru's hesitation through a small gesture. Let Yuna notice and offer to walk home together.",
        "ending": "Haru accepts. They leave the classroom together under one umbrella.",
        "required": "Clear umbrella\nSleeve gesture", "excluded": "Explicit confession\nSlapstick",
        "style": "Slice-of-life animation; restrained acting, reaction shots, and a quiet final wide shot.",
        "duration": 30, "shot_count": 6,
    }
    document = engine.generate({"brief": brief, "provider": "demo", "model": ""})
    story = document["story"]
    story.update(summary="A hesitant question becomes an invitation to share the walk home.",
                 beats=["Haru hesitates", "Yuna notices", "An invitation, quietly accepted"],
                 assumptions=["Authored documentation sample; not an AI-generated result."])
    rows = [
        ("Establish the distance", "Warm light falls across two desks. Rain beads on the window.",
         "Haru watches the rain while Yuna closes her schoolbag.", "haru", "Still raining.", "Wide", "Static"),
        ("Let the hesitation show", "Close on Haru's fingers gathering the edge of her sleeve.",
         "Haru glances at Yuna, then lowers her eyes.", "haru", "I forgot my umbrella.", "Close-up", "Static"),
        ("A reaction before a reply", "Yuna pauses beside her bag and turns toward Haru.",
         "Yuna softens her expression and reaches for the clear umbrella.", "yuna", "We can share mine.", "Medium", "Gentle push-in"),
        ("Offer a way forward", "Yuna holds up the clear umbrella, leaving space beside her.",
         "Yuna waits without rushing Haru; Haru lifts her gaze.", "yuna", "Want to walk together?", "Two-shot", "Static"),
        ("Resolve the hesitation", "Haru releases her sleeve. A small smile replaces her uncertainty.",
         "Haru nods and steps toward Yuna.", "haru", "Yes. I'd like that.", "Close-up", "Static"),
        ("Leave together", "Both girls walk toward the classroom door in the warm afternoon light.",
         "Yuna carries the closed umbrella as they leave side by side.", "yuna", "Let's go.", "Wide", "Slow follow"),
    ]
    state = {"characters": [
        {"character_id": "haru", "position": "By the classroom window", "pose": "Standing, holding her sleeve", "gaze": "Toward the rain", "emotion": "Hesitant"},
        {"character_id": "yuna", "position": "Beside the next desk", "pose": "Standing beside her bag", "gaze": "Toward Haru", "emotion": "Attentive"},
    ], "props": [{"name": "Clear umbrella", "holder": "yuna", "position": "Beside Yuna's schoolbag"}]}
    for index, (shot, row) in enumerate(zip(story["shots"], rows)):
        purpose, visual, action, speaker, line, size, movement = row
        shot.update(purpose=purpose, visual=visual, actions=[action],
                    dialogue=[{"speaker": speaker, "text": line, "delivery": "Softly, with a natural pause"}],
                    camera={"size": size, "angle": "Eye level", "movement": movement, "transition": "Cut"},
                    continuity="Keep the screen direction and warm afternoon light consistent.",
                    start_state=copy.deepcopy(state), locked=index == 0)
        if index == 2:
            state["props"][0]["position"] = "In Yuna's right hand"
        if index == 4:
            state["characters"][0].update(pose="Standing beside Yuna, hands relaxed", gaze="Toward Yuna", emotion="Relieved")
        if index == 5:
            for character in state["characters"]:
                character.update(position="At the classroom doorway", pose="Walking side by side", gaze="Toward the corridor", emotion="Content")
        shot["end_state"] = copy.deepcopy(state)
    document["history"] = [{"at": "2026-10-10T00:00:00+00:00", "event": "Authored English documentation sample"}]
    document["provenance"].update(created_at="2026-10-10T00:00:00+00:00", updated_at="2026-10-10T00:00:00+00:00")
    engine.validate_document(document)
    return document


def mock_director(provider, model, system, user, schema):
    request = json.loads(user)
    clips = []
    for clip in request["plan"]["clips"]:
        clips.append({
            "id": clip["id"], "context": "A classroom after school. Gentle rain and warm afternoon window light.",
            "subject_definitions": "Haru: short dark hair, navy uniform, reserved. Yuna: long dark hair, navy uniform, considerate.",
            "summary": "A quiet invitation to walk home together.",
            "retention_analysis": "Maintain both character identities and the clear umbrella throughout.",
            "shots": [{"id": shot["id"],
                       "direction": shot["source"]["visual"] + " " + " ".join(shot["source"]["actions"]) + " Camera: " + ", ".join(shot["source"]["camera"].values()) + ".",
                       "dialogue_language": "English", "deliveries": [line["delivery"] for line in shot["source"]["dialogue"]]}
                      for shot in clip["shots"]],
            "overall_soundscape": "Soft rain against the window, subtle fabric and footsteps.",
            "non_diegetic_music": "None; leave space for the pauses.",
        })
    return {"warnings": [], "notes": [], "boundaries": [], "reference_notes": [], "clips": clips}


def main():
    IMAGES.mkdir(parents=True, exist_ok=True)
    document = sample_document()
    SAMPLE.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(library, "ROOT", Path(temporary)), \
             patch.object(providers, "ROOT", Path(temporary)), \
             patch.object(providers, "load_settings", return_value={"OPENAI_API_KEY": "documentation-placeholder", "OPENAI_MODEL": "documentation-mock"}), \
             patch.object(providers, "generate_json", side_effect=mock_director) as upstream, \
             sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1050}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("localStorage.setItem('persona-storyboard.ui-language', 'en')")
            url = f"http://127.0.0.1:{server.server_port}"
            page.goto(url)
            page.locator("#file").set_input_files(str(SAMPLE))
            expect(page.locator("#board-title")).to_have_text(document["brief"]["title"])
            page.locator("#library-save").click()
            expect(page.locator("#notice")).to_be_visible()
            page.evaluate("scrollTo(0, 0)")
            page.screenshot(path=str(IMAGES / "create-en.png"))

            for title in ["Before the rain stops / review copy", "Before the rain stops / working copy"]:
                saved = copy.deepcopy(document)
                saved["brief"]["title"] = title
                assert page.request.post(url + "/api/library/save", data={"document": saved}).ok
            page.locator("#nav-manage").click()
            expect(page.locator(".library-row")).to_have_count(3)
            page.set_viewport_size({"width": 1600, "height": 850})
            page.screenshot(path=str(IMAGES / "manage-en.png"))
            page.locator(".library-row").last.get_by_role("button", name="Convert to prompts", exact=True).click()
            expect(page.locator("#conversion-shots input")).to_have_count(6)
            page.locator("#conversion-auto-split").click()
            expect(page.locator("#conversion-plan-result h3")).to_be_visible()
            assert page.evaluate("visiblePlan.clips.map(c => c.duration)") == [15, 15]
            page.locator("#conversion-consent").check()
            page.locator("#conversion-run").click()
            expect(page.locator("#conversion-results .prompt-output").first).to_be_visible()
            assert upstream.call_count == 1
            page.set_viewport_size({"width": 1920, "height": 1250})
            page.evaluate("scrollTo(0, 0)")
            page.screenshot(path=str(IMAGES / "convert-en.png"))
            with page.expect_download() as downloading:
                page.get_by_role("button", name="Download all prompts as TXT", exact=True).click()
            downloading.value.save_as(str(ROOT / "examples/before-the-rain-stops.prompts.txt"))

            page.set_viewport_size({"width": 1440, "height": 1150})
            page.locator("#settings-open").click()
            expect(page.locator("#settings-dialog")).to_be_visible()
            page.locator("#settings-dialog").screenshot(path=str(IMAGES / "api-settings-en.png"))
            assert not errors, errors
            browser.close()
            print("PASS: four English screenshots, importable sample, 30s -> 15s + 15s, TXT export. Mock AI only; private data untouched.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
