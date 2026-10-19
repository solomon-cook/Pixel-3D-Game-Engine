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
4. A three-pair 120-second 16×16 tiled-versus-exhaustive stress orbit is now
   recorded in [measurements-o03-stress-route.json](measurements-o03-stress-route.json).
   Fire overflow affected 1.95% of tile-frame samples, but full-frame work was
   effectively unchanged and GPU render was 1.42 ms slower with tiling. This is
   not a stress-route speedup. Repeat the 8×8 candidate under the same sustained
   protocol and capture motion checkpoints before deciding the tile size.
5. The 8×8 versus 16×16 study now has three alternating 120-second pairs and
   same-tick byte-identical capture evidence in
   [measurements-o03-tile-size-sustained.json](measurements-o03-tile-size-sustained.json).
   8×8 lowers fire overflow from 1.95% to 1.36%, but adds 1.37 MB, increases
   candidate memberships about 3.07×, and improves median frame work by only
   0.037 ms, with p95 not consistently better. Keep 16×16 as the default; the
   measured difference does not justify the extra storage.
6. Repeat the candidate and baseline on DX12 and another adapter. Keep the
   exhaustive option and existing ordering until image parity and fallback
   behavior pass on each backend.

7. **Complete for current validated budgets on M1 Max/Metal:** the refreshed
   two-emitter stress report records each category's capacity, candidate
   memberships, maximum occupancy and overflow count. At tick 300, fire tiles
   overflow naturally; smoke and both light categories do not, because each
   category's maximum accepted candidate count is at or below its tile-list
   capacity. Forced overflow reaches all four fallback paths, and all tiled,
   exhaustive, source-isolation and reversed-order images match exactly. Natural
   smoke/light overflow is therefore unreachable without raising validated
   runtime budgets; do not treat forced fallback as evidence of such an input.
   See [maximum-budget report](measurements-multi-emitter-overflow.json) and
   [study runner](../scripts/two_emitter_overflow_study.py). DX12 and other
   adapter validation remain open.

   The fail-closed study runner now generates separate camera-inside-plume and
   near-plane-intersection scene variants without changing the benchmark scene.
   Both added M1 Max/Metal fixed-tick views match exhaustive output byte-for-byte;
   the camera-inside view naturally overflows the fire list in all 920 tiles and
   exercises exhaustive fallback. These deliberately close, poorly composed
   images are correctness probes, not visual-quality evidence. See the added
   `projection_stress_scenes` and `projection_stress_matrix` fields in the
   maximum-budget report.

   The same runner now uses one paused serve session to compare tiled and
   exhaustive output after fixed steps to ticks 120 and 300, then after changing
   the campfire intensity at tick 300 without advancing simulation. All three
   tiled/exhaustive pairs match in pixels, tick and fire counts; the tick-120 and
   tick-300 images differ, and the paused edit changes the tick-300 image. Fire
   overflow is reached in 74–75 tiles in these states. This closes the planned
   moving-effect and paused-edit correctness probes on M1 Max/Metal, not
   continuous playback or visual acceptance. Results are in
   `live_state_matrix` in [the report](measurements-multi-emitter-overflow.json).

The native-window gate now has three alternating 120-second tiled/exhaustive
pairs after ten-second warm-ups on M1 Max/Metal. Tiling lowers the median GPU
atmosphere/fire stage by 1.187–1.216 ms per pair, while native FPS and full-frame
CPU deltas are small and mixed. This is a stage-level saving, not a whole-window
frame-win claim. Keep the 16×16 tile size and exhaustive overflow path. See
[native tile-list evidence](measurements-o03-native-tile-lists.json) and the
reproducible [native study runner](../scripts/tile_lists_native_study.py).

A separate maximum-budget two-emitter native study now completes three
alternating 120-second tiled/exhaustive pairs on `two-emitter-overflow-stress.json`
using the `dual-wide` clearing orbit. Every run reports both emitters and GPU
timestamp coverage. Exhaustive-minus-tiled paired median deltas are -0.231 FPS,
+0.018 ms CPU native frame work and +0.393 ms atmosphere/fire GPU time. GPU
stage savings repeat across pairs, while FPS and CPU results vary in sign; this
does not establish a whole-window win. Fixed-tick native image parity remains
covered separately. See [multi-emitter native report](measurements-multi-emitter-tile-native.json)
and [runner](../scripts/two_emitter_tile_native_study.py).

**Exit gate:** no dropped effects or lights; exact same-backend capture parity,
including natural overflow; stable membership after camera/state edits; and a net
whole-frame benefit on representative workloads. If no alternative size beats the
current setting, retain 16×16 and document the measured operating envelope. The
current stress route finds no whole-frame tiling benefit. The sustained 8×8
comparison finds no worthwhile total-frame gain; cross-backend evidence remains
open.

The camera-inside probe now also has sustained fallback-cost evidence. A generated
constant-camera `camera-inside-hold` route keeps natural fire fallback at 100% of
tile-frame samples across three alternating 120-second M1 Max/Metal pairs. Fixed-
tick tiled and exhaustive output matches exactly. Exhaustive-minus-tiled paired
medians are −0.327 ms frame work and −1.339 ms GPU render; GPU render favors
exhaustive evaluation in all three pairs. Tile-list build costs 1.27–1.39 ms per
frame, while atmosphere/fire deltas are mixed. This isolates the cost of an
adversarial all-overflow view and does not justify a global mode change. See
[the report](measurements-o03-camera-inside-overflow.json) and
[reproducible runner](../scripts/tile_overflow_camera_route_study.py).

**Smoke-bound materialization follow-up (18 October 2026):** a GPU compute pass
now builds deterministic smoke-lobe bounds once per dirty rendered state and
shares them between tile construction and ink-smoke shading. The direct shared
WGSL path remains the selectable default; `render.experiments.smoke_candidate_cache`
enables the cached variant. Same-tick two-emitter captures match byte-for-byte.
Three alternating 120-second pairs on two-emitter and heavy single-plume routes
found small/mixed GPU-stage changes, about +0.04 ms CPU tile-list encoding, and
whole-frame median regressions of +0.062 and +0.090 ms in the implementation-
revision comparison. Keep the experiment
disabled by default; do not claim a frame win. Cross-adapter and native playback
remain open. See [the report](measurements-o03-smoke-candidates.json).

The 19 October current-build recheck adds live Session toggle and invalidation
coverage. Separate direct and cached serve sessions received the same fixed
ticks, emitter and linked-light edits, successful shader reload, and reset/replay;
all seven matched captures had identical fire state and pixels. A separate
same-state Session toggle also matched direct/cached/direct output. This confirms
sampled correctness after the tested dirty events on M1 Max/Metal, not continuous
visual acceptance or cross-platform behavior. The 2,304-byte resource inventory
is a reserved allocation. New frame counters report six dirty-state dispatch
encodes and clean enabled skips; the same-state toggle check encodes one
dispatch only while enabled. These counters confirm scheduling, not GPU
completion time or performance benefit. Keep the cache opt-in because sustained
whole-frame results remain mixed/regressive. See
[current-build check](measurements-o03-smoke-candidate-invalidation-recheck.json)
and [runner](../scripts/smoke_candidate_invalidation_study.py).

A same-source release-profile rebenchmark now isolates the experiment toggle in
both two-emitter and heavy-plume scenes. Each used three alternating 120-second
pairs after 10-second warm-ups, with all 7,200 timed frames covered and no late
or skipped GPU samples. The two-emitter paired medians were −0.016 ms frame
work, −0.046 ms GPU render and +0.040 ms CPU tile-list encoding. Heavy-plume
medians were −0.398 ms frame work and −0.070 ms GPU render, with +0.012 ms CPU
tile-list encoding; one GPU-render pair was slower. These current-build results
are smaller or mixed by stage, and remain one-device offscreen evidence. Keep
the cache opt-in pending native review, broader adapters, and owner playback.
See [current sustained report](measurements-o03-smoke-candidate-sustained-current-build.json).

