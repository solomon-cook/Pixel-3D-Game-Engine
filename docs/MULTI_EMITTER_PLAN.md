# Bounded multi-emitter runtime plan

18 October 2026. The scene contract and core render path now accept up to two
emitters with explicit, unique primary-light IDs. Stable-ID sampling, per-source
compute, shading, heat, light and shadow paths are exercised by fixed-tick
Metal reviews. Maximum-budget correctness and a three-pair sustained offscreen
route are recorded; fixed-camera temporal evidence covers both 8³ and 16³
absorption-cache variants. A three-pair, 120-second-per-run comparison on the
dual-emitter review scene shows no total-render gain for either cache size;
the full 120-second 8³- and 16³-cache routes are now pixel-identical to direct
integration, and native-window cache toggles match at six route poses. Three
paired
120-second native runs show mixed component deltas and no robust whole-window
gain. Continuous native playback and portability gates remain open. The
single-source baseline remains selectable and pixel-identical.

The opt-in 8³ source-local absorption cache also has a matched 120-frame, 20 fps
temporal comparison using the fixed dual-wide camera. Effect counts match at all
frames; mean frame RGB error is 0.026/255 and mean temporal-change-magnitude
error is 0.020/255. This is offscreen M1 Max/Metal evidence, not a promotion
decision. The 16³ variant has 0.014/255 mean frame RGB error and 0.015/255 mean
temporal-change error, also with per-frame effect-count parity. See [8³ report](measurements-multi-emitter-absorption-temporal.json),
[16³ report](measurements-multi-emitter-absorption-temporal-cache16.json) and
[runner](../scripts/two_emitter_absorption_temporal_study.py).

The sustained dual-source comparison used three alternating 120-second pairs
per cache size. Candidate-minus-direct paired median frame-work deltas were
+0.027/+0.019 ms for 8³/16³; GPU-render deltas were +0.061/+0.081 ms. The
paired p95 deltas were +0.305/+0.034 ms for frame work and +0.072/+0.091 ms
for GPU render. Cache build medians were 0.034/0.044 ms GPU and 0.045/0.048 ms
CPU per frame; residency was 4,096/32,768 bytes. Keep both modes opt-in and do
not claim a performance benefit from this route. See [sustained report](measurements-multi-emitter-absorption-sustained.json)
and [runner](../scripts/two_emitter_absorption_sustained_study.py).

## Current boundary

- Scene validation accepts one or two emitters and requires explicit unique
  primary-light IDs for dual-source scenes. Per-emitter smoke simulation,
  atmosphere/optical, ink, absorption, opaque heat, authored primary-light and
  geometry shadow paths are connected. The review and maximum-budget scenes both
  exercise these paths on M1 Max/Metal. Cache-enabled fixed-tick review is
  complete. Tiled/exhaustive parity and sustained timing are recorded on both
  scenes: the maximum-budget scene has a serial-work reduction with a higher
  reported GPU-render metric; the review scene has a 1.20 ms median serial-work
  reduction, a 1.05 ms atmosphere/fire stage reduction and nearly flat reported
  GPU-render time. Native maximum-budget timing shows a GPU-stage reduction
  without a clear whole-window gain. Temporal samples cover both cache sizes and
  full 8³/16³-cache routes. Continuous native playback, additional-scene scaling
  and adapter gates remain open.
- Each `FireFrame` owns a 256-primitive pool; up to 12 derived particle lights
  are shared globally. O03 tile construction now includes both sources, and
  overflow falls back to exhaustive evaluation. Maximum-budget parity, forced
  fallback and three-pair offscreen and native sustained routes are recorded.
  Native tiling lowers median atmosphere/fire GPU time by 0.393 ms, while the
  median FPS delta is only -0.231 and the pair results are mixed; no whole-window
  win is established. A separate ordinary review-scene route has a smaller GPU-stage
  reduction and nearly flat whole-render GPU time, alongside a serial frame-work
  gain. See [review-scene report](measurements-multi-emitter-review-tile-sustained.json)
  and [runner](../scripts/two_emitter_sustained_study.py). Further scene scaling
  and portability evidence remain open.
- The CPU storage packer now merges sampled source candidates into the shared
  12-light budget by descending power, then stable emitter ID and event identity.
  It stores the selected lights in source zero's shared-light slot and reports
  local plus global drops. The dual-source review exercises the merged budget.
