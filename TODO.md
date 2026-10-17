# Engine work queue

The optimization queue tracks implementation separately from platform and visual
acceptance. O01 profiling, O08's inventory, O02 whole-map reuse, O03 single-emitter
tile lists and O07's bounds, shared meshes, instancing and culling are implemented with
M1 Max/Metal evidence.
Detailed steps, dependencies and acceptance criteria live in
[the optimisation plans](docs/OPTIMIZATION_PLAN.md). This is the execution index;
[STATUS.md](docs/STATUS.md) records runtime evidence and outstanding release gates.

## First: establish evidence

- [x] [O01: complete-frame and per-stage profiling](docs/OPTIMIZATION_PLAN.md#o01--measure-each-stage-and-the-complete-frame) — instrumentation, paired reports for all three workloads, profiling-overhead controls, and a native-window route are recorded in [measurements-o01.json](docs/measurements-o01.json). Exact queue latency and non-Metal adapter support remain explicit platform limitations.
- [x] [O08: resource/bandwidth inventory](docs/OPTIMIZATION_PLAN.md#o08--reduce-memory-traffic-and-unnecessary-gpu-work) — allocation, lifetime, upload, copy and logical attachment traffic inventory plus an adapter-gated Rg16Float effect-target trial are recorded in [measurements-o08.json](docs/measurements-o08.json); broader backend acceptance remains open.

## Then: preserve the image while avoiding work

- [x] [O02: whole-map shadow caching](docs/OPTIMIZATION_PLAN.md#o02--cache-static-shadow-maps) — full sun map and point-light cube reuse with conservative invalidation; M1 Max paired results and gates are in [measurements-o02.json](docs/measurements-o02.json).
- [x] [O07: stable object bounds, culling, shared meshes and instancing](docs/OPTIMIZATION_PLAN.md#o07--object-bounds-culling-and-shared-meshes) — per-camera/light culling and shared geometry measured; image, draw, vertex, memory and CPU evidence is in [measurements-o07-culling.json](docs/measurements-o07-culling.json).
- [x] [O03: bounded single-emitter tile lists with overflow fallback](docs/OPTIMIZATION_PLAN.md#o03--tile-lists-for-effects-and-local-lights) — byte-identical perspective, orthographic, close-smoke and glass captures; three paired route workloads and GPU diagnostics in [measurements-o03.json](docs/measurements-o03.json). Metal only; multi-emitter and DX12 gates remain open.
- [ ] O02: per-face invalidation after O07 live transforms and affected-object tracking exist.

## Then: measure and review quality/cost tradeoffs

- [x] [O04: projected-pixel detail](docs/OPTIMIZATION_PLAN.md#o04--detail-based-on-projected-pixel-contribution) — opt-in fire-segment LOD, exact-state parity checks, three projected-size capture pairs, threshold-crossing route and paired M1 Max timings recorded in [measurements-o04.json](docs/measurements-o04.json). Default promotion, sustained orbit/temporal review and non-Metal acceptance remain open.
- [x] [O05: cached smoke absorption](docs/OPTIMIZATION_PLAN.md#o05--reuse-smoke-transmittance-and-illumination-work) — opt-in primary fire-light cache prototype with 8³/16³ still and paired timing evidence in [measurements-o05.json](docs/measurements-o05.json). Promotion, motion, invalidation stress and cross-backend gates remain open.
- [x] [O06: specialised optical resolve](docs/OPTIMIZATION_PLAN.md#o06--specialise-optical-materials-and-avoid-repeated-shading) — opt-in opaque-reflector base-light reuse with direct transmissive fallback; matched stills and short paired route timings in [measurements-o06.json](docs/measurements-o06.json). Long-route, native-window and cross-backend gates remain open.
- [ ] O08: individually measured resource/pass-layout improvements — lazy optical snapshots save 3.69 MB in diffuse 640×360 scenes, the adapter-gated effect target saves 921,600 bytes, and two-channel smoke volumes save 1,179,648 bytes with reset/replay checks and pixel-identical M1 Max/Metal captures. Pass-copy redesign, timing impact and DX12/target-hardware gates remain open.

## Later scaling research

- [ ] Extend explicit emitter/thermal/light ownership before multi-fire stress tests.
- [ ] Consider active-region smoke simulation only if compute measurements justify it.

Keep selected pixel density and simulation state independent of camera detail.
Do not mark visual review, Windows rendering or target-hardware gates complete
from a source change or compilation result.