**Projected fire-bound reuse candidate (18 October 2026):** a separate opt-in GPU
pass now computes all 512 conservative fire bounds once per frame, replacing the
eight view-projection transforms repeated for every fire-primitive/tile pair. The
direct per-tile projection remains the default. The fixed-tick matrix covers all
named cameras in clearing, profiling-heavy, Material Atelier and the two-emitter
stress scene, including generated near-plane and camera-inside views: 21 pairs
match pixels, memberships, overflow counts and occupancy exactly. Three
alternating 120-second pairs per workload have complete 7,200-frame GPU timestamp
coverage. Paired median GPU-render improvements are 0.629/0.619/0.292/0.763 ms;
tile-build improvements are 0.308/0.310/0.145/0.626 ms. Full frame-work improves
in every workload's paired median, but Material Atelier p95 rises 0.179 ms and CPU
tile-list encoding rises slightly in three workloads. Natural fire fallback
remains 100% in the camera-inside route; the precomputed path preserves its exact
fallback behavior. A separate three-pair native clearing-orbit study on M1
Max/Metal lowers the atmosphere/fire stage median by 0.291–0.328 ms (paired
median 0.319 ms) and native-frame CPU median by 0.056 ms. FPS varies by pair
(−0.029 to +0.205; paired median +0.202), so no reliable whole-window gain is
established. Native-window measurement is complete for this host; owner visual
review and Windows/DX12 or other-adapter validation remain open. Keep the
candidate selectable and disabled by default. See the
[offscreen report](measurements-o03-fire-projected-bounds.json),
[native report](measurements-o03-fire-projected-bounds-native.json), and
[runners](../scripts/fire_bounds_precompute_study.py) and
[native study runner](../scripts/fire_bounds_native_study.py).

**19 October current-build recheck:** the direct and precomputed paths were
compared at 21 fixed-tick camera views across the same four workload families.
All images, tile memberships, overflow counts and occupancy match; natural fire
fallback remains 100% in the camera-inside workload. Three alternating pairs of
two-second routes completed with full 120-frame timing coverage and no skipped or
late samples, but these short windows are only a protocol check, not sustained
performance evidence. A paused Session API off/on capture also matches pixels
and tile metrics exactly. Keep the existing 120-second reports as the performance
evidence. See [current-build recheck](measurements-o03-fire-projected-bounds-recheck.json).

### 2. O02 moving-caster and invalidation routes

**Question:** Does per-face caching retain correctness and avoid excess redraw work
when casters actually move or change shadow participation?

1. Add a fixed-seed route with continuous caster movement across point-light face
   boundaries and the sun frustum, plus edits to a shadow-participating material.
2. Compare cached rendering against forced redraw throughout the route. Capture
   boundary crossings and reset, shader reload, light transform, light range and
   paused-edit events. Report dirty faces/reasons, redraw maps, CPU/GPU shadow time
   and residency. **Complete for discrete image checkpoints:** six paused poses
   keep the moving log visible in a wide orthographic view; each cached capture
   matches forced redraw byte-for-byte and redraws the same three-map old/new face
   union. See [measurements-o02-visible-caster.json](measurements-o02-visible-caster.json).
   The same six image pairs also match through the native `run --agent-stdio`
   window; exact dirty masks come from the headless paired captures because the
   live window may render between separate edit and capture requests. See
   [measurements-o02-visible-caster-native.json](measurements-o02-visible-caster-native.json).
3. **Complete in synthetic unit coverage:** missing bounds among otherwise known
   old/new caster bounds and invalid shadow frusta force all seven maps dirty.
   The live diagnostic reason now reports `unknown_caster_bounds` or
   `unknown_shadow_material_bounds` when conservative fallback is used. Validated
   scene assets currently cannot produce unknown mesh bounds, so this fallback
   cannot be induced through the live scene protocol; keep that limit visible.

**Exit gate:** discrete captures match forced redraw at all checkpoints, every
relevant edit invalidates the required maps, and stable segments show cache reuse.
These gates are now recorded on M1 Max/Metal, including offscreen and native
moving-image checkpoints. Continuous-invalidation cost is recorded separately.
Native-window stage and whole-window timing are now characterized for a continuous
moving caster; selective invalidation lowers the shadow stage but did not improve
measured whole-window throughput in this route. Windows/DX12 and other-adapter
acceptance remain open. See
[native shadow-cache comparison](measurements-o02-native-shadow-cache.json).

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
3. **Partial visual review:** deterministic 20 fps, 400-frame campfire orbit and
   12 fps quiet/bonfire profile pairs cross both hysteresis bands. Sampled
   threshold contact sheets were inspected; changes remain localized to the
   flame, with no obvious silhouette detachment or lost glow in the samples.
   A side-by-side in-app browser playback spot review of the baseline and LOD
   campfire GIFs also found no obvious silhouette break or fire/smoke separation
   across the viewed frames. This is not a full-duration human playback review;
   flicker and silhouette-crawl acceptance remain open.
   A paired frame-delta analysis now measures the absolute temporal-change-image
   error within ±2 samples of every LOD transition. Mean RGB MAE is
   0.0047/0.0073/0.0048 per 255 for campfire/quiet/bonfire; nearest-rank p95 is
   0.0118/0.0123/0.0121. This quantifies sampled transition differences but does
   not establish continuous playback acceptance at 20/12 fps. The runner also
   verifies full fire geometry, ember and particle-light count parity at every
   sampled frame and checks the observed tier transitions against the source
   motion report. See
   [transition report](measurements-o04-transition-temporal.json) and
   [runner](../scripts/projected_detail_temporal_transition_study.py).
4. **Complete on M1 Max/Metal:** add three alternating 120-second offscreen
   pairs each for campfire, quiet and bonfire. Paired GPU-render medians fell by
   0.113/0.124/0.052 ms. Frame-work was flat for campfire (-0.006 ms median,
   with mixed pairs), lower for quiet (-0.826 ms), and slightly higher for
   bonfire (+0.014 ms). Retained primitive medians changed 81→70, 55→40 and
   166→165. Keep LOD opt-in; the benefit depends on projected profile size.
   Full reports and run hashes are in
   [measurements-o04-sustained-profiles.json](measurements-o04-sustained-profiles.json).
5. **Native-window measurement complete on M1 Max/Metal:** three alternating
   120-second campfire orbit pairs show a paired median −0.057 ms atmosphere/fire
   GPU-stage delta and effectively flat native FPS (−0.001). Median retained
   primitives move 81→70 and rendered segments 6→4; projected-detail CPU cost
   rises by 0.00008 ms. This is not a whole-window performance win. The runner
   records tier occupancy, projected size, CPU cost, GPU stages and native frame
   metrics in [measurements-o04-native.json](measurements-o04-native.json).
   Keep the feature opt-in until continuous visual review and portability checks
   pass.

**Remaining exit gate:** repeatable transitions and a measured small M1 Max/Metal
win are documented. Quiet and bonfire profiles now cross their applicable bands;
per-frame full primitive, ember and particle-light counts match the baseline.
Sustained profile-specific timing is recorded on M1 Max/Metal. Continuous
playback review and Windows/DX12 or other GPU qualification remain open. Native
timing is measured, but fewer primitives and a small stage-level change are not a
whole-window frame-win claim. See
[measurements-o04-motion-review.json](measurements-o04-motion-review.json),
[transition temporal report](measurements-o04-transition-temporal.json) and
[measurements-o04-sustained-profiles.json](measurements-o04-sustained-profiles.json),
[native report](measurements-o04-native.json) and
[native runner](../scripts/projected_detail_native_study.py).

**19 October 2026 current-build recheck:** `scripts/projected_detail_orbit_study.py`
was rerun against `target/debug/engine-lab` on the M1 Max/Metal at the fixed
640×360 grid. All 14 camera checkpoints preserved fire-state parity. Candidate
images matched baseline hashes at full-detail checkpoints; they differed at
reduced-detail checkpoints only when the removed geometry affected visible
pixels. Those frames changed 18–105 pixels per 640×360 image, within x=302–336,
y=169–195 around the fire. The other reduced-detail checkpoints were also
pixel-identical because removed geometry was occluded from the camera. This is
a discrete current-build check, not continuous playback
acceptance or a new performance measurement. The tracked checkpoint and image
diff summary is in
[measurements-o04-current-build-recheck.json](measurements-o04-current-build-recheck.json);
raw captures remain under ignored `artifacts/o04/goal-recheck/slow-orbit/`.

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
3. **Complete on M1 Max/Metal:** refresh the cache after simulation updates,
   successful scene edits, reset, shader reload and re-enable; skip rebuilds for
   repeated renders with unchanged inputs. A paused serve study confirms identical
   repeated images, build counts at each dirty event, and zero residency when
   disabled. This saves redundant paused-state work; a moving scene still rebuilds
   after each fixed simulation step and no moving-route speedup is claimed. See
   [measurements-o05-refresh-policy.json](measurements-o05-refresh-policy.json).
