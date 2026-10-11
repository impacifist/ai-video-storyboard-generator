"""Capture public documentation using authored samples and mocked AI.

Requires Playwright + Chromium. Never reads user settings or saved storyboards.
Run from the repository root: python tools/capture_showcase.py
"""

import argparse
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


def korean_document():
    document = sample_document()
    brief = json.loads((ROOT / "examples/rainy-classroom.json").read_text(encoding="utf-8"))
    for character, character_id in zip(brief["characters"], ["haru", "yuna"]):
        character["id"] = character_id
    document["brief"] = brief
    document["story"].update(summary="함께 가자는 말을 망설이던 하루에게 유나가 먼저 우산을 내민다.",
                             beats=["소매 끝에 드러난 망설임", "마음을 알아챈 유나", "나란히 걸어가는 두 사람"],
                             assumptions=["소개 화면을 위해 직접 작성한 예시입니다. AI 생성 결과가 아닙니다."])
    rows = [
        ("두 사람의 거리", "따뜻한 오후 빛이 책상 위에 내려앉고, 창문에는 빗방울이 맺힌다.",
         "하루가 창밖을 바라보는 동안 유나는 가방을 닫는다.", "아직 비 오네.", "와이드", "고정"),
        ("소매 끝에 담긴 망설임", "하루가 소매 끝을 만지작거리는 손을 가까이 잡는다.",
         "하루가 유나를 슬쩍 바라봤다가 눈을 내리깐다.", "우산을 안 가져왔어.", "클로즈업", "고정"),
        ("대답보다 먼저 오는 반응", "가방을 챙기던 유나가 손을 멈추고 하루에게 고개를 돌린다.",
         "유나가 부드럽게 웃으며 투명 우산을 집어 든다.", "내 우산 같이 쓰면 되지.", "미디엄", "천천히 다가가기"),
        ("부담 없이 건네는 제안", "유나가 투명 우산을 들어 보이며 자신의 옆자리를 비워 둔다.",
         "유나는 재촉하지 않고 기다린다. 하루가 조심스럽게 고개를 든다.", "같이 갈래?", "투 샷", "고정"),
        ("망설임이 풀리는 순간", "하루가 소매를 놓는다. 긴장했던 얼굴에 작은 미소가 번진다.",
         "하루가 고개를 끄덕이고 유나 쪽으로 한 걸음 다가간다.", "응. 같이 가자.", "클로즈업", "고정"),
        ("나란히 교실을 나서며", "따뜻한 오후 빛 속에서 두 사람이 나란히 교실 문으로 향한다.",
         "유나는 접힌 우산을 들고 하루와 보폭을 맞춰 걷는다.", "그럼 가자.", "와이드", "천천히 따라가기"),
    ]
    state_words = {
        "By the classroom window": "교실 창가", "Standing, holding her sleeve": "서서 소매 끝을 만진다",
        "Toward the rain": "창밖의 비", "Hesitant": "망설임", "Beside the next desk": "옆 책상 곁",
        "Standing beside her bag": "가방 옆에 서 있다", "Toward Haru": "하루 쪽", "Attentive": "상대에게 집중함",
        "Clear umbrella": "투명 우산", "Beside Yuna's schoolbag": "유나의 가방 옆", "In Yuna's right hand": "유나의 오른손",
        "Standing beside Yuna, hands relaxed": "손의 힘을 풀고 유나 옆에 서 있다", "Toward Yuna": "유나 쪽", "Relieved": "안도함",
        "At the classroom doorway": "교실 출입문 앞", "Walking side by side": "나란히 걸어간다",
        "Toward the corridor": "복도 쪽", "Content": "편안함",
    }
    for shot, row in zip(document["story"]["shots"], rows):
        purpose, visual, action, line, size, movement = row
        shot.update(purpose=purpose, visual=visual, actions=[action],
                    camera={"size": size, "angle": "눈높이", "movement": movement, "transition": "컷"},
                    continuity="인물의 화면상 위치와 따뜻한 오후 빛을 유지한다.")
        shot["dialogue"][0].update(text=line, delivery="작은 목소리로, 자연스럽게 쉬어 가며")
        for key in ["start_state", "end_state"]:
            for item in shot[key]["characters"] + shot[key]["props"]:
                for field, value in item.items():
                    item[field] = state_words.get(value, value)
    document["history"][0]["event"] = "소개 화면용 한국어 예시 작성"
    engine.validate_document(document)
    return document


