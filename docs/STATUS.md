# Milestone status

17 October 2026. The first development implementation is runnable; visual and
platform acceptance are still open. This is a rendering lab and engine foundation.

Optimisation planning: [eight workstream plans](OPTIMIZATION_PLAN.md) and the
[execution queue](../TODO.md) define profiling, cached shadows, tiled effects,
projected detail, smoke absorption reuse, optical specialisation, object culling/
instancing and resource efficiency. O01's profiling implementation and M1 Max/Metal
workload evidence are complete. O08's inventory and targeted allocation changes
are implemented on M1 Max/Metal; an opt-in packed HDR format now halves target
storage with small still-image differences. Fixed-camera temporal captures, eight
sampled moving-route camera poses and moving-route timing evidence exist; fallback
and cross-backend measurements remain open. O03's bounded single-emitter tile lists and O07's per-camera/per-light culling,
shared meshes, instancing and live object transforms are implemented and measured
on M1 Max/Metal. Platform acceptance gates remain open.

O04's opt-in projected fire-segment LOD is implemented at 40/20 px with 48/24 px
hysteresis. Three matched 640×360 still pairs cover full, medium and low detail;
an 8-second repeated zoom route records tier occupancy. Medium/small tiers lowered
GPU render medians by about 0.11 ms in short serial pairs, while total frame-work
medians were slower and noisy. It remains disabled by default. Slow-orbit visual
review, native-window measurement, Windows/DX12 and other GPU qualification remain
open; see [measurements-o04.json](measurements-o04.json).

O05 now has an opt-in primary fire-light absorption cache at 8³ or 16³, rebuilt
each rendered frame so paused density and light edits are reflected on the next
render. Fixed-tick stills and three short paired orbit runs are recorded in
[measurements-o05.json](measurements-o05.json). The 16³ still is closer to direct
sampling by mean RGB error, but both tiers add a roughly 0.026–0.029 ms GPU build
pass and total GPU render medians were slightly slower. No default promotion is
recommended. Motion/temporal review, rapid density/light edit checks, cache
allocation cleanup while disabled, Windows/DX12 and other GPU qualification remain
open.

O06 now has an opt-in opaque-reflector lighting reuse path. It reverses the
matching same-pixel foreground atmosphere contribution from the HDR snapshot and
uses the opaque normal/depth snapshot; transmissive surfaces keep direct shading.
Three short M1 Max/Metal material-orbit pairs reduced optical-resolve medians by
about 0.19 ms and GPU-render medians by about 0.21 ms. CPU frame-work differences
were noisy. Fixed-tick material and smoke-over-reflector stills were visually close.
The path is disabled by default pending the longer moving route, native-window
measurements and Windows/DX12 or other GPU qualification; see
[measurements-o06.json](measurements-o06.json).

O01 profiling implementation now includes bounded asynchronous timestamps for
smoke compute, shadows, opaque geometry, atmosphere/fire, optical resolve and post;
serial latency and buffered throughput reports; a native vsynced route report;
fixed-step counts; CPU upload/simulation/render/UI/acquisition/presentation spans;
paired per-stage comparisons; optional timing-on/off overhead comparisons; source,
shader, scene and GLB hashes; draw/light/primitive counts; and a known-allocation
GPU memory estimate. `get_metrics` exposes frame-tagged timings. Native presentation
and egui GPU timestamps are recorded. Exact queue-latency measurement remains open:
wgpu timestamps have no calibrated host-clock mapping, so reports preserve
submit-to-readback completion latency separately. The memory figure excludes driver
alignment, transient allocations and timestamp storage. Three alternating 120-second
pairs plus timed/untimed controls cover clearing, `assets/scenes/profiling-heavy.json`
(one plume and eight point lights), and Material Atelier; a separate 120-second
native clearing route records presentation/UI/acquisition/vsync spans. Summary,
provenance and raw-report checksums are in [measurements-o01.json](measurements-o01.json);
full sample reports remain in the local ignored `artifacts/o01/` directory. Identical
baseline/candidate scene inputs characterize run variance and profiling overhead,
not optimization gains. Exact queue latency, adapters without timestamp support,
Windows DX12 and RTX-class rendering remain unverified.

