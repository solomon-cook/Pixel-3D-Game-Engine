# Milestone status

16 October 2026. The first development implementation is runnable; visual and
platform acceptance are still open. This is a rendering lab and engine foundation.

Implemented: reusable engine/library separation, native Metal/DX12 selection,
versioned/validated JSON scenes, static GLB/PNG assets, fixed-step smoke grid,
seeded fire/embers, directional/point shadows, HDR pixel rendering, integer
presentation, orthographic/perspective cameras, shared inspector/JSON-lines
operations, exact-tick capture, transactional shader reload and route benchmarks.

## Verification on this host

- Rust formatting, Clippy with warnings denied, nine unit tests, asset decoding,
  schema discovery and scene validation passed.
- Metal GPU integration passed: deterministic same-device replay, malformed
  commands/invalid edits, capture completion, orthographic rendering, visible
  self-shadow/glow mutations and invalid-shader rollback.
- Native resize, fullscreen, frame capture, command handling and shutdown passed.
  Automated minimization is unresolved on this macOS host: the OS keeps reporting
  `minimized: false` after the request. `verify.py --native` correctly fails that
  gate and saves partial results; do not report full native acceptance.
- macOS ARM64 and Windows x64 GNU release builds succeeded. Windows PE executable
  was cross-compiled here; CI definitions exist but no hosted CI result is claimed.
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

| Variant | Frame work median / p95 ms | GPU render median / p95 ms |
|---|---:|---:|
| baseline | 4.365 / 6.717 | 2.767 / 4.026 |
| pixel_cluster_lighting | 4.400 / 7.978 | 2.765 / 4.338 |
| stable_smoke_detail | 4.454 / 8.102 | 2.741 / 4.823 |
| connected_motion | 4.403 / 7.820 | 2.619 / 4.643 |
| Smoke-heavy close route | 5.681 / 9.964 | 3.633 / 5.689 |

The stress route uses maximum supported child count/size and smoke source density
with a close orbit. It exercises one large on-screen plume, not many emitters.
Experiments remain opt-in: timings alone do not justify promoting a visual mode.

## Outstanding gates

- Actual Windows DX12 rendering, image/motion review and performance on an RTX
  3060-class/16 GB PC. Compilation is not visual validation.
- Base M1/16 GB measurement and native presentation/UI timing. The provisional
  target remains 60 fps at 1080p with a selected 480×270 scene buffer.
- Fix/qualify native automated minimization and confirm restore behaviour.
- Reference-led billow hierarchy, heat/soot transition and multiple source scales;
  this is specified next work, not implemented multi-emitter support. The cheap
  thermal model is proposed in HEAT_SYSTEM.md; its new controls are not implemented.
- Owner visual review, including silhouettes, self-shadowing, camera motion,
  temporal stability and all three experimental comparisons.

Development Mac app and Windows executable bundles include editable assets/WGSL,
launch instructions and dependency notices. Mac signing is ad hoc; Windows is
unsigned. Production signing/notarization/distribution remain outside this lab.
Water, clouds, browser support, gameplay frameworks and a full editor are later work.