def mock_director(provider, model, system, user, schema):
    request = json.loads(user)
    english_shots = {shot["id"]: shot for shot in sample_document()["story"]["shots"]}
    korean = any(not char.isascii() for char in request["plan"]["clips"][0]["shots"][0]["source"]["visual"])
    clips = []
    for clip in request["plan"]["clips"]:
        clips.append({
            "id": clip["id"], "context": "A classroom after school. Gentle rain and warm afternoon window light.",
            "subject_definitions": ("Character 1 (haru): short dark hair, navy uniform, reserved. Character 2 (yuna): long dark hair, navy uniform, considerate."
                                    if korean else "Haru: short dark hair, navy uniform, reserved. Yuna: long dark hair, navy uniform, considerate."),
            "summary": "A quiet invitation to walk home together.",
            "retention_analysis": "Maintain both character identities and the clear umbrella throughout.",
            "shots": [{"id": shot["id"],
                       "camera": {**english_shots[shot["id"]]["camera"], "layout": english_shots[shot["id"]]["visual"]},
                       "direction": " ".join(english_shots[shot["id"]]["actions"]),
                       "dialogue_language": "Korean" if korean else "English", "deliveries": ["Softly, with a natural pause" for line in shot["source"]["dialogue"]]}
                      for shot in clip["shots"]],
            "overall_soundscape": "Soft rain against the window, subtle fabric and footsteps.",
            "non_diegetic_music": "None; leave space for the pauses.",
        })
    return {"warnings": [], "notes": [], "boundaries": [], "reference_notes": [], "clips": clips}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=["en", "ko"], default="en")
    language = parser.parse_args().language
    korean = language == "ko"
    IMAGES.mkdir(parents=True, exist_ok=True)
    document = korean_document() if korean else sample_document()
    prefix = "before-the-rain-stops.ko" if korean else "before-the-rain-stops"
    sample = ROOT / f"examples/{prefix}.storyboard.json"
    sample.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
            page.add_init_script(f"localStorage.setItem('persona-storyboard.ui-language', '{language}')")
            url = f"http://127.0.0.1:{server.server_port}"
            page.goto(url)
            page.locator("#file").set_input_files(str(sample))
            expect(page.locator("#board-title")).to_have_text(document["brief"]["title"])
            page.locator("#library-save").click()
            expect(page.locator("#notice")).to_be_visible()
            page.evaluate("scrollTo(0, 0)")
            page.screenshot(path=str(IMAGES / f"create-{language}.png"))

            titles = ["비가 그치기 전에 / 검토용 사본", "비가 그치기 전에 / 작업용 사본"] if korean else ["Before the rain stops / review copy", "Before the rain stops / working copy"]
            for title in titles:
                saved = copy.deepcopy(document)
                saved["brief"]["title"] = title
                assert page.request.post(url + "/api/library/save", data={"document": saved}).ok
            page.locator("#nav-manage").click()
            expect(page.locator(".library-row")).to_have_count(3)
            page.set_viewport_size({"width": 1600, "height": 850})
            page.screenshot(path=str(IMAGES / f"manage-{language}.png"))
            page.locator(".library-row").last.get_by_role("button", name="프롬프트로 변환" if korean else "Convert to prompts", exact=True).click()
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
            page.screenshot(path=str(IMAGES / f"convert-{language}.png"))
            with page.expect_download() as downloading:
                page.get_by_role("button", name="전체 프롬프트 TXT 저장" if korean else "Download all prompts as TXT", exact=True).click()
            downloading.value.save_as(str(ROOT / f"examples/{prefix}.prompts.txt"))
            exported = (ROOT / f"examples/{prefix}.prompts.txt").read_text(encoding="utf-8")
            assert "C01 | 15s" in exported and "C02 | 15s" in exported
            for shot in document["story"]["shots"]:
                for line in shot["dialogue"]:
                    assert line["text"] in exported
                    exported = exported.replace(line["text"], "")
            assert all(not char.isalpha() or char.isascii() for char in exported)

            page.set_viewport_size({"width": 1440, "height": 1150})
            page.locator("#settings-open").click()
            expect(page.locator("#settings-dialog")).to_be_visible()
            page.locator("#settings-dialog").screenshot(path=str(IMAGES / f"api-settings-{language}.png"))
            assert not errors, errors
            browser.close()
            print(f"PASS ({language}): four screenshots, importable sample, 30s -> 15s + 15s, original dialogue, English directions, TXT export. Mock AI only; private data untouched.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
