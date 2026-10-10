# MiniMax H3 — conversion guide

Checked: 2026-10-10. Maintainer-authored summary, not a copy of the official manual.

Sources:
- https://github.com/MiniMax-AI/MiniMax-H3
- https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md
- https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md

## Official guidance summary

H3 output spans four to fifteen seconds. Ref2VA accepts up to nine images; FL2VA is a different mode and must not be substituted for character references.

Base rewriting uses integrated_multimodal_description, overall_soundscape, non_diegetic_music. Reference rewriting uses subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, non_diegetic_music in that order. A Subject represents reusable content, not an asset; multiple Pictures can define one Subject. Keep picture numbering consistent. Write section descriptions in English while retaining original-language dialogue. Use [Shot 1] without a timestamp, followed by [Shot N] At MM:SS.mmm for later shots. Assign speaker IDs in vocal appearance order. Dialogue uses <d>[Language] original words</d>. Keep ambient/physical sound separate from audience-only music.

## Application contract

This application supports T2VA without images and Ref2VA with character images. It does not implement frame conditioning, video/audio uploads, Context-IR API invocation or video rendering. References are attached manually in exported order; the text compiler sees metadata, not image pixels. Identity must be described using the supplied character and image notes without inventing appearance. Maintain clip-local timing and adjacent end/start states. User review remains necessary.