## O08 resource and bandwidth inventory

The original 640×360 clearing/heavy inventory recorded 29,806,088 bytes. The current
renderer reports 22,808,600 known bytes before first camera-visible optical use and
24,651,800 bytes after live optical activation; the color snapshot adds 1,843,200 bytes. The
current Material Atelier capture reports 16,882,416 known bytes. These are
descriptor/structure-size estimates; driver alignment and transient/pipeline
storage are excluded.

At 640×360, the clearing/heavy frame has 15,904,768 bytes of modeled full-frame
attachment clear/write/load/store traffic before shader sampling with the current
Rg16Float effect target (the original RGBA16F estimate was 16,826,368 bytes):
shadow maps, opaque color/normal/depth, atmosphere HDR/effect target, and post output. Optical
frames add 3,686,400 logical bytes for the HDR snapshot copy read/write and
3,686,400 bytes of HDR optical attachment load/store. The normal/depth target stays
read-only as an optical shader input, removing its snapshot copy and optical
attachment writes. Seven shadow draws plus opaque geometry reference 84,317,760 bytes of vertex input if each draw fetches the full buffer;
optical geometry adds one more full-buffer reference. These quantities are API/
shader logical work estimates, not measured DRAM bandwidth. Metal tile storage,
caches, compression and overdraw can change external traffic substantially.

The smoke shader now stores density and temperature in adapter-gated Rg16Float
ping-pong volumes, requiring `TEXTURE_ADAPTER_SPECIFIC_FORMAT_FEATURES`; the
RGBA16F fallback remains. This saves 1,179,648 known bytes for the two 48×64×48
volumes. The full-format logical texel-request estimate falls from 20,054,016 to
10,027,008 bytes per fixed step. This is not physical bandwidth: the shader only
consumes x/y, and filtered sampling and cache behavior are hardware-dependent.
Reset uploads use the selected texel stride. GPU reset/replay checks passed, and
fixed-tick smoke/metal captures match the prior format byte-for-byte on this
M1 Max/Metal adapter. O01 measured smoke compute at about 0.0205 ms median,
compared with multi-millisecond post and atmosphere/fire stages; current evidence
does not justify active-region simulation.

A live M1 Max/Metal wgpu format query reported sampled, storage, render-attachment,
copy and filtering support for Rg16Float and the probed alternatives. The effect
depth/flame-coverage target now selects Rg16Float only when it is filterable and
supports render attachment plus texture binding; otherwise it falls back to
Rgba16Float. At 640×360 this saves 921,600 known bytes. Smoke ping-pong volumes
select Rg16Float only with the adapter-specific format feature and required
storage/sample support, falling back to Rgba16Float; they save 1,179,648 bytes.
Pure capability-selection tests now cover the required usages/features and the
Rgba16Float fallback path. They validate the branch logic only; unsupported-
format texture creation, shader pipelines and rendered output still need a
physical adapter without these capabilities.
The live allocation estimate also includes the tile debug uniform (16 bytes)
and timestamp resolve/readback buffers (864 bytes when timing is enabled); the
opaque query-set storage remains excluded. Tile-stat buffers/readbacks were
already included in the existing 192-byte total.
Matched images stayed pixel-identical, and reset/replay checks passed on this
M1 Max/Metal adapter. This is one adapter's result, not DX12 support. The HDR
snapshot now allocates only when a camera-visible optical batch first appears, saving
3,686,400 known bytes in diffuse scenes and optical scenes whose optical geometry
remains outside the camera. Frames without visible optical batches skip the HDR copy
and resolve; the snapshot remains resident after activation. Direct normal/depth sampling removes
another 1,843,200 bytes from the prior pair-of-snapshots design. Live material
activation, camera-away gating and fixed-tick capture parity were verified. Three
alternating 20-second pairs were followed by three 60-second material-orbit pairs. In the longer runs, median
paired optical-resolve delta was +0.0087 ms and whole GPU-render delta was
+0.0003 ms; frame-work deltas varied and do not establish GPU benefit. These
results support the memory and logical-traffic findings, not a timing claim.
Broader routes and Windows DX12/RTX acceptance remain open. Full provenance and
per-resource breakdown are in [measurements-o08.json](measurements-o08.json).
The required `python3 scripts/verify.py --gpu` run passed on this M1 Max/Metal
host, including Clippy, workspace tests, scene validation and GPU integration
checks. This verifies Rg16Float texture/pipeline creation and lazy snapshot lifetime on
Metal, not fallback execution on another adapter or cross-backend behavior. A valid 640×360 Material Atelier scene with an away-facing camera reported
zero visible objects, zero optical batches and zero snapshot bytes. A live reflectivity
edit remained unallocated while offscreen, then allocated one 1,843,200-byte HDR snapshot
when the camera switched to the edited geometry. Turning the camera away again reported
zero optical batches and no optical-resolve timestamp while retaining the snapshot. The
metal-close seed-42 tick-300 image remained byte-identical to the saved reference. This
is frustum visibility, not full occlusion detection, and has only been exercised on
M1 Max/Metal.

