# O01–O08 follow-up execution plan

17 October 2026. This plan closes the largest correctness, visual and portability
gaps found in the O01–O08 review, then tests the next scaling steps. It is a plan,
not evidence that any open gate has passed. Keep the selected pixel grid fixed and
preserve a selectable baseline for every candidate.

## Shared evidence rules

- Use the existing deterministic scene, seed, named camera, fixed tick, resolution,
  code/shader/asset hashes and route. Include clearing, heavy single-plume/eight-light
  and Material Atelier workloads where relevant.
- For timing decisions, use at least three alternating baseline/candidate pairs,
  ten seconds of warm-up and 120-second moving routes. Report per-run medians and
  p95s, whole-frame work, CPU work, GPU stages, allocations and candidate counts.
  Include cache/build/fallback work; keep overlapping GPU intervals separate.
- Capture matched stills and motion samples for approximate techniques. Inspect
  close, distant, perspective, orthographic, smoke/optical overlap and threshold
  transitions. Keep image correctness, visual acceptance and performance acceptance
  as separate results.
- Record native-window and offscreen results separately. Run on M1 Max/Metal first,
  then Windows/DX12 and at least one other adapter. Record unsupported timestamps,
  format fallbacks, memory limitations and target hardware explicitly.
- Do not reduce the pixel grid to recover performance. Change effect quality only
  through an explicit, measurable control with the baseline available.

## Wave 1 — Close correctness and workload coverage on proven paths

### 1. O03 natural overflow and tile-size study

**Question:** Do bounded 16×16 lists remain correct and worthwhile under actual
crowding, and does another tile size improve the total cost?

1. Add deterministic stress scenes that concentrate maximum fire primitives,
   smoke lobes, authored lights and derived lights in a small screen region. Include
   camera-inside, near-plane, orthographic, moving-effect and paused-edit cases.
2. Cause real per-category tile overflow. Compare tiled output with exhaustive
   output at the same fixed tick; record overflowing tiles, affected categories,
   fallback invocations and the cost of exhaustive fallback. Keep the forced-overflow
   diagnostic as a separate test of the fallback branch.
3. Compare current 16×16 tiles with 8×8 tiles at the existing 640×360 grid. Record
   list-build CPU/GPU time, bytes, occupancy distributions, overflow frequency,
   shading time and full-frame cost. Do not select a tile size based on shading time
   alone.
4. Repeat the winning candidate and baseline on DX12 and another adapter. Keep the
   exhaustive option and existing ordering until image parity and fallback behavior
   pass on each backend.

**Exit gate:** no dropped effects or lights; exact same-backend capture parity,
including natural overflow; stable membership after camera/state edits; and a net
whole-frame benefit on representative workloads. If no alternative size beats the
current setting, retain 16×16 and document the measured operating envelope.

### 2. O02 moving-caster and invalidation routes

**Question:** Does per-face caching retain correctness and avoid excess redraw work
when casters actually move or change shadow participation?

1. Add a fixed-seed route with continuous caster movement across point-light face
   boundaries and the sun frustum, plus edits to a shadow-participating material.
2. Compare cached rendering against forced redraw throughout the route. Capture
   boundary crossings and reset, shader reload, light transform, light range and
   paused-edit events. Report dirty faces/reasons, redraw maps, CPU/GPU shadow time
   and residency.
3. Include unknown/missing-bound fallback. Verify that it redraws conservatively
   rather than trusting an incomplete revision key.

**Exit gate:** captures match forced redraw at all checkpoints, every relevant edit
invalidates the required maps, and stable segments show cache reuse. Report the
continuous-invalidation cost even if caching is not beneficial during motion.

## Wave 2 — Decide the opt-in approximations using sustained motion

### 3. O04 projected fire detail

1. **Complete on M1 Max/Metal:** add a 120-second orbit with repeated threshold
   crossings, branching flames and ember lights; report tier occupancy, retained
   primitives, GPU stages and whole-frame timing.
2. **Complete at deterministic checkpoints:** capture both sides of both
   hysteresis bands using the same camera/tick history. Counts, bounds, lighting
   and particle event identities match with LOD off/on. The capture API does not
   expose the heat field; code inspection confirms segment reduction occurs after
   full deterministic `FireFrame` sampling.
3. **Partial visual review:** matched PNG checkpoints were inspected. A continuous
   motion review for flicker, silhouette crawl, attachment and lost glow remains
   open; checkpoint stills cannot settle those temporal questions.
4. Keep the feature opt-in until a continuous visual review passes, the useful
   range is confirmed across additional fire profiles/sizes, and portability
   checks pass.

**Remaining exit gate:** repeatable transitions and a measured small M1 Max/Metal
win are now documented. Continuous motion review, broader fire/profile coverage,
native-window timing, and Windows/DX12 or other GPU qualification remain open.
Fewer primitives alone are not a frame-win claim.

### 4. O05 smoke absorption cache

