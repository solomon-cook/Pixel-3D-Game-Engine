# Pixel Engine · Emberwood lab

A proprietary Rust desktop engine for expressive pixel-art 3D games. The first
scene is a woodland fire with illuminated volumetric smoke, shadows and embers.
The reusable engine and the lab are separate workspace packages.

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
cargo run --release -p engine-lab -- benchmark --duration 120 --warmup 10
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
`connected_motion`, a comma-separated combination, or `all`. The inspector uses
the same mutations as the protocol. Shader files can be edited live and reloaded;
invalid replacements retain the last working pipelines.

```sh
python3 scripts/experiments.py
```

This generates matched views and a 120-second camera-route benchmark per variant.
See docs/RESEARCH.md for hypotheses and docs/STATUS.md for actual validation.

## Game-authored effects

Named scene profiles expose flame proportions/pace/curl, detached fragments,
embers, linear HDR palettes and simple thermal controls. Try
`run --effect-profile effect-quiet` or `effect-bonfire`. The inspector and JSON
commands edit the same validated profile data. Curve/particle budgets are separate
from the selected pixel grid. `render.palette_strength` and `bloom_strength`
control presentation after 3D HDR shading. Rounded flame lobes can grow smaller
upward branches; detached flickers/embers float in 3D and supply a capped set of
moving lights to geometry and smoke. Use `inspect_effects` for their runtime
positions/powers and stable identities. See [EFFECTS.md](docs/EFFECTS.md).

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

`inspect_scene` returns a compact overview. Select an object with
`{"id":1,"method":"inspect_scene","params":{"section":"objects","id":"fire-ring-0"}}`.
Capture responses stay compact; complete provenance is in the JSON sidecar.
Native mode also exposes `get_window`, `set_window` and `shutdown`; `describe`
documents their availability. Minimized windows keep servicing agent commands.