- The GPU fire-storage ABI now reserves two contiguous `FireFrame` slots. A
  fixed-tick M1 Max/Metal
  comparison is byte-identical to the prior single-frame ABI; the known
  allocation increases by 12,928 bytes. The renderer has a keyed multi-source
  sampling/upload path, now exercised through the bounded two-source scene. See
  [storage ABI evidence](measurements-multi-emitter-storage-abi.json).
- Fire tile construction and flame shading now iterate both frame slots. Tile
  indices encode source slot and primitive index; overflow evaluates each
  source's complete primitive pool. The source-zero capture remains byte-identical
  on M1 Max/Metal. The live two-source scene now exercises the dual-source tile
  and flame paths. See
  [fire consumer evidence](measurements-multi-emitter-fire-consumer.json).
- The renderer now owns the two-slot storage value and uploads it as a unit. The
  CPU packer preserves legacy sampling for one source and sorts multi-source
  frames by stable ID; tests cover one-source byte parity and two-source reorder
  stability. Reversing the two emitters in the live review scene preserves its
  fixed-tick output hash; see [storage packing evidence](measurements-multi-emitter-storage-packing.json)
  and [two-source review](measurements-multi-emitter-shadows.json).
- Each storage slot now also carries its source origin. The flame detail mask
  uses that origin for slot one while retaining the legacy uniform origin for
  slot zero. The capture remains pixel-identical, and the added origin metadata
  costs 32 known bytes.
- Each slot now carries its palette, breakup, shape, pixel-treatment and source
  intensity values. Flame shading selects the slot-one presentation independently;
  source zero still uses the legacy globals. The storage grows by another 192
  known bytes, and the fixed-tick capture remains pixel-identical. The live
  two-source scene uses independent source palettes and origins. See
  [per-source presentation evidence](measurements-multi-emitter-presentation.json).
- `Renderer::update_globals` now has a keyed multi-source branch that builds
  `FireKey`s in stable-ID order, packs both frames (including the shared particle
  lights), tracks projected-detail hysteresis independently per source, and
  rebuilds/uploads when source state or a source's detail tier changes. Current
  scene validation now accepts two emitters, and the keyed upload path has been
  exercised by the live two-source review capture. Source-specific shadow maps
  were also rendered for both lights. A maximum-budget CPU/GPU route comparison is
  measured on both the ordinary review scene and the maximum-budget stress scene;
  results differ by metric and workload. Additional-scene scaling and overload/
  lifecycle stress remain open. The existing
  single-source profiling-heavy fixed-tick RGBA capture remains byte-identical
  on M1 Max/Metal (SHA-256 `9faedb7b757c5043e8bf006f3e1bbffa0d4240e8ef6f0a2a85260612212a4a48`).
- Smoke compute now allocates a separate ping-pong density/temperature pair and
  source-config uniform per emitter, sorts those slots by stable ID, and dispatches
  one advection pass per source. Bounds, buoyancy, dissipation, density and thermal
  settings are source-local; reset clears every allocated source volume. Scene
  validation now allows two emitters. The soft atmosphere/optical shader and
  post heat have secondary-volume paths; inked smoke has a source-local puff
  path; and the absorption cache now has a source-local channel. Fixed-tick
  two-source captures exist, but that review used the direct absorption path.
  A maximum-budget sustained performance result is now available in
  [the paired report](measurements-multi-emitter-sustained.json); it shows lower
  serial frame-work with mixed GPU interval results. The current single-source RGBA capture
  remains pixel-identical, with the 80-byte source config reflected in the known
  fixed-buffer inventory; see [smoke compute evidence](measurements-multi-emitter-smoke-compute.json).
- The soft atmosphere integral now binds and samples a second source-local smoke
  volume in its fixed world-space domain. Camera-to-flame absorption includes that
  field, and the optical material pass shares the same integral. Stable-ID slot
  zero now owns the legacy global domain when multiple sources are prepared. The
  post heat pass now carries each source's heat output/cooling/lift and can sample
  the second temperature volume using its source-local shape/distortion settings.
  Source-count guards leave the one-emitter paths unchanged. Opaque materials
  with `heat_response` sample both source-local temperature fields. The two-source
  review scene exercises the renderer on Metal, though source-one heat's visual
  contribution and shadow-only differences still need focused A/B captures.
  The fixed-tick `profiling-heavy.json` hero capture remains pixel-identical at
  640×360 (SHA-256 `9faedb7b757c5043e8bf006f3e1bbffa0d4240e8ef6f0a2a85260612212a4a48`).
  See [atmosphere evidence](measurements-multi-emitter-atmosphere.json).
  The fixed-tick heat-path parity check is in
  [heat evidence](measurements-multi-emitter-heat.json).
