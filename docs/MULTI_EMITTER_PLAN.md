# Bounded multi-emitter runtime plan

17 October 2026. The renderer and scene contract still accept exactly one
emitter. A deterministic CPU sampling primitive now provides stable-ID source
seeds and sorted two-source `FireFrame` reconstruction; this is groundwork, not a
two-source runtime. This plan turns the existing stable emitter/profile/light IDs
into a testable two-source runtime without changing the single-source baseline.

## Current boundary

- Scene validation requires exactly one emitter. `Renderer::update_globals`,
  `shadow_matrices`, the smoke compute shader, post heat shimmer and the fire
  shading shaders use one source position/profile.
- `FireFrame` owns one 256-primitive pool and at most 12 derived particle lights.
  O03 builds one emitter's tile candidates; overflow correctly falls back to
  exhaustive evaluation, but there is no multi-source stress evidence.
- The CPU now has a pure global particle-light selector that merges sampled
  source candidates into the shared 12-light budget by descending power, then
  stable emitter ID and event identity. The renderer does not call it yet.
- The GPU fire-storage ABI now reserves two contiguous `FireFrame` slots, and
  the current shaders still read only slot zero. A fixed-tick M1 Max/Metal
  comparison is byte-identical to the prior single-frame ABI; the known
  allocation increases by 12,928 bytes. This is capacity groundwork only: the
  renderer still samples, uploads and renders one source. See
  [storage ABI evidence](measurements-multi-emitter-storage-abi.json).
- Fire tile construction and flame shading now iterate both frame slots. Tile
  indices encode source slot and primitive index; overflow evaluates each
  source's complete primitive pool. The source-zero capture remains byte-identical
  on M1 Max/Metal. The renderer still uploads only source zero, and source-specific
  palette/detail settings, smoke, global particle lights and shadow sets are not
  implemented. See [fire consumer evidence](measurements-multi-emitter-fire-consumer.json).
- The renderer now owns the two-slot storage value and uploads it as a unit. The
  CPU packer preserves legacy sampling for one source and sorts multi-source
  frames by stable ID; tests cover one-source byte parity and two-source reorder
  stability. The scene contract still prevents this two-source packer from being
  reached by a live scene. A fixed-tick capture after the storage upload remains
  byte-identical; see [storage packing evidence](measurements-multi-emitter-storage-packing.json).
- Each storage slot now also carries its source origin. The flame detail mask
  uses that origin for slot one while retaining the legacy uniform origin for
  slot zero. The capture remains pixel-identical, and the added origin metadata
  costs 32 known bytes. Per-source palette and shape settings are still shared
  through globals and remain unfinished.
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
when one source changes. Renderer cache ownership, per-source smoke and offscreen
simulation remain unimplemented.

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