4. **Partially complete:** for both cache sizes, compare direct/cached captures
   through paused density edits, rapid edits, linked primary-light motion/range,
   flicker, paused captures, four moving-ember checkpoints, shader reload and reset.
   Fire state matches at all 13 checkpoints per size; see
   [measurements-o05-invalidation.json](measurements-o05-invalidation.json).
   The 16³ cache now has a matched 400-frame 20 fps temporal comparison at the
   medium-smoke scale, including frame and temporal-change-magnitude RGB error.
   A native `run --agent-stdio` check confirms direct and 16³ captures stay
   bit-identical while paused for two wall-clock seconds. During the two-second
   resume, they advanced 121 and 120 ticks under host scheduling, then were
   stepped to tick 540 and matched fire state exactly. The full
   movie still needs human playback review. The matched 8³ temporal route now
   covers the same 400 ticks at medium smoke: mean frame RGB MAE is 0.285/255,
   p95 0.426/255, maximum channel difference 39/255, and mean temporal-change
   magnitude error 0.183/255; exact tick and effect-count parity holds. This is
   larger error than 16³ and has no total-cost benefit claim. Other-adapter
   acceptance and longer resume-duration evidence remained open. An extended
   native 10-second pause/resume check now finds direct and 16³ runs remain at
   tick 300 with identical paused images; they advanced 600 and 601 ticks during
   the wall-clock resume and were aligned at tick 1020 with matching fire state.
   At the aligned tick, 12,451/230,400 pixels differ; per-channel mean absolute
   errors are 0.092/0.052/0.049 and channel maxima 17/11/12. This is the cache's
   expected approximation error, not stale state; the cache remains off by
   default because its measured total-render cost did not improve. Human playback
   review and other-adapter acceptance remain open. See
   [16³ temporal](measurements-o05-temporal.json),
   [8³ temporal](measurements-o05-temporal-cache8.json) and
   [two-second pause/resume](measurements-o05-pause-resume.json) plus
   [extended pause/resume](measurements-o05-pause-resume-extended.json).

**19 October current-build recheck:** both cache sizes again preserve fire state
at all 13 edit, light, ember-motion, shader-reload and reset checkpoints. The
disabled path reports zero cache bytes; enabled 8³ and 16³ paths report 4,096
and 32,768 bytes. Across checkpoints the mean per-channel RGB errors are
0.320/0.182/0.149 for 8³ and 0.097/0.056/0.049 for 16³; maximum per-channel
errors are 21/17/12 and 18/10/12, respectively. This is discrete, headless
freshness/approximation evidence, not performance or continuous-playback
acceptance. See
[current-build report](measurements-o05-invalidation-current-build.json).

**Exit gate — closed as a non-promoted experiment (18 October 2026):** the tested
8³/16³ single-emitter workloads and the sustained two-emitter route show no
whole-render benefit over direct sampling. Keep the cache selectable for research
but disabled by default. Its fixed-tick, invalidation, replay and temporal image
behavior are characterized on M1 Max/Metal; human continuous-playback review and
other-adapter validation remain acceptance gates for any future promotion, not
prerequisites for closing this negative performance decision. Reopen only with a
new workload or backend measurement that demonstrates a total-cost opportunity.

### 5. O06 opaque lighting reuse

1. **Complete on M1 Max/Metal:** three alternating 120-second Material Atelier
   pairs plus three pairs on a mixed smoke/fire/material orbit include reflective
   and transmissive surfaces in front of and behind atmosphere.
2. **Partially complete:** direct and reused opaque lighting retain direct
   transmissive evaluation. A paused chrome roughness edit and near-glass camera
   were reviewed. The transmissive pass now handles the visible exit interface
   when the camera is inside glass, using the normal/view orientation and inverse
   refraction ratio, with reflection fallback under total internal reflection.
   Direct and reuse captures match exactly in one inside-glass and one near-plane
   camera stress case. Continuous camera motion and other-adapter behavior remain
   open; see [measurements-o06-camera-stress.json](measurements-o06-camera-stress.json).
3. **Complete offscreen:** report optical resolve, full GPU render, CPU frame work
   and image error separately. All six pairs show lower total GPU render time on
   this host. **Native-window measurement and same-session image check complete
   on M1 Max/Metal:** three alternating 120-second mixed-route pairs were measured
   after adding a depth-match fallback. It reduces same-session behind-view image
   differences from 17 to 13 pixels, but maximum channel error remains 83/29/4.
   On this guarded version, median optical-resolve time is 0.024 ms slower and
   median paired FPS delta is -0.117 fps. Same-session direct captures repeat
   exactly; mixed-close and glass-near match direct/reuse. Native whole-window
   gain is not established. Other-adapter, continuous visual and broader optical
   camera acceptance remain open. See
   [measurements-o06-native-reuse.json](measurements-o06-native-reuse.json) and
   [measurements-o06-sustained.json](measurements-o06-sustained.json).
   A fixed-tick offscreen tolerance sweep across mixed-from-behind, mixed-close
   and glass-near views reduced behind-view changed pixels from 12 to 4 as the
   guard tightened, while maximum channel error stayed 52/255. The other two
   views remained exact. A foreground-alpha gate from 0.001 to 0.25 changed none
   of the image comparisons. No timing was measured, so keep the current guard
   and investigate snapshot precision; see
   [measurements-o06-depth-guard.json](measurements-o06-depth-guard.json) and
   [the sweep runner](../scripts/optical_depth_guard_study.py).
   A follow-up HDR snapshot-color guard at thresholds 0.001, 0.01 and 0.05
   reduced behind-view changed pixels from 12 to 8 at the strongest threshold,
   but the 52/255 maximum channel error remained. The other two views stayed
   exact, and no timing or continuous-image acceptance was measured. This guard
   does not resolve the outlier and is not adopted; keep the measured depth guard
   unchanged. See [snapshot-color report](measurements-o06-snapshot-color-guard.json)
   and [reproducible runner](../scripts/optical_snapshot_color_guard_study.py).
   **Moving-route reconstruction issue resolved on M1 Max/Metal:** the guarded
   direct fallback previously shaded with the un-oriented normal, unlike the
   baseline camera-facing interface path. Matching exact depth and using that
   same oriented fallback removes the prior 188/255 spike. Across the 240-frame
   O06×O08 matrix, all variants preserve effect counts; RGBA16F reuse differs by
   one channel level on one pixel, while compact-HDR reuse has the same measured
   error as direct compact HDR (0.337/255 frame mean, 0.421/255 temporal-change
   mean). Looser depth tolerance restores an 87/255 outlier; alpha, radiance and
   normal-alignment gates do not improve the exact-depth result. See
   [factorial temporal report](measurements-o06-o08-factorial-temporal.json),
   [guard report](measurements-o06-temporal-depth-guard.json), and runners
   [factorial](../scripts/optical_factorial_temporal_study.py) and
   [guard](../scripts/optical_reuse_temporal_guard_study.py).

   A follow-up three-pair 120-second offscreen timing comparison using exact
   depth shows median GPU-render +0.027 ms and optical-resolve +0.023 ms; the
   median serial frame-work delta is -0.024 ms with mixed pair results. This
   does not establish a whole-GPU-render benefit, so leave reuse opt-in and
   disabled by default. Full paired data are in
   [measurements-o06-exact-depth-sustained.json](measurements-o06-exact-depth-sustained.json).
   A refreshed three-pair native-window run shows a median +0.043 FPS and
   +0.0043 ms optical-resolve delta; same-session direct/reuse captures match
   pixel-for-pixel at three fixed-tick cameras. This is not a material whole-render
   gain. See [native report](measurements-o06-native-exact-depth.json).

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
but combined temporal error and additional workloads remain open. A quantified
temporal sample now compares direct RGBA16F copy with direct compact-HDR copy over 240
frames at 20 fps on the same high-dynamic mixed route. Mean per-frame RGB error
is 0.342/255 (p95 frame mean 0.373/255, maximum channel error 29/255); mean
temporal-change-magnitude error is 0.418/255 (p95 frame mean 0.455/255, maximum
channel error 29/255). A matched 240-frame orbit covers all eight lighting,
copy and HDR combinations. Each variant preserves effect counts. The oriented
direct fallback and exact-depth reuse guard remove the former sparse 188/255
reuse outlier; RGBA16F reuse has only one 1/255 changed pixel, and compact HDR
reuse matches the direct compact-HDR aggregate error. Compact HDR with direct
lighting has 0.337/255 mean frame error and 0.421/255 temporal-change error on
this route. Human playback review and fallback/DX12 validation remain open. Three alternating
120-second native-window pairs now cover the high-dynamic mixed route. Candidate
minus baseline FPS deltas were +1.512/-0.769/+0.151 fps (median +0.151); native
CPU-frame median delta was -0.306 ms and GPU-stage deltas were small and mixed.
This does not establish a whole-window performance gain. See
[native compact-HDR evidence](measurements-o08-compact-hdr-native.json).
Additional 120-frame, 20 fps comparisons now cover
clearing, the heavy plume/eight-light workload, and Material Atelier. Mean frame
errors are 0.341/0.384/0.372 per 255; mean temporal-change-magnitude errors are
0.190/0.212/0.043 per 255, with maximum channel errors of 31/27/10. A sampled
three-workload contact sheet looked close, but does not establish continuous
human acceptance. These results show route-dependent error and do not establish a
perceptual threshold. See
[compact-HDR temporal evidence](measurements-o08-compact-hdr-temporal.json) and
the [reproducible capture/analysis runner](../scripts/compact_hdr_temporal_study.py).
Additional workload evidence and its runner are in
[measurements-o08-compact-hdr-workloads.json](measurements-o08-compact-hdr-workloads.json)
and [compact_hdr_workload_study.py](../scripts/compact_hdr_workload_study.py).