- Inked smoke now has source-local puff bounds and shading. The tile list
  reserves 36 candidates per source (72 total), with independent overflow
  fallback; secondary puffs sample their own smoke field, buoyancy, bubble
  settings and internal glow. The one-source `profiling-heavy.json` hero capture
  remains byte-identical (SHA-256 `9faedb7b757c5043e8bf006f3e1bbffa0d4240e8ef6f0a2a85260612212a4a48`).
  On M1 Max/Metal at 640×360, tile indices use 603,520 bytes, up 132,480 bytes
  from one-source capacity. The two-source review scene uses 25,889,280 known
  bytes including both smoke fields and primary shadow sets. On the maximum-budget
  route, three alternating 120-second pairs show 0.715 ms lower median serial
  frame-work for tiled rendering, while the reported GPU-render metric is 1.922 ms
  higher; tile-build rises 2.468 ms and atmosphere/fire falls 0.495 ms. These
  measurements are workload-specific, and GPU intervals may overlap. Per-source
  primary-light shadow maps and discrete invalidation have fixed-tick live review.
  The new native-window tiled/exhaustive study adds three maximum-budget pairs;
  its GPU atmosphere/fire stage favors tiling but whole-window performance is
  mixed. Other-scene and portability gates remain open. See
  [sustained performance evidence](measurements-multi-emitter-sustained.json) and
  [inked smoke evidence](measurements-multi-emitter-ink.json).
- The O05 absorption cache retains source zero in the red channel and builds a
  second light-transmittance field in the green channel over source one's local
  domain. Its colocated primary fire light selects that field; other lights and
  out-of-domain samples retain direct integration. The cache remains one 3D
  texture, so its memory cost does not increase. The source-zero fixed-tick RGBA
  hash remains unchanged and the Metal verifier passes. Cache-enabled dual-source
  captures at four cameras restore the direct image exactly after disable and
  retain one 4096-byte 8³ cache allocation; measured image error is recorded but
  no performance or temporal decision is claimed. See
  [source-local absorption evidence](measurements-multi-emitter-absorption.json)
  and [cache review](measurements-multi-emitter-absorption-cache.json).
- Opaque materials with `heat_response` now sample source one's local temperature
  field alongside the legacy primary volume and use the stronger local heat
  sample. Both source-local sample coordinates now come from stable source
  origins, and terrain below the smoke volume uses the source's lower heat slice
  instead of being rejected as out of bounds. The new binding adds no texture
  allocation. The source-zero fixed-tick capture remains byte-identical. A
  six-camera source-one A/B changes 168–5,695 pixels per view, with the clearest
  cue in the ground-focused camera. A full 120-second heat-off/on `dual-wide`
  comparison now samples 2,400 frames at 20 fps with matching ticks, camera poses,
  fire counts and particle-light counts. Mean heat-on/off frame MAE is 0.0084/255
  over the whole frame (mean 88 changed pixels); the cue is sparse in this wide
  route. Temporal-change difference MAE is 0.00087/255. A second 120-second
  heat-off/on orbit keeps the watchfire and ground centered from a low moving
  camera. Across 2,400 frames, mean full-frame A/B MAE is 0.7705/255 (9,331
  changed pixels on average), and temporal-change difference MAE is 0.0435/255.
  The inspected contact sheet shows the ground ring at all five sampled route
  checkpoints. Human continuous playback, native viewing and performance review
  remain open. See the [focused-route report](measurements-multi-emitter-heat-response-ground-orbit.json),
  [contact sheet](measurements-multi-emitter-heat-response-ground-orbit-contact.png),
  [wide-route report](measurements-multi-emitter-heat-response-temporal.json),
  [still A/B evidence](measurements-multi-emitter-opaque-heat.json) and
  [reproducible runner](../scripts/two_emitter_heat_response_temporal_study.py).