1. **Complete:** the disabled path now allocates no absorption field and does no
   cache build or cache timing work. It reuses an existing smoke volume only as an
   unused binding fallback; direct density sampling remains selected. Off/on/off
   GPU captures report 0/4096/0 cache bytes and identical images at the same tick
   before and after the enabled interval.
2. **Complete on M1 Max/Metal:** compare direct sampling with 8³ and 16³ cache
   modes over small, medium and screen-filling smoke. Three paired 120-second
   routes per tier separate the atmosphere/fire stage from cache build, total
   GPU render and CPU build time; image error, memory and fire-state parity are
   recorded in [measurements-o05-size-study.json](measurements-o05-size-study.json).
   Total GPU render medians were slower for all six cache comparisons, so no
   useful total-cost range has been established. This result does not qualify
   other GPUs or native-window rendering.
3. Test cache refresh choices tied to fixed simulation updates against rebuilding
   each render. This is a hypothesis to measure, not a behavior to assume.
4. **Partially complete:** for both cache sizes, compare direct/cached captures
   through paused density edits, rapid edits, linked primary-light motion/range,
   flicker, paused captures, four moving-ember checkpoints, shader reload and reset.
   Fire state matches at all 13 checkpoints per size; see
   [measurements-o05-invalidation.json](measurements-o05-invalidation.json).
   Remaining: continuous temporal image error and wall-clock pause/resume checks,
   plus a longer human motion review of lit rims, soot folds and contacts.

**Exit gate:** a workload range where total frame cost improves and motion quality
passes. If cache maintenance remains more expensive than direct samples, leave it
off and close the experiment with that result.

### 5. O06 opaque lighting reuse

1. **Complete on M1 Max/Metal:** three alternating 120-second Material Atelier
   pairs plus three pairs on a mixed smoke/fire/material orbit include reflective
   and transmissive surfaces in front of and behind atmosphere.
2. **Partially complete:** direct and reused opaque lighting retain direct
   transmissive evaluation. A paused chrome roughness edit and a near-glass camera
   were reviewed; camera-inside and true near-plane stress remain open.
3. **Complete offscreen:** report optical resolve, full GPU render, CPU frame work
   and image error separately. All six pairs show lower total GPU render time on
   this host; native-window and other-adapter results are still required before
   promotion. See [measurements-o06-sustained.json](measurements-o06-sustained.json).

**Exit gate:** sustained total-render gain larger than run variance, acceptable
images in reflection/transmission stress views and no stale live-edit output.

## Wave 3 — Measure optical and memory changes as a combined design

### 6. O06 × O08 factorial comparison

**Complete on M1 Max/Metal:** run the full matrix on one high-dynamic mixed
fire/smoke/reflector/glass scene and orbit. Each of the seven non-baseline
variants has three alternating 120-second pairs against direct lighting,
RGBA16F, snapshot/copy. The adapter supports packed HDR. Results, captures and
resource inventory are in [measurements-o06-o08-factorial.json](measurements-o06-o08-factorial.json).

| Lighting path | Optical path |
|---|---|
| Direct lighting | Snapshot/copy baseline |
| Reused opaque lighting | Snapshot/copy baseline |
| Direct lighting | No-copy overlay |
| Reused opaque lighting | No-copy overlay |

Repeat for default HDR and compact HDR where supported. Keep transmissive shading
on the direct path. Report known allocation, modeled logical traffic, measured GPU
stages, whole-frame work and image differences separately. Add high-dynamic-range
fire/smoke captures probe compact-HDR error alongside the timing route. No-copy
produced byte-identical fixed-tick output to copy for both HDR formats. Compact
HDR lowered known allocation by 1.84 MB; packed-HDR no-copy adds a 0.23 MB mask.
In this high-output scene, compact-HDR mean RGB error was 0.21–0.72/255 per
camera/channel, with a 28/255 maximum. The contact sheet remained visually close,
but temporal error and additional workloads remain open.

**Exit gate:** select a combination only when it improves a declared target (memory,
traffic or runtime) without violating image/temporal tolerances. Logical byte savings
alone do not establish physical bandwidth or speedup. Preserve fallbacks for missing
format support and shader/pipeline creation failure.

### 7. O08 individual candidate decisions

**Complete on M1 Max/Metal:** independent dispositions for lazy optical allocation,
normal/depth reuse, Rg16Float targets, compact HDR and no-copy overlay are recorded
in [DECISIONS_O08.md](DECISIONS_O08.md). The memory-saving implemented paths are
retained with capability gates; compact HDR and no-copy remain independent,
disabled-by-default experiments. Platform, continuous-temporal and broader-pass
acceptance stays open as summarized in that record.

Break the umbrella O08 item into decisions for lazy optical allocation, RG16 targets,
compact HDR, normal/depth reuse and no-copy overlay. For each, record supported
adapters, fallback behavior, memory delta, temporal and route image evidence, GPU
timings and decision (promote, keep experimental, or reject). Include query-set and
driver-allocation limitations in the inventory; do not present known allocation as
physical device residency.