The experimental `Rg11b10Ufloat` HDR target reduces the primary color target and
optical snapshot from 8 to 4 bytes per pixel when the adapter exposes the required
feature/usages. Three fixed-tick M1 Max stills looked very similar on visual review,
but 49–78% of pixels changed at low mean RGB error; sparse smoke pixels had a
30/255 maximum channel difference. Four additional fixed-camera captures over ticks
300–1200 show similar appearance and stable error (mean 0.362/255, maximum 9/255)
while fire/smoke evolve. Three alternating 120-second M1 Max/Metal material-orbit
pairs show a -0.0061 ms paired median GPU-render delta, about 0.24%; frame-work
deltas vary and no practical speedup is claimed. Eight sampled route camera poses
at fixed tick 1200 look similar, with mean RGB error 0.362–0.431/255 and maximum
channel error 10/255. The measured benefit is 1,843,200 fewer known target bytes at
640×360 on an optical scene. The format remains off by default. Fallback behavior,
DX12/other adapters and the HDR snapshot/pass-layout gate remain open. Full results are in
[measurements-o08.json](measurements-o08.json); local captures are under ignored
`artifacts/o08/compact-hdr-motion/` and `artifacts/o08/compact-hdr-route-captures/`.

The experimental `--optical-no-copy` overlay path keeps the source HDR immutable,
draws optical results to a separate color target plus R8Unorm coverage mask, and
selects covered pixels during post. Four seed-42 tick-300 image pairs (hero,
metal-close, glass-close, and compact-HDR glass-close) were pixel-identical on
M1 Max/Metal. At 640×360, RGBA16F coverage uses the output alpha channel and
replaces the 1,843,200-byte snapshot with an equally sized output, with no added
mask allocation. The known allocation matches the snapshot path. Its modeled
full-frame copy/attachment/post-read traffic is 5,529,600 bytes versus 7,372,800,
not a physical bandwidth measurement. Compact HDR retains a 230,400-byte R8 mask.
Three alternating 120-second route pairs found a -0.01817 ms median GPU-render
delta (~0.70%); frame-work deltas varied, so there is no practical speedup claim.
The option remains off by default. GPU verification
passed on M1 Max/Metal; native window, fallback adapters and Windows/DX12 remain
unverified. Full evidence is in [measurements-o08.json](measurements-o08.json),
with local captures and reports under `artifacts/o08/optical-no-copy-*`.
The RGBA16F alpha-coverage refinement and its refreshed timing reports are under
`artifacts/o08/optical-alpha-coverage/`.

## O03 single-emitter tile lists

The renderer builds ordered 16×16 scene-pixel lists for fire primitives, ink-smoke
lobes, point lights and particle lights. Per-tile capacities are 64, 36, 8 and 12
respectively. Conservative projection handles camera-inside/near-plane/invalid
cases by including the viewport. Overflow flags select exhaustive shader evaluation
for the affected category; tiled evaluation is enabled by default in this build
and can be switched to exhaustive mode. `set_tile_lists`, capture flags and
benchmark flags also expose an exhaustive baseline and a forced-fallback
diagnostic. Asynchronous frame-tagged counters report candidate memberships,
maximum occupancy and overflow tiles. At 640×360, the buffers add 471,040 list
bytes and 192 counter bytes; the known-allocation estimate for clearing is
30,277,320 bytes.

