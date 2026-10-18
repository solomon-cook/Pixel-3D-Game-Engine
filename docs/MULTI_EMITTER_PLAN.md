# Bounded multi-emitter runtime plan

17 October 2026. The renderer and scene contract still accept exactly one
emitter. A deterministic CPU sampling primitive now provides stable-ID source
seeds and sorted two-source `FireFrame` reconstruction; this is groundwork, not a
two-source runtime. This plan turns the existing stable emitter/profile/light IDs
into a testable two-source runtime without changing the single-source baseline.

## Current boundary

- Scene validation requires exactly one emitter. `shadow_matrices`, post heat
  shimmer and inked smoke still use one source position/profile. Per-emitter
  smoke simulation is implemented; the soft atmosphere/optical secondary-source
  branch is prepared but unreachable while validation remains single-source.
- `FireFrame` owns one 256-primitive pool and at most 12 derived particle lights.
  O03 builds one emitter's tile candidates; overflow correctly falls back to
  exhaustive evaluation, but there is no multi-source stress evidence.
- The CPU storage packer now merges sampled source candidates into the shared
  12-light budget by descending power, then stable emitter ID and event identity.
  It stores the selected lights in source zero's shared-light slot and reports
  local plus global drops. The live scene contract still runs only the one-source path.
- The GPU fire-storage ABI now reserves two contiguous `FireFrame` slots. A
  fixed-tick M1 Max/Metal
  comparison is byte-identical to the prior single-frame ABI; the known
  allocation increases by 12,928 bytes. The renderer has a keyed multi-source
  sampling/upload path, but validation prevents a two-source runtime. See
  [storage ABI evidence](measurements-multi-emitter-storage-abi.json).
- Fire tile construction and flame shading now iterate both frame slots. Tile
  indices encode source slot and primitive index; overflow evaluates each
  source's complete primitive pool. The source-zero capture remains byte-identical
  on M1 Max/Metal. No live two-source scene has exercised this shader path; shadow
  sets and fire lighting remain single-source. See
  [fire consumer evidence](measurements-multi-emitter-fire-consumer.json).
- The renderer now owns the two-slot storage value and uploads it as a unit. The
  CPU packer preserves legacy sampling for one source and sorts multi-source
  frames by stable ID; tests cover one-source byte parity and two-source reorder
  stability. The scene contract still prevents this two-source packer from being
  reached by a live scene. A fixed-tick capture after the storage upload remains
  byte-identical; see [storage packing evidence](measurements-multi-emitter-storage-packing.json).
- Each storage slot now also carries its source origin. The flame detail mask
  uses that origin for slot one while retaining the legacy uniform origin for
  slot zero. The capture remains pixel-identical, and the added origin metadata
  costs 32 known bytes.
- Each slot now carries its palette, breakup, shape, pixel-treatment and source
  intensity values. Flame shading selects the slot-one presentation independently;
  source zero still uses the legacy globals. The storage grows by another 192
  known bytes, and the fixed-tick capture remains pixel-identical. The live
  renderer still fills slot zero only, so this is not dual-source visual
  acceptance. See [per-source presentation evidence](measurements-multi-emitter-presentation.json).
- `Renderer::update_globals` now has a keyed multi-source branch that builds
  `FireKey`s in stable-ID order, packs both frames (including the shared particle
  lights), tracks projected-detail hysteresis independently per source, and
  rebuilds/uploads when source state or a source's detail tier changes. Current
  scene validation still requires one emitter, so this upload branch is not
  reachable from a live scene. It has not been validated with two frames on the
  GPU; shadows and opaque/heat lighting remain single-source. The existing
  single-source profiling-heavy fixed-tick RGBA capture remains byte-identical
  on M1 Max/Metal (SHA-256 `9faedb7b757c5043e8bf006f3e1bbffa0d4240e8ef6f0a2a85260612212a4a48`).
- Smoke compute now allocates a separate ping-pong density/temperature pair and
  source-config uniform per emitter, sorts those slots by stable ID, and dispatches
  one advection pass per source. Bounds, buoyancy, dissipation, density and thermal
  settings are source-local; reset clears every allocated source volume. Scene
  validation still allows one emitter. The soft atmosphere/optical shader has
  secondary-volume sampling, while inked smoke, heat and absorption-cache shading
  still use source zero. There is no two-source GPU capture or performance result
  yet. The current single-source RGBA capture
  remains pixel-identical, with the 80-byte source config reflected in the known
  fixed-buffer inventory; see [smoke compute evidence](measurements-multi-emitter-smoke-compute.json).
