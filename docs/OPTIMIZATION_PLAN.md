# Pixel renderer optimisation plans

16 October 2026. O01 profiling instrumentation, O02 whole-map shadow reuse, O03
single-emitter tile lists and O07 object bounds, shared meshes, culling, instancing
and live transforms are implemented and measured on M1 Max/Metal. O08's first
resource inventory is recorded; its remaining layout/pass changes remain proposed. O04 has
an opt-in projected fire-segment experiment; its default-promotion and
visual/platform acceptance gates remain open. O05 and O06 have opt-in prototypes
and first measurements. Platform and broader visual acceptance remains open; these
plans extend the current renderer and do not replace the smoke/fire art direction.
[TODO.md](../TODO.md) tracks execution. Runtime and acceptance evidence remain in
[STATUS.md](STATUS.md).
The ordered follow-up gates for O01–O08 are in
[O01-O08_FOLLOWUP_PLAN.md](O01-O08_FOLLOWUP_PLAN.md).

## Contract and evidence

The selected scene pixel grid stays fixed. Optimisations must preserve the broad
rounded smoke billows, attached secondary bubbles, darker folds and plume interior,
radial fire illumination, slow branching flames, solid flame pixels, heat shimmer
and detached world-space lights. Different games retain control through profiles.
Simulation state, heat and particle births must not depend on camera visibility.

There are two acceptance classes:

- **Image-preserving:** scheduling, caching, conservative culling and data layout.
  Compare matched captures on the same device; investigate any difference before
  accepting it. Use declared tolerances for different backends.
- **Approximate:** projected detail and lighting caches. Require still and motion
  review against the baseline, including folds, silhouettes, flicker and camera
  movement. A timing improvement alone cannot promote them.

Every workstream keeps an independently selectable baseline. New switches,
commands and report fields described here are proposals until implemented and
exposed by `engine-lab describe`. Controls must use shared Session operations,
with validation, correlated errors and frame-boundary application. Diagnostics
stay machine-readable; agent stdout remains response-only.

Use fixed scene/asset/shader hashes, seed, camera route, tick range, pixel grid and
effect settings. Run at least three alternating baseline/candidate pairs, each
with 10 simulation seconds of warm-up and a 120-second moving route. Record all
runs, median and p95 frame/pass times, memory and workload counts. Include build,
upload, cache maintenance and fallback costs in the total; gains must exceed
observed run variance. Run instrumented and minimally instrumented comparisons
to expose profiling overhead. Record latency and throughput separately.

Start with the clearing, heavy single-plume/eight-light workload and Material
Atelier. Include perspective and orthographic views, close-up and distant smoke,
camera-inside/near-plane cases, heat shimmer, moving fragments, pauses and edits.
Existing multi-emitter scenes are unsupported: extend the one-emitter contract
explicitly before claiming tests with many fires.

The latest baseline is [measurements-pixel-fire.json](measurements-pixel-fire.json):
solid flames with heat shimmer measured 5.450 ms median / 9.538 ms p95 offscreen
frame work and 3.093 / 3.842 ms GPU rendering on M1 Max/64 GB at 640×360.
These measurements exclude native presentation, and GPU render timestamps exclude
smoke compute. They establish neither native FPS nor base-M1/RTX-3060 acceptance.
No speedup is promised by this plan.

## O01 — Measure each stage and the complete frame

**Purpose:** establish where work and stalls actually occur before changing it.

Today `render/mod.rs` times the combined shadow-to-post render submission.
Smoke compute and native presentation/UI lack GPU stage timings. The offscreen
benchmark intentionally waits for GPU completion per sample; normal window
rendering uses non-blocking timing readback. Keep that distinction visible.

Implementation:

1. Add labelled CPU spans for simulation reconstruction/submission, buffer uploads,
   command encoding, readback, surface acquisition and presentation/UI. Count fixed
   steps per frame so catch-up work is distinguishable from rendering cost.
2. Add optional GPU timestamps for smoke compute, sun shadow, point shadows,
   opaque geometry, atmosphere/fire, optical snapshots/resolve and post. Measure
   presentation/UI in the native host when supported. Query capabilities and
   report unavailable measurements as null with a reason.
3. Use bounded asynchronous query/readback slots with submission/frame/tick IDs.
   Do not introduce GPU waits in the native hot path. Report skipped or late
   samples; handle several simulation steps before one render.
4. Retain the serial offscreen latency benchmark and add a separately labelled
   buffered throughput/native route mode. Separate CPU work, GPU work, wall time,
   vsync, acquisition waits and queue latency rather than summing overlapping spans.
5. Extend metrics and comparison tooling with source/settings hashes, backend,
   timing coverage, pass distributions, target memory, primitive/light/draw counts
   and measurement overhead. Expose the same report through the inspector and API.

**Acceptance:** timing-disabled output matches the baseline; unsupported timestamp
hardware still works; query exhaustion never blocks or corrupts reports. A
repeatable report identifies the dominant costs for all three workloads and
distinguishes offscreen from native results. Add meaningful report/protocol tests.

**Deliverable:** a profiling report and one-command paired comparison workflow.
Dependency: none. This is the first implementation task.

