"""Generation-only completion of character states omitted for off-screen cast."""

import copy

from .schema import ValidationError

FIELDS = ("position", "pose", "gaze", "emotion")
NEUTRAL = {"position": "화면 밖", "pose": "대기", "gaze": "화면 밖", "emotion": "차분함"}
NOTE_PREFIX = "누락된 인물 상태 자동 보완: "


def _entries(state):
    if not isinstance(state, dict) or not isinstance(state.get("characters"), list):
        raise ValidationError("상태 데이터의 캐릭터 목록이 올바르지 않습니다.")
    result, changed = {}, False
    for entry in state["characters"]:
        if not isinstance(entry, dict):
            changed = True
            continue
        character_id = entry.get("character_id")
        if not isinstance(character_id, str) or not character_id.strip() or character_id in result:
            changed = True
            continue
        result[character_id] = {"character_id": character_id, **{
            field: value if isinstance(value := entry.get(field), str) and value.strip() else ""
            for field in FIELDS}}
    return result, changed


def _fill(entries, ids, inherited, sibling):
    changed = bool(set(entries) - set(ids))
    result = {}
    for character_id in ids:
        existing = entries.get(character_id)
        if existing is None:
            existing = {"character_id": character_id}
            changed = True
        else:
            existing = copy.deepcopy(existing)
        for field in FIELDS:
            if existing.get(field, "").strip():
                continue
            value = next((source.get(field) for source in (inherited.get(character_id), sibling.get(character_id))
                          if isinstance(source, dict) and isinstance(source.get(field), str)
                          and source[field].strip()), "")
            existing[field] = value or NEUTRAL[field]
            changed = True
        result[character_id] = existing
    return result, changed


def complete_story(story, brief, locked_ids=()):
    """Complete model omissions before strict validation; annotate visible repairs."""
    ids = [character["id"] for character in brief["characters"]]
    locked_ids = set(locked_ids)
    previous_end = {}
    repaired_shots = []
    for shot in story["shots"]:
        start_state, end_state = shot["start_state"], shot["end_state"]
        start_entries, start_cleaned = _entries(start_state)
        end_entries, end_cleaned = _entries(end_state)
        start, start_filled = _fill(start_entries, ids, previous_end, end_entries)
        end, end_filled = _fill(end_entries, ids, start, previous_end)
        start_state["characters"] = [start[character_id] for character_id in ids]
        end_state["characters"] = [end[character_id] for character_id in ids]
        previous_end = end
        if shot["id"] not in locked_ids and (start_cleaned or end_cleaned or start_filled or end_filled):
            repaired_shots.append(shot["id"])

    if repaired_shots and len(story["assumptions"]) < 100:
        labels = ", ".join(repaired_shots[:8])
        if len(repaired_shots) > 8:
            labels += f" 외 {len(repaired_shots) - 8}개 컷"
        story["assumptions"].append(
            f"{NOTE_PREFIX}{labels}. 이전 컷 또는 화면 밖 기준으로 상태를 채웠으며, "
            "실제 등장과 행동은 화면·행동 설명을 따릅니다.")
    return repaired_shots


def complete_batch(batch, brief, previous_shots=()):
    """Fill a batch before its local validation, inheriting its handoff state."""
    ids = [character["id"] for character in brief["characters"]]
    previous_end = {}
    if previous_shots:
        try:
            previous_end, _ = _entries(previous_shots[-1]["end_state"])
            previous_end, _ = _fill(previous_end, ids, {}, {})
        except (KeyError, TypeError, ValidationError):
            previous_end = {}

    repaired = []
    for shot in batch["shots"]:
        start_state, end_state = shot["start_state"], shot["end_state"]
        start_entries, start_cleaned = _entries(start_state)
        end_entries, end_cleaned = _entries(end_state)
        start, start_filled = _fill(start_entries, ids, previous_end, end_entries)
        end, end_filled = _fill(end_entries, ids, start, previous_end)
        start_state["characters"] = [start[character_id] for character_id in ids]
        end_state["characters"] = [end[character_id] for character_id in ids]
        previous_end = end
        if start_cleaned or end_cleaned or start_filled or end_filled:
            repaired.append(shot["id"])

    if repaired and len(batch["assumptions"]) < 100 and not any(
            item.startswith(NOTE_PREFIX) for item in batch["assumptions"]):
        batch["assumptions"].append(
            f"{NOTE_PREFIX}{', '.join(repaired[:8])}. 이전 컷 또는 화면 밖 기준으로 상태를 채웠으며, "
            "실제 등장과 행동은 화면·행동 설명을 따릅니다.")
    return repaired