- The soft atmosphere integral now binds and samples a second source-local smoke
  volume in its fixed world-space domain. Camera-to-flame absorption includes that
  field, and the optical material pass shares the same integral. Stable-ID slot
  zero now owns the legacy global domain when multiple sources are prepared. The
  source-count guard leaves the one-emitter integral unchanged. Inked smoke,
  heat/refraction, source-specific lighting and cache construction remain
  incomplete; validation still prevents a live two-source GPU capture.
  The fixed-tick `profiling-heavy.json` hero capture remains pixel-identical at
  640×360 (SHA-256 `9faedb7b757c5043e8bf006f3e1bbffa0d4240e8ef6f0a2a85260612212a4a48`).
  See [atmosphere evidence](measurements-multi-emitter-atmosphere.json).
- One 48×64×48 Rg16Float density/temperature pair occupies 1,179,648 bytes.
  One point-light cubemap set occupies 1,572,864 bytes. The 8 authored point
  lights and 12 derived particle lights are global renderer budgets.

## Proposed first runtime limit

Start with **two** emitters, each with a stable scene ID, `effect_profile`, and
unique colocated `light_id`. Keep the existing single-source scene and output
byte-identical. Do not accept a scene with more emitters until both are rendered
and simulated; there must be no silent first-emitter-only behavior.

Give each source its own deterministic FireFrame and smoke density/temperature
pair. The CPU sampler in `crates/engine/src/effects.rs` now rejects more than two
sources and duplicate IDs, derives event seeds from the user seed plus a stable
FNV-1a hash of the emitter ID, and sorts source processing by stable ID. Tests
confirm replay, array-reorder invariance, event identity stability and independence
when one source changes. Renderer-owned per-source smoke resources, reset,
dispatch and offscreen simulation are implemented; live two-source scene
acceptance and rendering remain incomplete.

Use a fixed per-source smoke domain around each emitter so distant sources do not
shrink the existing 48×64×48 resolution. Each source gets its own thermal output,
cooling and lift settings. Composite density/temperature contributions in the
shading path with a bounded two-source loop. The pixel grid remains unchanged.

Retain the global eight authored-light limit and 12 derived-light limit. Reserve
one authored primary light per emitter; choose derived lights across both fires
by stable descending power with ID/event tie-breaks. Give each primary fire light
its own six-face shadow set, subject to the existing per-face invalidation and
culling rules. Extend tile-list construction to include both sources; preserve
the exhaustive overflow fallback and report per-source plus aggregate occupancy.

## Estimated fixed costs at 640×360

The second source adds approximately 1,179,648 bytes for its smoke volumes,
1,572,864 bytes for its primary-light cubemap, and 12,336 bytes for one current
FireFrame, before bind groups, source uniforms, transient resources, or driver
alignment: about **2.77 MB** known additional resource bytes. Two smoke dispatches
suggest roughly twice the current 0.0205 ms median smoke-compute stage, but this
is a linear estimate only; profile it on hardware. Rendering may grow more than
linearly in crowded tiles because it adds flame candidates and another volume
contribution. Existing tile overflow must remain correct under that load.

## Delivery and acceptance gates

1. Add validation tests for two unique emitters, profile references, unique
   primary-light ownership, bounds, and an explicit maximum. Preserve old v1
   single-emitter JSON loading.
2. Add deterministic CPU tests: same seed/tick/source ID replays; changing one
   source does not alter the other source's frame; reordering scene emitters
   preserves each source's frame and event identities.
3. Add a two-fire scene with separate profiles, positions and light IDs. Capture
   each source alone and together at named cameras, fixed seed/ticks and the
   selected 640×360 grid. Inspect close, shared-screen and orthographic views.
4. Stress maximum fire primitives, 8 authored lights, 12 derived lights, crowded
   tile overflow, reset/replay, paused edits, camera motion, offscreen simulation,
   shader reload rollback and resource recreation. Report dropped budgets.
5. Measure serial GPU stages, smoke compute, CPU update/upload, allocations and
   full frame work against the single-source baseline. Keep source ordering,
   light selection and visual output deterministic on the same device.
6. Verify Metal first, then run the same scene/captures on Windows/DX12 and at
   least one other adapter before claiming portability. Keep the two-source cap
   until those results and the memory budget pass.

No multi-emitter rendering/simulation runtime, visual result, performance gain or
target hardware support is implied by this plan or the deterministic CPU sampler.