**19 October current-build factorial recheck:** all eight direct/reuse, copy/no-
copy and HDR variants again preserve effect counts across 240 frames at 20 fps.
Direct/copy and direct/no-copy images match byte-for-byte for both formats.
Reuse differs from matched direct output by one 1/255 channel value on one pixel
in RGBA16F and by three such pixels across three frames in compact HDR. Compact
HDR frame and temporal error remain around 0.337/0.421 per 255 with a 38/255
maximum channel difference. This is a headless temporal check, not performance
or full human playback acceptance. The contact sheet and hashes are preserved in
[the current-build report](measurements-o06-o08-factorial-current-build-recheck.json).

**Exit gate:** select a combination only when it improves a declared target (memory,
traffic or runtime) without violating image/temporal tolerances. Logical byte savings
alone do not establish physical bandwidth or speedup. Preserve fallbacks for missing
format support and shader/pipeline creation failure.

### 7. O08 individual candidate decisions

**Complete on M1 Max/Metal:** independent dispositions for lazy optical allocation,
normal/depth reuse, Rg16Float targets, compact HDR, no-copy overlay and dirty
fixed-step uploads are recorded in [DECISIONS_O08.md](DECISIONS_O08.md). The memory-saving implemented paths are
retained with capability gates; compact HDR and no-copy remain independent,
disabled-by-default experiments. No-copy now also has three alternating native
120-second pairs on the mixed optical route. Optical-resolve deltas are mixed
(-0.014, +0.023, -0.043 ms), as are whole-window FPS deltas (-0.155, +0.306,
+0.293); this does not establish a reliable frame-time gain. See
[measurements-o08-native-no-copy.json](measurements-o08-native-no-copy.json).
Platform, continuous-temporal and broader-pass acceptance stays open as
summarized in that record.

The dirty render-Globals upload now has three alternating native 120-second
pairs on both clearing and profiling-heavy routes on M1 Max/Metal. Each uses
ten-second warm-ups and >99% render and smoke-compute timestamp coverage measured
against actual fixed ticks. The profiling-heavy route removes about 1.38 Globals
writes and 1,173 upload bytes per rendered frame; optimized-minus-legacy paired
median FPS is -0.070, CPU-frame +0.001 ms, CPU-upload +0.004 ms and
atmosphere/fire GPU -0.014 ms; CPU simulation-encode median delta is +0.014 ms.
Material Atelier has median deltas of +0.069 FPS, +0.011 ms CPU-frame,
-0.017 ms CPU-upload, -0.014 ms CPU simulation-encode and -0.007 ms
atmosphere/fire GPU. Two-emitter medians are +0.044 FPS, -0.019 ms CPU-frame,
-0.004 ms CPU-upload, +0.008 ms CPU simulation-encode and -0.004 ms
atmosphere/fire GPU. Pair signs vary across the workload matrix;
together the routes support a traffic reduction without a whole-window speedup
claim. Windows/DX12 and other-adapter checks remain open. See
[clearing report](measurements-o08-globals-upload-native.json),
[profiling-heavy report](measurements-o08-globals-upload-native-profiling-heavy.json),
[Material Atelier report](measurements-o08-globals-upload-native-materials.json),
[two-emitter report](measurements-o08-globals-upload-native-two-emitter.json),
and [runner](../scripts/globals_upload_native_study.py).

**Lazy snapshot native lifecycle complete on M1 Max/Metal:** a paused shared
Session edits an optical material while the camera faces away, then captures
away/visible/away/visible. Snapshot residency stays at zero until nine optical
batches become camera-visible, rises by exactly 1,843,200 bytes once, and remains
resident without further allocation after turning away and returning. Optical
resolve timestamps are absent in the away views and present in the visible views;
residency stays fixed across seven visible views, including inside-glass and
near-plane stress cameras. All eight paused native captures and same-adapter
headless references match byte-for-byte. DX12 and other-adapter resource lifecycle
remain open. See
[native report](measurements-o08-lazy-optical-native.json) and
[runner](../scripts/lazy_optical_native_study.py).

The RG16 fallback now has a diagnostic `--force-rg16-fallback` path that exercises
RGBA16F effect-target and smoke-volume creation/rendering on a capable adapter.
Two fixed-tick M1 Max/Metal scenes and all 120 sampled frames across a moving
fire-camera route match the native RG16 images byte-for-byte. A native-window
fallback capture also matches its headless counterpart exactly. The fallback
uses 2,101,248 more known bytes at 640×360. This strengthens local fallback
evidence but leaves physical unsupported-adapter and DX12 acceptance open. See
[offscreen report](measurements-o08-rg16-fallback.json),
[current-build recheck](measurements-o08-rg16-fallback-current-build.json),
[native report](measurements-o08-rg16-native-fallback.json), the
[offscreen runner](../scripts/rg16_fallback_study.py) and
[native runner](../scripts/verify_native_rg16_fallback.py).

**Fixed-step submission batching, native timing measured on three routes:**
corrected three-pair 120-second M1 Max/Metal studies confirm 54.2–55.5% fewer
simulation submissions. Clearing, Material Atelier and profiling-heavy median
batched-minus-serial FPS deltas are +0.233/+0.301/+0.212; CPU frame-work deltas
are -0.151/-0.121/-0.094 ms. GPU stages shift slightly in mixed directions.
Fixed-tick image parity is recorded separately in
`measurements-o08-batch-parity.json`. These results do not establish DX12 or other-
adapter acceptance. See [clearing](measurements-o08-batch-native.json),
[Material Atelier](measurements-o08-batch-native-materials.json),
[profiling-heavy](measurements-o08-batch-native-profiling-heavy.json) reports and
[runner](../scripts/simulation_batch_native_study.py).

These corrected studies replace earlier native results: the native loop used to
call `Session.step(1)` per tick and never invoked the batching path. It now groups
all fixed ticks accumulated for a rendered frame and still applies caster motion
at each tick. The serial mode remains the reference path.

