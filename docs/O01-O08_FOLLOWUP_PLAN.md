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

1. Extend review beyond a zoom threshold route to a 120-second orbit with repeated
   threshold crossings, close smoke, branching flames and bright small embers.
2. Capture both sides of each hysteresis boundary and replay with the same camera
   history. Verify simulation state, particle births, heat and derived lights are
   unchanged by the detail toggle.
3. Report tier occupancy and retained primitives beside GPU stage and whole-frame
   timing. Review silhouette, flicker, silhouette crawl, flame attachment and lost
   glow against the full-detail baseline.
4. Keep the feature opt-in unless its quality/cost tradeoff is useful across more
   than the original single-fire sizes and passes portability checks.

**Exit gate:** repeatable transition behavior, acceptable motion review and a
measured useful range. Otherwise retain as a lab-only experiment or remove the
unsupported promotion claim; do not conflate fewer primitives with a frame win.

### 4. O05 smoke absorption cache

1. Make the disabled path avoid cache allocation and cache work. Verify direct
   sampling remains the selected fallback when the experiment is off or invalid.
2. Compare direct sampling with 8³ and 16³ cache modes over small, medium and
   screen-filling smoke. Separate cache construction/update, lookup and direct
   sampling time; include memory and invalidation costs in total work.
3. Test cache refresh choices tied to fixed simulation updates against rebuilding
   each render. This is a hypothesis to measure, not a behavior to assume.
4. Exercise density changes, primary-light motion/range, live flicker, moving ember
   lights, pause/resume, reset, shader reload and rapid edits. Compare temporal image
   error as well as fixed-tick stills, focusing on lit rims, soot folds and contacts.

**Exit gate:** a workload range where total frame cost improves and motion quality
passes. If cache maintenance remains more expensive than direct samples, leave it
off and close the experiment with that result.

### 5. O06 opaque lighting reuse

1. Run at least three alternating 120-second Material Atelier routes plus a mixed
   smoke/fire/material route; include reflective and transmissive surfaces in front
   of and behind atmosphere.
2. Compare direct and reused opaque lighting; retain direct transmissive evaluation.
   Review camera-inside/near-plane and live material edits as correctness cases.
3. Report resolve, full GPU render, CPU frame work and image error separately. Add
   native-window and other-adapter results before considering promotion.

**Exit gate:** sustained total-render gain larger than run variance, acceptable
images in reflection/transmission stress views and no stale live-edit output.

## Wave 3 — Measure optical and memory changes as a combined design

### 6. O06 × O08 factorial comparison

Run a controlled matrix on the same scene, route, adapter and build:

| Lighting path | Optical path |
|---|---|
| Direct lighting | Snapshot/copy baseline |
| Reused opaque lighting | Snapshot/copy baseline |
| Direct lighting | No-copy overlay |
| Reused opaque lighting | No-copy overlay |

Repeat for default HDR and compact HDR where supported. Keep transmissive shading
on the direct path. Report known allocation, modeled logical traffic, measured GPU
stages, whole-frame work and image differences separately. Add high-dynamic-range
fire/smoke cases to probe compact-HDR error, not only existing material stills.

**Exit gate:** select a combination only when it improves a declared target (memory,
traffic or runtime) without violating image/temporal tolerances. Logical byte savings
alone do not establish physical bandwidth or speedup. Preserve fallbacks for missing
format support and shader/pipeline creation failure.

### 7. O08 individual candidate decisions

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