**Implementation state:** `engine-lab benchmark` provides serial latency and
buffered throughput modes with bounded, non-blocking render and smoke-compute
timestamp slots. `benchmark-native` records vsynced route samples, CPU surface/UI/
presentation spans, and GPU presenter/inspector timings. `get_metrics` exposes
frame IDs and skipped/late counts. `scripts/profile_compare.py` fingerprints code,
shaders, scenes and GLB assets; preserves raw reports; compares paired stages; and
can compare GPU-timed versus untimed runs. Reports estimate known GPU allocations
and separate readback completion latency from GPU stage time. Per-pass GPU intervals
can overlap on a backend, so they are not summed; the end-to-end shadow-to-post
interval is reported separately. Three alternating 120-second pairs, each with
ten seconds of warm-up and GPU-timestamp-disabled overhead controls, are recorded
for clearing, the heavy single-plume/eight-light scene and Material Atelier. A
separate 120-second native clearing route records surface/UI/vsync behavior. The
paired scenes are identical within each workload, so their deltas describe run
variance rather than an optimization. Summary, provenance and raw-report checksums
are in [measurements-o01.json](measurements-o01.json); full local reports are under
`artifacts/o01/`. Timed-capture parity, bounded-slot exhaustion and native
presentation timing were checked on the M1 Max/Metal adapter. Wgpu timestamps are
not calibrated to host time, so exact queue latency remains unavailable; reports
keep it null with a reason and preserve asynchronous completion-to-readback latency
separately. Windows/DX12 and adapters without timestamp support remain hardware
acceptance gates. Offscreen and native scopes are recorded separately; no
target-hardware or optimization gain is claimed.

## O02 — Cache static shadow maps

**Purpose:** avoid redrawing unchanged shadows while retaining live fire flicker.

The current renderer draws one directional map and six primary point-light faces
every frame. The directional projection is currently world-fixed. Brightness and
colour changes affect shading, not shadow geometry.

Implementation:

1. Add explicit shadow validity/revision keys and dirty reasons. Include projection,
   light position/direction/range, caster geometry/transform revisions and material
   changes that alter shadow participation. Invalidate after reset/resource rebuild
   or successful relevant shader reload. Camera changes alone do not invalidate
   the current fixed projections; future camera-fitted projections must do so.
2. Initially reuse the complete sun map and complete point-light cube when valid.
   Skip encoding their passes. Apply brightness/colour/flicker at shading time
   without forcing a redraw. Validate edits while the simulation is paused.
3. After O07 supplies object bounds and draw metadata, track dirty cube faces and
   affected casters conservatively. Retain a full-map fallback for uncertain bounds.
4. Expose hit/miss counts, dirty faces/reasons, redraw CPU/GPU time and residency.
   Keep a force-redraw diagnostic mode for comparisons.

**Acceptance:** cached and forced-redraw captures agree through light moves,
range/direction edits, material shadow-class changes, reset and shader reload.
Changing only colour/power reuses maps while lighting visibly responds. Transform
and shadow-participation edits redraw only maps whose conservative bounds overlap;
unknown bounds retain the full-map fallback. Profile both static reuse and
continuous invalidation.

**Deliverable:** image-preserving shadow reuse, followed by optional per-face reuse.
Dependency: O01; per-face refinement also needs O07. Roll back to forced redraw
on any invalid or unknown cache state.

**Implementation state (17 October 2026):** live transform revisions retain old
and new object bounds. The renderer tests both against the sun and six point-face
frusta, and it tests bounds for objects using shadow-participation materials.
Only dirty map passes and matrix buffers are updated. Sun projection changes dirty
the sun map; point-light position/range changes dirty the six cube faces. Unknown
changes, missing bounds, reset, renderer/resource construction and successful
shader reload retain the full-map fallback. `get_metrics` reports the sun face
followed by six cube faces per primary source, with source IDs in
`shadow_source_ids` order. The bounded two-emitter path now invalidates only the
moved source's six faces; source-light, sun, caster, material, shader-reload and
reset captures match forced redraw on M1 Max/Metal. See
[two-source invalidation evidence](measurements-multi-emitter-shadow-invalidation.json).
`set_shadow_cache` and benchmark `--force-shadow-redraw` expose the full-redraw
control. Per-frame metrics and route reports expose hits, misses, resident bytes,
redrawn map count, CPU shadow encoding and dirty reason. Three alternating
120-second clearing-route pairs on M1 Max/Metal show median full-render GPU time
3.151 ms forced versus 2.672 ms cached, with 7200/7200 cache hits after warm-up.
See [measurements-o02.json](measurements-o02.json). This does not qualify Windows
DX12 or RTX-class behavior. Per-face reuse remains dependent on O07 bounds.

## O03 — Tile lists for effects and local lights

**Purpose:** scale shader work with effects touching a pixel, rather than testing
every candidate at every pixel.

Fire already has conservative ray/bounds rejection, but still loops over a bounded
primitive array. Ink smoke reconstructs its parent/child candidates per fragment.
Tile lists must beat those existing bounds tests after including list-build cost.

Implementation:

1. Materialise smoke-lobe candidates once per fixed tick using shared WGSL
   generation functions; keep GPU density-dependent presence on the GPU. Do not
   mirror procedural shader noise on the CPU or read the volume back. Give lobes
   stable emitter/birth/child identities for later LOD and diagnostics.
2. Bin fire primitives, smoke groups and local lights into conservative screen
   tiles. Trial 8×8 and 16×16 scene-pixel tiles. Include secondary bubbles, curl,
   motion, heat-distortion influence, and near-plane/camera-inside cases in bounds.
   Derive a light's finite influence from its shading contract or a declared error
   threshold; never silently truncate a nonzero light tail.
3. Preserve intersection ordering and the additional overlap hit used for contact
   shading. Preserve current nearest/strongest-light selection semantics before
   experimenting with different light budgets. Keep sun/global contributions.