**Dirty upload follow-up (18 October 2026):** the render `Globals` uniform is
not consumed by `smoke.wgsl`; fixed-step inputs are read from the per-source
group-1 configuration buffer. `update_globals` now returns after the simulation
config write instead of queuing an unused render-uniform write. Tick-120 output
matches byte-for-byte, and three alternating 120-second clearing-orbit pairs
measure one fewer 848-byte write per simulation tick. CPU-upload spans improve
consistently, but whole-frame and GPU-render deltas are small and mixed. Treat
this as a verified traffic reduction without a throughput claim. See
[the report](measurements-o08-globals-upload.json).

The next O08 pass-layout probe moved the smoke shader's resources to group 0 and
removed render `Globals` from the advection pipeline layout. This coordinated
change is required because the explicit prior pipeline layout demanded a group-0
bind even though the shader did not declare group-0 resources. Fixed-tick
clearing and two-emitter captures match exactly. Four native M1 Max/Metal
three-pair studies cover clearing, profiling-heavy, Material Atelier and
two-emitter routes, with >99% render and smoke-compute timestamp coverage. The
coverage denominator is the number of actual fixed ticks. Median FPS deltas are
+0.049/+0.097/+0.011/-0.033; CPU-frame deltas +0.028/-0.066/-0.068/+0.041 ms;
simulation-encode deltas -0.032/-0.061/-0.030/+0.014 ms; and atmosphere/fire GPU
deltas -0.0014/+0.0218/+0.0064/-0.0025 ms, respectively. Results are mixed and
the two-emitter route regresses slightly on FPS. Keep the conclusion to fewer
encoded bind commands, without a general throughput claim. More native routes,
playback review, DX12 and other-adapter gates remain open. See
[the offscreen report](measurements-o08-smoke-bind-layout.json), the four
[native reports](measurements-o08-smoke-bind-layout-native.json),
[profiling-heavy](measurements-o08-smoke-bind-layout-native-profiling-heavy.json),
[materials](measurements-o08-smoke-bind-layout-native-materials.json),
[two-emitter](measurements-o08-smoke-bind-layout-native-two-emitter.json) and
[native runner](../scripts/smoke_bind_layout_native_study.py).

Break the umbrella O08 item into decisions for lazy optical allocation, RG16 targets,
compact HDR, normal/depth reuse and no-copy overlay. For each, record supported
adapters, fallback behavior, memory delta, temporal and route image evidence, GPU
timings and decision (promote, keep experimental, or reject). Include query-set and
driver-allocation limitations in the inventory; do not present known allocation as
physical device residency.

**Exit gate:** every candidate has an independent disposition and verification
scope. The O08 umbrella stays open while any promoted/default candidate lacks the
required physical fallback or target-backend validation. Forced fallback on the
M1 Max validates resource/pipeline creation and fixed-tick output; it does not
substitute for an adapter that lacks RG16 capabilities.

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

The static route kept casters and lights still, so shadow-map GPU timing was not
available after cache warm-up. The moving-caster route is now **complete offscreen
on M1 Max/Metal**: all four tiers and all three path comparisons used three
alternating 120-second pairs, ten seconds of warm-up, seed 42 and 640×360. The
`rock-0` caster follows the same deterministic 5-unit, 20-second orbit in both
variants. Each of the 72 runs records 7,200 caster-change invalidations, 7,200
frames with shadow redraw, and the same 15,840 shadow-pass redraws. The baked
reference initially failed because its transform-updated vertex buffer lacked
`COPY_DST`; that usage is fixed, GPU verification passed, and a 300-frame baked
moving-caster route completed.

The scene-scale runner accepts `--moving-caster <scene-object-id>` and uses
separate report and benchmark directories to preserve static baseline evidence.
Full sustained results, per-run shadow cache counters, timing, scene hashes and
comparison provenance are in
[measurements-o07-moving-caster.json](measurements-o07-moving-caster.json).

With culling enabled versus instancing-only, paired median frame-work / GPU-render
deltas were −0.025/−0.048 ms at 276 objects, −0.361/−0.172 ms at 552,
−0.804/−0.550 ms at 1,104, and +0.202/−0.096 ms at 2,208. The paired GPU
shadow-map stage fell by 0.022, 0.102, 0.215 and 0.309 ms respectively. Relative
to baked rendering, culling+instancing changed frame work by approximately 0,
−0.144, −0.483 and +0.193 ms, and GPU render by +0.001, −0.076, −0.356 and
−0.255 ms. Thus culling saves shadow-stage work as scene size grows, but the
whole-frame result is not monotonic and turns slower at 2,208 objects. Keep the
current path; these data do not justify indirect drawing or occlusion culling.
Native-window measurement is complete on this Mac. Owner continuous-playback
review and non-Metal acceptance remain open; fixed-tick moving-caster visual
evidence is recorded below.

`benchmark-native` now exposes the same culling, instancing and moving-caster
controls and records per-frame caster positions and shadow-cache changes alongside
presentation timings. A native Metal smoke route verifies the baked path and orbit
at a fixed five-unit radius. The full native four-tier matrix is now complete:
three comparisons per tier, each with three alternating 120-second pairs after
ten-second warm-up (72 runs). Native results are mixed. At 2,208 objects,
culling+instancing versus instancing-only lowered the paired median GPU shadow
stage by 0.448 ms and native CPU-frame work by 0.475 ms, while median FPS fell by
4.199. Other tiers likewise do not show a consistent whole-window win. Keep the
current path; this evidence does not justify a more complex submission path.
Full metrics and per-run summaries are in
[measurements-o07-native-scale-study.json](measurements-o07-native-scale-study.json);
raw resumable outputs remain under ignored `artifacts/o07/`. Native-window
measurement is complete on this Mac. The fixed-tick moving-caster visual route
now covers 120 matched frames at 20 fps-equivalent sampling across baked,
instancing-only and culling+instancing paths. The two instanced modes are
pixel-identical for all frames; versus baked, instancing changes a median of 3
pixels (maximum 13), and culling adds no further differences. Five sampled
checkpoints were inspected; owner review of continuous playback and non-Metal
acceptance remain open. See
[continuous-motion report](measurements-o07-continuous-motion.json), its
[contact sheet](../artifacts/o07-continuous-motion-review-20261018/contact-sheet.png)
and the extended [motion capture runner](../scripts/capture_motion.py).

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

**Counter implementation: instrumented paths complete on M1 Max/Metal.**
`engine-lab capture --shading-counters` executes companion instrumented draws for
world, volumetric and optical passes and serializes fire primitive, smoke
lobe/bubble, density/absorption, light-candidate, shadow, reflection and
transmission counts. Earlier selected baseline, diagnostic and optical no-copy
captures produced byte-identical pixels at matched fixed ticks. The ordinary
renderer produces the image first; companion draws use lazily allocated scratch
color targets while reading the normal scene depth. At 640×360, diagnostics add
4,608,000 known bytes on the default RGBA16F path, released when the mode is
disabled. Compact HDR no-copy adds one 230,400-byte scratch mask plane within its
format-specific allocation. Expanded coverage now
confirms byte identity across 12 profile/view pairs. Captures are recorded in
[measurements-o01-shading-counters.json](measurements-o01-shading-counters.json).
Atomic counter captures are diagnostic only; their timings are not comparable.
Sparse start/mid/end samples now cover a full 120-second camera orbit with a
moving caster; the separate report is
[measurements-o01-shading-counter-route.json](measurements-o01-shading-counter-route.json).
Native-window checks and other-adapter validation remain open.

**Native Session control added (18 October 2026):** `set_shading_diagnostics` now toggles the companion-counter path through the shared Session API and native inspector, which displays the latest fire, smoke, lighting, shadow and optical counts. A paused native-window study captures disabled/diagnostic/disabled at tick 120: all 22 counter fields are present and nonzero where expected, scratch targets allocate 4,608,000 bytes only while enabled, and all three images are pixel-identical. The fixed-tick native access and image-preservation gate now passes on M1 Max/Metal; continuous playback, performance, and other-adapter checks remain open. See [native counter report](measurements-o01-shading-counter-native.json) and [runner](../scripts/shading_counter_native_study.py).

