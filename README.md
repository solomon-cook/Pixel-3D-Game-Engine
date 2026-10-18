# Pixel Engine · Emberwood lab

A proprietary Rust desktop engine for expressive pixel-art 3D games. The first
scene is a woodland fire with illuminated volumetric smoke, shadows and embers.
The reusable engine and the lab are separate workspace packages.

Read the [engine vision](docs/VISION.md) for the long-term direction: selectable
pixel density, procedural generation, expressive simulation and physics, and
style-aware engine experiments grounded in visual and performance evidence.

See [the work queue](TODO.md) and [optimisation plans](docs/OPTIMIZATION_PLAN.md)
for completed profiling instrumentation, whole-map shadow reuse, tiled effect lists,
opt-in projected fire detail, smoke absorption reuse, optical surface reuse and
geometry culling. Optical snapshots allocate on first camera-visible optical
geometry; the effect coverage target and smoke volumes use adapter-gated two-channel formats with
fallbacks. Other memory layout work remains proposed. Measurements are recorded in
[docs/measurements-o01.json](docs/measurements-o01.json),
[docs/measurements-o02.json](docs/measurements-o02.json),
[docs/measurements-o02-visible-caster.json](docs/measurements-o02-visible-caster.json),
[docs/measurements-o02-visible-caster-native.json](docs/measurements-o02-visible-caster-native.json),
[docs/measurements-o02-native-shadow-cache.json](docs/measurements-o02-native-shadow-cache.json),
[docs/measurements-o03.json](docs/measurements-o03.json),
[docs/measurements-o03-native-tile-lists.json](docs/measurements-o03-native-tile-lists.json),
[docs/measurements-o04.json](docs/measurements-o04.json),
[docs/measurements-o04-sustained-profiles.json](docs/measurements-o04-sustained-profiles.json) and
[docs/measurements-o05.json](docs/measurements-o05.json),
[docs/measurements-o05-temporal.json](docs/measurements-o05-temporal.json),
[docs/measurements-o05-temporal-cache8.json](docs/measurements-o05-temporal-cache8.json),
[docs/measurements-multi-emitter-absorption-moving-route.json](docs/measurements-multi-emitter-absorption-moving-route.json),
[docs/measurements-multi-emitter-absorption-moving-route-cache16.json](docs/measurements-multi-emitter-absorption-moving-route-cache16.json),
[docs/measurements-multi-emitter-tile-native.json](docs/measurements-multi-emitter-tile-native.json),
[docs/measurements-multi-emitter-review-tile-sustained.json](docs/measurements-multi-emitter-review-tile-sustained.json),
[docs/measurements-multi-emitter-heat-response-temporal.json](docs/measurements-multi-emitter-heat-response-temporal.json),
[docs/measurements-multi-emitter-heat-response-ground-orbit.json](docs/measurements-multi-emitter-heat-response-ground-orbit.json),
[docs/measurements-multi-emitter-heat-response-native.json](docs/measurements-multi-emitter-heat-response-native.json),
[docs/measurements-multi-emitter-heat-response-native-contact.png](docs/measurements-multi-emitter-heat-response-native-contact.png),
[docs/measurements-multi-emitter-shader-rollback.json](docs/measurements-multi-emitter-shader-rollback.json),
[docs/measurements-multi-emitter-shader-rollback-native.json](docs/measurements-multi-emitter-shader-rollback-native.json),
[docs/measurements-multi-emitter-heat-response-ground-orbit-contact.png](docs/measurements-multi-emitter-heat-response-ground-orbit-contact.png),
[docs/measurements-multi-emitter-heat-response-temporal-contact.png](docs/measurements-multi-emitter-heat-response-temporal-contact.png),
[docs/measurements-multi-emitter-absorption-native.json](docs/measurements-multi-emitter-absorption-native.json),
[docs/measurements-multi-emitter-absorption-native-sustained.json](docs/measurements-multi-emitter-absorption-native-sustained.json),
[docs/measurements-o05-pause-resume.json](docs/measurements-o05-pause-resume.json),
[docs/measurements-o06.json](docs/measurements-o06.json) and
[docs/measurements-o06-camera-stress.json](docs/measurements-o06-camera-stress.json),
[docs/measurements-o06-native-reuse.json](docs/measurements-o06-native-reuse.json),
[docs/measurements-o06-o08-factorial-temporal.json](docs/measurements-o06-o08-factorial-temporal.json),
[docs/measurements-o06-temporal-depth-guard.json](docs/measurements-o06-temporal-depth-guard.json),
[docs/measurements-o06-exact-depth-sustained.json](docs/measurements-o06-exact-depth-sustained.json),
[docs/measurements-o06-native-exact-depth.json](docs/measurements-o06-native-exact-depth.json),
[docs/measurements-o07-culling.json](docs/measurements-o07-culling.json),
[docs/measurements-o07-scale-study.json](docs/measurements-o07-scale-study.json),
[docs/measurements-o07-moving-caster.json](docs/measurements-o07-moving-caster.json),
[docs/measurements-o07-native-scale-study.json](docs/measurements-o07-native-scale-study.json) and
[docs/measurements-o08.json](docs/measurements-o08.json),
[docs/measurements-o08-native-no-copy.json](docs/measurements-o08-native-no-copy.json).

