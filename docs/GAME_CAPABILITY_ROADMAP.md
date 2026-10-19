# Game capability roadmap

## Purpose

This is a proposed roadmap for growing Pixel Engine from a renderer and authoring
lab into a reusable desktop game engine. It describes capabilities that support
multiple games, including 2.5D and freely explored 3D games. It is not a plan to
recreate a particular title.

The renderer, deterministic scene contract and shared Session operations are a
foundation. They are not yet a complete gameplay runtime, animation pipeline,
content editor or shipping toolchain. Preserve the boundary between
`pixel-engine` (reusable engine/runtime) and `engine-lab` (host, inspector,
transport and development tools).

## Design constraints

- Preserve freely explored 3D as a real engine capability. 2.5D constraints
  should be selectable game or level configuration, not assumptions baked into
  the renderer or world model.
- Keep the chosen pixel density explicit and stable. Allow intentional style
  changes, but do not reduce it automatically to recover performance. Scale
  effects, simulation and other quality budgets independently.
- Keep authored state readable, versioned and inspectable. Runtime edits from
  tools and automation should use shared engine operations with validation.
- Keep deterministic fixed-tick capture and seeded procedural content as
  first-class workflows. Gameplay may add controlled nondeterminism, but must
  identify it and support repeatable debugging.
- Add systems in independently useful slices. Avoid a universal editor,
  scripting language or physics feature set before a concrete game workflow
  proves its requirements.
- Keep renderer approximations, optional quality paths and platform acceptance
  limits visible in `docs/STATUS.md` and `docs/RESEARCH.md`.

## Current foundation

Implemented foundations include a separate engine crate and lab crate,
versioned/validated JSON scenes, static opaque GLB and PNG assets, seeded
fixed-step simulation, perspective and orthographic cameras, lights and
shadows, pixel-buffer presentation, materials and effects, fixed-tick captures,
benchmarks and shared Session commands. Scene topology and assets are startup
data; only supported uniform-backed values and selected object transforms are
currently editable live.

The current scene contract does not include skeletal or GLB animation, general
alpha materials, gameplay entities, collision, input actions, navigation,
dialogue, audio, save data, district streaming or a full scene editor. These are
roadmap items, not existing capabilities. See `README.md`, `docs/ARCHITECTURE.md`
and `docs/STATUS.md` for current details and validation limits.

## Relationship to O01–O08

The game-capability roadmap follows the renderer foundation work in O01–O08.
The ordered O01–O08 acceptance work remains governed by
[`O01-O08_FOLLOWUP_PLAN.md`](O01-O08_FOLLOWUP_PLAN.md), with implementation and
platform evidence tracked in [`STATUS.md`](STATUS.md). O01–O08 are not all
finished: several implementations and M1 Max/Metal measurements exist, while
visual, sustained-motion, Windows/DX12, other-adapter and target-hardware gates
remain open. Do not treat this roadmap as evidence that those gates passed.

Before the game-runtime work becomes the primary implementation track:

1. Complete or explicitly disposition each remaining O01–O08 follow-up gate.
   A decision to retain a baseline or reject an experiment is a valid
   disposition; a candidate does not need to be promoted just to close its
   workstream.
2. Keep implementation, correctness, visual review, performance decision and
   target-platform verification as separate recorded states in `STATUS.md`,
   `RESEARCH.md` and the measurement reports.
3. Carry the accepted performance evidence and unresolved hardware limits into
   the game-runtime budgets. Do not infer Windows or target-PC rendering support
   from a successful build or Metal-only measurements.

O01–O08 then continue as the profiling and renderer-maintenance track alongside
game development. Their outputs inform capability work as follows:

| O work | What the game roadmap builds on | Boundary to preserve |
|---|---|---|
| O01 profiling and operation counters | Baselines for animation, world simulation, crowds, streaming and complete-frame cost | Keep diagnostic overhead and overlapping GPU stages visible; measure representative routes, not only isolated effects |
| O02 shadow reuse and invalidation | Revision-based invalidation as moving actors and authored worlds change | Reuse only with correct invalidation; uncertain state falls back to redraw |
| O03 bounded tile lists | Measured scaling for effects and local lights as scenes become busier | Keep overflow fallback correct and include list-build cost; do not infer arbitrary actor scalability from a bounded effects path |
| O04 projected detail | Explicit effect/detail budgets as scene content becomes larger | Scale effect quality independently; never silently lower the selected pixel grid |
| O05 smoke absorption cache | A measured pattern for caching derived simulation/render data | Keep opt-in or omit when sustained total-frame evidence does not justify cost |
| O06 optical specialization | Workload-specific handling for reflective/transmissive materials | Preserve direct-shading fallback and image-quality gates; do not generalize a narrow result |
| O07 bounds, shared meshes, culling, instancing and transforms | Existing per-object metadata and measured geometry-submission paths for larger worlds | Gameplay entities, animation, and GPU draw instances remain separate concepts; retain exhaustive/correctness paths |
| O08 resource and pass layout | Allocation/lifetime accounting and adapter-aware resource choices for new runtime systems | Profile each new allocation and pass; keep fallbacks and avoid adopting layout changes on memory savings alone |

The current follow-up plan may establish only workload-specific or Metal-only
acceptance. Carry those limits forward explicitly. Runtime work can use proven
contracts such as stable object IDs, bounds and Session operations, but must not
claim that those contracts already provide gameplay entities, skeletal
animation, collision or general world streaming.

## Workstreams after the O01–O08 transition

### 0. Runtime boundary and game data contract

**Goal:** Define how a game uses the engine without making the lab itself the
game runtime.

**Engine work:**

- Introduce a game-runtime layer that owns the fixed-step loop, world lifecycle,
  input sampling, game state and save/load coordination.
- Define stable, versioned identifiers for entities, assets, scenes, events and
  authored resources. Keep rendering objects as presentation data attached to
  gameplay entities, rather than making render objects the gameplay model.
- Separate immutable authored definitions from mutable runtime state. Specify
  validation, defaults, migrations and deterministic serialization before
  expanding the scene schema.
- Route editor, native host, headless tools and future game hosts through shared
  engine APIs. Keep diagnostics on the diagnostic channel and responses on the
  command channel.
- Establish lifecycle/error rules for scene load, unload, reset, pause, resume,
  save and shutdown.

**Acceptance evidence:** A small non-rendering runtime can load a versioned
world, advance fixed ticks, pause/resume, serialize state, reload it and produce
the same result from the same inputs. A malformed asset or command produces a
recoverable error without corrupting the running session.

**Depends on:** Existing scene validation and Session contract.

### 1. Art, assets and animation

**Goal:** Make authored animated characters and props first-class alongside
static geometry and procedural effects.

**Engine work:**

- Choose and document supported sources: retain static GLB/PNG; add GLB skeletal
  animation and skinning, and a versioned sprite-sheet/flipbook asset for
  hand-authored pixel animation. Define coordinate, frame rate, pivot, palette,
  filtering and import rules.
- Add alpha-tested/cutout and appropriately blended materials with explicit
  sorting/depth behavior. Do not treat every transparent asset as one render
  path.
- Add animation clips, looping, blending, state transitions, playback speed,
  events/markers and deterministic seek/sample by fixed tick. Expose the same
  controls to gameplay and inspection tools.
- Add asset dependency tracking, validation, hot-reload rules and useful import
  diagnostics. Keep failed reloads transactional so working assets remain live.
- Specify how high-resolution hand-authored pixels, 3D geometry, lighting and
  the selected scene pixel grid compose. Support per-asset source resolution
  without silently changing the output grid.

**Acceptance evidence:** A deterministic character run/jump/turn sequence and a
mixed sprite/3D scene render correctly from named cameras at fixed ticks. Alpha
ordering, palette/texture filtering, animation event timing and reload rollback
have explicit image and runtime checks. Compare motion, not only a still.

**Depends on:** Runtime data contract; asset identity and versioning.

### 2. World, camera, input and physical interaction

**Goal:** Provide reusable movement and interaction primitives while allowing a
game to choose its own camera and movement constraints.

**Engine work:**

- Add action-based input mapping for keyboard, mouse and controller, with
  rebinding, focus/capture rules, dead zones and input recording/replay.
- Add collision shapes, spatial queries, sweep tests, triggers and a fixed-step
  character controller. Establish units, timestep, collision layers, slopes,
  steps, moving platforms and deterministic resolution rules.
- Add configurable movement constraints (free 3D, plane, lane/depth bands or
  authored rails) and camera rigs (follow, rail, fixed composition, transitions
  and scripted shots). Constraints belong to game/world data, not a global
  renderer mode.
