# Next research path: fire simulated in a field

Proposal, 16 October 2026. This is not an implemented effect mode. The reusable
curve/fragment/ember implementation in EFFECTS.md remains the measured baseline.

## Recommendation

Investigate a hybrid: persistent heat/burning-state transport supplies natural
motion, while profile curves act as optional source/flow guides and artistic
controls. Preserve independent render palettes, thresholds, contour treatment
and pixel presentation. Compare this against the baseline instead of declaring
one representation universally best.

For predominantly side-on or orthographic games, test a shallow, emitter-local
3D field with a few depth layers. For freely rotating cameras, use a small full
3D field. A 2D-looking final image does not by itself justify discarding world
depth. A single camera-facing simulation plane would compromise rotation,
self-shadowing and interaction around objects. Do not rotate simulation state
with the camera or reset it when the view changes.

## Information to transport

- Heat above ambient: rising tendency, cooling and optional hot-soot emission.
- Burning progress/reaction age: freshly ignited material becomes older flame,
  then stops emitting. Start with this simpler state before chemical fuel and
  oxygen conservation.
- Smoke/soot density: survives after the flame cools and receives external light.
- Shared flow: wind, buoyancy and a few coherent curls carry all these quantities.

Transported burning pockets could stretch, pinch and separate through motion
of the field. This is a hypothesis to test, not a promise that scalar advection
alone creates convincing breakup. Coherent velocity/curl and adequate local
resolution matter. Embers remain a bounded particle system launched from active
burning regions; not every grid cell needs to become a particle.

## A bounded first experiment

1. Add a tight fire domain, for example 32×64×16 cells, around the source. These
   dimensions are provisional quality settings, not a measured optimum. The
   existing larger smoke domain remains separate: its cells are too coarse to
   assume they will resolve thin flame tips in every scene.
2. Advect heat and burning progress in fixed steps. Inject an authored source,
   reduce progress with age, cool heat independently of soot. Use shared wind
   and prescribed coherent vortices initially; pressure projection is a later
   measured option, not a prerequisite for the first artistic experiment.
3. Render emission/absorption using a few depth samples or volume slices in the
   predominantly front-facing mode. Keep depth testing, shadows and parallax.
   Offer bounded ray sampling/full-depth mode for camera rotations. Sample count
   and simulation dimensions remain independent of the selected pixel grid.
4. Feed aggregate heat/soot into the larger smoke domain and derive stable local
   light signals from downsampled emission. Reuse GPU data without frame-by-frame
   CPU readback. Avoid tying brightness to how many simulation cells are active.
5. Map heat, burning age and thickness to authored HDR colours. Add stable
   clustered shading/contours only after the broad silhouette and motion work.
   Preserve rounded smoke forms and dark internal folds; a generic soft-fluid
   image is not automatically closer to the supplied reference.
6. Compare the two paths with the same source scale, seed, camera route, pixel
   buffer and matched warmth/exposure. Record simulation, VFX render and total
   frame cost separately where supported. Keep useful alternatives as lab modes.

A 32×64×16 RGBA16F field needs 256 KiB per state, or 512 KiB for ping-pong state,
before velocity, lighting, obstacles or other scratch buffers. That arithmetic
is a memory estimate, not a GPU-time claim. Neither few cells nor low output
resolution removes fill/overdraw cost. Measure a large on-screen flame and many
sources, keep pool/tile budgets explicit, and inspect p95 as well as median.

## How to choose

| Representation | Best reason to use it | Limitation to test |
|---|---|---|
| Current bounded curves/particles | Direct artistic control, predictable geometry budget and deterministic reconstruction | Motion/breakup is procedural; complex interacting flow must be prescribed |
| Shallow transported field | Rich coherent motion for restricted viewing angles, some depth and shared thermal state | Thin volume at grazing angles, layer artifacts, transport diffusion |
| Coarse full 3D field | Free camera rotation and spatial interaction | More cells/samples; small tips need a tight domain/detail treatment |
| Baked flipbook/atlas | Many distant decorative effects with predictable cost | Repetition and limited response to wind/obstacles; blending/lighting work remains |

Use the current system as the economical fallback and as a possible guide to
source shape. Do not replace it with an unmeasured solver. Field simulation is
the more promising next investigation for emergent curling and breakup; its
visual/performance advantage has not yet been demonstrated in this engine.

## Relevant prior work

[NVIDIA GPU Gems 3, chapter 30](https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-30-real-time-simulation-and-rendering-3d-fluids)
describes advected reaction coordinates for fire, artist-defined colour mappings,
and deriving light from a reduced fire volume. These are useful established
building blocks; the proposed engine experiment is not claimed as a new method.

[GPU Gems, chapter 39](https://developer.nvidia.com/gpugems/gpugems/part-vi-beyond-triangles/chapter-39-volume-rendering-techniques)
explains texture/slice volume rendering, transfer functions, absorption and
sampling artifacts. Its treatment of view-dependent sampling is relevant to
choosing between shallow fixed-view and freely viewed effects.

[Wavelet Turbulence for Fluid Simulation](https://www.tkim.graphics/WTURB/)
is relevant to separating coarse motion from added detail. It does not establish
that its complete method is appropriate for our real-time pixel-art budget.