**Expanded profile/view sample (18 October 2026):** fixed-tick counter captures
now cover campfire, quiet and bonfire profiles at hero, smoke-close, fire-study
and orthographic cameras on M1 Max/Metal. Operation counts range from 26,374 to
2,309,781 fire-primitive candidates and 25,106 to 451,096 smoke-density samples
across these views. Scratch-target companion passes restore byte-identical output
in all 12 normal/counter pairs. Fixed-tick Material Atelier camera coverage now
includes hero, metal-close, glass-close, subsurface-close and orthographic views,
plus a compact-HDR optical-no-copy glass case; all six pairs match exactly and
report optical interactions. See
[optical coverage report](measurements-o01-optical-counter-coverage.json) and its
[runner](../scripts/shading_counter_optical_coverage.py). The optical camera-motion
counter route is also complete on M1 Max/Metal: three sparse
samples from a 120-second `materials.json` `material-orbit` report 211,446–311,506
optical surface interactions and 8,839–21,180 successful transmission
interactions. A separate uninstrumented run of the identical scene hash, route,
seed and duration measured a 2.076 ms median optical-resolve stage and 2.828 ms
median GPU render. Counter-run timings remain disabled and unusable. Counter-hook
injection now checks each WGSL pattern's exact occurrence count, including the
explicit two-source cases, and fails on missing or unexpected duplicates. This
prevents shader edits from silently changing which operations are counted.
Continuous playback, native-window and other-adapter coverage remain open. See
[profile/view counter evidence](measurements-o01-counter-profile-scope.json) and
its [capture runner](../scripts/shading_counter_profile_study.py), plus the
[optical route report](measurements-o01-optical-counter-route.json) and
[reproducible runner](../scripts/shading_counter_optical_route.py).

**Atmosphere path attribution (18 October 2026):** the companion counter set now
also reports total volume fragments and partitions them into the soft-volume and
inked-smoke paths. The expanded runner captures both scene styles, all three fire
profiles and all four cameras. All 24 normal/diagnostic pairs are byte-identical;
the path partition equals 230,400 fragments in every 640×360 capture. The runner
now fails on an incomplete matrix, changed image or invalid path partition. At the
bonfire/fire-study checkpoint, inked smoke records 451,096 density samples and
372,216 direct-absorption samples, while the soft-volume style records 181,010,226
and 115,967,532 respectively. These counts expose workload scale, not elapsed
cost. A matched uninstrumented 120-second `clearing-orbit` timing study now has
three alternating pairs for soft-volume on M1 Max/Metal. Median atmosphere/fire
stage-of-run medians are 12.919 ms baseline and 13.055 ms candidate; paired
deltas are −0.336/−0.156/+0.136 ms. Whole GPU-render paired deltas are
−0.324/−0.152/+0.179 ms, and frame-work deltas are −0.413/−0.192/+0.331 ms.
Run-to-run variation changes the sign, so no speedup or shader rewrite is
supported. See [path report](measurements-o01-counter-paths.json), the
[soft-volume timing report](measurements-o01-soft-volume-route.json), and the
[reproducible timing runner](../scripts/soft_volume_route_study.py), plus the
updated [counter runner](../scripts/shading_counter_profile_study.py).

An additional O03 isolation run used the same soft-volume route and three
alternating 120-second pairs, with tile lists enabled as baseline and exhaustive
evaluation as candidate. Exhaustive-minus-tiled paired medians were +2.610 ms
frame work, +2.202 ms GPU render, +2.570 ms atmosphere/fire and −0.327 ms
tile-list build time. Fixed tick 120, seed 42 and 640×360 output matched
pixel-for-pixel. This supports tile lists for this soft-volume workload on M1
Max/Metal. It does not establish native-window or other-adapter performance. See
[the comparison report](measurements-o01-soft-volume-tile-lists.json); the
runner now exposes `--candidate-disable-tile-lists` and captures parity.

Use O01 stage data to split the multi-millisecond atmosphere/fire work by candidate
category and representative coverage. O01 shows smoke advection near 0.02 ms on the
measured M1 Max scene, so do not pursue active-region solver work without new data.
Use the counters on the optical motion route. Pair them with uninstrumented stage timings; counter counts alone do
not measure per-operation cost. Use O03 lists and O04 detail as independent switches
to identify which operations dominate. Keep fixed pixel density and capture matched
views.

**Exit gate:** path-specific operation counts and representative fixed-tick image
parity are now recorded. Name a measured dominant operation and its scaling
variable before proposing a shader or algorithm rewrite. Soft-volume style has
uninstrumented sustained timing, but paired variation is larger than a stable
whole-frame or atmosphere/fire benefit. Any future rewrite needs operation-level
cost evidence, quality review and a selectable fallback.

## Wave 5 — Bounded multi-emitter implementation

After the single-emitter tile, cache, optical and adapter gates above are recorded,
implement the existing [bounded two-emitter plan](MULTI_EMITTER_PLAN.md). Start with
two stable-ID sources and separate deterministic FireFrames/smoke fields; preserve
single-emitter byte identity and array-order-independent results. Add scenes with
separated and overlapping fires, shared tiles, maximum primitive/light budgets,
shadow overlap, reset/replay and offscreen simulation. Measure each source and
aggregate occupancy, memory, CPU work, GPU stages and fallback rates.

