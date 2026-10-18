# Engine work queue

The optimization queue tracks implementation separately from platform and visual
acceptance. O01 profiling, O08's inventory, O02 whole-map reuse, O03 single-emitter
tile lists and O07's bounds, shared meshes, instancing, culling and static-shadow
scene-scale evidence are implemented with M1 Max/Metal evidence.
Detailed steps, dependencies and acceptance criteria live in
[the optimisation plans](docs/OPTIMIZATION_PLAN.md). This is the execution index;
[STATUS.md](docs/STATUS.md) records runtime evidence and outstanding release gates.

## First: establish evidence

- [x] [O01: complete-frame and per-stage profiling](docs/OPTIMIZATION_PLAN.md#o01--measure-each-stage-and-the-complete-frame) — instrumentation, paired reports for all three workloads, profiling-overhead controls, and a native-window route are recorded in [measurements-o01.json](docs/measurements-o01.json). Exact queue latency and non-Metal adapter support remain explicit platform limitations.
- [x] [O08: resource/bandwidth inventory](docs/OPTIMIZATION_PLAN.md#o08--reduce-memory-traffic-and-unnecessary-gpu-work) — allocation, lifetime, upload, copy and logical attachment traffic inventory plus an adapter-gated Rg16Float effect-target trial are recorded in [measurements-o08.json](docs/measurements-o08.json); broader backend acceptance remains open.

## Then: preserve the image while avoiding work

- [x] [O02: whole-map shadow caching](docs/OPTIMIZATION_PLAN.md#o02--cache-static-shadow-maps) — full sun map and point-light cube reuse with conservative invalidation; M1 Max paired results and gates are in [measurements-o02.json](docs/measurements-o02.json).
- [x] [O07: stable object bounds, culling, shared meshes, instancing and live transforms](docs/OPTIMIZATION_PLAN.md#o07--object-bounds-culling-and-shared-meshes) — per-camera/light culling, shared geometry and validated live object transforms measured; a four-tier 276–2,208-object study shows small culling+instancing frame-work gains on a static-shadow route. Full per-run evidence is in [measurements-o07-scale-study.json](docs/measurements-o07-scale-study.json), alongside [core O07 evidence](docs/measurements-o07-culling.json). Moving-caster shadow scaling, native-window and non-Metal acceptance remain open.
- [x] [O03: bounded single-emitter tile lists with overflow fallback](docs/OPTIMIZATION_PLAN.md#o03--tile-lists-for-effects-and-local-lights) — byte-identical perspective, orthographic, close-smoke, glass and natural-overflow captures; three paired route workloads plus preliminary 8×8/fallback evidence in [measurements-o03.json](docs/measurements-o03.json) and [measurements-o03-overflow.json](docs/measurements-o03-overflow.json). A three-pair 120-second natural-overflow orbit measures 1.95% fire-list overflow but no full-frame benefit over exhaustive evaluation; 8×8 sustained, route-image, native-window, multi-emitter and DX12 gates remain open. See [measurements-o03-stress-route.json](docs/measurements-o03-stress-route.json).
- [x] O02: per-face invalidation using O07 live transform revisions and affected-object bounds, with full-map fallback for uncertain state; static, six-pose movement, material/light/reload/reset, and three paired 120-second moving-caster reports are in [measurements-o02.json](docs/measurements-o02.json), [measurements-o02-moving-caster.json](docs/measurements-o02-moving-caster.json), [measurements-o02-invalidation.json](docs/measurements-o02-invalidation.json), and [measurements-o02-moving-route.json](docs/measurements-o02-moving-route.json). A linked fire-light position edit moves its emitter atomically. The live unknown-bound fallback, native-window, image checkpoints during motion, and Windows/DX12 acceptance gates remain open.

## Then: measure and review quality/cost tradeoffs

- [x] [O04: projected-pixel detail](docs/OPTIMIZATION_PLAN.md#o04--detail-based-on-projected-pixel-contribution) — opt-in fire-segment LOD, exact-state parity checks, three projected-size capture pairs, threshold-crossing route and paired M1 Max timings recorded in [measurements-o04.json](docs/measurements-o04.json). Default promotion, sustained orbit/temporal review and non-Metal acceptance remain open.
- [x] [O05: cached smoke absorption](docs/OPTIMIZATION_PLAN.md#o05--reuse-smoke-transmittance-and-illumination-work) — opt-in primary fire-light cache; sustained 8³/16³ comparisons across three smoke scales show no total GPU render win, so no default promotion. Paused edits, light changes, moving embers, reload and reset pass discrete parity checks; continuous temporal/restart and portability gates remain open. Evidence: [measurements-o05.json](docs/measurements-o05.json), [size study](docs/measurements-o05-size-study.json), [invalidation study](docs/measurements-o05-invalidation.json).
- [x] [O06: specialised optical resolve](docs/OPTIMIZATION_PLAN.md#o06--specialise-optical-materials-and-avoid-repeated-shading) — opt-in opaque-reflector base-light reuse with direct transmissive fallback; three paired 120-second material routes and three mixed smoke/fire/material routes show lower GPU-render time on M1 Max/Metal. Continuous, native-window, camera-inside/near-plane and cross-backend gates remain open. Evidence: [measurements-o06.json](docs/measurements-o06.json), [sustained study](docs/measurements-o06-sustained.json).
- [ ] O08: individually measured resource/pass-layout improvements — candidate dispositions are now split in [DECISIONS_O08.md](docs/DECISIONS_O08.md). Camera-visible lazy optical allocation saves 3.69 MB until optical geometry is visible at 640×360; normal/depth now samples directly, saving another 1.84 MB on optical scenes and 7.37 MB of modeled optical-pass traffic per frame. Adapter-gated RG16 targets save 2.10 MB total with replay and image parity on M1 Max/Metal. Three short and three longer route pairs found no GPU timing gain. The opt-in Rg11b10Ufloat HDR target saves 1.84 MB on optical scenes; three alternating 120-second route pairs found a consistent but very small GPU timing difference, four fixed-camera temporal samples and eight moving-route poses looked similar. The experimental `--optical-no-copy` overlay path gives exact fixed-tick image parity and removes the snapshot copy. On RGBA16F, alpha coverage avoids the former 0.23 MB mask and keeps known allocation equal to the snapshot path; its revised logical model saves 1.84 MB/frame at 640×360. Three alternating 120-second route pairs show only a small GPU timing delta and variable frame-work. An O06×O08 2×2×2 matrix on a high-dynamic smoke/fire/material scene found reuse and no-copy GPU gains and exact no-copy image parity; packed HDR kept a measurable image difference and adds a 0.23 MB mask in the no-copy mode. Full paired results are in [measurements-o06-o08-factorial.json](docs/measurements-o06-o08-factorial.json). It remains opt-in; other-adapter fallback, broader pass redesign and DX12/target-hardware gates remain open.

  RG16 format-selection logic now has adapter-independent tests for usage/feature gating and the RGBA16F fallback. This does not replace physical fallback rendering or Windows/DX12 acceptance.

  Runtime inventory also counts the tile debug uniform and optional timestamp staging buffers; opaque QuerySet allocation remains excluded.

## Later scaling research

- [ ] Execute the remaining O01–O08 correctness, sustained-motion,
  optical-combination, dynamic shadow-scaling, operation-counter and
  cross-adapter gates in
  [O01-O08_FOLLOWUP_PLAN.md](docs/O01-O08_FOLLOWUP_PLAN.md) before promoting
  opt-in approximations or expanding the emitter cap.

  O01 operation counters now cover world, volume and optical paths with
  byte-identical fixed-tick captures; M1 Max/Metal results are in
  [measurements-o01-shading-counters.json](docs/measurements-o01-shading-counters.json).
  Sparse counters also cover a full moving-caster camera route in
  [measurements-o01-shading-counter-route.json](docs/measurements-o01-shading-counter-route.json).
  Native-window, additional optical-motion and other-adapter checks remain open.

- [x] Simulation-driven surface heat cue — implemented and reviewed at fixed ticks across four named cameras. Readability is projection-dependent and the measured GPU-render increase is small; keep it opt-in, with authored-scene promotion gated on O08 and broader visual/DX12 acceptance. Evidence: [measurements-heat-cue.json](docs/measurements-heat-cue.json).
- [x] Bind emitters to their thermal/fire profile and primary point light by stable IDs; legacy scenes retain positional light binding. Multi-fire stress tests and per-emitter simulation/render ownership remain open.
- [ ] Implement the bounded two-emitter runtime described in [MULTI_EMITTER_PLAN.md](docs/MULTI_EMITTER_PLAN.md); do not expand scene validation before per-source simulation/render support exists.
- [x] Evaluate active-region smoke simulation against O01 stage data. Current M1 Max/Metal measurements put smoke compute at 0.0205–0.0206 ms median versus 2.42–3.25 ms render stages, so there is no timing case for an active-region prototype; re-evaluate if compute cost or workload changes.

Keep selected pixel density and simulation state independent of camera detail.
Do not mark visual review, Windows rendering or target-hardware gates complete
from a source change or compilation result.