Four exact-tick view sets (hero perspective, close smoke, orthographic and glass
close-up) matched byte-for-byte among tiled, exhaustive and forced-fallback modes.
The hero clearing capture was visually inspected. Three alternating 10-second
serial pairs after 5-second warm-ups on M1 Max/Metal measured full-render GPU
medians from 3.017 to 2.575 ms for clearing, 3.878 to 3.393 ms for the heavy
single-plume/eight-light scene, and 2.984 to 2.478 ms for Material Atelier. Full
frame work paired median deltas were -2.202, -0.991 and -1.022 ms. List build cost
was 0.413–0.633 ms GPU median and 0.10–0.16 ms CPU encoding; the material case had
a +0.279 ms CPU encode delta even as full-frame work fell. Route runs recorded no
natural overflow. These stills and M1 Max results do not establish motion quality,
native performance or cross-device support. Multi-emitter ownership, 8×8 tile
evaluation, natural over-capacity stress, Windows/DX12 and other GPU vendors remain
open. Details and hashes are in [measurements-o03.json](measurements-o03.json); raw
pair reports are in local ignored `artifacts/o03/`.

Emitter/profile ownership remains one-emitter at runtime. Scene emitters now
bind their thermal/fire profile by `effect_profile` and their colocated primary
point light by `light_id`; legacy scenes may omit the light link and use the
original position match. This removes renderer-side light identity inference
from migrated scenes, but does not add per-emitter smoke fields, tile lists, or
fire-light shadow maps. Multi-emitter stress and Windows/DX12 checks remain open.

`python3 scripts/verify.py --gpu` passed on this host: formatting, Clippy,
30 workspace tests, scene validation and material/fire GPU checks. The verifier
reports `native: false`; native-window lifecycle and Windows/DX12 rendering remain
unverified.

## O02 whole-map shadow cache

The renderer now keeps all seven shadow maps valid across frames with unchanged
casters, effective shadow transmission, sun projection and fire-light projection.
Camera and light color/power changes retain the maps. Sun projection edits redraw
the sun map; fire-light position/range edits redraw the point cube. Reset, successful
shader reload and uncertain key state redraw all seven maps. Cache metrics report
the dirty reason, per-face mask, redrawn map count, 5,767,168 resident map bytes and
CPU shadow-encoding time. `set_shadow_cache` forces redraw through the protocol;
benchmark reports also accept `--force-shadow-redraw`. Live `set_object_transform`
updates the draw transform, conservative bounds and baked reference vertices, and
returns a per-object transform revision. O02 per-face tracking uses old and new
conservative bounds against each map frustum. Shadow-
participation material edits test the bounds of affected objects. The renderer
redraws only marked faces and reports a `[sun,+X,-X,+Y,-Y,+Z,-Z]` mask through
`get_metrics`. The M1 Max protocol check moved `fire-ring-0` and dirtied three maps;
its capture was byte-identical to a forced seven-map redraw. Missing or uncertain
bounds and unsupported caster changes still take the full-map path.

The captures at 640×360 with seed 42/tick 0 were byte-identical for first cache
render, forced redraw and subsequent cache hit. Protocol checks confirmed hits on
camera/light-power changes and invalidation for sun movement, reset, successful
shader reload and material shadow-class change; unit checks cover caster, material,
sun and point projection/range revisions. O01's transactional shader rollback
checks still apply; failed reloads do not invalidate because the working pipelines
remain installed.

Three alternating serial offscreen 120-second clearing-orbit pairs after 10-second
warm-up on Apple M1 Max/64 GB/Metal at 640×360 compared identical scene inputs.
Forced redraw versus cached medians of run medians were 6.365 versus 5.592 ms frame
work and 3.151 versus 2.672 ms whole-render GPU time; paired candidate-minus-control
median deltas were -0.769 and -0.479 ms. CPU shadow encoding was 0.558 ms versus
0.000083 ms; CPU upload was 0.345 versus 0.219 ms, as matrix writes stop with shadow
reuse. In the measured cached runs, all 7200 frames were hits and none redrew a map;
forced mode redrew seven maps each frame. These are M1 Max static-route results,
not native-window or Windows DX12 acceptance. Full pair/run provenance is in
[measurements-o02.json](measurements-o02.json), with raw samples under local ignored
`artifacts/o02/shadow-static/`.