The first renderer ABI step is complete: storage now has two fixed-layout
`FireFrame` slots, existing code uploads slot zero, and a matched Metal capture is
byte-identical to the prior ABI. Tile construction and fire shading can consume
both slots, but the live renderer still populates only slot zero; the source-zero
capture remains byte-identical. The fire storage also carries one source origin
per slot, so the flame detail mask can anchor slot one independently while
retaining the legacy source-zero uniform. Each frame slot now also stores
source-specific flame palette, shape, breakup, pixel treatment and activity.
The renderer populates both slots in stable-ID order; the CPU packing helper
prepares both source frames and settings, and merges sampled particle
lights into the shared twelve-light budget. Tests cover reorder invariance,
legacy sampler parity and selected-light/drop accounting. The live renderer now
populates both slots in a fixed-tick dual-source Metal review. Smoke compute has
source-local ping-pong volumes, uniforms and per-source dispatches in stable-ID
order. The soft atmosphere/optical integral now binds a second source volume and
samples its independent domain; a fixed-tick source-zero capture remains
byte-identical. Scene validation accepts two emitters, and the review exercises
the dual-source render path. Inked smoke, a source-local absorption-cache
channel, the opaque-material heat cue's second temperature field, post heat and
source-specific primary-light shadows are implemented. Fixed-tick cache/heat A/B,
maximum-budget parity and forced fallback pass. Three alternating 120-second
offscreen pairs show 0.715 ms lower median serial frame-work for tiled rendering,
but the reported GPU-render metric is 1.922 ms higher. Tile-build rises 2.468 ms
and atmosphere/fire falls 0.495 ms; GPU intervals may overlap, so keep this result
workload-specific. Direct-versus-cache temporal samples now cover both 8³ and
16³ source-local caches in the fixed dual-wide view; continuous playback,
performance benefit, native-window and other-adapter review remain open. Per-source
primary-light, sun, caster, material, shader-reload and reset invalidation now
match forced redraw at fixed tick; see
[shadow invalidation evidence](measurements-multi-emitter-shadow-invalidation.json)
and [heat evidence](measurements-multi-emitter-heat.json).
Source-local inked smoke is implemented with 36 puff candidates per source,
separate overflow fallback and a 72-entry total tile capacity. GPU validation and
single-source parity pass on M1 Max/Metal; the expanded tile index buffer uses
603,520 bytes at 640×360. The dual-source capture matrix exercises source
isolation and combined rendering; maximum-budget correctness and one sustained
performance route are recorded. A native-window fixed-tick session study now
matches tiled and exhaustive output across all six named cameras, source-isolated
scenes, and reversed emitter order. Other-scene scaling, temporal playback,
native sustained performance and cross-adapter gates remain open; see
[inked smoke evidence](measurements-multi-emitter-ink.json).
The second-source cache stores optical depth in the green channel of the existing
3D cache texture, over the emitter's source-local domain. It adds no cache
allocation and preserves the source-zero hero capture hash. A fixed-tick dual-
source cache-on/off/on study now covers four cameras at tick 120. The 8³ cache
allocates 4,096 bytes; disabling releases it and restores the exact direct PNG.
The approximate-cache image error is measured and inspected, but no sustained
performance or temporal-quality decision is claimed. See
[absorption evidence](measurements-multi-emitter-absorption.json) and
[dual-source cache evidence](measurements-multi-emitter-absorption-cache.json).
The cache also has a matched 120-frame, 20 fps fixed-camera temporal comparison
across both emitters. At seed 42 and 640×360, direct and 8³-cache variants have
identical effect counts at every frame. Mean RGB error is 0.026/255 (p95
0.032/255), mean temporal-change-magnitude error is 0.020/255, and maximum
channel difference is 21/255. A second comparison now covers the full 120-second
`clearing-orbit` on the maximum-budget two-emitter scene, split into deterministic
segments. At 20 fps, the 8³ comparison covers 2,400 frames; at 15 fps, the 16³
comparison covers 1,800 frames. Direct and cached images and temporal deltas are
byte-identical in both runs, with matching camera poses, cache mode, modeled
residency and effect counts throughout. Both contact sheets were inspected. See
[16³ moving-route report](measurements-multi-emitter-absorption-moving-route-cache16.json).
A separate native-window session toggles direct/cache/direct at six route keyframes; repeated direct images are deterministic,
cache mode/residency are correct, and every native pair matches pixel-for-pixel.
These captures do not establish continuous native playback or a timing win. Three
alternating 120-second native pairs show +0.263 median FPS, +0.083 ms CPU native
frame work, and -0.092 ms atmosphere/fire GPU time; surface-acquisition variance
keeps this from establishing a robust whole-window win. Offscreen total-render
measurements also remain slower with caching. See [native sustained report](measurements-multi-emitter-absorption-native-sustained.json)
and [runner](../scripts/two_emitter_absorption_native_sustained_study.py), plus
[native capture report](measurements-multi-emitter-absorption-native.json)
and [runner](../scripts/two_emitter_absorption_native_study.py), plus [moving-route
report](measurements-multi-emitter-absorption-moving-route.json) and [runner](../scripts/two_emitter_absorption_moving_route_study.py). See
[8³ temporal report](measurements-multi-emitter-absorption-temporal.json),
[16³ temporal report](measurements-multi-emitter-absorption-temporal-cache16.json)
and [reproducible runner](../scripts/two_emitter_absorption_temporal_study.py).
Three alternating 120-second pairs per cache size now measure the two-emitter
route. Median candidate-minus-direct GPU-render deltas are +0.061/+0.081 ms for
8³/16³, with paired frame-work deltas of +0.027/+0.019 ms; this route shows no
total-render benefit. Cache build GPU medians are 0.034/0.044 ms and CPU medians
are 0.045/0.048 ms per frame, with 4,096/32,768 resident bytes. See
[sustained report](measurements-multi-emitter-absorption-sustained.json) and
[runner](../scripts/two_emitter_absorption_sustained_study.py). Keep the cache
opt-in; playback, native-window and cross-adapter review remain open.
Opaque `heat_response` materials now sample the second emitter's local
temperature volume as well. The source-zero Metal capture is byte-identical and
the verifier passes. A source-one-only, 120-second heat-off/on `dual-wide` route
samples 2,400 frames at 20 fps with matching ticks, poses, fire counts and light
counts. Mean full-frame A/B MAE is 0.0084/255 (88 changed pixels on average); the
wide-view cue is sparse. Temporal-change difference MAE is 0.00087/255. The
wide-route contact sheet was inspected; mean A/B difference there is 0.0084/255.
A second 120-second route orbits the watchfire with the ground in view. Across
2,400 frames, mean A/B MAE is 0.7705/255 (9,331 changed pixels on average), and
temporal-change difference MAE is 0.0435/255. The inspected contact sheet shows
the heat ring at each of five sampled checkpoints. A native-window fixed-tick A/B
now repeats those five focused poses at tick 300 in one paused session; heat-on
changes 5,776–7,715 pixels per pose, and the inspected native contact sheet shows
the ring in every heat-on sample. This confirms same-session native image
contribution, not continuous playback or an owner visual-acceptance decision. No
performance conclusion is drawn. See the [native report](measurements-multi-emitter-heat-response-native.json),
[native contact sheet](measurements-multi-emitter-heat-response-native-contact.png)
and [native runner](../scripts/two_emitter_heat_response_native_study.py), plus the
[focused-route report](measurements-multi-emitter-heat-response-ground-orbit.json),
[offscreen contact sheet](measurements-multi-emitter-heat-response-ground-orbit-contact.png),
[wide-route report](measurements-multi-emitter-heat-response-temporal.json),
[still A/B evidence](measurements-multi-emitter-opaque-heat.json) and
[offscreen runner](../scripts/two_emitter_heat_response_temporal_study.py).
`Renderer::update_globals` has a keyed two-source sampling and upload branch with
independent projected-detail tiers. The two-source fixed-tick capture matrix now
covers each source alone, both together and reversed scene emitter order across
four cameras on M1 Max/Metal; combined hashes are identical under reversal. The
existing single-source profiling-heavy fixed-tick RGBA hash remains identical on
M1 Max/Metal. See the
[storage ABI](measurements-multi-emitter-storage-abi.json) and
[fire consumer](measurements-multi-emitter-fire-consumer.json) and
[storage packing](measurements-multi-emitter-storage-packing.json) comparisons,
plus [per-source origin](measurements-multi-emitter-source-origins.json),
[presentation evidence](measurements-multi-emitter-presentation.json) and
[atmosphere evidence](measurements-multi-emitter-atmosphere.json) and
[heat evidence](measurements-multi-emitter-heat.json).

A second sustained comparison now covers the ordinary two-emitter review scene
on the same 120-second orbit. Across three alternating 120-second offscreen pairs,
tiled and exhaustive fixed-tick captures match exactly. Tiled rendering saves a
median 1.199 ms serial frame work and 1.050 ms atmosphere/fire GPU time, while
adding 1.131 ms tile-list build time; total reported GPU render is 0.038 ms slower.
The maximum-budget stress scene still shows a higher reported GPU-render metric
with tiling, so these results define two measured operating points, not a
universal speedup. See [review-scene report](measurements-multi-emitter-review-tile-sustained.json)
and [runner](../scripts/two_emitter_sustained_study.py).

**Exit gate:** source ownership, deterministic replay, fixed-tick overflow and
reset/edit checks pass on Metal for the reviewed scenes. Cache temporal
quality now includes a full 120-second offscreen route with exact direct/cache
image parity; native fixed-tick cache captures match at six poses, and three
120-second native pairs show no robust whole-window gain. Continuous native
playback, broader resource recreation stress, DX12 and another-adapter
acceptance remain open. A dual-emitter native surface resize/restore study
preserves the fixed-tick image and renderer inventory. The runner now waits up to
five seconds for the OS-reported minimize and restore states; macOS still reports
`minimized: false` after the request, so this gate remains unverified and the
report correctly fails its full-check flag. See [lifecycle report](measurements-multi-emitter-native-lifecycle.json)
and [runner](../scripts/two_emitter_native_lifecycle_study.py). A dual-source
transactional reload study now appends WGSL syntax errors to each of the 13
runtime shader-directory modules in isolation. At seed 42/tick 120, all failures
reach WGSL parsing while preserving the baseline image and cached shadows; after
restoring every module, a successful reload produces the same image and redraws
all 13 shadow maps. The embedded presentation shader is not hot-reloadable. The
companion native-window run covers fire and volume failures plus a successful
restored reload; all images match the original fixed-tick capture. Per-frame
shadow masks are not attributed to native reload requests because rendering can
occur between requests. Cross-adapter shader coverage remains open. See the
[headless rollback report](measurements-multi-emitter-shader-rollback.json),
[native rollback report](measurements-multi-emitter-shader-rollback-native.json)
and [runner](../scripts/two_emitter_shader_reload_rollback_study.py). Fixed-tick native
tiled/exhaustive output matches across six cameras, source isolation and reversed
emitter order. Keep the cap at two until the remaining correctness, memory and
performance budgets pass.

