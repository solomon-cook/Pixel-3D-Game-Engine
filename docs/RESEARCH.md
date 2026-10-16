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
