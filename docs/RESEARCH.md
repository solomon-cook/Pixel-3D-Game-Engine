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

Three alternating 2-second serial pairs per size on M1 Max/Metal reduced median
GPU render time by about 0.11 ms in medium and small views, but paired total frame
work was mixed and the candidate run medians were 0.13–0.23 ms slower overall.
This is too small and noisy to support promotion. The implementation stays off by
default pending longer moving-route review and Windows/DX12 qualification. Full
commands, hashes, measurements and caveats are in [measurements-o04.json](measurements-o04.json);
local captures and raw runs are under ignored `artifacts/o04/`.

## Evidence procedure

Run `scripts/experiments.py` after a release build. Each variant uses seed 42,
tick 300 and the same three cameras, plus a moving 120-second route after ten
seconds of warm-up. PNG/JSON captures and raw frame samples go to artifacts.
Keep numerical findings in docs/STATUS.md and record visual limitations there.
Promotion requires visible improvement, acceptable frame cost and cross-platform
review. A failed hypothesis is retained as useful evidence, not silently enabled.


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

The O08 inventory found two full-resolution RGBA16F snapshots allocated in every
scene although diffuse scenes skip both copies and optical resolve. The renderer
now starts with the existing HDR/normal targets as unused optical bind-group
fallbacks and allocates the dedicated snapshots on first optical use. At 640×360,
the known allocation falls by 3,686,400 bytes for diffuse scenes. A live reflectivity
edit activated the optical pass and allocated the snapshots; the diffuse smoke and
opaque-metal fixed-tick captures were byte-identical to pre-change captures. No
frame-time reduction is claimed because the old diffuse path already skipped the
copy and optical draw. The effect-depth/flame-coverage attachment now uses Rg16Float
when the adapter reports filterable sampled and render-attachment support, falling
back to Rgba16Float. On this M1 Max/Metal adapter it saves 921,600 bytes at 640×360;
matched smoke and opaque-metal captures at scale 1 were pixel-identical to saved
baselines. This confirms the path on one Metal adapter only; no timing benefit is
claimed. The full live-allocation report, format selection and limits are in
[measurements-o08.json](measurements-o08.json).

The smoke density/temperature ping-pong pair also uses Rg16Float when the adapter
exposes `TEXTURE_ADAPTER_SPECIFIC_FORMAT_FEATURES` and filterable sampled/write-only
storage support; otherwise it retains Rgba16Float. The selected path requests that
device feature, updates the storage binding and reset-upload stride, and saves
1,179,648 bytes at 48×64×48. Fixed-seed reset/replay verification passed, and
smoke-close plus opaque-metal captures at 640×360 were byte-identical to the prior
format. The nominal full-texel request estimate halves, but no frame-time or
external-bandwidth gain is claimed. Fallback execution and DX12 remain open.