- Add interaction affordances and a small set of engine-level primitives such
  as activate, inspect, use and conversation start. Game-specific rules remain
  in game data or game code.
- Add a navigation representation only after collision and world chunk
  boundaries are settled; support both authored paths and generated navigation
  where useful.

**Acceptance evidence:** A playable test map supports keyboard and controller,
repeatable movement/collision, interaction, camera transitions and deterministic
input replay. Run the same gameplay inputs at the same fixed ticks and compare
state and captures. Demonstrate both constrained movement and unconstrained 3D.

**Depends on:** Runtime loop, stable entity transforms and animation interface.

### 3. Gameplay state, events and narrative interactions

**Goal:** Let game authors compose interactions and sequences without coupling
gameplay logic to render passes or lab UI widgets.

**Engine work:**

- Add a typed event/command model for gameplay (input actions, triggers,
  interaction results, animation markers, scene changes and save checkpoints).
- Define a composable interaction model with conditions, actions, cooldowns,
  priorities and clear ownership of persistent state.
- Add data-authored dialogue with speaker, text, choices, conditions, effects,
  localization keys and state persistence. Keep dialogue UI themeable and
  separate from the dialogue data/runtime.
- Support scripted sequences and authored camera/animation/audio cues with
  deterministic start, interruption, skip and resume behavior.
- Select a narrow extension mechanism: data-driven graphs or a constrained
  scripting interface. Keep privileged engine operations typed, validated and
  inspectable; do not introduce an unrestricted language until real game needs
  justify it.
- Add save slots, schema versions, migration and recovery for authored game
  state.

**Acceptance evidence:** A sample level combines exploration, a conditional
interaction, branching dialogue, an interrupted sequence and save/reload. State
transitions are inspectable and repeatable, and invalid game data is reported
with asset/entity context.

**Depends on:** Runtime lifecycle, input/actions, stable IDs, serialization.

### 4. NPCs, simulation and world scale

**Goal:** Scale from a few authored actors to busy spaces without requiring
every actor to run full gameplay and rendering cost all the time.

**Engine work:**

- Add reusable actor/behavior building blocks: schedules, waypoint/path
  following, perception, attention, simple reactions, conversation state and
  reset/return-to-routine behavior.
- Separate high-detail nearby simulation from cheaper distant/background
  updates. Make update frequency, activation radius and fidelity explicit and
  measurable; do not silently change visual pixel density.
- Add scene/district partitioning, asynchronous load/unload, transition
  boundaries, persistent state handoff and streaming diagnostics.
- Provide crowd/render batching and animation update strategies that preserve
  identity, ordering and predictable behavior. Establish entity-count and
  memory budgets from measured representative scenes.
- Integrate authored and procedural generation through reproducible seeds,
  constraints, style controls and inspectable generated outputs.

**Acceptance evidence:** A representative multi-area route measures loading,
memory, simulation, rendering and presentation over sustained play. Nearby NPCs
retain gameplay behavior; distant/background agents use documented cheaper
updates. Replaying the same seed/input yields the same authored/generated
layout and relevant gameplay decisions.

**Depends on:** Entity/component lifecycle, navigation, save state and profiling.

### 5. Audio, UI and player-facing presentation

**Goal:** Make presentation a shared engine service that responds to game state
and supports accessible, localizable player experiences.

**Engine work:**

- Add spatial audio emitters/listeners, buses, snapshots/mix states, occlusion
  hooks, streaming music and sound-event playback. Keep audio backend and asset
  formats replaceable behind a small engine interface.
- Add world/UI event hooks so ambience, dialogue, music and sound cues respond
  to game state without polling render internals.
- Provide reusable UI primitives for prompts, dialogue, menus, subtitles,
  settings and accessibility. Keep game identity/theme in authored UI data.
- Add localization keys and font/glyph coverage checks; support subtitle timing,
  text scale, remapping and other core accessibility settings.

**Acceptance evidence:** A small scene mixes spatial ambience, a state change,
dialogue/subtitles and a transition without audio pops or stale emitters. Verify
pause/focus, volume settings, subtitle timing, localization fallback and
keyboard/controller operation.

**Depends on:** Event model, state lifecycle and asset pipeline.

