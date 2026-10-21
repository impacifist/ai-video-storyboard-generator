"""Mock direction components; intentionally contain no original spoken words."""

import copy


def direction_output(layout, assets=()):
    boundaries = []
    for boundary in layout.get("boundaries", []):
        state = copy.deepcopy(boundary["original_start_context"])
        for character in state["characters"]:
            character.update(position="Beside the seat", pose="Sitting upright", gaze="Toward the other character", emotion="Attentive")
        for prop in state["props"]:
            prop.update(english_name="Phone", position="On the seat")
        boundaries.append({"id": boundary["id"], "state": state})
    return {"warnings": [], "notes": [], "boundaries": boundaries,
        "handoffs": [{"id": h["id"], "bridge": "Continue the approved gesture and response at the same conversational pace.",
                      "sound_bridge": "Keep the established room ambience continuous."} for h in layout.get("handoffs", [])],
        "reference_notes": [{"label": a["label"], "target_name": "Phone" if a.get("kind") == "prop" else "Lighting" if a.get("kind") == "other" else "", "note": "Preserve the specified reference attributes." if a["note"] else ""} for a in assets], "clips": [{
        "id": clip["id"], "context": "A quiet classroom; consistent lighting and character identity.",
        "subject_definitions": "Preserve the supplied character identities.", "summary": "A restrained interaction.",
        "retention_analysis": "Preserve facial identity and clothing from assigned references.",
        "shots": [{"id": shot["id"], "direction": "Follow the planned action with subtle expressions.", "pacing_weight": 1,
                   "speech_cues": [{"speaker": line["speaker"], "mode": "unspecified", "onset": "Begin the assigned line with the approved gesture or response."} for line in shot["source"]["dialogue"]],
                   "camera": {"size": "Medium shot", "angle": "Eye level", "movement": "Locked camera",
                              "transition": "Cut on the reaction", "layout": "Character 1 on the left, Character 2 on the right."},
                   "dialogue_language": "Korean", "deliveries": ["Very quietly" if line["delivery"] else "" for line in shot["source"]["dialogue"]]} for shot in clip["shots"]],
        "overall_soundscape": "Quiet room ambience.", "non_diegetic_music": "N/A"} for clip in layout["clips"]]}
