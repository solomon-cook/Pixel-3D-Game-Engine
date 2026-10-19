# Rendering research

Every variant remains independently selectable. Baseline defaults remain in
place pending visual review and Mac/Windows qualification. No technique here is
claimed as an unprecedented invention.

## Pixel-cluster lighting

Hypothesis: grouping neighbouring illumination on coherent surfaces produces
more intentional shapes at low resolution without flattening material colour.
Implementation: a 2×2 neighbourhood rejects different normals and depth breaks,
then partially shares luminance while retaining local chroma. Display-space
luminance quantisation and ordered dithering remain available in the baseline.
Compare fine silhouettes, bright fire edges, terrain shading and slow pans.
The current experiment shares illumination in screen-aligned groups; investigating
surface-anchored groups is a next step if camera crawling is objectionable.

## Stable smoke detail

Hypothesis: density variation advected with smoke reads more coherently than
screen-aligned ray offsets. Implementation compares screen-hashed ray jitter
with fixed ray positions and moving world-space density detail. This is an
approximation to material-attached detail; the detail field itself is procedural,
not yet a transported coordinate field. Compare slow orbit, disocclusion and
thin wisps rather than judging one still.

Prior art: [Hashed Alpha Testing](https://research.nvidia.com/publication/2017-02_hashed-alpha-testing),
Wyman and McGuire (2017), explores stable hashed transparency sampling. Our
volumetric treatment is an experiment informed by that problem, not a copy of
its algorithm or an established solution to all temporal aliasing.

## Connected motion

Hypothesis: coherent gusts communicate a shared environment more strongly than
independent animation. A spatial wind function drives the advection velocity;
the experiment additionally couples flame bending and ember drift to that field.
The baseline uses steady wind for smoke and separate ember/fire trajectories.
Compare gust onset and direction, flame readability, smoke response and replay.

## Projected fire detail

Hypothesis: reducing fire tongue curve segments below a projected-size threshold
can lower per-pixel fire evaluation without changing the simulation or selected
pixel grid. The opt-in experiment estimates projected height for both camera
projections and uses 40/20 px downshift thresholds with 48/24 px return thresholds.
It preserves the full deterministic frame for bounds and particle lights. At
640×360, fixed orthographic captures measured 66 px (full), 28.3 px (tier 1,
6→4 segments) and 16.5 px (tier 2, 6→3). The matched images differed in 0, 59 and
55 output pixels respectively; visual inspection found the changes confined to
the small flame silhouette. An 8-second repeated zoom route spent 64/314/102 frames
in tiers 0/1/2 without frame-to-frame tier chatter.

The 8-second zoom suggested small GPU savings but noisy frame cost. A follow-up
20-second orbit, including a close-smoke approach and repeated six times in three
alternating 120-second serial pairs on M1 Max/Metal, occupied tiers 0/1/2 for
27.5/54.4/18.1% of frames. Median rendered primitives fell from 81 to 71; GPU
render improved 0.065 ms at the median of paired deltas, while whole-frame deltas
were mixed and improved only 0.012 ms at the median. Fourteen matched threshold
checkpoints preserved deterministic fire counts, bounds, emitted lighting and
particle identities; heat is not directly exposed by the inspection API, though
the segment reduction follows full simulation sampling in code. Contact-sheet
review found differences localized to the small flame. This still does not review
continuous flicker/crawl/attachment or establish value across other fire sizes and
profiles. Keep the experiment disabled by default pending broader artistic and
portability review. Reproduce with
`python3 scripts/projected_detail_orbit_study.py --benchmark`; tracked summary is
in [measurements-o04.json](measurements-o04.json), and captures/raw runs remain in
ignored `artifacts/o04/`.

## Evidence procedure

Run `scripts/experiments.py` after a release build. Each variant uses seed 42,
tick 300 and the same three cameras, plus a moving 120-second route after ten
seconds of warm-up. PNG/JSON captures and raw frame samples go to artifacts.
Keep numerical findings in docs/STATUS.md and record visual limitations there.
Promotion requires visible improvement, acceptable frame cost and cross-platform
review. A failed hypothesis is retained as useful evidence, not silently enabled.

## Smoke compute bind-group simplification

Hypothesis: because `smoke.wgsl` declares only group 1, the render `Globals`
group at index 0 might be omitted from each compute pass. The direct removal
experiment fails wgpu validation at dispatch: the explicit `advection` pipeline
layout still requires a bind group at index 0. No render, visual, or timing result
was produced. The coordinated follow-up moved smoke resources to group 0, changed
the pipeline layout to contain only those source-local resources, and removed the
render Globals bind. It passed GPU validation and preserved clearing,
dual-emitter, profiling-heavy and Material Atelier tick-120 images. Three
clearing-orbit pairs lowered median simulation encode by 0.005–0.015 ms, while
profiling-heavy and Material Atelier three-pair results did not repeat that CPU
change consistently. Keep the layout for its reduced bind-command count, without
a general timing, GPU-render or native-window claim. See
[the report](measurements-o08-smoke-bind-layout.json).

## O08 smoke-step Globals upload cleanup

Hypothesis: `update_globals` should not queue the render-only Globals uniform
write during smoke compute, because the advection shader reads fixed-step inputs
from its source-local configuration. Tick-120 clearing and two-emitter captures
remain byte-identical. Four native M1 Max/Metal three-pair routes now confirm
about 1.37–1.38 fewer Globals writes and 1.16–1.17 KB fewer uploaded bytes per
rendered frame. CPU simulation-encode median deltas are mixed across
clearing/profiling-heavy/Material Atelier/two-emitter: -0.017/+0.014/-0.014/
+0.008 ms. FPS and other stage results also vary; keep this as verified upload
traffic reduction, without a throughput claim. The reports distinguish native
CPU spans and use actual fixed ticks for smoke-compute timestamp coverage. See
[clearing](measurements-o08-globals-upload-native.json),
[profiling-heavy](measurements-o08-globals-upload-native-profiling-heavy.json),
[Material Atelier](measurements-o08-globals-upload-native-materials.json),
[two-emitter](measurements-o08-globals-upload-native-two-emitter.json), the
[offscreen report](measurements-o08-globals-upload.json) and the
[reproducible runner](../scripts/globals_upload_native_study.py).


## Accepted visual direction from this session

Keep the original large spherical smoke puffs. Add smaller secondary spheres as
parts of them. Preserve the main motion and shading. Reject noisy sculpting and
a fused continuous plume: those iterations obscured the forms the owner liked.
The original reference establishes inked contours, broad warm/cool bands and
forked hot-yellow fire. The later landscape images establish pixel density only,
not output size, camera framing or aspect ratio. No reference artwork is bundled.

The current child-puff count and size are authorable settings, making this
relationship tunable without editing shaders or the simulation.


## Cheap connected smoke shading

Owner clarification: keep rounded individual puffs, but darken intersections
and deeper smoke where the plume blocks the fire. Do not flatten all normals
into one averaged plume normal. A metaball-like relationship should remain
cheap when smoke occupies much of the view.

Implementation: blend the two closest analytic surface normals only near a
contact; retain separate large/secondary lobes and soften interior ink. Estimate
firelight transmission with six midpoint density samples through the existing
48×64×48 simulation grid. Keep a cool soot floor, with optional internal emission.
Skip smoke tests outside the volume and child tests outside conservative bounds.
No surface-search loop or mesh reconstruction is added to the inked renderer.
This only approximates smooth union: silhouettes are still analytic puff caps,
not a mathematically reconstructed metaball surface. Small lobes do not cast
exact geometric shadows. The initial interval-union shadow implementation was
replaced by the fixed-sample approximation to reduce cost.

Matched captures: artifacts/occlusion-unshadowed.png and
artifacts/smoke-contact-lighting.png (seed 42, tick 300, smoke-close).
Short exploratory timing, 600 moving-route frames after 120 warm-up frames,
M1 Max/Metal/640×360: initial analytic shadow median GPU 3.512 ms, p95 5.157 ms;
coarse-grid shadow plus bounds/local blend median 2.870 ms, p95 4.014 ms.
Both measure the whole renderer. This is not a controlled per-pass cost or proof
of arbitrary plume-count scalability. The final long-route report supersedes
these preliminary timings. The current scene contract supports one emitter;
many-emitter smoke still needs instancing/tile culling and dedicated stress tests.
Keep the fixed pixel grid while reducing secondary lobes or effect samples for
lower effect quality. Do not reduce scene resolution automatically.


The next reference-led generation and scale pass is specified in
[SMOKE_DIRECTION.md](SMOKE_DIRECTION.md). Its recommendations are design work;
they do not imply that hierarchy/area emitters or many-source rendering exist.


## Fire geometry baseline and transported-field proposal

Implemented the reusable bounded curve/particle baseline described in EFFECTS.md:
fixed-tick world-space state, cached GPU records, analytic intersections, HDR
palette/glow controls and separate heat cooling. Matched still/motion captures
are in artifacts/fire-profile.png and artifacts/fire-motion. The first capture
exposed repeated per-segment hot beads; radial heating was changed to follow the
continuous tongue axis. Shape/colour is game-authored, not a fixed engine style.

The next alternative is documented in FIRE_FIELDS.md: a shallow/full 3D field
with transported heat and burning state, guided by authored sources. That path
is a proposal and has not been benchmarked or visually validated. Keep the
current baseline for comparison and inexpensive effects. Do not equate a 2D
presentation with a camera-facing simulation whose state changes with the view.


Latest reference pass: added authorable edge/tip breakup and smaller, more
frequent detached pieces, preserving the slower main motion. Breakup noise is
advected in emitter-relative world coordinates; it is not re-randomised per
frame. Smoke illumination now uses radial falloff from local point lights and
absorption through the same body. Colour is no longer selected primarily by
puff age. Up to eight local point sources are accepted; the nearest two receive
smoke absorption sampling. Only the fire source casts geometry shadows.
This preserves a bounded sample budget but leaves multi-light selection
transitions and many-emitter scaling as explicit research limits.

## Stable emitter light ownership (17 October)

Hypothesis: stable scene IDs should identify an emitter's thermal/fire profile
and primary point light, so later multi-emitter work does not infer ownership
from coincident floating-point positions. Emitters now accept `light_id`; the
linked point light must exist and remain colocated with the emitter. Shipped
scenes declare `fire-light`. Older scenes without the field keep the previous
position-based binding. The current renderer still processes one emitter and
one simulation field, so this is a data-contract foundation only: no multi-fire
visual or scaling claim is made. The baseline fire representation is unchanged;
there is no pixel or shader cost. Verification should cover scene validation,
live `describe` schema, fixed-tick captures and the GPU verify workflow. Per-
emitter simulation buffers, light budgets, tile-list ownership and multi-source
stress tests remain open.

## Active-region smoke gate (17 October)

Decision: do not prototype active-region smoke simulation from the current
measurements. The O01 stage report contains 7,200 smoke-compute samples per
workload: clearing median 0.020583 ms (p95 0.02225 ms), heavy plume median
0.0205 ms (p95 0.022209 ms), while corresponding post and atmosphere/fire
medians are 2.42–3.25 ms. O08 records these timings and notes that stage spans
overlap. The observed compute cost is too small to justify risking heat/density
transport changes for a speculative gain. Reconsider only if profiling shows a
meaningful rise in compute cost or a workload with a materially larger grid/source
count; no visual or scaling result is claimed for active-region simulation.

## O08 format fallback selection

The Rg16Float effect target and smoke-volume selectors now have adapter-free
unit coverage for their usage/feature gates and Rgba16Float fallback. This
checks decision logic, not resource creation or visual output on an adapter that
lacks Rg16Float support. The runtime fallback remains unverified on physical
non-Metal/DX12 hardware; keep the format trials opt-in/gated until that evidence
exists.

## O08 small-buffer accounting

The live allocation estimate now includes the 16-byte tile-list debug uniform
and the timestamp resolve/readback buffers: 864 bytes when timestamp collection
is enabled, zero otherwise. The three tile-stat readbacks were confirmed already
included with the 48-byte counter in the existing 192-byte total, so they are
not double-counted. Timestamp QuerySet storage stays excluded because wgpu does
not expose its allocation size. The corrected delta is 880 bytes for timed
sessions (16 bytes untimed); this improves inventory completeness but has no
meaningful optimization value.

## O03 natural overflow and tile-size diagnostic (17 October)

Added [tile-overflow-stress.json](../assets/scenes/tile-overflow-stress.json), a
deterministic one-emitter scene that saturates the bounded fire-primitive list.
At seed 42/tick 1800, tiled and exhaustive captures matched byte-for-byte for
both 16×16 and experiment-only 8×8 builds. In 120 sampled frames after a 10-second
warm-up, max tile occupancy was 101/64 for 16×16 and 91/64 for 8×8; corresponding
fire-list fallback rates were 1.48% and 0.56%. Smoke and light categories did not
overflow because their candidate maxima match their fixed capacities.

The 8×8 list allocation is 1.843 MB, 3.91 times the 16×16 allocation of 471 KB
at 640×360 (tile-grid rounding makes the ratio slightly below four).
One two-second serial run per mode is too short and unpaired to select a tile size;
the measured GPU build medians were 1.396 ms (16×16) and 1.416 ms (8×8), while
tile-enabled whole-render medians exceeded exhaustive in this saturated scene.
Keep the production 16×16 setting. This stress flame intentionally sacrifices
artistic scale for occupancy coverage; no motion, native-window or DX12 claim is
made. Full sample metrics and image hashes are in
[measurements-o03-overflow.json](measurements-o03-overflow.json); raw reports and
captures are local under ignored `artifacts/o03/`.

The 8×8 experiment also found a benchmark-reporting bug: tile size was hard-coded
to 16 in the summary even though allocation/capability values reflected the shader
configuration. The summary now reads the live capability value, and the refreshed
8×8 raw reports identify 8 correctly. Production shaders and renderer constants
were restored to 16×16.

On 18 October, three alternating 120-second camera-orbit pairs compared isolated
16×16 and 8×8 builds of this same stress scene. The 8×8 build lowered fire
fallback from 1.95% to 1.36% and maximum occupancy from 144 to 128, but increased
known allocation by 1.37 MB and candidate memberships about 3.07×. Median paired
full-frame work improved only 0.037 ms, with no consistent p95 improvement;
end-to-end GPU render improved 0.019 ms while tile-list build cost increased
0.019 ms. Keep 16×16 as the default because the measured gain does not justify
the additional memory on this route. Tick-1800 captures from both builds matched
byte-for-byte. This remains a Metal-only diagnostic result without native-window
or continuous visual review. Full evidence is in
[measurements-o03-tile-size-sustained.json](measurements-o03-tile-size-sustained.json).

## O03 camera-inside all-overflow cost (18 October)

A generated constant-camera route places the camera inside the two-emitter fire
plume and naturally overflows the fire list in all 920 tiles. Three alternating
120-second pairs compare tiled evaluation with the exhaustive baseline on M1
Max/Metal; all 7,200 frames per run have GPU timing samples, and tick-300
captures match exactly. Exhaustive-minus-tiled paired medians are −0.327 ms
frame work and −1.339 ms GPU render. The tiled run spends 1.27–1.39 ms per frame
building lists that cannot avoid fire fallback; atmosphere/fire deltas are mixed.
This isolates the cost of an adversarial all-overflow view. Keep the general
16×16 path and fallback selectable; this result does not justify a global mode
change. See [the report](measurements-o03-camera-inside-overflow.json) and
[reproducible runner](../scripts/tile_overflow_camera_route_study.py).

## O03 fire projected-bound precompute (18 October)

Hypothesis: O03 spends avoidable GPU work reprojecting the same fire bounds once
for every screen tile. The selectable candidate dispatches one invocation per
fire slot, projects the same eight conservative corners once per frame, and stores
pixel-space rectangles for the tile builder. The direct projection path remains
the default and the exhaustive tile-list mode remains separately available.

The 8 KiB buffer and extra dispatch are included in the resource and tile-build
measurements. On M1 Max/Metal, 21 fixed-tick views across clearing, heavy plume,
Material Atelier and two-emitter stress scenes match pixel output, memberships,
overflow counts and occupancy exactly. Three alternating 120-second pairs per
workload show paired median GPU-render changes of −0.629/−0.619/−0.292/−0.763 ms
and tile-build changes of −0.308/−0.310/−0.145/−0.626 ms. Paired frame-work
medians improve by 0.071/0.513/0.041/0.334 ms, while Material Atelier p95 frame
work regresses by 0.179 ms. CPU tile-list encoding rises slightly on clearing,
Material Atelier and the all-overflow view. Keep it opt-in: the native surface,
Windows/DX12 and other-adapter behavior remain unqualified, and the GPU-render
savings do not make the whole-frame p95 uniformly better. A separate three-pair
native clearing-orbit study on M1 Max/Metal lowers atmosphere/fire GPU-stage
median by 0.291–0.328 ms (paired median 0.319 ms) and native-frame CPU median by
0.056 ms. FPS deltas vary (−0.029, +0.205, +0.202; paired median +0.202 FPS),
which does not establish a reliable whole-window win. Native results keep the
candidate opt-in; owner visual review and Windows/DX12 or other-adapter evidence
remain open. The all-overflow camera retains 100% fire fallback. See
[offscreen measurements](measurements-o03-fire-projected-bounds.json),
[native measurements](measurements-o03-fire-projected-bounds-native.json), the
[offscreen runner](../scripts/fire_bounds_precompute_study.py), the
[native runner](../scripts/fire_bounds_native_study.py), and raw paired reports
under ignored `artifacts/o03/fire-projected-bounds/` and
`artifacts/o03/fire-bounds-native/`.

A 19 October current-build recheck repeats the 21-view matrix and verifies a
paused Session API toggle. Images and tile metrics match exactly; the generated
camera-inside route still exercises 100% fire fallback. Three two-second pairs
cover 120 frames each with complete timestamps, but are correctness/protocol
evidence only. Sustained claims remain based on the separate 120-second report.
See [the recheck](measurements-o03-fire-projected-bounds-recheck.json).

## Material response beneath pixel treatment (16 October)

Hypothesis: independent HDR metalness/refraction/scattering parameters retain
material identity across palette strength and camera movement without increasing
the selected scene resolution. The Material Atelier uses matched full, environment-
only reflection and diffuse-baseline configurations, five cameras and a moving
sequence. It adds bounded first-layer screen-space optics, Fresnel, exponential
absorption and authored thin-body backlighting. Prior methods and explicit limits
are in MATERIALS.md. Measurements are in measurements-materials.json; current
Metal captures distinguish the materials, while SSR disocclusion and refracted
smoke boundaries remain approximation limits. No claim of novel BRDFs, true
multiple scattering, or cross-platform optical acceptance is made.

## Rounded curve lobes and emitted particle lights (16 October)

Hypothesis: short curved flame bodies with broader swept lobes and smaller
upward branches give more rounded masses while retaining controlled licking
motion. Deriving transient local lights from the exact detached-particle state
should connect floating fragments to both surface and internal smoke lighting.
The implementation keeps analytic ray/ellipsoid intersection and pure seeded
trajectories; it adds no full combustion solver, screen sprite simulation or
uncapped per-particle shadow lights. Twelve strongest emitted sources are kept;
smoke shades the best two in addition to two authored sources. Light-free and
long-curve alternatives remain data settings, compared by fire_study.py. Standard
local-light attenuation/emission and curve-swept volumes are prior methods; the
combination is an engine experiment, with no claim of unprecedented technique.

## Solid fire coverage and pixel-grid hot air (16 October)

Hypothesis: opaque coverage and a discrete HDR heat ramp retain stronger pixel
shapes than translucent, continuously shaded fire, while a separate hot-air warp
communicates heat without softening the flame. The implementation retains the
same world curves, branches, detached particles and lights. Atmosphere depth
protects foreground smoke/geometry and the fire itself; the post warp uses eight
bounded temperature samples and integer HDR lookups without temporal history.
[GPU Gems 2, Generic Refraction Simulation](https://developer.nvidia.com/gpugems/gpugems2/part-ii-shading-lighting-and-shadows/chapter-19-generic-refraction-simulation)
is prior work for scene-image coordinate perturbation and masking. The wind/heat
envelope, depth rejection and fixed pixel offsets here are engine choices, not
a claim of a new refraction technique. Matched soft/solid/no-heat captures, a
moving sequence and the route comparison use fire_study.py --study pixels.

## O01 stage profiling characterization (16 October)

Three alternating 120-second serial route pairs with ten-second warm-ups were
recorded for clearing, a single heavy plume with eight point lights, and Material
Atelier. Each variant used identical scene inputs within its workload; paired
differences therefore estimate run variation and do not claim an optimization.
Every pair also has timestamp-enabled and timestamp-disabled runs. On Apple M1 Max /
Metal at 640×360, median whole-render GPU times were 3.15 ms for clearing, 3.87 ms
for the heavy plume and 3.39 ms for Material Atelier. The leading measured stage
medians were post (2.53 ms), post (3.25 ms) and post/optical resolve (2.75/2.65 ms),
respectively. Pass intervals may overlap; they are not additive costs. Timestamp
instrumentation increased median frame work by 0.11–0.28 ms across the matched
timed/untimed controls.

A separate 120-second native clearing route measured 43.48 frames/s, 8.83 ms median /
70.28 ms p95 native CPU frame and 6.36 ms median / 64.79 ms p95 surface acquisition.
It includes native surface and vsync behavior, unlike the unpaced offscreen runs.
Exact CPU-to-GPU queue latency is unavailable because wgpu timestamps have no
calibrated host-clock mapping; readback-completion latency is reported separately.
All three workloads had 7,200/7,200 serial render and smoke-compute timing samples
with no skipped or late samples. Native GPU sample summaries are filtered to the
measured frame/tick window; slot skip/late counters include warm-up. Full sample reports are locally retained under
`artifacts/o01/`; [measurements-o01.json](measurements-o01.json) records provenance,
summary values and checksums. This evidence is a measurement baseline only; no
renderer optimization was tested or promoted.

## Output-preserving O01 shader counters (18 October)

Hypothesis: diagnostic atomics can be collected without asking the instrumented
shader variant to produce the accepted image. The previous approach substituted
instrumented world, volumetric and optical pipelines for normal rendering; its
expanded sample changed one or two flame pixels in six close-camera cases. The
renderer now draws the normal passes first, then repeats the instrumented draws
into lazily allocated scratch targets while reading the normal scene depth. This
retains shader work and counters without modifying the captured color or depth.
At 640×360, scratch targets add 4,608,000 known bytes on the default RGBA16F path;
compact HDR no-copy adds one 230,400-byte mask plane within its format-specific
allocation. These allocations release when diagnostic mode is disabled. This adds work only
when `--shading-counters` is enabled; its timings remain unusable as
performance evidence. M1 Max/Metal fixed-tick checks across campfire, quiet and
bonfire profiles at hero, smoke-close, fire-study and orthographic cameras now
match all 12 baseline images byte-for-byte and return nonzero operation counts.
A five-view Material Atelier matrix and a compact-HDR optical-no-copy glass case
also match the normal image byte-for-byte while reporting metal, glass and
subsurface optical interactions. This closes
sampled image parity for those views, not continuous playback, native-window or
cross-adapter validation. See the [expanded fire report](measurements-o01-counter-profile-scope.json)
and [optical report](measurements-o01-optical-counter-coverage.json).

## O01 atmosphere path invocation counters (18 October)

The shading diagnostic buffer now records total volume-pass fragment invocations
and splits them by soft-volume versus inked-smoke style. Three profiles, four
cameras and both styles produce 24 normal/diagnostic pairs with exact pixel
parity. At the bonfire/fire-study fixed tick, the soft-volume case records
181,010,226 density samples and 115,967,532 direct-absorption samples, compared
with 451,096 and 372,216 for inked smoke. Both render 230,400 volume fragments.
The counter report normalizes counts by output pixels, but neither those values
nor the raw counts are timings. A matched uninstrumented 120-second
`clearing-orbit` study now records three alternating soft-volume pairs on M1
Max/Metal. Median atmosphere/fire run medians were 12.919 ms for baseline and
13.055 ms for candidate; paired deltas were −0.336/−0.156/+0.136 ms. GPU-render
deltas were −0.324/−0.152/+0.179 ms and frame-work deltas were
−0.413/−0.192/+0.331 ms. The paired signs vary and the median run-level
atmosphere/fire cost does not improve, so no speedup or shader rewrite is
supported. See [path counter report](measurements-o01-counter-paths.json),
[soft-volume route report](measurements-o01-soft-volume-route.json), the
[fixed-tick runner](../scripts/shading_counter_profile_study.py) and the
[sustained timing runner](../scripts/soft_volume_route_study.py).

The O01 soft-volume route also isolates O03 tile-list cost using three
alternating 120-second tiled-versus-exhaustive pairs. On M1 Max/Metal,
exhaustive-minus-tiled paired medians were +2.610 ms frame work, +2.202 ms
GPU-render and +2.570 ms atmosphere/fire; tile-list build time decreased by
0.327 ms when disabled. Fixed tick 120 at seed 42 matched pixel-for-pixel at
640×360. This supports the tiled path on this workload, not a general adapter or
native-window claim. See [tile-list comparison](measurements-o01-soft-volume-tile-lists.json).


## Shared geometry and conservative visibility (16 October)

Hypothesis: storing repeated geometry/material variants once and rejecting objects
outside each camera/light frustum can cut draw submission and vertex traffic while
retaining offscreen shadow casters. The implementation groups only consecutive
matching instances to preserve scene order, computes independent camera and shadow
visibility, and treats missing/invalid bounds as visible. In the clearing route,
camera submissions fell by about half and point-shadow submissions fell sharply;
whole-render GPU time stayed nearly flat across three short M1 Max/Metal pairs.
The mesh buffer uses less GPU storage, while runtime-selectable exact comparisons
retain a 10.54 MB CPU baked reference stream. Instanced vertex transforms cause a
small number of changed pixels at quantization edges; culling adds none in the
reviewed cameras. The measured work is therefore an engine optimization tradeoff,
not a claim of visual identity or universal speedup. See
[measurements-o07-culling.json](measurements-o07-culling.json) for paired data,
images and platform limits.

## Coarse smoke transmittance cache (17 October)

Hypothesis: reusing primary fire-light optical depth may reduce repeated smoke
density reads while preserving the view-dependent surface normals and radial light
falloff. An opt-in 8³/16³ field is rebuilt every rendered frame; the 8³ and 16³
fields use 4 KiB and 32 KiB respectively. Particle lights and out-of-volume points
retain direct sampling. Three short paired M1 Max/Metal route runs measured median
cache-build passes near 0.026 ms and 0.029 ms; whole GPU render medians increased
slightly, so the cache remains disabled by default. In one fixed smoke-close still,
mean absolute RGB error versus direct sampling was lower at 16³ (0.056) than 8³
(0.207) when averaged over all channels. This does not establish temporal quality
or a useful performance range. Review motion, edits while paused and other GPU
backends before promotion; full provenance is in
[measurements-o05.json](measurements-o05.json).

## Reuse shaded bases for opaque optical surfaces (17 October)

Hypothesis: an opaque reflective surface already has its lit base color in the
post-volume HDR snapshot. The optical pass can recover that base by removing the
same-pixel foreground atmosphere contribution, avoiding a second full surface
lighting evaluation. The opt-in path uses the matching normal/depth snapshot and
keeps the existing shader for transmissive materials, which are discarded by the
opaque pass. No extra texture is allocated. In three short M1 Max/Metal
material-orbit pairs, median optical-resolve time fell about 0.19 ms and total GPU
render about 0.21 ms; CPU frame-work results were noisy. Metal, hero, glass-close
and smoke-over-reflector captures stayed visually close, with small localized
half-float differences. The consistent short-run GPU result merits longer review,
but does not qualify the change for a default. See
[measurements-o06.json](measurements-o06.json).

## Lazy optical snapshots (17 October)

The original O08 renderer allocated two full-resolution RGBA16F snapshots in every
scene although diffuse scenes skip optical resolve. The initial lazy-allocation
change saved 3,686,400 bytes in diffuse scenes. The current pass allocates only one
HDR snapshot on first camera-visible optical use and reads the opaque normal/depth
target directly.
A live reflectivity edit activates the pass; fixed-tick smoke, metal and glass
captures remain byte-identical. No frame-time reduction is claimed for lazy
allocation. The effect-depth/flame-coverage attachment now uses Rg16Float
when the adapter reports filterable sampled and render-attachment support, falling
back to Rgba16Float. On this M1 Max/Metal adapter it saves 921,600 bytes at 640×360;
matched smoke and opaque-metal captures at scale 1 were pixel-identical to saved
baselines. This confirms the path on one Metal adapter only; no timing benefit is
claimed. The full live-allocation report, format selection and limits are in
[measurements-o08.json](measurements-o08.json).

A paused native Session on M1 Max/Metal now repeats the lazy-allocation lifecycle:
a live chalk-reflectivity edit while facing away leaves snapshot residency at zero
and has no optical-resolve timestamp. The first hero view creates one 1,843,200-byte
snapshot for nine optical batches; turning away skips resolve while retaining the
allocation, and returning does not allocate again. Repeated paused away/hero
captures match each other and same-adapter headless captures byte-for-byte. The
same native/headless parity holds across seven visible views, including the
inside-glass and near-plane stress cameras, with no further snapshot allocation.
This is native lifecycle evidence for one adapter, not DX12 or other-adapter
qualification. See
[native report](measurements-o08-lazy-optical-native.json) and its
[runner](../scripts/lazy_optical_native_study.py).

The smoke density/temperature ping-pong pair also uses Rg16Float when the adapter
exposes `TEXTURE_ADAPTER_SPECIFIC_FORMAT_FEATURES` and filterable sampled/write-only
storage support; otherwise it retains Rgba16Float. The selected path requests that
device feature, updates the storage binding and reset-upload stride, and saves
1,179,648 bytes at 48×64×48. Fixed-seed reset/replay verification passed, and
smoke-close plus opaque-metal captures at 640×360 were byte-identical to the prior
format. The nominal full-texel request estimate halves, but no frame-time or
external-bandwidth gain is claimed. Fallback execution and DX12 remain open.

## Optical normal snapshot removal (17 October)

The optical pass does not need to replace the opaque normal/depth attachment:
later passes use the opaque values, and the optical shader can sample that target
directly when it is not bound as a render attachment. The pass now writes HDR only.
It retains one HDR color snapshot to avoid reading from the HDR attachment that it
updates. At 640×360 this removes one 1,843,200-byte snapshot from optical scenes,
one full-texture copy read/write (3,686,400 logical bytes), and the optical normal
attachment load/store (3,686,400 logical bytes) per frame. Matched smoke-close,
opaque-metal and glass captures were pixel-identical; no frame-time gain is
claimed. The HDR copy remains for future pass-layout work. See
[measurements-o08.json](measurements-o08.json).

Three alternating 20-second and three 60-second serial material-orbit pairs
compared revision 1742044 against 632be12 on the same M1 Max/Metal host. The
longer-run median paired GPU optical-resolve delta was +0.0087 ms and whole
GPU-render delta +0.0003 ms. Frame-work deltas were variable and CPU-side; no GPU
timing gain was measured. Full per-stage medians, run order and raw reports are in
[measurements-o08.json](measurements-o08.json), `artifacts/o08/timing-optical-copy/`
and `artifacts/o08/timing-optical-copy-60s/`.

## Camera-visible optical resolve gate (17 October)

Optical materials can stay in scene data while their objects leave the camera
frustum. The renderer now derives optical activation from the camera-culled draw
batches, allocates the retained HDR snapshot on the first visible optical batch,
and skips the snapshot copy and optical pass on frames with no such batches. This
keeps the snapshot lazy across offscreen startup and live edits. A live reflectivity
edit while the camera faced away left the snapshot at zero bytes; switching to the
edited geometry allocated 1,843,200 bytes and produced three optical batches. In a
separate fixed-tick run, metal-close remained byte-identical to the saved O08
reference. Returning to the away camera reported zero visible optical batches and
no optical-resolve timestamp; the previously allocated snapshot remained resident.
The M1 Max/Metal test does not detect full occlusion, demonstrate a GPU-time gain,
or validate DX12/other adapters. Evidence and hashes are in
[measurements-o08.json](measurements-o08.json).

## Packed HDR target probe (17 October)

`Rg11b10Ufloat` is available as a renderable, filterable, sampled/copy target on the
current M1 Max/Metal adapter when `RG11B10UFLOAT_RENDERABLE` is requested. The
`--compact-hdr` startup variant uses four bytes per pixel for the primary HDR color
target and lazy optical snapshot, instead of eight; `Rgba16Float` remains the
default and unsupported-adapter fallback. Three matched fixed-tick views for metal,
smoke and glass looked very similar at native capture scale, but are not pixel
identical. Mean absolute RGB error ranged from 0.32 to 0.45/255; the smoke view had
a sparse maximum channel difference of 30/255. Four additional matched seed-42
hero-camera captures at ticks 300, 600, 900 and 1200 cover fire/smoke evolution.
Visual review found no new instability; per-tick mean RGB error stayed near
0.362/255, with a 9/255 maximum channel difference in this view. Eight matched
camera poses sampled every 15 seconds along `material-orbit`, at the same tick 1200,
looked similar throughout the orbit; mean RGB error ranged from 0.362 to 0.431/255,
with a 10/255 maximum channel difference. This isolates camera viewpoint and does
not combine route movement with changing fire/smoke state. Three alternating
120-second `material-orbit` pairs after 10-second warm-up measured candidate GPU
render medians 0.0051–0.0092 ms lower (paired median -0.0061 ms, about 0.24% of
baseline). Frame-work deltas varied, so this is not evidence of a practical
performance gain. The confirmed tradeoff is 1,843,200 fewer known target bytes at
640×360 for a small precision loss. Keep the format opt-in. The eight route poses
are sparse fixed-tick captures, not a continuous sequence. Fallback and DX12 review
remain open. See [measurements-o08.json](measurements-o08.json) and ignored
`artifacts/o08/compact-hdr-motion/` and `artifacts/o08/compact-hdr-route-captures/` captures.

## Optical overlay output without snapshot copy (17 Oct 2026)

Hypothesis: keep the source HDR texture immutable for reflection/refraction
sampling, render optical fragments into a separate overlay, and use a coverage mask
in post to avoid copying the HDR texture each frame. The opt-in `--optical-no-copy`
path uses a lazily allocated RGBA16F (or selected compact HDR) output and R8Unorm
mask; a missing R8 render/sample capability falls back to the existing snapshot-copy
path. The default remains unchanged.

On M1 Max/Metal, seed-42 tick-300 hero, metal-close and glass-close captures were
pixel-identical at 640×360. A glass-close compact-HDR pair was also pixel-identical.
RGBA16F coverage uses the overlay alpha channel, so the candidate replaces the
1,843,200-byte snapshot with an equally sized output and no separate mask; known
optical-scene allocation matches the snapshot path. Compact HDR still allocates
the 230,400-byte mask. A clearing scene with no visible optics allocated neither
output, mask nor snapshot. For RGBA16F, the logical full-frame estimate falls from
7,372,800 to 5,529,600 bytes for snapshot-copy/optical attachment versus overlay
attachment/post reads. This modeled 1,843,200-byte reduction is not physical DRAM
traffic.

Three alternating 120-second material-orbit pairs measured a -0.01817 ms median
GPU-render delta and -0.01671 ms optical-resolve delta. Frame-work deltas varied;
the render-time difference is small and does not establish practical speedup.
Keep this research option disabled by default. Native-window rendering, fallback
execution on other adapters, Windows/DX12 and compact-HDR route timing remain
unverified. Captures and raw timing reports are under ignored
`artifacts/o08/optical-no-copy-captures/` and
`artifacts/o08/optical-no-copy-timing/`; full details are in
[measurements-o08.json](measurements-o08.json).

# Simulation-driven surface heat cue

Hypothesis: a small stepped warm shift plus an edge accent can make simulated
fire heat legible as a gameplay risk cue on selected opaque materials while
reusing the current fixed-step temperature volume and pixel grid. `heat_response`
is an opt-in per-material scalar (0..1, default 0); zero avoids the shader sample.
The prototype adds no readback, simulation pass, or per-particle work. Heat is an
artistic signal, not a physical temperature or damage measurement.

Prior art in this engine includes the fire point-light contribution to material
lighting and the post-process heat shimmer driven by the same temperature field.
This experiment moves a compact signal into opaque surface shading and uses
material authoring to select gameplay-relevant surfaces.

Visual check: with `heat_response=1`, the matched `fire-study` capture at seed 42,
tick 300 and 640×360 changed 220 scene pixels around the fire base; repeating the
capture produced identical pixels. A later multiview review used response 0.8,
seed 42 and ticks 120/300/900. Six camera/tick pairs changed 5–203 pixels each:
fire-study and smoke-close showed the cue most clearly, hero framing showed a
small localized mark, and the orthographic overview changed only five pixels.
The zero-response capture remains pixel-identical to baseline; repeated
fire-study tick-300 captures were also pixel-identical. The cue remains
projection-dependent and this is style evidence, not gameplay-usability acceptance.
Captures are in ignored `artifacts/heat-cue-review/`.

Cost check: three alternating 120-second `clearing-orbit` pairs with 10-second
warmup on Apple M1 Max/Metal measured a 0.0112 ms median paired increase in GPU
render time (2.5669 ms baseline vs 2.5781 ms candidate); opaque geometry increased
0.0068 ms. Full route/frame work varied more than the GPU delta. See
[`measurements-heat-cue.json`](measurements-heat-cue.json). Keep the feature
opt-in; the cue is subtle from wide views, and Windows DX12 and broader visual
acceptance remain open.

## O02 discrete moving-caster check (17 October)

Hypothesis: per-face invalidation should redraw the sun plus only the point-light
faces intersecting the caster's old or new conservative bounds. A paused seed-42
protocol run moved `fallen-log` through six positions around the point light. Every
cached capture matched a forced seven-map redraw byte-for-byte. Each edit redrew
three maps (sun and the old/new point-face union); an unchanged follow-up rendered
zero maps and reported a cache hit. Per-pose masks and CPU shadow-encoding samples
are in [measurements-o02-moving-caster.json](measurements-o02-moving-caster.json),
and `scripts/shadow_caster_study.py` reproduces the route.

This is correctness evidence for discrete edits, not a continuous-motion timing
result. The moved log was outside the selected camera view; no art conclusion is
drawn. The unknown-bounds fallback, 120-second moving route, native window and
Windows/DX12 remain open.

## O02 live projection and material invalidation (17 October)

The live-edit matrix initially could not move the fire point light: scene
validation correctly requires it to remain coincident with its emitter, but the
shared parameter edit changed only the light. `set_parameter` now moves a linked
emitter in the same validated transaction when its light position changes;
legacy position-bound emitters follow the same rule. Invalid edits remain
transactional. The focused unit check covers explicit and legacy links plus
rejection without partial mutation.

On M1 Max/Metal at 640×360, log transmission, sun projection, linked point-light
position, point-light range, successful shader reload and reset each produced
byte-identical cached/forced captures. Masks were respectively 2, 1, 6, 6, 7 and
7 maps, with reasons `shadow_materials_changed`,
`directional_light_projection_changed`, `point_light_projection_changed`,
`point_light_range_changed`, `shader_reload` and `reset`. See
[measurements-o02-invalidation.json](measurements-o02-invalidation.json). These
paused checkpoints do not measure continuous invalidation cost. Synthetic unit
coverage now checks mixed known/missing old/new caster bounds and invalid shadow
frusta; each case forces all seven maps dirty. The live diagnostic reason reports
`unknown_caster_bounds` or `unknown_shadow_material_bounds` for those fallbacks.
Current validated scene assets always produce bounds, so the live protocol cannot
induce an unknown-bound case without a new asset type or test hook. Native-window
and non-Metal behavior remain open.

## O02 continuous moving-caster cost (18 October)

Three alternating serial 120-second pairs with a 10-second warm-up used the same
seed-42 clearing orbit and a deterministic radius-5, 20-second `fallen-log`
circle, updated through the shared Session transform operation every frame. The
cache path reduced shadow-map submissions by 66.3% (16,968 vs 50,400 per run),
CPU shadow encoding by about 0.084 ms, and the shadow GPU interval by about
0.264 ms. There were no cache-hit frames because movement invalidated at least one
map every frame.

The paired whole-render GPU delta was consistently around -0.05 ms, but whole-frame
work deltas straddled zero and p95 frame work was worse for the candidate. The
overlapping GPU pass intervals are reported separately. Per-face invalidation
therefore saves map work on this moving path without a demonstrated whole-frame
win. The fixed-pose capture study supplies cached/forced image checks; the timed
route did not capture PNGs. Keep the established static-cache benefit separate
from this continuous-invalidation result. See
[measurements-o02-moving-route.json](measurements-o02-moving-route.json); raw
frame samples are local under ignored `artifacts/o02/moving-route-120s/`.

A separate 640×360 wide orthographic view keeps the moving log on screen through
the six discrete caster poses. Cached images match forced redraw byte-for-byte at
every pose; each move dirties three point/sun faces. The contact sheet was
visually inspected. Reproduce with
`python3 scripts/shadow_caster_visible_study.py`; measurements and source hashes
are in [measurements-o02-visible-caster.json](measurements-o02-visible-caster.json).

The same six pose pairs were captured through native `run --agent-stdio` on a
2560×1600 physical window; cached and forced-redraw images match byte-for-byte.
Because the host may render between mutation and capture requests, the report
omits per-pose invalidation masks for this native run. It establishes native
capture parity, not native-window timing or surface-present image inspection. See
[measurements-o02-visible-caster-native.json](measurements-o02-visible-caster-native.json).

## O05 absorption-cache scale study (18 October)

Direct sampling, 8³ cache and 16³ cache were compared at small, medium and
screen-filling smoke scales, at fixed 640×360 resolution, with three paired
120-second seed-42 orbit runs for each cache tier and scale. Fire-state inspection
matched exactly at tick 300. The 16³ still was closer to direct sampling by
per-channel mean absolute RGB error in every scale: small 0.014/0.007/0.008,
medium 0.080/0.044/0.040 and screen-filling 0.251/0.155/0.119 (R/G/B, 0–255).

The cache reduced the targeted atmosphere/fire GPU interval by 0.058–0.101 ms.
However, the GPU build interval costs 0.025–0.033 ms and the total GPU render
median was slower by 0.025–0.044 ms in all six comparisons. CPU cache construction
costs 0.034–0.043 ms per frame. Whole-frame medians favored the candidate, but
that did not agree with total GPU render and was not used as a win claim. Keep the
cache opt-in and disabled by default. Small-to-large quality improves with 16³,
but no total-render workload range is established. Continuous temporal error,
live edit invalidation and other GPU backends remain open. Full paired data and
capture hashes: [measurements-o05-size-study.json](measurements-o05-size-study.json).

## O05 edit and discrete-motion freshness (18 October)

For both 8³ and 16³ caches, direct and cached sessions matched at 13 deterministic
checkpoints after paused density edits, rapid successive density changes, linked
primary-light movement/range, flicker, four moving-ember advances, shader reload
and reset. Fire state was identical at every checkpoint. Image differences stayed
within the cache tier's expected approximation; visual inspection of representative
edit and motion stills found no abrupt discontinuity. This confirms the current
per-render rebuild follows these discrete edits. Representative stills show the
expected approximation without an obvious new defect, but do not establish
continuous temporal quality, wall-clock resume behavior, or native-window behavior. See
[measurements-o05-invalidation.json](measurements-o05-invalidation.json).

A 19 October current-build rerun repeats those 13 checkpoints for each cache
size. Fire state remains identical, disabled allocation remains zero, and
enabled cache residency is 4,096/32,768 bytes. The mean per-channel RGB errors
across checkpoints are 0.320/0.182/0.149 for 8³ and 0.097/0.056/0.049 for 16³;
maximum channel errors are 21/17/12 and 18/10/12. These discrete readings do not
replace full temporal or backend validation. See
[the current-build report](measurements-o05-invalidation-current-build.json).

## O06 sustained opaque lighting reuse (18 October)

Three paired 120-second routes on Material Atelier and three on a mixed
smoke/fire/material scene used 640×360, seed 42 and a 10-second warm-up. On M1
Max/Metal, all six pairs reduced total GPU render time: median paired deltas were
-0.169 ms in Material Atelier and -0.081 ms in the mixed scene. Optical resolve
fell by -0.166 ms and -0.076 ms, with atmosphere/fire timing effectively stable.
CPU frame-work medians also improved in each workload. Fixed-tick captures
included hero/metal/glass views, smoke ordering around reflective and transmissive
objects, a near-glass view, and a live chrome roughness edit. The glass close view
had rare pixels with up to 34/255 channel error; average error stayed below
0.006/255 per channel. The mixed stress captures differed by at most 12 pixels,
with maximum channel error 1/255.

These offscreen results extend the earlier short profile but do not settle
continuous motion, native-window output or other adapters. Separate fixed-tick
inside-glass and near-plane direct/reuse checks are recorded in
[measurements-o06-camera-stress.json](measurements-o06-camera-stress.json). Keep
the path opt-in pending the remaining checks. Full captures and paired stage
data: [measurements-o06-sustained.json](measurements-o06-sustained.json).

## O06 × O08 factorial (18 October)

A controlled 2×2×2 matrix combined direct/reused opaque lighting, copy/no-copy
optical output and RGBA16F/packed HDR on a mixed high-dynamic fire/smoke/reflector/
glass orbit. Seven variants each had three alternating 120-second pairs against
the direct/copy/RGBA16F baseline. Reuse reduced total GPU render by 0.078–0.108 ms
in RGBA16F and 0.081–0.107 ms in packed HDR. Direct no-copy reduced GPU render by
0.026 ms and 0.013 ms, respectively; direct packed-HDR/copy was within run spread.
No-copy captures matched copy byte-for-byte for both HDR formats.

RGBA16F no-copy replaces the snapshot with an equally sized output and keeps known
allocation flat while avoiding the copy traffic. Packed HDR saves 1.84 MB known
allocation against the RGBA16F baseline but has higher per-pixel quantization error
in this high-output case. Packed-HDR no-copy adds a 0.23 MB mask over packed-HDR
copy. This is Metal offscreen evidence only; temporal, native-window and additional
adapter checks remain open. Full paired timing and capture data:
[measurements-o06-o08-factorial.json](measurements-o06-o08-factorial.json).

A 19 October rerun of the eight-way matrix on the current binary preserves effect
counts in every variant. Direct/no-copy matches direct/copy byte-for-byte for
both HDR formats. Reuse changes one RGBA16F pixel by 1/255 and three compact-HDR
pixels across three frames by 1/255. Compact-HDR aggregate error remains
0.337/255 per-frame mean and 0.421/255 temporal-change mean, with a 38/255
maximum channel difference. This is temporal evidence, not a performance claim
or full-duration human acceptance. See
[current-build report](measurements-o06-o08-factorial-current-build-recheck.json).

## O04 projected-detail motion review (18 October)

A route-aware capture script drives the named camera from validated scene
keyframes before each fixed-tick image capture. The new 31-object fire study
scene provides an unobstructed orbit across the 40/20 px thresholds and 48/24 px
return hysteresis. At 640×360, seed 42 and M1 Max/Metal, a 400-frame 20 fps
campfire pair crossed all four transitions twice. Quiet and bonfire each have
120-frame 12 fps pairs crossing their applicable band. Full primitive counts,
ember counts and particle-light counts matched on every paired frame. Changed
pixels stayed within a 27–33 px flame-region bounding box across the three
profiles; sampled threshold sheets showed no obvious detachment or lost glow.

The GIF/APNG deliverables were generated and hashed, but continuous playback was
not available in the locked native Mac session and the in-app browser rejected
local-file URLs. This evidence therefore does not close flicker or silhouette
crawl review, and it contains no sustained timing claims for the two added
profiles. The feature remains opt-in. Commands, hashes, tier occupancy and
transition sizes are in [measurements-o04-motion-review.json](measurements-o04-motion-review.json);
the generated frame sequences and preview files are under ignored
`artifacts/o04/continuous-motion/`.

The native-window follow-up adds three alternating 120-second campfire orbit
pairs on M1 Max/Metal. Projected-detail LOD reduces median retained primitives
from 81 to 70 and the atmosphere/fire GPU stage by 0.057 ms; the per-pair GPU
stage deltas are −0.057/−0.062/−0.041 ms. Native FPS deltas are −0.102/+0.056/
−0.001, with a paired median effectively flat at −0.001 fps. LOD CPU work adds
0.00008 ms median. This does not establish a whole-window gain or visual
acceptance; retain the disabled default. See
[native report](measurements-o04-native.json) and
[runner](../scripts/projected_detail_native_study.py).

A 19 October current-build recheck at seed 42 and 640×360 compared 14 fixed-tick
camera checkpoints. Fire counts, bounds, lighting and particle-light state match
at every checkpoint. Full-detail captures are byte-identical. Some reduced-
detail captures also match byte-for-byte when removed geometry is occluded; the
other reduced-detail captures differ in 18–105 fire-region pixels, within the
bounds reported in the JSON. This run makes no performance claim. Continuous
playback and non-Metal acceptance remain open. See
[current-build recheck](measurements-o04-current-build-recheck.json).
The accompanying seed-42/tick-300 default-scene capture confirms the renderer
keeps the measured opt-in paths off, including projected detail, absorption
cache, optical reuse, no-copy, compact HDR and fire-bound precompute. The disabled
absorption cache uses zero bytes; 2,304-byte smoke-candidate and 8,192-byte
fire-bound buffers remain reserved for their shared bind groups. This fixed
10,496-byte reserve is recorded as default renderer cost, not as enabled
experimental work.

## O05 absorption-cache temporal and pause/resume review (18 October)

At medium smoke scale, direct sampling and the 16³ cache were captured at
640×360, seed 42, ticks 300–1497, on the same 20-second orbit at 20 fps. Exact
tick/camera and fire/effect-count parity held over 400 frames. Mean frame RGB
MAE was 0.096/255 (p95 0.177/255, maximum channel difference 19/255). Mean error
in per-channel frame-to-frame change magnitude was 0.104/255. The metric omits
change direction and is not a substitute for continuous playback review; sampled
contact sheets show small smoke-region differences. No total-render win follows
from this quality study, and the cache remains disabled by default.

The same route at 8³ also held tick/camera and fire/effect-count parity over 400
frames. Mean frame RGB MAE was 0.285/255 (p95 0.426/255, maximum channel
difference 39/255), and mean frame-to-frame change-magnitude error was
0.183/255. The contact sheet shows differences mainly in the smoke volume, with
no claim of continuous playback acceptance. The 16³ cache is closer to direct
sampling on this route. No temporal result establishes a total-render win; see
[measurements-o05-temporal-cache8.json](measurements-o05-temporal-cache8.json).

A native `run --agent-stdio` M1 Max/Metal check held each variant at tick 300 for
two wall-clock seconds: tick and image hash stayed unchanged. Each variant then
advanced for two wall-clock seconds (121 direct ticks, 120 cached ticks), was
paused, and stepped to tick 540; fire state matched exactly there. This validates
paused freshness and post-resume cache consistency for the tested duration, not
other devices or continuous user-facing playback. Longer motion review,
Windows/DX12 and other adapters remain open. Reproduction scripts are
`scripts/absorption_cache_temporal_study.py` and
`scripts/absorption_cache_pause_resume_study.py`; reports are linked from TODO
and STATUS.

## O05 dirty-input refresh policy (18 October)

A 16³ cache study at 640×360 steps the clearing scene to tick 300 and then
captures unchanged paused output, a linked primary-light edit, another simulation
step, shader reload, reset/replay, disable and re-enable. All nine assertions
passed: the unchanged paused image hash stayed identical while build count held
and skip count increased; each dirty event caused a build; disabling released the
32,768-byte field, and re-enabling rebuilt it. `get_metrics` exposes cumulative
`absorption_cache_builds` and `absorption_cache_skips` for this comparison.

This removes redundant work for repeated renders of a paused state. In a moving
route, each fixed simulation step still dirties the cache, so this result does not
reverse the earlier total-render slowdown or justify enabling the cache by
default. Evidence is in
[measurements-o05-refresh-policy.json](measurements-o05-refresh-policy.json);
the reproducible study is `scripts/absorption_cache_refresh_study.py`.

## O06 camera-inside and near-plane follow-up (18 October)

The optical pass previously discarded transmissive backfaces, so an inside-glass
view could not shade the exit interface correctly. The shader now chooses the
interface normal from the geometric normal/view relationship, selects the
inside/outside refraction ratio, and treats WGSL's zero-vector refraction result
as total internal reflection. Two named 640×360, seed-42, tick-300 cameras cover
an oblique inside-glass view and a view 0.1 world units outside the glass sphere.
Direct and opaque-light-reuse captures were byte-identical in both cases. The
inside view changed substantially from the prior wrong-side shading; the
contact sheet shows the environment through the exit interface without a new
direct/reuse discrepancy. This is fixed-tick offscreen Metal evidence only;
continuous motion, native-window performance and other adapters remain open.
Reproduce with `scripts/optical_camera_stress_study.py`; report:
[measurements-o06-camera-stress.json](measurements-o06-camera-stress.json).

## Opaque heat cue over low terrain (18 October)

The two-source opaque heat A/B initially produced identical images with the
secondary emitter enabled. The cause was geometric: near watchfire the review
terrain is below y=-0.6, while the cue samples only 0.45 units above the surface;
that sample fell below the source-local volume, so the shader correctly rejected
it as out of bounds. A flat-field synthetic check showed the secondary binding
and sampled channel were live. The correction derives each source volume from its
stable source origin and clamps only the sampled height to origin.y-0.1 when the
surface sample falls lower; horizontal bounds and the original flat-ground sample
are preserved. This adds no texture allocation.

At seed 42/tick 300 on M1 Max/Metal, the isolated watchfire A/B changed pixels in
all six views (168–5,695 pixels). Visual inspection found the clearest stepped
ring in the ground-focused view; the broad views show small changes. This verifies
fixed-tick contribution, not temporal smoothness, gameplay readability across
motion, performance, or DX12. Captures and report are in ignored
`artifacts/two-emitter-heat-response/`; reproducible inputs are in
[`two_emitter_heat_response_study.py`](../scripts/two_emitter_heat_response_study.py),
with the versioned summary in
[`measurements-multi-emitter-opaque-heat.json`](measurements-multi-emitter-opaque-heat.json).

## Two-source ink-smoke tile-list addressing (18 October)

The maximum-budget tiled capture initially differed from exhaustive rendering
in 9,616 pixels. Increasing projected puff bounds reduced the difference
non-monotonically, which ruled out a simple under-sized geometric bound as the
whole cause. Reading the fixed-layout storage contract exposed two offset errors:
each tile reserves 36 primary plus 36 secondary indices, but primary construction
advanced by only 36 entries per tile, and secondary shading read from the primary
segment instead of the secondary segment. The first error caused cross-tile
primary/secondary writes; the second fed source one the wrong puff IDs.

The builder now advances by 72 entries per tile, primary shading reads that tile's
first segment, and secondary shading reads the segment beginning at +36. The
existing capacities, buffer allocation and dispatch count are unchanged. The
M1 Max/Metal stress runner now reports exact tiled/exhaustive output for all six
named cameras, each emitter alone, forced fallback and reversed emitter order.
The 402-primitive stress scene naturally overflows 74 fire tiles but not either
36-entry smoke list; forced overflow remains an exact reference check. The
source-zero profiling-heavy capture is byte-identical to the prior source-zero
capture. This resolves fixed-tick correctness for this scene. A separate
three-pair, 120-second
maximum-budget offscreen route measured tiled versus exhaustive serial frame-work
of 10.780 versus 11.495 ms median-of-pair-medians; tiled was lower in all three
pairs. The reported GPU-render metric was 9.299 versus 7.377 ms, with a 2.485 ms
tile-build stage and a 6.408 ms atmosphere/fire stage for tiled. These interval
metrics can overlap, so retain both the whole frame-work result and stage costs;
do not infer a general win from this one route. Tiled mode also retained the
603,520-byte index buffer. The full report is
[`measurements-multi-emitter-sustained.json`](measurements-multi-emitter-sustained.json).
Reproduce with
[`two_emitter_overflow_study.py`](../scripts/two_emitter_overflow_study.py) and
inspect [the report](measurements-multi-emitter-overflow.json).

## O06 x O08 moving-camera temporal interaction (18 October)

The moving-route O06 x O08 factorial covers all eight direct/reuse,
copy/no-copy and RGBA16F/Rg11b10Ufloat combinations for 240 frames at 20 fps on
the 640x360 mixed fire/smoke/material route. Every variant preserves the
baseline fire and effect counts. Direct RGBA16F copy and no-copy remain exact;
direct compact HDR has 0.337/255 mean frame error and 0.421/255 mean
temporal-change error. Investigation traced the former 188/255 reuse spike to
the fallback shading an un-oriented normal when a depth guard rejected snapshot
reuse. The fallback now uses the same camera-facing interface normal as the
direct path, and the production guard requires exact depth equality.

With that correction, RGBA16F reuse has a single 1/255 channel difference on
one pixel across the route; compact-HDR reuse has the same measured aggregate
error as direct compact HDR. A guard sweep shows looser depth tolerance brings
back an 87/255 sparse edge error. Foreground-alpha/radiance and normal-alignment
gates do not improve exact-depth output. The sampled contact sheet remains
visually close; continuous playback acceptance remains open. See
[factorial temporal report](measurements-o06-o08-factorial-temporal.json) and
[guard report](measurements-o06-temporal-depth-guard.json), with runners
[`optical_factorial_temporal_study.py`](../scripts/optical_factorial_temporal_study.py)
and [`optical_reuse_temporal_guard_study.py`](../scripts/optical_reuse_temporal_guard_study.py).

A new three-pair 120-second offscreen comparison for exact-depth reuse shows
median GPU-render +0.027 ms and optical-resolve +0.023 ms. Serial frame-work
has a mixed -0.024 ms median delta; this is not a whole-GPU-render win. Keep the
feature opt-in and disabled by default pending broader route and other-adapter
evidence. A refreshed native-window three-pair study shows median FPS +0.043
for reuse, with median optical-resolve +0.0043 ms; same-session captures at
three fixed-tick cameras are pixel-identical. These small mixed timing changes
do not establish a whole-render win. See [exact-depth sustained report](measurements-o06-exact-depth-sustained.json) and
[native-window report](measurements-o06-native-exact-depth.json).

## O03 materialized smoke candidates (18 October)

The initial shader path reconstructs deterministic parent-lobe bounds in every
screen tile and again for each pixel candidate. A GPU compute pass now evaluates
up to 72 source-local bounds once for the dirty rendered state and shares that
buffer between tile construction and ink-smoke shading. Density-derived presence,
parent radius, and child bubbles remain evaluated from the live smoke field in the
shader. The implementation uses 2,304 known bytes and has an exact same-tick,
same-device reference path through `render.experiments.smoke_candidate_cache`;
that experiment defaults off. Simulation steps, reset, validated live parameter
edits, and shader reload mark the data dirty. Camera-only changes do not, because
the stored bounds are world-space.

On M1 Max/Metal, the original implementation-revision comparisons found the
candidate GPU-render median 0.017 ms lower on the dual-emitter review route and
0.013 ms higher on the heavy single-plume route. CPU tile-list encoding increased
0.041/0.044 ms; paired whole-frame work increased 0.062/0.090 ms. The GPU-stage
change is too small and workload-dependent to justify enabling the cache by
default. Same-tick direct/cached dual-emitter captures are byte-identical. Keep
the direct path as default and the buffer path as an experiment. Reports:
[measurements-o03-smoke-candidates.json](measurements-o03-smoke-candidates.json);
raw comparisons are under ignored `artifacts/o03/smoke-candidate-*-selectable/`.
The newer same-source release-profile comparison below isolates the runtime
toggle on the current instrumented binary and is the applicable current-build
performance evidence; the original figures remain as revision-history data.

### Current-build toggle and invalidation check (19 October)

The fixed-tick live recheck runs matched direct and cached serve sessions through
tick 120, a paused campfire smoke-density edit, a linked fire-light position
edit, one further simulation step, successful shader reload, and reset/replay to
tick 120. Fire-state JSON and rendered pixels matched at all seven checkpoints.
A separate same-session direct/cache/direct toggle at tick 120 also preserved
the image and received the expected Session acknowledgments. This is current
M1 Max/Metal sampled-path evidence. New cumulative frame counters report six
dispatch encodes across the six dirty cached states and skip counts on unchanged
enabled renders; the toggle session encodes one build only while enabled. The
2,304-byte candidate-buffer inventory remains reserved allocation. These
counters show scheduled command-buffer work, not GPU completion time or cost.
Keep the path opt-in: these current checks establish correctness and actual
dispatch scheduling, but not enough evidence for promotion. A same-source
release-profile rebenchmark compared the toggle directly on two-emitter and
heavy-plume routes, three alternating pairs of 120 seconds each after 10-second
warm-ups. All six runs per route covered 7,200 timed frames with zero skipped or
late GPU samples. Two-emitter paired medians: frame work −0.016 ms, GPU render
−0.046 ms, CPU tile-list encoding +0.040 ms. Heavy-plume medians: frame work
−0.398 ms, GPU render −0.070 ms, CPU tile-list encoding +0.012 ms; one GPU-render
pair regressed. These M1 Max/Metal offscreen results vary by stage and workload.
Native playback, continuous owner review, Windows/DX12, and other adapters
remain open. See
[current check](measurements-o03-smoke-candidate-invalidation-recheck.json) and
[current sustained report](measurements-o03-smoke-candidate-sustained-current-build.json),
[runner](../scripts/smoke_candidate_invalidation_study.py).

## O02/O07 source-specific point-shadow contribution (19 October 2026)

Hypothesis: the second emitter's cube-array point shadow contributes to opaque
world shading independently of its direct light. To isolate that term, the
two-emitter review scene enables only `watchfire`; a diagnostic copy of
`world.wgsl` returns full visibility for valid source slots while retaining the
same scene, primary-light intensity, sun shadow, smoke and volume-shadow paths.
The ordinary renderer remains the reference. At seed 42/tick 300 on M1 Max/Metal,
all four views changed: 34,136 pixels in `dual-wide`, 6,729 in `smoke-close`,
8,024 in `watchfire-study` and 1,754 in `heat-ground-study`. Mean RGB error was
0.394/0.209/0.308/0.844 per 255, respectively. The contact sheet shows localized
illumination changes on nearby terrain and objects. This closes the focused
source-one opaque point-shadow contribution check, not continuous playback,
performance, owner visual acceptance or cross-adapter validation. Reproduce with
[the report](measurements-multi-emitter-shadow-contribution.json), [the contact
sheet](measurements-multi-emitter-shadow-contribution-contact.png) and [the
runner](../scripts/two_emitter_shadow_contribution_study.py).

## Native lifecycle and live playback recheck (19 October 2026)

On the unlocked M1 Max/Metal host, the GPU verifier still passes. The native
suite confirms resize, fullscreen entry/exit, request handling, shutdown and a
fixed tick-120 capture. Minimization remains unverified: `set_window` returned
`requested: true`, while `is_minimized` stayed false in the current release
Session and in a full native verifier run using a temporary signed app bundle
with the current release executable. A focus-instrumented release recheck waited
eight seconds: focus changed from true after resize to false after the minimize
request, while `is_minimized` and `occluded` both stayed false. The longer wait
did not resolve the gate. The owner reported using the desktop concurrently;
other UI activity may have changed focus, making the minimize result
inconclusive. Repeat in an isolated native session before diagnosing the engine
request path. A release rebuild from the current checkout passed and now has
offscreen fixed-tick capture evidence, but its executable hash differs from the
binary used in the recorded lifecycle runs; the rebuilt binary has not received
native lifecycle verification. A live
current-release native viewport reported tick 423
running at 640×360; the smoke still forms a tall regular stack of rounded puffs.
This is an observed visual concern, not owner acceptance or a temporal score.
Keep the macOS minimize/restore, owner playback, DX12 and another-adapter gates
open. See [native verification](measurements-native-window-verification-current-build.json) and its [tick-120 capture](measurements-native-window-verification-current-build.png).

## Current-build RG16 fallback recheck (19 October 2026)

The current debug build reran the forced RGBA16F effect-depth and smoke-volume
fallback comparison on Apple M1 Max/Metal at the fixed 640×360 pixel grid. The
profiling-heavy and Materials scenes matched the native Rg16Float path at tick
120; all 120 sampled frames from tick 120 through 477 on the moving fire-camera
route also matched byte-for-byte. The fallback adds 2,101,248 known GPU bytes.
This confirms current-build fallback rendering on capable hardware. It does not
simulate a device that physically lacks Rg16Float support, nor validate DX12.
See [the report](measurements-o08-rg16-fallback-current-build.json); the
original forced-fallback evidence is preserved in
[measurements-o08-rg16-fallback.json](measurements-o08-rg16-fallback.json).

## Debug/release fixed-tick output comparison (19 October 2026)

Eleven M1 Max/Metal captures used seed 42, tick 120 and the selected 640×360
pixel grid with unchanged scene JSON and named cameras. Ten pairs were
byte-identical, covering clearing, a heavy plume, two emitters, smoke-candidate
and projected-detail opt-ins, and four Materials cameras. Materials/hero was the
only non-identical pair: 87 pixels changed, mean absolute channel error was
0.00048/255 and the maximum was 108/255 at one flame-edge pixel. Other changed
pixels were small. Three repeats within each build were byte-identical; tick 300
and 600 also showed a sparse cross-profile edge divergence. A schema-validated
Materials scene with its only emitter disabled reduced the difference to four
pixels at one level. `inspect_effects` reports the same active fire-primitive
fingerprint, counts, bounds and particle lights across profiles, so the remaining
difference is downstream of CPU fire-primitive generation. Setting smoke density
to zero leaves all 87 changed pixels, while disabling the emitter reduces the
result to four one-level differences; this isolates the outlier to downstream
fire rendering. The exact projection or shading operation is not isolated.
Keep the selected grid and renderer defaults;
record no broad debug/release identity claim until the edge case is understood.
The captures are offscreen and single-adapter, not native playback or
cross-vendor determinism evidence. See the [report](measurements-debug-release-profile-parity.json)
and [contact sheet](measurements-debug-release-profile-parity-contact.png).