Final `python3 scripts/verify.py --gpu` completed successfully on Apple M1 Max
with Metal (`verified: true`, `gpu: true`, `native: false`). Workspace formatting,
clippy, 24 unit tests, scene validation and material/fire GPU checks passed. Native
window lifecycle and Windows DX12 rendering remain unverified.

## O07 object bounds, culling and shared meshes

The renderer stores each geometry/material key once in local space and retains a
stable object/material identity, transform, range and conservative world AABB for
every scene object. Camera visibility and each of the seven shadow frusta are
computed independently; invalid/unknown bounds remain visible. Batching extends
only across consecutive compatible objects, preserving authored draw order. The
shared Session command and engine-lab flags independently select culling and
instancing, including the baked exhaustive reference mode.

On the 276-object clearing scene, 68 geometry/material keys use 143,454 shared
vertices (8,607,240 GPU bytes), versus 175,662 object-expanded vertices
(10,539,720 bytes). The selectable instance transform buffers use 247,296 bytes.
The normal shared path reduces geometry GPU storage by about 16% versus one
object-expanded vertex buffer. For exact comparison mode, the renderer lazily adds
the 10,539,720-byte unshared GPU buffer; it also retains 10,539,720 bytes of CPU
baked reference vertices so the setting can be switched during a Session.

Three alternating 6-second clearing-orbit pairs with 2-second warm-up on Apple
M1 Max/Metal compared culling disabled against culling enabled while instancing
stayed enabled. Median camera visibility fell from 276 to 157 objects; median
submitted vertices fell from 175,662 to 89,571 and camera draw batches from 69 to
26. Across the seven maps, median visible-object counts were 276/61/81/2/31/72/76;
the sun map retains all 276, including objects outside the camera view. Median CPU
culling cost was 0.023 ms (p95 0.063 ms). Paired whole-frame work delta was
-0.388 ms; GPU render delta was -0.018 ms, which is effectively unchanged within
three short pairs. A separate exhaustive-versus-shared/culling paired run also
showed nearly flat frame and GPU times. See the measurements report for all run
summaries and limits.

At 640×360, seed 42 and tick 0, the baked culling-off/instancing-off hero capture
matches the saved pre-change PNG byte-for-byte. Instanced GPU transforms change 1
hero pixel, 1 orthographic pixel, 4 smoke-close pixels and 12 glass-close pixels
against their baked references due to floating-point/raster quantization. In all
four inspected views, enabling culling adds zero further pixel differences versus
instancing-only. The four images were visually inspected. Bounds and frustum tests
cover GLB geometry, transformed positive nonuniform scale/rotation, perspective,
orthographic, behind-camera, side-plane and invalid-bound cases.

`python3 scripts/verify.py --gpu` passed on M1 Max/Metal: formatting, Clippy, 30
workspace tests, validation, material GPU and pixel-fire GPU checks. It reports
`native: false`; native window and Windows DX12 rendering remain unverified.
Live object transforms now update the model matrix, conservative bounds and baked
reference vertices, returning a per-object transform revision. Per-face invalidation
and its comparison are recorded in [measurements-o02.json](measurements-o02.json).
Full provenance and checksums are in
[measurements-o07-culling.json](measurements-o07-culling.json).

Implemented: reusable engine/library separation, native Metal/DX12 selection,
versioned/validated JSON scenes, static GLB/PNG assets, fixed-step smoke grid,
seeded fire/embers, directional/point shadows, HDR pixel rendering, integer
presentation, orthographic/perspective cameras, shared inspector/JSON-lines
operations, exact-tick capture, transactional shader reload and route benchmarks.
Named effect profiles now own bounded flame curves, cooling fragments, embers,
HDR palettes, edge/tip breakup, curve quality and thermal source/cooling/lift.
Smoke now has radial illumination/absorption from its nearest two local lights,
with up to eight point lights per scene and geometry shadows on the fire light. Pixel style controls
remain separate from world-space effect state. See EFFECTS.md.