### 6. Authoring tools and content workflow

**Goal:** Make the engine practical for a team to create, inspect and revise
content without making every change a code task.

**Engine/lab work:**

- Evolve the inspector into a scene editor using shared Session operations:
  hierarchy, transform, camera, light, material, effect and animation views.
- Add reusable prefabs/scene composition, asset browser, validation reports,
  undo/redo and clear dirty/save state. Keep scene files reviewable in version
  control and define conflict boundaries for team editing.
- Add focused authoring surfaces for input maps, interaction graphs, dialogue,
  NPC routes/schedules, audio zones and camera sequences as those runtime
  contracts stabilize.
- Add play-in-editor, pause/step, time controls, entity inspection, event/state
  traces, deterministic capture and replay from the same engine operations.
- Add build/import automation and source-to-runtime asset manifests; report
  missing, stale and unsupported assets before packaging.

**Acceptance evidence:** An author can create and revise the vertical-slice
level, animation, interaction and dialogue through documented files/tools,
reopen it without data loss, inspect runtime state and reproduce a reported
issue from a capture/replay bundle.

**Depends on:** Stable data contracts for each authored feature. Build the
smallest useful authoring surface alongside each feature rather than attempting
a complete editor up front.

### 7. Shipping, portability and operations

**Goal:** Turn the runtime into a dependable desktop product foundation.

**Engine work:**

- Define target hardware and budgets for CPU, GPU, memory, load times and
  sustained frame pacing at representative selected resolutions.
- Implement graphics capability detection and documented fallbacks; validate
  actual rendering on each claimed backend. Compilation alone is not acceptance.
- Add packaging, asset cooking, crash/log collection, settings persistence,
  save backup/recovery, controller detection and clean shutdown.
- Add content and runtime compatibility checks for upgrades, with explicit
  behavior when a save or asset version cannot be migrated.
- Keep profiling and fixed-input capture available in packaged builds or a
  development build mode, with sensitive/player data excluded by default.

**Acceptance evidence:** Install and play the vertical slice on each supported
hardware/backend target. Measure sustained routes, scene transitions, memory,
frame pacing and recovery from malformed content or interrupted saves. Record
results and unresolved gates in `docs/STATUS.md`.

**Depends on:** A representative content slice and chosen target platforms.

## First capability slice

Do not attempt all workstreams before making something playable. The first
cross-system slice should prove:

1. One authored 3D environment with explicit pixel density, lighting and a
   camera that can use either free 3D movement or a constrained 2.5D path.
2. One animated controllable character with repeatable movement and collision.
3. A few static and animated actors, one interaction and one short branching
   dialogue sequence.
4. One simple NPC route/reaction, spatial ambience and subtitles.
5. A save/reload boundary, deterministic replay/capture and basic packaging.

This slice is a capability test, not a genre commitment. It should be deliberately
small, but use the same reusable runtime contracts intended for larger games.

## Cross-cutting acceptance gates

- **Visual:** matched fixed-tick captures plus continuous-motion review at the
  selected output grid; evaluate compositing, silhouettes, temporal stability
  and readability. A still or automated test cannot certify the art direction.
- **Determinism:** fixed-tick replay on the same device reproduces gameplay
  state and captures; cross-device GPU output uses documented tolerances.
- **Performance:** representative sustained routes measure simulation, render,
  loading, memory and presentation. Keep stage timing distinct from whole-frame
  and native-window results.
- **Portability:** actual GPU/runtime validation per target backend. Keep
  unverified targets listed in `docs/STATUS.md`.
- **Authoring:** bad inputs fail with useful context; edits are inspectable,
  undoable or safely recoverable; native, headless and tool workflows share
  engine operations.
- **Scope control:** each capability is promoted from proposed to implemented
  only after its acceptance evidence exists. Visual or performance experiments
  retain independent baselines and records in `docs/RESEARCH.md`.

## Proposed dependency order after O01–O08 disposition

O01–O08 follow-up and recorded dispositions → runtime/data contract →
animation/assets and input/world basics → playable character slice →
interaction/dialogue/save → NPC simulation and audio → district streaming and
authoring expansion → target-hardware shipping gates. Focused tools should
accompany each stable data contract. O01 profiling and applicable O02–O08
renderer work continue on their own evidence-led track and should not be
represented as gameplay-runtime progress.
