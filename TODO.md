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
- [x] [O07: stable object bounds, culling, shared meshes, instancing and live transforms](docs/OPTIMIZATION_PLAN.md#o07--object-bounds-culling-and-shared-meshes) — per-camera/light culling, shared geometry and validated live object transforms measured; image, draw, vertex, memory, CPU and transform evidence is in [measurements-o07-culling.json](docs/measurements-o07-culling.json).
- [x] [O03: bounded single-emitter tile lists with overflow fallback](docs/OPTIMIZATION_PLAN.md#o03--tile-lists-for-effects-and-local-lights) — byte-identical perspective, orthographic, close-smoke and glass captures; three paired route workloads and GPU diagnostics in [measurements-o03.json](docs/measurements-o03.json). Metal only; multi-emitter and DX12 gates remain open.
- [x] O02: per-face invalidation using O07 live transform revisions and affected-object bounds, with full-map fallback for uncertain state; M1 Max protocol/capture evidence is in [measurements-o02.json](docs/measurements-o02.json). Windows/DX12 acceptance remains open.

## Then: measure and review quality/cost tradeoffs

- [x] [O04: projected-pixel detail](docs/OPTIMIZATION_PLAN.md#o04--detail-based-on-projected-pixel-contribution) — opt-in fire-segment LOD, exact-state parity checks, three projected-size capture pairs, threshold-crossing route and paired M1 Max timings recorded in [measurements-o04.json](docs/measurements-o04.json). Default promotion, sustained orbit/temporal review and non-Metal acceptance remain open.
- [x] [O05: cached smoke absorption](docs/OPTIMIZATION_PLAN.md#o05--reuse-smoke-transmittance-and-illumination-work) — opt-in primary fire-light cache prototype with 8³/16³ still and paired timing evidence in [measurements-o05.json](docs/measurements-o05.json). Promotion, motion, invalidation stress and cross-backend gates remain open.
- [x] [O06: specialised optical resolve](docs/OPTIMIZATION_PLAN.md#o06--specialise-optical-materials-and-avoid-repeated-shading) — opt-in opaque-reflector base-light reuse with direct transmissive fallback; matched stills and short paired route timings in [measurements-o06.json](docs/measurements-o06.json). Long-route, native-window and cross-backend gates remain open.
- [ ] O08: individually measured resource/pass-layout improvements — camera-visible lazy optical allocation saves 3.69 MB until optical geometry is visible at 640×360; normal/depth now samples directly, saving another 1.84 MB on optical scenes and 7.37 MB of modeled optical-pass traffic per frame. Adapter-gated RG16 targets save 2.10 MB total with replay and image parity on M1 Max/Metal. Three short and three longer route pairs found no GPU timing gain. The opt-in Rg11b10Ufloat HDR target saves 1.84 MB on optical scenes; three alternating 120-second route pairs found a consistent but very small GPU timing difference, four fixed-camera temporal samples and eight moving-route poses looked similar. The format remains opt-in; fallback testing, its remaining snapshot-copy cost, broader pass redesign and DX12/target-hardware gates remain open.

## Later scaling research

- [ ] Extend explicit emitter/thermal/light ownership before multi-fire stress tests.
- [ ] Consider active-region smoke simulation only if compute measurements justify it.

Keep selected pixel density and simulation state independent of camera detail.
Do not mark visual review, Windows rendering or target-hardware gates complete
from a source change or compilation result.