Materials now support metallic/roughness reflection, bounded SSR with environment
fallback, single-layer refraction/absorption and faux subsurface backlighting.
A live GPU material table, shared inspector/protocol controls and the Material
Atelier comparison scene are implemented. See MATERIALS.md for explicit limits.

## Verification on this host

- Rust formatting, Clippy with warnings denied, 22 unit tests, asset decoding,
  schema discovery and scene validation passed.
- Metal GPU integration passed: deterministic same-device replay, malformed
  commands/invalid edits, capture completion, orthographic rendering, visible
  self-shadow/glow mutations, profile/particle/HDR palette edits, and invalid world/
  fire shader rollback. Additional checks exercise moving coloured lights and
  the independent fire-breakup controls. Legacy scene defaults and invalid profile references pass
  the unit checks.
- Native resize, fullscreen, frame capture, command handling and shutdown passed.
  Automated minimization is unresolved on this macOS host: the OS keeps reporting
  `minimized: false` after the request. `verify.py --native` correctly fails that
  gate and saves partial results; do not report full native acceptance.
- macOS ARM64 and Windows x64 GNU release builds succeeded. Windows PE executable
  was cross-compiled here. Initial repository CI passed on both hosted platforms;
  that result predates this effect-profile update and is not a visual GPU test.
- Matched stills were inspected. Original puff shapes and child bubbles remain;
  contact normals/ink and shared density-grid shadowing are approximate. The
  current art still has an overly regular stacked silhouette. Owner acceptance
  and motion review against the reference remain open. See SMOKE_DIRECTION.md.

## Measured performance

### O01 profiling characterization

M1 Max / 64 GB / Metal at 640×360. Each offscreen value is the median of three
120-second run medians after a 10-second warm-up. Baseline and candidate scene
inputs are identical within a workload. Pass intervals can overlap, so stage values
must not be summed; the whole-render measurement is separate.

| Workload | Frame work median / p95 ms | Whole-render GPU median / p95 ms | Leading GPU stage medians ms | Known GPU allocations |
|---|---:|---:|---|---:|
| Clearing orbit | 6.31 / 10.61 | 3.15 / 4.17 | post 2.53; atmosphere/fire 2.42; opaque 1.71 | 29.8 MB |
| Heavy plume + 8 lights | 6.75 / 11.97 | 3.87 / 5.04 | post 3.25; atmosphere/fire 3.13; opaque 2.40 | 29.8 MB |
| Material Atelier | 6.43 / 10.73 | 3.39 / 4.70 | post 2.75; optical resolve 2.65; atmosphere/fire 1.59 | 20.4 MB |

GPU timestamp instrumentation raised median frame work by 0.11–0.28 ms in the
paired timed/untimed controls. Timing-disabled exact-tick captures were byte-
identical to the timed capture. The separate native clearing route ran for 120 s
at 43.48 measured frames/s on this desktop, with 8.83 ms median / 70.28 ms p95
native CPU frame and 6.36 ms median / 64.79 ms p95 surface acquisition. These
native results include the active display and vsync path and must not be compared
directly with unpaced offscreen values. Exact queue time is null because wgpu
timestamps have no host-clock calibration; async readback completion latency is
reported separately. See [measurements-o01.json](measurements-o01.json) for source
hashes, paired deltas, coverage, workloads and report checksums.

Apple M1 Max / 64 GB / Metal, 640×360 pixels, 48×64×48 smoke grid. Each route
contains 7,200 frames over 120 simulation seconds after 10 seconds warm-up.
Runs are offscreen and unpaced; these are not 1080p native-window FPS results.
GPU timestamps exclude simulation compute; total frame work includes simulation
submission and synchronous GPU completion. Raw samples are in artifacts; compact
source hashes and metrics are in measurements.json.