## Start

Install Rust using [rustup](https://rust-lang.org/tools/install/). The project
pins its toolchain. Windows builds require Visual Studio C++ build tools; Mac
builds require Xcode command-line tools. Native backends are Metal and DX12.

```sh
cargo run --release -p engine-lab -- run
```

Right-drag + WASD flies the camera; Q/E moves vertically; Shift speeds up.
Tab toggles the inspector, Space pauses, F5 reloads shaders, F11 toggles fullscreen.
Choose named perspective or orthographic views in the inspector.

```sh
cargo run --release -p engine-lab -- validate
cargo run --release -p engine-lab -- describe
cargo run --release -p engine-lab -- capture --camera hero --tick 300 --output artifacts/hero.png
cargo run --release -p engine-lab -- capture --tick 300 --shading-counters --output artifacts/shading-counters.png
cargo run --release -p engine-lab -- capture --scene assets/scenes/materials.json --camera metal-close --compact-hdr --output artifacts/metal-compact-hdr.png
cargo run --release -p engine-lab -- benchmark --duration 120 --warmup 10
cargo run --release -p engine-lab -- benchmark-native --duration 120 --warmup 10
python3 scripts/profile_compare.py --baseline assets/scenes/materials.json --candidate assets/scenes/materials.json --measure-overhead
python3 scripts/capture_motion.py --scene assets/scenes/projected-detail-motion-review.json --route projected-detail-review-orbit --camera fire-study --frames 400 --stride 3 --experiments projected_detail_lod --output artifacts/o04/continuous-motion/lod-20fps --gif
python3 scripts/absorption_cache_temporal_study.py
python3 scripts/absorption_cache_pause_resume_study.py
python3 scripts/optical_camera_stress_study.py
python3 scripts/verify.py --gpu --native
python3 scripts/package.py
```

Windows: use `python` for scripts and PowerShell/cmd for commands. The packaged
Windows build has `Launch Lab.cmd`; the Mac bundle opens by double-click.
Development Mac signing is ad hoc, not Developer ID signing/notarization.

## Agent access

`engine-lab serve` is a real-GPU session without a window. Use `run --agent-stdio`
to work in the native window. Sessions start paused. Send one JSON object per
line and read one response with the matching ID. Diagnostics use stderr.

```json
{"id":1,"method":"inspect_scene"}
{"id":2,"method":"step","params":{"ticks":300}}
{"id":3,"method":"set_camera","params":{"id":"smoke-close"}}
{"id":4,"method":"capture_frame","params":{"path":"artifacts/smoke.png","scale":4}}
{"id":5,"method":"set_parameter","params":{"path":"environment.wind","value":[0.7,0,0.1]}}
{"id":6,"method":"set_object_transform","params":{"id":"fire-ring-0","position":[0,1,0]}}
```

Use `describe` for command discovery and scene JSON schema. Image captures have
JSON sidecars containing the full scene, camera, seed, tick and GPU identity.
Capture scale is integer nearest-neighbour scaling of the selected scene buffer.

## Rendering and experiments

The current default pixel grid is 640×360, selected to explore the finer apparent
pixel density in the supplied art references. Those references do not prescribe
the output image size, aspect ratio or camera framing. Explicit `--resolution
320x180`, `480x270`, `640x360` and `960x540` presets are available; scene JSON can
specify other aspect ratios. Windows use integer scaling and
letterboxing. No automatic scene-resolution changes are made.

Use `--experiments pixel_cluster_lighting`, `stable_smoke_detail`,
`connected_motion`, `projected_detail_lod`, a comma-separated combination, or
`all`. Projected fire detail is opt-in and leaves the selected pixel grid,
simulation frame, bounds and emitted lights unchanged. The inspector uses the
same mutations as the protocol. Shader files can be edited live and reloaded;
invalid replacements retain the last working pipelines.

```sh
python3 scripts/experiments.py
```

This generates matched views and a 120-second camera-route benchmark per variant.
See docs/RESEARCH.md for hypotheses and docs/STATUS.md for actual validation.
`profile_compare.py` alternates baseline/candidate offscreen route runs and writes
untouched raw reports, fingerprints, per-stage paired deltas, and optional timed/
untimed overhead comparisons. `benchmark-native` records actual surface acquisition,
present and vsync spans in a native window. For compile-time renderer experiments,
`profile_compare.py` accepts separate `--baseline-binary`/`--candidate-binary` and
`--baseline-shaders`/`--candidate-shaders` inputs and fingerprints each variant;
`--baseline-source-root`/`--candidate-source-root` select the corresponding source
checkouts for provenance.
`assets/scenes/profiling-heavy.json`
provides the single-plume, eight-point-light workload; it keeps the chosen 640×360
grid and clearing route.

`capture --shading-counters` selects instrumented world, volumetric and optical
pipelines for one fixed-tick capture. The JSON sidecar reports fire, smoke,
absorption, light candidate, shadow, reflection and transmission operation
counts. Atomic counters perturb the diagnostic capture and are not performance
timings.

For sparse checkpoints on a moving route, pass
`--shading-counter-sampling` to `benchmark`. It samples start, midpoint and end,
disables GPU timestamps, and marks timing data unusable in the report. The route
may also use `--moving-caster` to sample changing shadow membership.

`--compact-hdr` opts into an `Rg11b10Ufloat` HDR color target when the active adapter
supports filtered sampling, render targets, copies and the required render feature.
The default remains `Rgba16Float`; selected format and fallback capability appear in
capture metadata and the `serve` readiness report. This experimental format is
startup-only and may change final pixel colors slightly.

## Game-authored effects

Named scene profiles expose flame proportions/pace/curl, detached fragments,
embers, linear HDR palettes and simple thermal controls. Try
`run --effect-profile effect-quiet` or `effect-bonfire`. The inspector and JSON
commands edit the same validated profile data. Curve/particle budgets are separate
from the selected pixel grid. `render.palette_strength` and `bloom_strength`
control presentation after 3D HDR shading. Rounded flame lobes can grow smaller
upward branches; detached flickers/embers float in 3D and supply a capped set of
moving lights to geometry and smoke. Use `inspect_effects` for their runtime
positions/powers and stable identities. The clearing now uses solid pixel flame
coverage with four heat-colour bands and a bounded, depth-aware heat shimmer
above it. Both controls remain independent of geometry and pixel resolution.
See [EFFECTS.md](docs/EFFECTS.md).

```sh
python3 scripts/capture_motion.py --profile effect-campfire --gif
```

The motion script always writes PNG frames/metadata; optional previews use Pillow.

## Game-authored materials

Metallic, reflective, refractive/transmissive and faux subsurface materials are
live scene data. The comparison lab has chrome, copper, glazed ceramic, clear
and amber glass, and backlit wax. Open Materials in the shared inspector to edit
colour, roughness, metallic/reflection, transmission, IOR, absorption, thickness
and scattering. Reflection quality is independent of pixel resolution.

```sh
cargo run --release -p engine-lab -- run --scene assets/scenes/materials.json
python3 scripts/material_study.py
```

See [MATERIALS.md](docs/MATERIALS.md) for the model, scene layout, protocol examples,
measured costs and the single-layer/screen-space limits.

## Current contract

V1 supports static triangle GLB geometry with OPAQUE alpha mode, 8-bit embedded GLB base-colour
textures, PNG scene textures, procedural geometry, one directional light, up to eight
point lights (the fire source casts geometry shadows) and one bounded fire/smoke
emitter. Smoke samples the nearest two active lights for radial illumination and
shared volume absorption; additional fill lights do not cast geometry shadows. The smoke grid is
48×64×48. Textures use a 128×128-per-layer nearest-filtered atlas. GLB animation,
skins, alpha materials, water, clouds and a full scene editor are later work.

Scene topology/assets and render resolution load at startup. Uniform-backed
parameters can change live. `reset` clears smoke history before comparisons.
GPU simulation is repeatable on the same device; cross-vendor bit equality is
not a promise. Offscreen benchmark results exclude the window/inspector/vsync
and are not a full desktop performance certification.


The default inked effect keeps the original large smoke puffs with a varied count of up to four smaller
secondary bubbles attached to each. Their count and relative size can be edited
in the inspector or through `emitters.campfire.secondary_bubbles` (0..8) and
`emitters.campfire.bubble_scale` (0.1..0.5). Parent motion and GPU advection remain
unchanged. Local normal blending softens contact regions while preserving the
individual billows. Six samples through the existing smoke grid estimate shared
local-light occlusion with radial distance falloff; this is a cheap metaball-like lighting approximation, not
an implicit-surface ray marcher. `self_shadow_strength` (0..4) controls absorption
and `internal_glow` (0..4, default 0) adds emission from within the plume.
`emitters.campfire.style` switches between `ink` and `volume`.

The experimental `render.experiments.smoke_absorption_cache` option caches
optical depth for the primary authored fire light. Choose
`render.absorption_cache_resolution` as 8 or 16 (default 8); the cache rebuilds
after smoke simulation updates and relevant state changes, then reuses its field
for repeated renders of an unchanged state. Particle lights and fallback points
keep direct sampling. It is off by default and has not shown a GPU-time reduction
on the measured moving Metal workload. See [O05 measurements](docs/measurements-o05.json)
and the [refresh-policy study](docs/measurements-o05-refresh-policy.json).

The experimental `render.experiments.optical_surface_reuse` option reuses opaque
reflector shading from the matching scene snapshot. It retains direct shading for
transmissive materials and is off by default pending longer and cross-backend
validation. See [O06 measurements](docs/measurements-o06.json).

`inspect_scene` returns a compact overview. Select an object with
`{"id":1,"method":"inspect_scene","params":{"section":"objects","id":"fire-ring-0"}}`.
Capture responses stay compact; complete provenance is in the JSON sidecar.
Native mode also exposes `get_window`, `set_window` and `shutdown`; `describe`
documents their availability. Minimized windows keep servicing agent commands.