**Exit gate:** every candidate has an independent disposition and verification
scope. The O08 umbrella stays open while any promoted/default candidate lacks the
required physical fallback or target-backend validation.

## Wave 4 — Scale scene structure and identify the next GPU bottleneck

### 8. O07 scene-scale study

**Complete on M1 Max/Metal for the measured static-shadow route:** deterministic
clearing-derived tiers at 276, 552, 1,104 and 2,208 objects were compared using
baked, instancing-only and culling+instancing paths. All 12 direct/adjacent
comparisons used three alternating 120-second pairs, ten seconds of warm-up,
seed 42 and 640×360. The direct baked-to-culled+instanced paired median GPU/frame
work deltas were −0.009/−0.031, −0.066/−0.116, −0.135/−0.053 and
−0.151/−0.025 ms by tier. At 2,208 objects, CPU culling reached 0.739 ms median
while camera-visible objects fell from 2,208 to 868 and draw batches from 2,208
to 377. Gains are small and not monotonic; keep the existing path, but do not
prototype indirect drawing or occlusion culling from these results. Full per-run
medians, p95s, GPU stages, visibility, allocations, provenance and captures are in
[measurements-o07-scale-study.json](measurements-o07-scale-study.json).

The route kept casters and lights static so shadow maps remained cached; steady
shadow-map GPU timing is therefore unavailable in those paired runs. A moving
caster route is still required to measure shadow-submission scaling. Native-window
and non-Metal adapter validation also remain open.

1. Generate deterministic scenes at increasing object counts and mesh reuse rates,
   starting from the current 276-object clearing scene and increasing by measured
   steps. Include offscreen casters, mixed materials and shared versus unique meshes.
2. Compare baked reference, instancing-only and culling+instancing. Report CPU
   culling/encoding/upload time, batches, vertices, geometry bytes, GPU geometry
   time and full-frame work.
3. Only prototype indirect drawing or occlusion culling if larger workloads show
   geometry submission is a material bottleneck. Preserve offscreen shadow casters
   and conservative behavior for unknown bounds.

**Exit gate:** scaling data identifies a workload threshold and bottleneck. Add a
more complex submission path only when it beats the measured simpler path and has
an exhaustive fallback.

### 9. Profile atmosphere/fire shading before solver work

**Partial: measured on M1 Max/Metal.** The evidence synthesis in
[measurements-o01-shading-attribution.json](measurements-o01-shading-attribution.json)
combines O01 stage timings with O03 tile memberships, O04 retained fire primitives,
O05 absorption-cache changes and O06 optical-resolve changes. O01's heavy scene
measures 3.130 ms atmosphere/fire and 0.0205 ms smoke compute; the O05 cache lowers
atmosphere/fire by 0.058–0.101 ms but increases total GPU-render time by 0.025–0.044
ms. This rules out active-region solver work as the next step. O03/O04/O06 probes
show sensitivity to candidate work, retained primitives and optical reuse, but do
not isolate exact per-pixel operation costs.

Still open: GPU counters for primitive intersection tests, smoke-lobe tests,
executed density/absorption samples, shadow comparisons and optical ray samples.
The current report preserves these as explicit measurement gaps; it does not claim
that their individual costs have been measured.

Use O01 stage data to split the multi-millisecond atmosphere/fire work by candidate
category and representative coverage. O01 shows smoke advection near 0.02 ms on the
measured M1 Max scene, so do not pursue active-region solver work without new data.
Instrument and compare primitive tests, smoke-lobe tests, density/absorption samples,
shadow lookups and optical interactions. Use O03 lists and O04 detail as independent
switches to identify which operations dominate. Keep fixed pixel density and capture
matched close, distant and crowded views.

**Exit gate:** name a measured dominant operation and its scaling variable before
proposing a shader or algorithm rewrite. Any follow-up must include its per-stage
cost, full-frame cost, quality evidence and fallback.

## Wave 5 — Bounded multi-emitter implementation

After the single-emitter tile, cache, optical and adapter gates above are recorded,
implement the existing [bounded two-emitter plan](MULTI_EMITTER_PLAN.md). Start with
two stable-ID sources and separate deterministic FireFrames/smoke fields; preserve
single-emitter byte identity and array-order-independent results. Add scenes with
separated and overlapping fires, shared tiles, maximum primitive/light budgets,
shadow overlap, reset/replay and offscreen simulation. Measure each source and
aggregate occupancy, memory, CPU work, GPU stages and fallback rates.

**Exit gate:** all source ownership, deterministic replay, overflow, reset/edit and
resource-recreation checks pass on Metal; then run the same evidence on DX12 and
another adapter before raising the source cap. Keep the cap at two until correctness,
memory and performance budgets pass.

## Program completion record

Maintain per-candidate states for implementation, automated correctness, visual
review, performance decision and target-adapter verification. Update
[STATUS.md](STATUS.md), [TODO.md](../TODO.md) and the measurement JSON as each gate
finishes. A compile or a passing unit test does not close visual or hardware gates.