| Current variant | Frame work median / p95 ms | GPU render median / p95 ms |
|---|---:|---:|
| campfire_radial | 3.110 / 5.478 | 1.570 / 2.893 |
| smoke_heavy_8_lights | 4.526 / 7.289 | 2.268 / 3.327 |

The table above records the effect-profile revision before the material layer.
Current material comparison results are in measurements-materials.json.

The stress route uses maximum supported child count/size and smoke source density
with a close orbit and eight active point lights. It exercises one large on-screen
plume, not many emitters.
Experiments remain opt-in: timings alone do not justify promoting a visual mode.
The earlier three-experiment report is preserved in measurements-smoke-baseline.json;
those numbers predate the fire-profile update. Historical before/after reports compare
complete renderer iterations, including changed heat, radial lights, edge breakup and glow; it does not isolate
one algorithm. GPU p95 did not improve uniformly. The six-second fixed-camera
motion capture measured effect CPU sampling/upload at a median 0.0103 ms; see measurements.json for its limited scope.

## Outstanding gates

- Actual Windows DX12 rendering, image/motion review and performance on an RTX
  3060-class/16 GB PC. Compilation is not visual validation.
- Base M1/16 GB measurement and native presentation/UI timing. The provisional
  target remains 60 fps at 1080p with a selected 480×270 scene buffer.
- Fix/qualify native automated minimization and confirm restore behaviour.
- Reference-led billow hierarchy, heat/soot transition and multiple source scales;
  this remains further work. Basic thermal controls/independent cooling now run,
  while heat-driven persistent smoke billows are still proposed. FIRE_FIELDS.md
  specifies the transported-fire/shallow-volume alternative; it is not implemented.
- Owner visual review, including silhouettes, self-shadowing, camera motion,
  temporal stability and all three experimental comparisons.

Development Mac app and Windows executable bundles include editable assets/WGSL,
launch instructions and dependency notices. Mac signing is ad hoc; Windows is
unsigned. Production signing/notarization/distribution remain outside this lab.
Water, clouds, browser support, gameplay frameworks and a full editor are later work.

## Simulation-driven surface heat cue

An opt-in material `heat_response` samples the existing temperature volume for
opaque shading and adds a stepped warm mark with a pixel edge cue. Zero response
preserves pixel output. Matched captures at seed 42/tick 300 were repeatable; the
active cue changed 220 pixels near the fire base. Three 120-second M1 Max/Metal
route pairs measured a 0.0112 ms median paired GPU-render increase. The prototype
remains opt-in; a follow-up fixed-tick check across hero, fire-study, smoke-close
and orthographic cameras changed 5–203 pixels, with the clearest mark in close
views and only five changed pixels in orthographic view. Repeated fire-study
output was pixel-identical. This is a style check; gameplay readability and
DX12 acceptance remain open. See
[RESEARCH.md](RESEARCH.md) and [measurements-heat-cue.json](measurements-heat-cue.json).

## Material comparison validation

- The original clearing at seed 42 / hero / tick 300 was pixel-identical before
  and after adding the material layer. All 20 unit tests, lint/formatting and the
  Metal integration suites passed, including live metallic/roughness, transmission/
  IOR/absorption, subsurface/thickness/colour edits, exact restoration/replay,
  orthographic capture, invalid values and invalid optical shader rollback.
- Matched five-camera stills and a 120-frame moving-camera sequence were generated.
  Metal/glass/scattering are visually distinct. SSR has visible screen-space
  discontinuities and roughness filtering is approximate; not production optical
  acceptance. Foreground smoke integration is shared but strong refractive
  distortion across smoke remains approximate.
- Same Material Atelier geometry, lights, 640×360 grid and fixed route; 7,200
  samples each after 600 warm-up frames. Offscreen/unpaced; GPU excludes smoke
  compute. Complete variants, not isolated-pass overhead:

| Material variant | Frame work median / p95 ms | GPU render median / p95 ms |
|---|---:|---:|
| full | 5.574 / 10.396 | 2.573 / 4.353 |
| environment-only | 4.542 / 8.282 | 2.227 / 3.590 |
| diffuse-baseline | 3.528 / 6.213 | 1.528 / 2.472 |

## Flame-cluster iteration