4. Use bounded storage with occupancy/overflow counters. Any overflow uses an
   exhaustive fallback for that tile; it must not silently drop effects or lights.
   Invalidate view lists on camera/projection, state or resource changes, including
   paused edits. Keep any render interpolation inside conservative bounds.
5. Profile exhaustive versus tiled modes at current caps and several screen
   coverages. Only then design multi-emitter ownership, per-source grids/bounds,
   schemas, thermal/light budgets and stress scenes for 10/50 emitters.

**Acceptance:** matched images agree, including contact folds, offscreen lights,
near-plane intersections and forced overflow. Tests prove overflow fallback and
stable membership. Reports include list build time, bytes, candidates per tile,
fallback rate and whole-frame cost on Metal and DX12.

**Deliverable:** switchable single-emitter tiled rendering plus a measured scaling
limit. Dependency: O01. Multi-emitter support is a separate extension, not implied
by this optimisation. Related method: AMD's
[Forward+/tiled-lighting sample](https://gpuopen.com/learn/tiledlighting11-directx-11-sdk-sample/);
its DirectX implementation is prior work, not a dependency to import wholesale.

**Implementation state (16 October 2026):** a GPU compute pass builds ordered
16×16-pixel lists for fire primitives (capacity 64), ink-smoke lobes (36), point
lights (8) and particle lights (12). Conservative projected bounds include the
whole viewport for camera-inside, near-plane and invalid projections. Shader loops
retain source order and use exhaustive category evaluation when a tile overflows;
the diagnostic forced-overflow switch exercises that fallback. Shared WGSL
functions supply deterministic smoke-lobe bounds. `set_tile_lists`, capture flags,
capability inventory, asynchronous per-category membership/overflow/occupancy
metrics and tile-build CPU/GPU timings are exposed by engine-lab. Tiled evaluation
is enabled by default in this build and can be switched to exhaustive evaluation.
At 640×360 the lists use 471,040 bytes plus 192 bytes of counters; the known
allocation estimate increases by 471,232 bytes.

On Apple M1 Max/Metal, three alternating 10-second serial pairs after 5-second
warm-ups at 640×360 showed tiled versus exhaustive median-of-run-medians GPU render
times of 3.017→2.575 ms (clearing), 3.878→3.393 ms (heavy single plume/eight
lights) and 2.984→2.478 ms (Material Atelier). Candidate-minus-baseline paired
medians for full frame work were -2.202, -0.991 and -1.022 ms respectively.
Measured tile-build GPU medians were 0.621, 0.633 and 0.413 ms; CPU list encoding
medians were about 0.15, 0.16 and 0.10 ms. The material workload's CPU encode
median rose by 0.279 ms even as frame work and GPU time fell. No overflow occurred
in these route samples. Matched exact-tick tiled, exhaustive and forced-fallback
PNGs were byte-identical in hero perspective, close smoke, orthographic and glass
views; the hero image was visually inspected. This supports the current default
on these measured Metal workloads, not a universal performance claim. Eight-pixel
tiles were not trialed. Multi-emitter ownership, natural
overflow stress, motion acceptance, native-window performance, Windows/DX12 and
other GPUs remain open. Full data, hashes, commands and limits are in
[measurements-o03.json](measurements-o03.json); raw route reports are under local
ignored `artifacts/o03/`.

**Natural overflow follow-up (17 October 2026):** the deterministic diagnostic
scene [tile-overflow-stress.json](../assets/scenes/tile-overflow-stress.json)
produces fire-list occupancy up to 101 candidates against the 64-entry capacity;
maxima for smoke and light lists remain within their fixed bounds. At 16×16,
1.48% of measured tile-frame samples overflowed the fire list; an experiment-only
8×8 build reduced this to 0.56%. All four same-tick tiled/exhaustive captures
matched byte-for-byte. The 8×8 allocation is 1,843,200 bytes versus 471,040 for
16×16 (3.91× at 640×360 due to tile-grid rounding), and one short benchmark per
mode is inconclusive: build medians were 1.396
and 1.416 ms respectively, with no alternating long-run comparison. A benchmark
summary field was corrected to read tile size from live capabilities rather than
hard-coding 16. The production setting remains 16×16. This is diagnostic evidence,
not natural-overflow acceptance or a promotion decision. Full values, hashes and
limits are in [measurements-o03-overflow.json](measurements-o03-overflow.json);
raw reports and captures are under ignored `artifacts/o03/`.

## O04 — Detail based on projected pixel contribution

**Purpose:** spend geometry and shading effort where the chosen pixel grid can
show it, with stable transitions during movement.

Implementation:

1. Estimate projected size using the scene buffer, supporting both camera types.
   Classify silhouette, contact-shading, reflection and lighting contributions
   separately. A tiny bright ember can still matter even when its shape is tiny.
2. Retain full secondary bubbles/curve segments for large effects. For smaller
   effects, try fewer children and curvature-adaptive curve segments, then simpler
   silhouettes. Merge omitted detail's coverage/density conservatively instead of
   abruptly deleting its parent. Keep collision/heat/light state unchanged.
3. Choose thresholds through matched captures; trial subpixel and 1–4 pixel
   features before selecting defaults. Use stable IDs and hysteresis or a bounded
   transition band to prevent popping. Document/reset any presentation history so
   exact-tick captures remain reproducible with a declared camera history.
4. Integrate geometry LOD only after O07. Offscreen objects still contribute to
   shadows and relevant reflection/light work. Expose retained/merged counts and
   projected-size distributions through a debug view and agent metrics.

**Acceptance:** slow zooms, orbits and repeated threshold crossings show no
obvious popping, crawling, flattened smoke or lost glow. Identical seed/tick
simulation and derived-light state match with LOD on/off. Same capture history
replays deterministically. Benchmark small, medium and screen-filling effects.

**Deliverable:** independently selectable visual LOD with reviewed thresholds,
separate from simulation quality and pixel resolution. Dependencies: O01 and O03;
geometry LOD also needs O07. Existing post-lighting pixel-cluster averaging stays
a separate experiment; it does not currently avoid the lighting work it averages.

**Implemented experiment:** `render.experiments.projected_detail_lod` estimates
the profile's projected fire height from the active perspective or orthographic
camera. Hysteresis selects full/medium/low curve segment counts at 40/20 px,
returning at 48/24 px. This first slice reduces tongue segments only; it preserves
the deterministic full frame for bounds, particle births and emitted lights, and
does not adapt smoke, branches, reflections, pixel size or simulation. The toggle
defaults off. See [measurements-o04.json](measurements-o04.json) for captures and
paired M1 Max timings. Slow orbit/popping review and target-platform qualification
remain open; the current cost data does not justify enabling it by default.

## O05 — Reuse smoke transmittance and illumination work

**Purpose:** reduce repeated density sampling without flattening rounded billows
or losing the nearest light's radial gradient and dark shared interior.

Today ink smoke samples density toward selected lights at each shaded surface.
Test caching the expensive absorption term, keeping surface normals, distance
falloff, colour and live intensity in final shading.

Implementation:

1. Prototype a coarse per-source transmittance field in the emitter's volume,
   starting with 8³ and 16³ cells for the primary fire light. Compare with the
   existing direct samples; investigate sky/sun separately if measurements justify it.
2. Refresh from density changes at fixed ticks. Rebuild promptly on light
   position/range or volume changes, reset and successful relevant reload, including
   paused edits. Apply power/colour/flicker live rather than baking stale radiance.
3. Keep fast-moving particle lights direct initially. Preserve rounded normals,
   child contacts and internal-emission controls. Consider a direct correction
   near sources/high gradients only if it demonstrably recovers the important detail.
4. Select cache resolution/update policy as explicit effect quality, with a direct
   fallback for small workloads or invalid caches. Measure build, sampling, memory
   and invalidation cost; a cache is not automatically cheaper for one campfire.

**Acceptance:** fire-facing rims, contact recesses, deep soot, internal emission
and moving ember light remain legible in stills and motion. Test rapid light
motion, flicker, density changes and pausing. Quantify image error and temporal
error alongside human review; never promote a faster but visibly flat result.

**Deliverable:** optional coarse absorption cache with a documented useful range.
Dependencies: O01 and the revision/invalidation conventions from O02. O03 helps
bound participating source work; the first cache prototype can be evaluated alone.

**Prototype result:** the opt-in implementation caches primary authored fire-light
optical depth in a configurable 8³ or 16³ field, rebuilding each rendered frame;
particle lights and out-of-volume points retain direct sampling. A sustained
three-scale study used three paired 120-second orbit runs for every size/tier.
On M1 Max/Metal, the targeted atmosphere/fire stage improved by 0.058–0.101 ms,
while the separate cache build cost 0.025–0.033 ms on GPU and 0.033–0.043 ms on
CPU. Total GPU render medians were 0.025–0.044 ms slower in all six comparisons.
The 16³ fixed-tick captures were closer to direct by mean absolute RGB error at
all three scales, but this did not establish a total-render win. Neither tier is
promoted. The disabled path allocates no cache texture or build pass; an off/on/off
GPU replay confirmed 0/4096/0 cache bytes and identical disabled output before and
after. Fixed-tick temporal error and a two-second native-window pause/resume
parity check are recorded in [measurements-o05-temporal.json](measurements-o05-temporal.json)
and [measurements-o05-pause-resume.json](measurements-o05-pause-resume.json).
The dirty-input policy reuses the field across unchanged paused renders and rebuilds
after fixed simulation updates, successful parameter edits, reset, shader reload
and re-enable. A protocol study confirms byte-identical repeated paused output,
expected build/skip counts, and zero residency while disabled; see
[measurements-o05-refresh-policy.json](measurements-o05-refresh-policy.json).
A later live `serve` toggle exposed a missing secondary-smoke binding when the
volume groups were recreated after enabling the cache. The runtime bind group now
matches its five-entry layout; a fresh off/on/off protocol capture completed with
4096 cache bytes while enabled. This confirms the toggle route and resource
lifetime, not image parity or multi-emitter cache support; see
[runtime-toggle evidence](measurements-o05.json).
The bounded two-emitter extension now has a full 120-second, 20 fps moving-camera
comparison on the maximum-budget scene. Across 2,400 direct/cache pairs, camera
poses and effect counts match every frame; the 8³ cached output is byte-identical
to direct output and has zero temporal-change error on this route. This is one
offscreen M1 Max/Metal scene, not continuous native playback or performance
acceptance; the cache remains off by default because sustained total-render
timings did not improve. A native-window session now toggles direct/cache/direct
at six fixed orbit poses; every pair matches pixel-for-pixel and the 8³ residency
is present only while enabled. Continuous native playback and portability remain
open. Three alternating 120-second native-window pairs now show +0.263 median
FPS, +0.083 ms CPU native
frame work and -0.092 ms atmosphere/fire GPU time; surface-acquisition deltas are
mixed, so this does not establish a robust whole-window win. Keep the cache off by
default. See [native sustained report](measurements-multi-emitter-absorption-native-sustained.json)
and [runner](../scripts/two_emitter_absorption_native_sustained_study.py), plus
[moving-route report](measurements-multi-emitter-absorption-moving-route.json)
and [runner](../scripts/two_emitter_absorption_moving_route_study.py), plus the
[native report](measurements-multi-emitter-absorption-native.json) and
[native runner](../scripts/two_emitter_absorption_native_study.py).
The bounded multi-emitter extension reuses the same RGBA16Float cache: source
zero remains in red, and green stores source one's optical depth over its local
domain for its colocated primary fire light. It adds no cache allocation and
retains direct integration for other lights and out-of-domain points. Source-zero
parity is preserved, and dual-emitter moving-route/native fixed-tick output now
match direct sampling exactly on the measured Metal scenes. Sustained results show
no total-render benefit; see [multi-emitter cache evidence](measurements-multi-emitter-absorption.json),
[moving-route report](measurements-multi-emitter-absorption-moving-route.json) and
[native report](measurements-multi-emitter-absorption-native.json).
The matching 8³ temporal study recorded mean frame RGB MAE 0.285/255, p95
0.426/255, maximum channel difference 39/255 and mean temporal-change magnitude
error 0.183/255, with exact tick/effect-count parity. The 16³ cache is closer to
direct sampling; neither variant has a demonstrated total-render win. See
[measurements-o05-temporal-cache8.json](measurements-o05-temporal-cache8.json).
Human review of continuous playback, native-window performance acceptance and
non-Metal qualification remain open.
See [measurements-o05.json](measurements-o05.json) and
[measurements-o05-size-study.json](measurements-o05-size-study.json).

## O06 — Specialise optical materials and avoid repeated shading

**Purpose:** stop recomputing surface lighting and foreground atmosphere where
equivalent results are already available.

The optical pass currently shades surfaces again and reconstructs foreground
atmosphere. It also processes the combined vertex buffer even though its shader
rejects non-optical surfaces. Extra buffers can cost more than the saved arithmetic,
so compare alternatives before choosing a layout.

Implementation:

1. Use O01 to isolate optical geometry, HDR/normal-depth copies, SSR and repeated
   atmosphere cost in the material lab and mixed smoke/material views.
2. With O07 draw ranges, submit only relevant optical geometry. Separate opaque
   reflective materials from transmissive surfaces and skip unused features/passes.
3. Prototype reuse of opaque surface lighting and the matching foreground integral
   for opaque reflectors. Compare a compact intermediate against recomputation.
   Glass needs atmosphere evaluated to its own surface depth; reusing the opaque
   backdrop's integral blindly would be wrong.
4. If SSR dominates, investigate conservative hierarchical-depth tracing separately.
   Preserve current roughness, environment fallback, single-layer transmission,
   absorption and depth ordering. Keep structural optimisation separate from any
   change to the material approximation itself.

**Acceptance:** reflective/transparent objects behind and in front of smoke/fire,
heat shimmer and foreground silhouettes retain correct ordering and live edits.
Compare image differences, total pass time and added bandwidth/memory. Nested
glass remains unsupported. Camera-inside exit refraction now has a separate
fixed-tick M1 Max/Metal sample; this does not establish continuous-motion support.

**Deliverable:** specialised optical paths, selected by measured whole-frame gain.
Dependencies: O01; geometry partitioning needs O07. Optional SSR prior work:
[AMD stochastic screen-space reflections](https://gpuopen.com/manuals/fidelityfx_sdk/techniques/stochastic-screen-space-reflections/).
This is a technique reference, not a requirement to adopt its SDK.

**Prototype result:** `render.experiments.optical_surface_reuse` reuses opaque
reflector shading from the matching atmosphere-composited snapshot, subtracting
the foreground contribution before recovering the base surface color. It adds no
texture allocation. Transmissive surfaces retain direct lighting because the
opaque pass omits them. On M1 Max/Metal, three paired 120-second routes reduced
total GPU render by 0.169 ms in Material Atelier and 0.081 ms in a mixed
smoke/fire/material scene; optical resolve fell by 0.166 ms and 0.076 ms. Frame
work improved across all six pairs. Matched hero, close metal/glass, smoke-ordering
and live roughness-edit captures were inspected. Inside-glass and near-plane
direct/reuse captures now match exactly at fixed ticks. Keep the experiment off by
default pending continuous motion review, native-window performance measurement
and cross-backend validation. See [measurements-o06.json](measurements-o06.json),
[measurements-o06-sustained.json](measurements-o06-sustained.json) and
[measurements-o06-camera-stress.json](measurements-o06-camera-stress.json).

## O07 — Object bounds, culling and shared meshes

**Purpose:** retain enough scene structure to avoid irrelevant draws and duplicated
mesh data, and support precise shadow invalidation.

The renderer now stores unique local-space mesh/material streams with stable
per-object transforms, draw ranges and conservative world-space bounds. Per-camera
and per-shadow-frustum visibility are prepared independently, then compatible
consecutive instances are batched without changing scene order.

Implementation:

1. Preserve stable object/material IDs, draw ranges and conservative world bounds
   alongside the current mesh. Add bounds/debug counters before changing rendering.
2. Cull per camera and per light frustum independently. An object outside the
   camera can still cast a visible shadow. Retain conservative reflection visibility
   and future procedural-displacement margins.
3. Introduce shared mesh streams and instance transforms for identical asset or
   procedural variants. Different procedural seeds can change shape; only share
   when the full geometry key matches. Keep texture/material identities stable.
4. Add validated transform operations and per-object revision propagation through
   Session, then connect changed bounds to O02 dirty maps/faces. Live transforms are
   a runtime feature; scene topology and assets remain startup-only.

**Acceptance:** the explicit culling-off/instancing-off reference path must match
saved pre-change captures. Culling-on is compared against instancing-only in
perspective, orthographic, smoke-close and optical views; offscreen casters remain
in light frusta. Bounds contain decoded GLB/procedural vertices and transformed
instances. Positive nonuniform scales are covered; negative scales are rejected by
the scene schema. Compare draw count, submitted vertices, geometry storage and CPU
culling cost across repeated content. Exact PNG parity is expected from the baked
reference path; GPU instance transforms may differ at a few color-quantization
boundary pixels.

**Deliverable:** bounds/draw metadata first, then conservative culling and instancing
as separately measured changes. Dependency: O01. Use exhaustive drawing on uncertain
bounds; don't let an optimisation silently remove content.

**Implementation state (16 October 2026):** the engine keeps stable per-object
ranges, IDs, transforms and world bounds while storing one local vertex stream per
geometry/material key. It independently culls camera and seven shadow frusta;
unknown bounds remain visible. Consecutive matching mesh instances batch in scene
order. Runtime controls expose culling and instancing independently, with a baked
reference path for exact pre-change comparison. Positive nonuniform object scale
and rotation are covered by bound tests; negative scale remains prohibited by the
scene schema. Evidence, pixel comparisons, per-view submissions, GPU storage and
paired M1 measurements are in
[measurements-o07-culling.json](measurements-o07-culling.json). Exact baked
reference rendering matches the saved baseline. Instanced GPU transforms introduce
one to twelve changed pixels in reviewed original 640×360 views; culling introduces no
additional changes in those views. The `set_object_transform` Session operation now
validates object position, XYZ rotation and positive scale, updates local/world bounds,
instance transforms and the baked comparison stream, and returns a per-object revision.
A live transformed object matched a fresh static instanced capture byte-for-byte; the
updated baked stream differed by one pixel from a fresh baked reference. Culling on and
off captures matched. Moving the caster invalidates all seven maps safely; per-face
tracking is the next O02 step. The measured culling route substantially reduces
camera/light submissions, while whole-render GPU timing remains nearly unchanged.
The selectable baked comparison stream retains 10.54 MB of CPU vertices for the
clearing scene. Native-window and Windows DX12 verification remain open. Live transforms
and per-object revisions are now available; O02 per-face invalidation remains the next
cache refinement.

**Scene-scale follow-up (18 October 2026):** four deterministic tiers from 276 to
2,208 objects were measured with baked, instancing-only and culling+instancing
paths using three paired 120-second routes each. Direct baked-to-culled+instanced
whole-frame work deltas ranged from −0.025 to −0.116 ms; the 2,208-object tier
reduced visible camera objects from 2,208 to 868 and batches from 2,208 to 377,
with 0.739 ms median CPU culling. A matching moving-caster four-tier matrix now
records shadow-pass timing and invalidation counters. Culling lowers the GPU
shadow-map stage by 0.022–0.309 ms versus instancing-only, but the complete-frame
result is mixed and is slower at 2,208 objects. The gain does not justify adding
indirect or occlusion drawing. Native culling/instancing/moving-caster controls
and a resumable four-tier matrix runner are implemented, but sustained native
window comparisons, continuous-motion visual review and non-Metal acceptance
remain open. See
[static measurements](measurements-o07-scale-study.json) and
[moving-caster measurements](measurements-o07-moving-caster.json).

## O08 — Reduce memory traffic and unnecessary GPU work

**Purpose:** optimise the complete pass/data layout for desktop GPUs after costs
are visible, with specific attention to Apple's tile-based architecture.

Implementation:

1. Inventory resource sizes, lifetimes, attachment loads/stores, snapshots, uploads
   and bytes touched per frame. Start with HDR/normal-depth/optical copies, the
   effect-depth/flame-mask target and the density/heat ping-pong textures.
2. Trial compatible packing, narrower formats, dirty uploads, fewer copies and
   submission batching individually. Query sampled/storage/render format support;
   unused channels alone do not prove an RG16 storage replacement is portable.
   Verify pass ordering and ping-pong hazards when batching fixed steps.
3. Compare measured bandwidth and pass overhead on Metal and DX12. Use only
   capabilities actually exposed by wgpu. Do not assume Metal-specific tile-memory
   techniques or a wholesale deferred renderer will benefit both backends.
4. Only if smoke compute dominates, prototype active-region simulation with
   conservative transport/buoyancy/turbulence halos and explicit boundary handling.
   Preserve density/heat transport and seeded replay; never stop simulation simply
   because smoke is offscreen. Keep this later experiment out of the first pass.

**Implemented candidate — fixed-step submission batching:** `Session::step` now
groups up to six consecutive ticks into one queue submission. Each dispatch reads
its own aligned per-tick smoke configuration (including wind/time), compute timing
queries remain associated with their tick, and separate ordered compute passes
preserve the smoke-volume ping-pong sequence. Frame diagnostics report both fixed
steps and simulation submissions; the resource inventory includes the config ring.
The pre-batch and candidate builds produce byte-identical 640×360 images at tick
120 for clearing, profiling-heavy and two-emitter review scenes. The candidate also
matches when 120 ticks are requested once, as twenty six-tick requests, 120
one-tick requests, or mixed request sizes. A direct build-to-build sample reports
20 queue submissions for one 120-tick request versus 120 before batching; the
captured CPU submit times are single samples and are not performance evidence.
See [parity report](measurements-o08-batch-parity.json) and its
[reproducible runner](../scripts/simulation_batch_parity.py). Alternating sustained
catch-up bursts now have three alternating baseline/candidate pairs on clearing
and two-emitter review. After 600 warm-up ticks, each timed request advances 7,200
fixed ticks without rendering: host request latency fell by 293 ms and 318 ms at
the respective workload medians, while reported queue-submit CPU time fell by
174 ms and 177 ms. All six pairs improved. The 7,200 submissions fell to 1,200
per run. These results support catch-up burst efficiency only; they do not measure
render throughput, moving-route frame cost or GPU completion latency. See
[burst report](measurements-o08-batch-submit-cost.json) and its
[reproducible runner](../scripts/simulation_batch_cost_study.py). Continuous-route,
native-window and other-adapter acceptance remain open.

The route benchmark now accepts fixed simulation steps per rendered sample and
keeps an independently selectable one-submit-per-tick baseline, also exposed as
`--disable-simulation-batching` and the shared Session command
`set_simulation_batching`. Four workloads have three alternating 120-second
moving-route pairs after ten-second warm-ups at six ticks per sample (10 Hz);
baseline and candidate tick/camera fingerprints match for every sample. Median
queue-submit CPU fell by 0.20–0.23 ms/sample across all four workloads. Median
full frame work improved by 0.17–0.24 ms for clearing, profiling-heavy and
two-emitter review, but regressed by 0.26 ms on Material Atelier. GPU-render
medians rose by 0.01–0.11 ms on three workloads and were mixed on profiling-heavy;
frame-work p95 also regressed on Material Atelier and was mixed on the heavy scene.
Keep the serial path available: batching reduces CPU submission cost, but its
full-frame benefit depends on the workload and is not a universal rendering or
native FPS gain. See
[route report](measurements-o08-batch-route.json) and its
[runner](../scripts/simulation_batch_route_study.py).

A separate three-pair native-window clearing-orbit comparison on M1 Max/Metal
records 5,175–5,218 rendered frames per 120-second run. Median paired batched-minus-
serial deltas are +0.0003 ms native CPU frame work, +0.016 ms CPU simulation
submission, -0.085 fps, +0.00004 ms smoke compute and -0.0034 ms atmosphere/fire.
These are effectively flat whole-window results with mixed small stage changes;
they do not establish a native performance win. Fixed-tick parity remains covered
by the separate image study. Broader native workloads, continuous visual review
and other-adapter/DX12 acceptance remain open. See
[native report](measurements-o08-batch-native.json) and its
[runner](../scripts/simulation_batch_native_study.py).

The native study now also covers Material Atelier's 120-second `material-orbit`
in three alternating pairs. Median batched-minus-serial deltas are -0.073 fps,
-0.0054 ms native CPU frame work, +0.0227 ms CPU simulation submission,
-0.00008 ms smoke compute and -0.0070 ms atmosphere/fire. These small changes do
not show a whole-window gain. See
[Material Atelier report](measurements-o08-batch-native-materials.json).

**Acceptance:** image/state comparisons survive pause/reset, repeated fixed steps,
camera moves, resource recreation and invalid shader rollback. Report memory,
total GPU/CPU time and supported formats on each backend, including any precision
or transport error. Keep fallback layouts for unsupported hardware.

**Deliverable:** a resource budget followed by individually justified layout/pass
changes; sparse simulation remains evidence-gated research. Dependency: O01;
repeat the audit after O03/O05/O06 introduce resources. Background:
[Apple GPU and tile-based rendering guidance](https://developer.apple.com/documentation/metal/tailor-your-apps-for-apple-gpus-and-tile-based-deferred-rendering).

**Implemented O08 change:** one optical HDR color snapshot allocates lazily when a
camera-visible optical
batch first appears. The original normal/depth target remains
read-only during optical resolve, so the pass no longer copies it or writes a
second color attachment. Diffuse 640×360 scenes save 3,686,400 known bytes relative
to the original unconditional snapshot pair; optical scenes use one snapshot and
save another 1,843,200 bytes relative to the prior pair design. At 640×360 this
also removes 7,372,800 modeled logical copy/attachment bytes from each optical
frame. A live material edit was verified to allocate the color snapshot without
changing fixed-tick output relative to the prior build. The effect-depth and
flame-coverage target also uses adapter-gated Rg16Float when filterable and usable
as a render attachment and sampled texture, with Rgba16Float fallback. On M1
Max/Metal at 640×360 this saves 921,600 known bytes and matched smoke and metal
captures were pixel-identical at native capture scale. Smoke density/temperature ping-pong volumes
also use adapter-gated Rg16Float storage when `TEXTURE_ADAPTER_SPECIFIC_FORMAT_FEATURES`
and sampled/write-only storage support are available, with an Rgba16Float fallback.
The measured pair saves 1,179,648 bytes; reset/replay verification and matched
smoke/metal captures passed on M1 Max/Metal. Three alternating 20-second and
three 60-second material-orbit pairs found no GPU timing benefit: the longer run
had a +0.0087 ms median optical-resolve delta and +0.0003 ms total GPU-render
delta, while frame-work results varied. The normal-path HDR snapshot copy can now
be bypassed by the experimental `--optical-no-copy` option (also
`render.optical_no_copy` in scene JSON). It writes optical fragments to a lazily
allocated color overlay and R8Unorm coverage mask; post selects covered pixels
while the source HDR remains immutable. Four matched fixed-tick views, including
compact HDR, were pixel-identical on M1 Max/Metal. At 640×360, the candidate
RGBA16F uses the overlay alpha channel for coverage, replacing the 1,843,200-byte
snapshot with an equally sized output and no extra mask allocation. Known optical
scene allocation therefore matches the snapshot path. The revised full-frame
logical copy/attachment/post-read model is 5,529,600 bytes versus 7,372,800 for
copy plus optical attachment, a modeled 1,843,200-byte reduction; this is not
measured physical bandwidth. Three alternating 120-second material-orbit pairs
found a -0.01817 ms median GPU-render delta (~0.70%), while frame-work deltas
varied. No practical speedup is established. Compact HDR still uses the separate
230,400-byte mask and its different traffic model. The experiment stays disabled by
default pending broader pass-layout review and Windows/DX12 validation. The
per-frame gate uses
camera-frustum draw batches, so offscreen optical materials skip both the copy and
resolve; fully occluded surfaces may still activate the pass. The snapshot remains
resident after first visibility to support later camera/material edits. See
[measurements-o08.json](measurements-o08.json).

**Inventory checkpoint (17 October 2026):** known allocations, resource lifetimes,
per-frame logical attachment/copy traffic, nominal smoke sample/store footprint,
dynamic/startup upload payloads and a live M1 Max/Metal texture-format query are
recorded in [measurements-o08.json](measurements-o08.json). The report does not
measure external-memory bandwidth. Lazy optical snapshots reduce diffuse-scene
allocations by 3,686,400 bytes; adapter-gated Rg16Float effect coverage saves
921,600 bytes and smoke volumes save 1,179,648 bytes on the measured M1 Max/Metal
adapter. The opt-in optical overlay path removes the HDR copy with exact fixed-tick
image parity on this adapter. RGBA16F alpha coverage avoids a separate mask and
preserves known allocation size; compact HDR still needs the 230,400-byte mask.
No practical timing gain is demonstrated. Validate fallback and pass layouts on other adapters,
including Windows/DX12.
The 17 October current-renderer inventory refresh reports 22,809,480 known bytes
for clearing before optical activation and 16,883,296 bytes for Material Atelier
with its visible HDR snapshot; timestamp staging and the tile debug uniform are
now counted. See `current_resource_inventory_refresh` in the measurement report.
O08 layout/pass experiments and the later sparse-smoke gate
remain open.

**O06×O08 factorial (18 October):** the eight combinations of direct/reused
opaque lighting, copy/no-copy optical output and RGBA16F/packed HDR were captured
on a high-dynamic mixed smoke/fire/reflector/glass workload; each of seven
non-baseline variants also ran three paired 120-second routes. On M1 Max/Metal,
reuse reduced GPU render by 0.078–0.108 ms in RGBA16F and 0.081–0.107 ms in packed
HDR. Direct no-copy reduced GPU render by 0.026 ms and 0.013 ms, respectively;
direct packed-HDR/copy alone was within run spread. The no-copy captures matched
copy byte-for-byte. RGBA16F no-copy kept known allocation flat while replacing a
1.84 MB snapshot with an equally sized output. Packed HDR saved 1.84 MB compared
with RGBA16F, with measurable high-output image differences; packed-HDR no-copy
adds a 0.23 MB mask over packed-HDR copy. Keep all options independent and
experimental until temporal, broader workload and adapter fallback checks pass.
See [measurements-o06-o08-factorial.json](measurements-o06-o08-factorial.json).

An opt-in `Rg11b10Ufloat` HDR color-target trial is available with
`--compact-hdr` (or `render.compact_hdr` in scene JSON). It halves bytes for the
primary HDR target and its optical snapshot when the adapter exposes the required
render feature and filterable sampled/copy/render usages. On one M1 Max/Metal
adapter, three fixed-tick material/smoke still pairs looked very similar, but
were not pixel-identical: mean absolute RGB error was 0.32–0.45/255 and the
smoke view reached 30/255 in sparse pixels. The variant remains opt-in; motion,
timing, DX12 and other-adapter fallback/rendering checks remain open. See
[measurements-o08.json](measurements-o08.json).

## Delivery order and promotion

| Wave | Work | Exit evidence |
|---|---|---|
| 1 | O01 profiling; O08 resource inventory | Comparable complete-frame reports and identified bottlenecks |
| 2 | O02 whole-map reuse; O07 bounds/draw metadata | Image-preserving A/B results and correct invalidation |
| 3 | O03 single-emitter tiles; O07 culling/instancing as justified | Net gains including maintenance cost; no dropped effects/casters |
| 4 | O04 visual detail and O05 absorption cache | Reviewed stills/motion and measured quality/cost choices |
| By measured priority | O06 optical specialisation; O08 selected layout changes | Workload-specific net benefit and backend checks |
| Later | Multi-emitter ownership/stress; sparse simulation | Explicit contracts, correctness and scaling evidence |

O06 need not wait for visual experiments if profiling identifies it as the dominant
cost. Keep each change small enough to disable and compare independently.

For each completed workstream, save a machine-readable report plus a concise
research entry: hypothesis, implementation/source hashes, prior work, workload,
paired timings, image differences, motion findings, limits and decision. Keep
`implemented`, `automated_checks_passed`, `visual_reviewed` and
`target_hardware_verified` as separate states. Capture/report tools must finish
successfully or return an actionable error rather than an incomplete success.

Run formatting, linting, focused unit/integration checks and GPU verification when
runtime changes land. Re-run native lifecycle checks for affected host work. Actual
Metal and DX12 rendering is required for backend acceptance; Windows compilation
alone does not qualify it. Base M1/16 GB, RTX-3060-class/16 GB and the unresolved
native minimisation gate remain open in [STATUS.md](STATUS.md).

Promote approximations only after owner visual review and performance validation.
Preserve useful alternatives as lab modes. Browser support, a full editor and a
general gameplay framework remain outside this optimisation programme.
