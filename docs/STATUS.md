# Milestone status

16 October 2026. The first development implementation is runnable; visual and
platform acceptance are still open. This is a rendering lab and engine foundation.

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

- Rust formatting, Clippy with warnings denied, 20 unit tests, asset decoding,
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