Rounded swept lobes now follow short parent curves with smaller upward branches.
Detached pieces can originate on either curve; fragments and embers use their
actual world-space positions as derived local-light sources. The budget is 12
active lights globally; geometry evaluates those sources and smoke adds its two
most influential, with shared density absorption. Their colours/powers follow
particle heat and lifetime. No per-particle solid-geometry shadows are generated.
`inspect_effects`, live controls and omitted-work diagnostics expose the state.

The material comparison table above describes commit 42d8af9 before adding
particle lighting; it must not be treated as a timing of this fire revision.
Current fire comparisons are in measurements-fire-clusters.json.

| Fire variant | Frame work median / p95 ms | GPU render median / p95 ms |
|---|---:|---:|
| clustered-lit | 4.883 / 10.480 | 2.660 / 5.527 |
| clustered-unlit | 3.358 / 9.452 | 1.839 / 5.068 |
| long-curves-unlit | 3.307 / 9.291 | 1.809 / 4.944 |

All variants used 7,200 moving-route frames after 600 warm-up frames on the
M1 Max / 64 GB / Metal at 640×360. Timings are offscreen and unpaced; GPU render
excludes smoke compute. Variance is substantial at p95; these are not target
hardware or native presentation acceptance results. The clustered-lit versus
clustered-unlit pair isolates enabling supplementary particle lighting within
otherwise identical current flame/smoke settings.

The final format/lint checks, 20 unit tests and both Metal GPU integration suites
passed. Tests cover branch/particle capacity, stable moving light identities and
three-axis motion, light-free geometry equality, visible illumination changes,
invalid light/branch budgets, replay and shader rollback.

The current macOS application and Windows x64 GNU executable bundles rebuilt
successfully with assets/shaders/notices. The self-contained Mac bundle rendered
the material scene from outside the checkout. Native Mac commands successfully
resized to 1440×900 logical pixels, entered fullscreen, returned to the original
window size, changed a material, captured a frame and shut down. The inspector
and material scene were visually inspected in the native window. The earlier
minimization gate is still unresolved; no full native-suite pass or Windows
DX12 visual validation is claimed.

## Solid pixel fire and heat distortion

The clearing profiles now use opaque occupied flame pixels with four discrete
HDR heat bands. Bloom/dither are suppressed inside solid flame pixels, preserving
external glow. The existing slow curves, branches, detached pieces and derived
lights remain independent. A bounded hot-air post warp samples the existing
temperature field and uses integer pixel offsets; new effect-depth/coverage data
protects the fire and foreground geometry/smoke. The continuous treatment and
heat-off mode remain live controls. See EFFECTS.md for authoring and limitations.

Formatting/linting, 20 unit tests and the Metal integration suites passed. New
GPU checks cover discrete flame colours, unchanged particle/light reconstruction,
visible shimmer, foreground stripe protection, fixed-tick restoration/replay,
invalid values and post-shader rollback. The source M1 Max captures and selected
motion frames were inspected; human art acceptance remains open. The older
material/fire-cluster tables above describe their recorded revisions, not this
new rendering treatment. Current timings are in measurements-pixel-fire.json.

| Pixel-fire treatment | Frame work median / p95 ms | GPU render median / p95 ms |
|---|---:|---:|
| solid-heat | 5.450 / 9.538 | 3.093 / 3.842 |
| solid-no-heat | 5.419 / 9.419 | 3.059 / 3.787 |
| soft-no-heat | 5.353 / 9.255 | 3.054 / 3.788 |

Each variant has 7,200 moving-route samples after 600 warm-up frames, on this
M1 Max / 64 GB / Metal with a fixed 640×360 scene grid. GPU render timings exclude
smoke simulation compute; total frame work includes simulation submission and
GPU completion. These are offscreen/unpaced results, not native 1080p FPS or
target-hardware qualification. All three variants use the new effect-depth
target, so this does not isolate its cost against the preceding binary.

The current Mac and Windows x64 GNU development bundles build successfully.
The Mac window captured the new pixel/heat treatment, and the self-contained Mac
bundle produced the identical fixed-tick image from outside the checkout. Windows
DX12 visual acceptance and the existing native minimization gate remain open.