**Maximum-budget ink-smoke parity: corrected and verified on M1 Max/Metal.** The
reproducible route initially differed from exhaustive output in 9,616 of 230,400
pixels. Inspection found two indexing errors in the expanded per-tile smoke buffer:
the primary list used a 36-entry stride although storage reserves 72 entries per
tile, and the secondary reader omitted its 36-entry offset. Primary entries could
overlap the prior tile's secondary entries, while secondary shading read primary
candidate IDs. The builder and both readers now use the shared 72-entry tile stride
and the secondary segment offset. At seed 42/tick 300, tiled output now matches
exhaustive output byte-for-byte in all six named cameras; both isolated emitters,
forced fallback and reversed emitter order also match. The same-tick source-zero
profiling-heavy capture remains byte-identical to its prior evidence hash. Natural
overflow in this scene affects 74 fire-list tiles; the smoke lists fit their per-
source 36-entry capacity and do not overflow. This does not provide temporal,
sustained native-window performance, DX12 or other-adapter evidence. Reproduce with [the stress
scene](../assets/scenes/two-emitter-overflow-stress.json), [the runner](../scripts/two_emitter_overflow_study.py)
and [the report](measurements-multi-emitter-overflow.json). No additional list
allocation or dispatch was introduced; the existing buffer layout is now addressed
consistently.

**Source-specific opaque shadow contribution (19 October 2026):** a watchfire-only
two-source scene now compares the normal world shader with a diagnostic variant
that returns full visibility for valid primary-light source slots. Direct-light
intensity, sun shadows and smoke/volume shadow paths remain unchanged. All four
fixed-tick views change: 1,754–34,136 pixels at seed 42/tick 300, with the
ground-focused view showing the largest mean RGB difference (0.844/255). This
confirms the source-one point-shadow contribution on M1 Max/Metal; it does not
establish performance or playback quality. See the [report](measurements-multi-emitter-shadow-contribution.json),
[contact sheet](measurements-multi-emitter-shadow-contribution-contact.png) and
[runner](../scripts/two_emitter_shadow_contribution_study.py).

## Program completion record

Maintain per-candidate states for implementation, automated correctness, visual
review, performance decision and target-adapter verification. Update
[STATUS.md](STATUS.md), [TODO.md](../TODO.md) and the measurement JSON as each gate
finishes. A compile or a passing unit test does not close visual or hardware gates.

### Current exit-gate dispositions (19 October 2026)

| Track | Evidence-backed disposition | Remaining acceptance |
|---|---|---|
| O01 profiling and counters | M1 Max/Metal stage attribution and output-preserving diagnostics do not support an active-region solver rewrite or a general shader rewrite. Keep counters diagnostic-only. A current debug/release parity matrix is exact in 10 of 11 fixed-tick cases. The Materials/hero difference is repeatable per binary; active fire-primitive fingerprints and view matrices match, while two perspective-projection slots differ and propagate to 7/16 view-projection and 15/16 inverse slots. Two-way matrix substitution makes both profiles byte-identical under either shared matrix pair, with each result matching that pair's default profile image; this proves camera-matrix causality for the measured flame-edge difference. [Evidence](measurements-o01-shading-attribution.json), [counters](measurements-o01-shading-counters.json), [debug/release parity and matrix substitution](measurements-debug-release-profile-parity.json). | Continuous playback, exact queue-latency attribution, native review and another adapter. |
| O02 shadow caching | Per-face invalidation matches forced redraw at fixed checkpoints and lowers the shadow stage in the moving route, but whole-window throughput is mixed. Keep conservative full-map fallback. [Evidence](measurements-o02-moving-route.json), [native](measurements-o02-native-shadow-cache.json). | Windows/DX12 and another adapter. |
| O03 tiled effects | Retain 16×16 lists and exhaustive per-category overflow fallback; 8×8 storage cost outweighs its small frame-work change. Fire-bound precompute and smoke-candidate materialization remain disabled opt-ins with M1 evidence. [Stress](measurements-o03-stress-route.json), [tile size](measurements-o03-tile-size-sustained.json), [fire bounds](measurements-o03-fire-projected-bounds.json), [fire-bound current recheck](measurements-o03-fire-projected-bounds-recheck.json), [smoke-candidate correctness](measurements-o03-smoke-candidate-invalidation-recheck.json), [smoke-candidate current sustained](measurements-o03-smoke-candidate-sustained-current-build.json). | Owner motion review, Windows/DX12 and another adapter; current paired performance is one-device offscreen only. |
| O04 projected fire detail | Keep LOD disabled by default: profile-dependent GPU changes are small, frame-work is mixed, and native FPS is effectively flat. Current fixed-tick state/image evidence is recorded above. [Sustained](measurements-o04-sustained-profiles.json), [current recheck](measurements-o04-current-build-recheck.json). | Full-duration human playback review and non-Metal qualification. |
| O05 absorption cache | Close the performance decision as a non-promoted experiment: tested 8³/16³ and dual-emitter routes show no total-render win. Preserve direct sampling as default. [Size study](measurements-o05-size-study.json), [dual-emitter timing](measurements-multi-emitter-absorption-native-sustained.json), [current invalidation recheck](measurements-o05-invalidation-current-build.json). | Continuous human review and other-adapter evidence only if promotion is reconsidered. |
| O06 opaque-light reuse | Keep reuse disabled: exact-depth guarding removed the moving-route spike, but sustained GPU-render timing is slower and a behind-view fixed-tick image error remains. [Sustained](measurements-o06-exact-depth-sustained.json), [temporal](measurements-o06-o08-factorial-temporal.json), [current recheck](measurements-o06-o08-factorial-current-build-recheck.json). | Broader optical camera/playback review and another adapter. |
| O07 culling and instancing | Keep the existing path; shadow-stage savings grow with scene size but whole-frame/native results are mixed and non-monotonic. Do not add indirect or occlusion submission based on these runs. [Scale](measurements-o07-moving-caster.json), [native](measurements-o07-native-scale-study.json). | Owner continuous-playback review and non-Metal qualification. |
| O08 resource/pass candidates | Keep independent candidate decisions and capability fallbacks. The current-build forced RGBA16F fallback matches two scenes and 120 sampled motion frames exactly on capable Metal hardware; physical unsupported-format fallback and DX12 qualification remain open. Compact HDR and no-copy remain experimental; known logical savings do not prove physical bandwidth or speed. [Decisions](DECISIONS_O08.md), [factorial](measurements-o06-o08-factorial.json), [current temporal recheck](measurements-o06-o08-factorial-current-build-recheck.json), [current RG16 fallback](measurements-o08-rg16-fallback-current-build.json). | Physical unsupported-format fallback and target-backend/DX12 qualification; continuous-temporal review for experimental paths. |
| Bounded two-emitter extension | Fixed-tick ordering, fallback, shader rollback and selected native controls are verified on M1 Max/Metal; cap remains two because the maximum-budget route has mixed whole-render cost. [Correctness](measurements-multi-emitter-overflow.json), [sustained](measurements-multi-emitter-sustained.json). | Continuous playback, broader resource-recreation, sustained native benefit, Windows/DX12 and another adapter. |

### Native window control gate (19 October 2026)

The unlocked-host retry passed resize, fullscreen entry and exit flags,
deterministic tick-120 capture, command handling and shutdown on M1 Max/Metal.
A current release Session and a full verification run from a temporary app
bundle both acknowledged `set_window minimized=true` but left `minimized=false`;
an 8-second focus-instrumented poll showed focus lost while `minimized` and
`occluded` stayed false. The owner reported using the desktop concurrently during
earlier checks, so isolation is not established. The exact current release
executable was then fixed to retain and reapply its last windowed logical size
after the macOS fullscreen transition. The current release native verifier
confirms stable restoration to 1800×1200 physical pixels, resize, fullscreen
entry/exit, capture and shutdown. The eight-second minimization poll still did
not observe `minimized` or `occluded`; earlier concurrent desktop use means an
isolated session is not established, so minimization remains open. A live
current-release viewport showed a moving tick-423 scene at 640×360, with the
same tall, regular smoke-puff stack. This is sampled playback evidence, not owner
acceptance or a temporal-quality measurement. Owner visual acceptance,
minimization, DX12 and another-adapter gates remain open. See [native
verification](measurements-native-window-verification-current-build.json) and its
[tick-120 capture](measurements-native-window-verification-current-build.png).

These dispositions close measured decisions where the evidence is sufficient; they
do not convert unresolved visual or platform acceptance into a pass. The overall
follow-up remains open until the listed external acceptance gates are either
verified or explicitly retired with new evidence.
