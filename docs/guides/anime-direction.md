# Japanese 2D animation direction

Application direction policy, used in storyboard generation, revision, review and video conversion. Default to Japanese 2D animation when the brief does not specify another medium. An explicit user style overrides this default. This does not imply Japanese dialogue. Preserve assigned dialogue languages and the application's output-language contracts.

## Layout before camera spectacle

Design the opening composition and the space needed for the whole action, not merely a pleasing still image. State the primary subject, its screen placement and scale, eye level, foreground/background relationships and relevant prop placement. Leave room for the planned movement. Maintain readable silhouettes and an unambiguous focus of attention. Do not add background details that compete with the story point.

For quiet 2D dialogue scenes, prefer stable layouts and selective character animation. Holds, eye movements, restrained head turns, hand acting and delayed reactions can carry the beat. A held composition is not a frozen or lifeless performance. Choose broader action for a brief that calls for it; do not impose elastic 3D acting on every scene. Avoid gratuitous orbits, handheld shake, lens effects or continuous zooms. A move is appropriate when it reveals information, follows necessary action or changes the intended emphasis.

## Acting and editing

Make the stimulus, its recognition, and the character's response legible. Do not pile multiple unrelated expressions and body actions onto the same instant. Allow anticipation and a readable settling pose where useful, including subtle anticipation in restrained acting. Preserve the user's dramatic tempo instead of assigning a fixed pause to every line.

Each source shot is one continuous camera view. A new angle reached by an edit belongs to the next shot; a camera move remains inside the current view. Identify the cut's motivating event and the next shot's opening attention target. Separate a shot's ending transition from its internal camera motion. Preserve eyelines and movement direction. Default to a clear cut when no alternative is specified; do not replace source transitions with dissolves, morphs or camera travel merely to make the sequence seem smooth.

Use the existing storyboard fields for this design: purpose for the viewing reason, visual for layout, actions for acting progression, camera for framing/angle/movement/transition, continuity for the handoff. Do not add schema fields during storyboard generation. Before output, mentally play the sequence in time: can the viewer locate the characters, follow the attention shift, read the response and understand the cut? Review concerns are advisory, not automatic save failures.

## Conversion preserves the design

Translate the approved camera and layout into the required English camera component for every planned segment. Preserve its source size, angle, movement and transition; do not redesign an approved storyboard during conversion. Describe the primary subject and its placement in camera.layout. Keep direction for acting, with no contradictory camera instructions. The renderer emits these camera fields explicitly. Do not put timestamps or dialogue in camera fields.

A technical 15-second split may divide a single source shot. Continue the same view, ongoing motion and canonical state without restarting a move or treating the split as a new edit. Only the segment that ends the source shot receives its ending transition. Do not invent the next shot's action inside the current shot or invent an additional shot after the selected plan ends.

Repeat the same source camera size, angle, movement and transition translations for split portions; the renderer binds them once from the first supplied portion. Layout may describe the evolving segment state but must agree with that shared camera design. For a 2D brief, explicitly identify Japanese 2D animation in clip context rather than leaving the medium to inference.

Avoid calling a whole shot locked while also prescribing a zoom or orbit. If an approved shot intentionally holds then moves, describe the phases clearly in movement. If the approved source itself is contradictory, preserve the intended content and report the ambiguity in advisory notes for revision; do not silently choose a new camera design. In generation, simplify an overloaded shot or distribute acting across the requested shots before finalizing. Do not squeeze a long speech into a short slot by instructing unnaturally fast delivery. In conversion, flag timing uncertainty in notes and preserve original speech and allocation; do not retime an approved plan automatically.

Sources and adaptation decisions: storyboard-direction-research.md. These are practical application choices, not a claim that every Japanese production uses one directing style.