- Each source primary light now owns six cube-array shadow faces in stable emitter
  ID order. Shadow matrices, caster culling, dirty-face invalidation and opaque,
  optical and volumetric light selection use the matching source layer. The
  resource remains six faces for one source and grows by 1,572,864 bytes per
  additional source. M1 Max/Metal validates the cube-array pipeline and preserves
  the single-source capture hash. The live dual-source review reports all 13 maps
  drawn on initialization and stable source ordering under reversed emitter
  arrays. A source-light edit now dirties only its six cube faces; sun, caster,
  material, reload and reset edits were compared with forced redraw and all
  fixed-tick images matched. Sustained moving-caster stress remains open. See
  [shadow evidence](measurements-multi-emitter-shadows.json) and
  [invalidation evidence](measurements-multi-emitter-shadow-invalidation.json).
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
dispatch and offscreen simulation are implemented and exercised in the live
two-source fixed-tick review scene.

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
alignment: about **2.77 MB** by the original estimate. The live dual-source
inventory reports 25,889,280 known bytes at 640×360, including 13 shadow maps,
both smoke fields, tile indices and per-shadow instance buffers. This is not a
paired one-source delta. Two smoke dispatches suggest roughly twice the current
0.0205 ms median smoke-compute stage, but this is a linear estimate only; profile
it on hardware. Rendering may grow more than linearly in crowded tiles because
it adds flame candidates and another volume contribution. Existing tile overflow
must remain correct under that load.

## Delivery and acceptance gates

1. **Implemented:** validation accepts one or two emitters, checks profile
   references and source bounds, requires explicit primary-light IDs for dual
   scenes, rejects duplicate ownership and a third emitter. Legacy single-source
   scene JSON remains valid.
2. **Implemented:** deterministic CPU tests cover same seed/tick/source replay,
   source independence and array-order invariance.
3. **Initial live review complete:** `assets/scenes/two-emitter-review.json` has
   separate profiles, positions and linked lights. The reproducible capture
   runner records each source alone, together and with reversed emitter order at
   four named cameras, seed 42, tick 120 and 640×360. The combined image hashes
   match under reversed emitter order; close, shared-screen and orthographic
   outputs were inspected. See
   [two-source evidence](measurements-multi-emitter-shadows.json).
4. Stress maximum fire primitives, 8 authored lights, 12 derived lights, crowded
   tile overflow, reset/replay, paused edits, camera motion, offscreen simulation,
   shader reload rollback and resource recreation. Report dropped budgets.
5. Measure serial GPU stages, smoke compute, CPU update/upload, allocations and
   full frame work against the single-source baseline. Keep source ordering,
   light selection and visual output deterministic on the same device.
6. Verify Metal first, then run the same scene/captures on Windows/DX12 and at
   least one other adapter before claiming portability. Keep the two-source cap
   until those results and the memory budget pass.

The bounded runtime, fixed-tick visual result and one maximum-budget sustained
route are measured on M1 Max/Metal. Serial frame-work improves for that route
while the reported GPU-render metric worsens; this is not a universal performance
claim. Native fixed-tick cache and tiled/exhaustive captures are recorded, as is
a three-pair native cache timing study. A native surface resize/restore study
preserves the fixed-tick dual-emitter image and renderer resource inventory; the
host did not register minimize, so that path remains unverified. See
[native lifecycle evidence](measurements-multi-emitter-native-lifecycle.json) and
[runner](../scripts/two_emitter_native_lifecycle_study.py). Continuous native
playback, broader workload scaling, cross-adapter correctness and target-hardware
support remain unverified. Gate 4's reset/replay, paused-edit and shader-reload
checks have focused dual-source shadow invalidation evidence, while broader
resource recreation and device-loss behavior remain open. A new dual-source shader
rollback study appends WGSL syntax errors to the fire and volume modules in an
isolated shader directory. At seed 42/tick 120, each failed reload retains the
baseline image and reuses all shadow maps; restoring the modules reloads successfully,
keeps the image identical and redraws all 13 maps for the successful reload. This
closes fixed-tick headless Metal rollback coverage for these modules, not native or
cross-adapter behavior. See [rollback report](measurements-multi-emitter-shader-rollback.json)
and [runner](../scripts/two_emitter_shader_reload_rollback_study.py).
