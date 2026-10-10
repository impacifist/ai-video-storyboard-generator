"""Non-destructive dialogue allocation and explicit shared split boundaries."""

import copy
import math


def speech_seconds(lines):
    # Same rough characters/second heuristic as local storyboard review; not measured audio.
    return round(sum(len("".join(line["text"].split())) for line in lines) / 5, 2)


def retimed(document, selected):
    result = copy.deepcopy(document)
    for shot in result["story"]["shots"]:
        if shot["id"] in selected and shot["dialogue"]:
            shot["duration"] = max(shot["duration"], math.ceil(speech_seconds(shot["dialogue"]) + .5))
    return result


def decorate(document, layout):
    originals = {shot["id"]: shot for shot in document["story"]["shots"]}
    entries = [(clip, shot) for clip in layout["clips"] for shot in clip["shots"]]
    layout["boundaries"] = []
    for index, (clip, shot) in enumerate(entries):
        if shot.get("continues_from_previous"):
            shot["source"].pop("start_state", None)
        if shot.get("continues_in_next"):
            shot["source"].pop("end_state", None)
            next_clip, next_shot = entries[index + 1]
            key = f"B{len(layout['boundaries']) + 1:02d}"
            shot["exit_boundary_id"] = key
            next_shot["entry_boundary_id"] = key
            original = originals[shot["id"]]
            layout["boundaries"].append({"id": key, "source_shot_id": shot["id"],
                "source_offset": shot["source_end"], "from_clip": clip["id"], "to_clip": next_clip["id"],
                "original_start_context": copy.deepcopy(original["start_state"]),
                "original_end_context": copy.deepcopy(original["end_state"])})

    if layout["split_mode"] == "fixed":
        for key, original in originals.items():
            segments = [s for _, s in entries if s["id"] == key]
            if not segments:
                continue
            remaining = [round(s["end"] - s["start"], 6) for s in segments]
            for segment in segments:
                segment["source"]["dialogue"] = []
                segment["dialogue_indices"] = []
            lines = copy.deepcopy(original["dialogue"])
            whole = speech_seconds(lines)
            owner = next((i for i, capacity in enumerate(remaining) if capacity >= whole), None)
            if owner is not None:
                segments[owner]["source"]["dialogue"] = lines
                segments[owner]["dialogue_indices"] = list(range(1, len(lines) + 1))
            else:
                # Keep line order and never split or duplicate an utterance. Uncertain fits become notes.
                cursor = 0
                for line_index, line in enumerate(lines, 1):
                    needed = speech_seconds([line])
                    fitting = next((i for i in range(cursor, len(segments)) if remaining[i] >= needed), None)
                    cursor = fitting if fitting is not None else max(range(cursor, len(segments)), key=remaining.__getitem__)
                    segments[cursor]["source"]["dialogue"].append(line)
                    segments[cursor]["dialogue_indices"].append(line_index)
                    remaining[cursor] -= needed

    layout["notes"] = []
    for clip, shot in entries:
        estimated = speech_seconds(shot["source"]["dialogue"])
        available = round(shot["end"] - shot["start"], 6)
        shot["speech_estimate_seconds"] = estimated
        if estimated > available:
            layout["notes"].append(f"{clip['id']} {shot['id']}: 대사 예상 {estimated:g}초 / 배정 {available:g}초. "
                                   "실제 음성 측정 전 추정치입니다. 대사 시간 확보 방식으로 다시 계획하거나 낭독 시간을 확인하세요.")
    return layout
