# Milestone status

17 October 2026. The first development implementation is runnable; visual and
platform acceptance are still open. This is a rendering lab and engine foundation.

Optimisation planning: [eight workstream plans](OPTIMIZATION_PLAN.md) and the
[execution queue](../TODO.md) define profiling, cached shadows, tiled effects,
projected detail, smoke absorption reuse, optical specialisation, object culling/
instancing and resource efficiency. O01's profiling implementation and M1 Max/Metal
workload evidence are complete. O08's inventory and targeted allocation changes
are implemented on M1 Max/Metal; an opt-in packed HDR format now halves target
storage with small still-image differences. Fixed-camera temporal captures, eight
sampled moving-route camera poses and moving-route timing evidence exist; fallback
and cross-backend measurements remain open. O03's bounded single-emitter tile lists and O07's per-camera/per-light culling,
shared meshes, instancing and live object transforms are implemented and measured
on M1 Max/Metal. Platform acceptance gates remain open.

O07's `capture_motion.py` runner now supports the three geometry modes and a
deterministic moving caster through the shared Session API. A matched 120-frame
clearing-orbit comparison at 20 fps-equivalent fixed ticks found zero image
changes from culling versus instancing-only, and a median of three changed pixels
(maximum 13) from instancing versus baked rendering. Sampled checkpoints show
no obvious scene-pop; owner continuous-playback review and other-adapter
acceptance remain open. See
[the motion report](measurements-o07-continuous-motion.json).

O08 fixed-step submission batching is now implemented as a bounded candidate:
`Session::step` encodes up to six consecutive ticks per queue submission, with a
per-tick smoke configuration ring, tick-associated compute queries and ordered
ping-pong passes. GPU verification on M1 Max/Metal matches pre-batch images at
tick 120 across clearing, profiling-heavy and two-emitter review scenes, including
four different request partitions. One 120-tick request now reports 20 compute
submissions instead of 120. Three alternating 10-second-warm-up/120-second
fixed-step catch-up pairs show 293/318 ms lower median host request latency on
clearing/two-emitter review, with no rendering during the measured burst. This is
not frame-throughput evidence. A separate three-pair 120-second moving-route
comparison at six ticks per 10 Hz sample covers clearing, profiling-heavy,
Material Atelier and two-emitter review. Route/tick fingerprints match exactly;
median CPU queue submission falls 0.20–0.23 ms per sample. Median frame work
improves by 0.17–0.24 ms on three workloads but regresses by 0.26 ms on Material
Atelier. GPU-render median changes are neutral or slower on three workloads and
frame-work p95 is mixed. The serial path remains selectable with
`set_simulation_batching` or `--disable-simulation-batching`. Corrected three-pair
native studies cover clearing, Material Atelier and profiling-heavy. They confirm
54.2–55.5% fewer smoke submissions. Batched-minus-serial median FPS deltas are
+0.233/+0.301/+0.212 and CPU frame-work deltas are -0.151/-0.121/-0.094 ms;
GPU-stage changes are small and mixed. These are M1 Max/Metal native results;
other-adapter acceptance remains open. The earlier native measurements were
replaced because the native loop then submitted one tick at a time, bypassing
batching. The corrected loop groups due fixed ticks while retaining the serial
baseline.
See [parity report](measurements-o08-batch-parity.json),
[burst report](measurements-o08-batch-submit-cost.json),
[route report](measurements-o08-batch-route.json),
[clearing native report](measurements-o08-batch-native.json),
[Material Atelier report](measurements-o08-batch-native-materials.json),
[profiling-heavy report](measurements-o08-batch-native-profiling-heavy.json), and the runners
[parity](../scripts/simulation_batch_parity.py),
[burst](../scripts/simulation_batch_cost_study.py), and
[route](../scripts/simulation_batch_route_study.py),
[native](../scripts/simulation_batch_native_study.py).

O04's opt-in projected fire-segment LOD is implemented at 40/20 px with 48/24 px
hysteresis. In the 120-second 640×360 clearing orbit, including a close-smoke
approach and repeated crossings, the candidate occupied tiers 0/1/2 for
27.5/54.4/18.1% of frames and reduced median retained primitives from 81 to 71.
Three alternating M1 Max/Metal pairs measured a median GPU-render improvement of
0.065 ms; whole-frame deltas were mixed, with a median improvement of only
0.012 ms. These are small, single-profile results. Fourteen same-tick camera
checkpoints confirmed repeatable
transitions and exact parity for fire counts, bounds, lighting and particle event
identities. A deterministic 20 fps, 400-frame orbit crosses both thresholds four
times; quiet and bonfire profile pairs also cross their applicable bands. Per-frame
full primitive, ember and particle-light counts match in all three profiles.
Sampled contact sheets show changes in the flame region, with no obvious loss of
attachment or glow in those samples. Three alternating 120-second pairs per
profile now measure campfire, quiet and bonfire under the same 640×360 route.
Paired GPU-render medians improved by 0.113/0.124/0.052 ms respectively.
Frame-work deltas were -0.006 ms (mixed pairs) for campfire, -0.826 ms for quiet,
and +0.014 ms for bonfire. The measured geometry medians moved 81→70 primitives
for campfire, 55→40 for quiet and 166→165 for bonfire. This identifies a stronger
quiet-profile range but does not justify changing the disabled-by-default
setting. Full pairs, GPU stages, run hashes, scene variants and tier counts are
in [measurements-o04-sustained-profiles.json](measurements-o04-sustained-profiles.json).
The paired deterministic sequences have also been compared frame-to-frame around
every LOD transition (±2 samples): temporal-change-image mean RGB MAE is
0.0047/0.0073/0.0048 per 255 for campfire/quiet/bonfire. This is sampled numeric
evidence only; full fire-geometry, ember and particle-light count parity also
holds at every sample. Continuous playback acceptance remains open. See
[transition report](measurements-o04-transition-temporal.json) and
[runner](../scripts/projected_detail_temporal_transition_study.py).
An in-app browser spot review viewed the campfire baseline and LOD GIFs side by
side across several seconds; no obvious silhouette break or fire/smoke
separation appeared in the sampled frames. This does not close full-duration
human review. A three-pair native-window campfire orbit now lowers the
atmosphere/fire GPU-stage median by 0.057 ms, with effectively flat paired FPS
(−0.001); the retained-primitive median moves 81→70 and the projected-detail
calculation adds about 0.00008 ms CPU. This does not establish a whole-window
win. Keep LOD disabled by default; continuous human review and portability
remain open. See
[measurements-o04.json](measurements-o04.json),
[measurements-o04-motion-review.json](measurements-o04-motion-review.json) and
[measurements-o04-sustained-profiles.json](measurements-o04-sustained-profiles.json),
[native report](measurements-o04-native.json) and
[native runner](../scripts/projected_detail_native_study.py).
The 19 October current-release repeat adds three alternating 120-second
offscreen campfire pairs at 640×360. Candidate-minus-baseline paired medians are
−0.049 ms frame work and −0.146 ms GPU render, with all three pairs favoring the
candidate on both metrics. This does not supersede the earlier native result of
effectively flat FPS, nor does it close visual or platform acceptance. Keep LOD
disabled by default. See
[current-release sustained report](measurements-o04-sustained-current-release.json).
The 19 October current-build recheck matched fire state at all 14 projected-size
checkpoints; baseline and candidate images were identical at full detail, while
visible reduced-detail changes affected 18–105 pixels per 640×360 image and were
confined to the fire region; some reduced-detail views were pixel-identical when
the removed geometry was occluded. This discrete parity check does not replace
continuous playback review. See the
[current-build report](measurements-o04-current-build-recheck.json).
The same-tick default-scene capture also confirms projected detail, absorption
cache, optical reuse, optical no-copy, compact HDR and projected-fire-bound
precompute are disabled; the absorption cache reports zero bytes. The smoke- and
fire-bounds candidate buffers are nevertheless reserved at 2,304 and 8,192 bytes
respectively (10,496 bytes total), with their optional compute paths disabled.

O05 has an opt-in primary fire-light absorption cache at 8³ or 16³. It rebuilds
after smoke simulation updates or scene/shader/reset changes, and skips repeated
renders when inputs are unchanged. A paused serve study confirms identical
repeated images and a rebuild after each tested dirty event; disabling releases
the cache field. The disabled path allocates no cache field and does no build pass; a live
off/on/off Metal capture reports 0/4096/0 cache bytes and reproduces the same
disabled image. A later live toggle audit fixed a missing secondary-smoke
binding in the recreated volume group; off/on/off captures now succeed with the
expected 0/4096/0-byte cache lifecycle. The audit did not compare image parity.
A sustained three-scale study compares direct, 8³ and 16³ at
640×360 using three paired 120-second orbit runs per tier. At all scales 16³ is
closer to direct in fixed-tick mean RGB error. The cache reduced the targeted
atmosphere/fire GPU stage by 0.058–0.101 ms, but adds 0.025–0.033 ms GPU build
work and the total GPU render median was 0.025–0.044 ms slower in all six
comparisons. No useful total-render win is demonstrated, so keep the cache off by
default. See [measurements-o05.json](measurements-o05.json) and the detailed
[size study](measurements-o05-size-study.json). A 400-frame, 20 fps medium-smoke
route compares direct and 16³ cache output: mean frame RGB MAE is 0.096/255 and
mean frame-to-frame change-magnitude error is 0.104/255, with exact tick and
fire/effect-count parity. A native `run --agent-stdio` pause/resume check found
identical images and fixed ticks during a two-second pause; during a two-second
resume the direct and cached sessions advanced 121 and 120 ticks under host
scheduling, then matched fire state after alignment to fixed tick 540. See
[temporal](measurements-o05-temporal.json) and
[pause/resume](measurements-o05-pause-resume.json) reports. The refresh-policy
study is in [measurements-o05-refresh-policy.json](measurements-o05-refresh-policy.json).
The matching 8³ 400-frame route has mean RGB MAE 0.285/255, p95 0.426/255,
maximum channel difference 39/255 and mean temporal-change magnitude error
0.183/255, with exact tick/effect-count parity; 16³ remains closer to direct.
See [measurements-o05-temporal-cache8.json](measurements-o05-temporal-cache8.json).
An extended ten-second native pause/resume study again keeps both runs at tick
300 with identical paused images. Resume advanced 600/601 ticks under host
scheduling, then both were aligned to tick 1020 with matching fire state. At
that tick, direct versus 16³ cache differs on 12,451/230,400 pixels, with mean
per-channel absolute error 0.092/0.052/0.049 and maximum 17/11/12. This is a
small approximation difference after state alignment, not evidence of a stale
cache; total-render cost still does not justify enabling it. See
[extended pause/resume evidence](measurements-o05-pause-resume-extended.json).
Continuous human playback review, Windows/DX12 and other-GPU qualification remain
open. Both cache sizes passed 13 discrete
direct/cache checkpoints spanning paused density edits, primary-light changes,
flicker, moving embers, shader reload and reset, with exact fire-state parity;
see [invalidation study](measurements-o05-invalidation.json). A 19 October
current-build recheck repeats all 13 checkpoints at both sizes; the disabled path
uses zero cache bytes, while 8³ and 16³ use 4,096 and 32,768 bytes. Mean per-
channel error is 0.320/0.182/0.149 for 8³ and 0.097/0.056/0.049 for 16³; this
does not establish continuous playback or performance. See the
[recheck report](measurements-o05-invalidation-current-build.json).

O06 now has an opt-in opaque-reflector lighting reuse path. It reverses the
matching same-pixel foreground atmosphere contribution from the HDR snapshot and
uses the opaque normal/depth snapshot; transmissive surfaces keep direct shading.
The transmissive shader also handles camera-inside exit surfaces, with a
normal/view-based interface orientation and total-internal-reflection fallback.
M1 Max/Metal fixed-tick inside-glass and near-plane camera stress pairs match
direct/reuse captures byte-for-byte; see
[measurements-o06-camera-stress.json](measurements-o06-camera-stress.json).
Three paired 120-second M1 Max/Metal routes in both Material Atelier and a mixed
smoke/fire/material scene reduced GPU-render medians by 0.169 ms and 0.081 ms,
respectively; optical-resolve medians fell by 0.166 ms and 0.076 ms. CPU frame-work
medians also improved in these six runs. Matched hero, metal, glass, mixed-ordering
and near-glass captures were inspected; a live opaque material edit had no stale
output. A native-window mixed-route comparison now has three alternating
120-second pairs after adding a depth-match fallback at optical silhouette edges:
reuse median optical-resolve time is 0.024 ms slower and FPS is slightly lower
(median delta -0.117 fps). The guard reduced changed pixels in the behind-smoke
view from 17 to 13 of 230,400, but the maximum channel error remains 83/255.
Direct repeat captures are exact; mixed-close and glass-near match exactly. Keep
this feature disabled by default pending an acceptable behind-smoke image, native
whole-window gain, continuous motion review, broader camera/pass cases and other-GPU
qualification. See
[measurements-o06.json](measurements-o06.json), the full
[sustained study](measurements-o06-sustained.json), and
[native-window comparison](measurements-o06-native-reuse.json). Native run traces
and side-by-side captures are retained locally under
`artifacts/o06/native-lighting-reuse/`; image hashes and per-pixel errors are in
the report.

A fixed-tick depth-guard sweep across mixed-from-behind, mixed-close and glass-near
views tested progressively stricter snapshot depth tolerances. It reduced the
offscreen behind-view difference from 12 pixels to 4, but the maximum channel
error stayed 52/255; the other two views were exact at every setting. This does
not resolve the high-error pixels. A separate foreground-atmosphere alpha gate at
limits 0.001–0.25 changed none of the three image comparisons. No candidate timing
was measured, so retain the currently measured guard and investigate snapshot
precision instead of widening the alpha condition. See
[depth-guard report](measurements-o06-depth-guard.json) and
[reproducible sweep](../scripts/optical_depth_guard_study.py).

A targeted HDR snapshot-color gate was also measured at thresholds 0.001, 0.01
and 0.05. The strongest threshold reduced the behind-view difference from 12 to
8 pixels, but left the maximum channel error at 52/255; mixed-close and glass-near
remained exact. This does not fix the outlier and has no timing evidence, so it
is not part of the renderer. See
[snapshot-color report](measurements-o06-snapshot-color-guard.json) and
[runner](../scripts/optical_snapshot_color_guard_study.py).

A matched 240-frame, 20 fps `mixed-close` orbit now exercises the O06×O08
factorial. The depth-match fallback shades its direct path with the same
camera-facing interface normal as the baseline; exact depth matching prevents
the earlier sparse fire/glass edge outlier. All eight variants preserve effect
counts. RGBA16F opaque reuse differs in one pixel by one channel level (1/255);
compact-HDR reuse has the same measured error as direct compact HDR, 0.337/255
mean frame error and 0.421/255 mean temporal-change error. The earlier 188/255
peak is gone. See [factorial temporal report](measurements-o06-o08-factorial-temporal.json)
and [runner](../scripts/optical_factorial_temporal_study.py).

A 19 October current-release, 120-frame rerun keeps the same eight-way
factorial and confirms effect-count parity at every tick. Direct/no-copy and
lighting-reuse variants match their RGBA16F baseline byte-for-byte for this
sequence. Compact HDR measures 0.3422/255 mean frame error, 0.4376/255 mean
temporal-change error and a 29/255 maximum channel difference; lighting reuse
does not add to that format error. The owner accepted motion and visual
continuity in the labeled six-second, 20 fps four-panel offscreen review. A
current-release 400-frame, 20-second eight-variant factorial comparison now
extends that route; owner review is pending. All effect counts match in every
variant. This is M1 Max/Metal image evidence, not timing or native presentation
acceptance. See the [full-orbit report](measurements-o06-o08-factorial-temporal-full-orbit-current-build.json)
and [six-second report](measurements-o06-o08-factorial-temporal-current-build.json).

The refreshed 240-frame guard report shows the production exact-depth condition
has one 1/255 difference on one pixel; loosening depth matching restores an
87/255 peak. Alpha, radiance and normal-alignment gates do not improve the exact
guard result. A three-pair 120-second offscreen comparison measures median
GPU-render +0.027 ms and optical-resolve +0.023 ms for reuse; serial frame-work
is -0.024 ms with mixed pairs. The corrected candidate has no reliable whole-GPU
render win, so it remains opt-in and disabled by default. A refreshed native
three-pair study shows only +0.043 median FPS and +0.0043 ms optical-resolve;
same-session direct/reuse captures match pixel-for-pixel across three cameras.
See the [native report](measurements-o06-native-exact-depth.json),
[guard report](measurements-o06-temporal-depth-guard.json),
[sustained comparison](measurements-o06-exact-depth-sustained.json), and
[guard runner](../scripts/optical_reuse_temporal_guard_study.py). A new
current-release three-pair mixed-route rerun measures paired median frame-work
+0.030 ms and GPU-render +0.113 ms; GPU render is slower in two pairs, so this
establishes no whole-render benefit. See the [current-release sustained
report](measurements-o06-exact-depth-sustained-current-release.json).
The 19 October current-build 240-frame factorial recheck confirms all effect
counts match. Direct no-copy is pixel-identical to copy for both HDR formats;
reuse adds one 1/255 pixel difference in RGBA16F and three in compact HDR across
the full sequence. Compact HDR retains a 0.337/255 frame mean, 0.421/255 temporal
mean and 38/255 maximum channel difference. See the
[current-build report](measurements-o06-o08-factorial-current-build-recheck.json);
human continuous playback remains open.

O01 profiling implementation now includes bounded asynchronous timestamps for
smoke compute, shadows, opaque geometry, atmosphere/fire, optical resolve and post;
serial latency and buffered throughput reports; a native vsynced route report;
fixed-step counts; CPU upload/simulation/render/UI/acquisition/presentation spans;
paired per-stage comparisons; optional timing-on/off overhead comparisons; source,
shader, scene and GLB hashes; draw/light/primitive counts; and a known-allocation
GPU memory estimate. `get_metrics` exposes frame-tagged timings. Native presentation
and egui GPU timestamps are recorded. Exact queue-latency measurement remains open:
wgpu timestamps have no calibrated host-clock mapping, so reports preserve
submit-to-readback completion latency separately. The memory figure excludes driver
alignment, transient allocations and timestamp storage. Three alternating 120-second
pairs plus timed/untimed controls cover clearing, `assets/scenes/profiling-heavy.json`
(one plume and eight point lights), and Material Atelier; a separate 120-second
native clearing route records presentation/UI/acquisition/vsync spans. Summary,
provenance and raw-report checksums are in [measurements-o01.json](measurements-o01.json);
full sample reports remain in the local ignored `artifacts/o01/` directory. Identical
baseline/candidate scene inputs characterize run variance and profiling overhead,
not optimization gains. Exact queue latency, adapters without timestamp support,
Windows DX12 and RTX-class rendering remain unverified.
The default `scripts/verify.py` path now runs six `profile_compare` unit tests
before Rust validation; they cover nearest-rank summaries, missing-stage pair
alignment, scene-relative GLB paths, route-ID selection and nested source/shader
fingerprints.

Expanded O01 diagnostic-counter captures now cover three fire profiles and four
named cameras on M1 Max/Metal. Counts span 26,374–2,309,781 fire-primitive
candidates and 25,106–451,096 smoke-density samples. Counter mode now draws the
ordinary renderer first, then runs instrumented world, volume and optical companion
passes into lazily allocated scratch color targets. Those passes read the normal
depth and scene inputs without modifying the accepted image. At 640×360 this adds
4,608,000 known bytes in the default RGBA16F path. Compact HDR no-copy requires
one extra 230,400-byte mask plane within its format-specific scratch allocation;
disabling diagnostics releases the targets.
The expanded fixed-tick matrix matches all 12 baseline captures
byte-for-byte, with nonzero operation counts. Counter-run timings remain diagnostic
and are not performance evidence. The optical `material-orbit` now has
three sparse counter samples on
M1 Max/Metal, with nonzero surface, reflection and transmission work, plus a
separate uninstrumented 120-second timing run on the identical scene hash and
route. Median optical resolve was 2.076 ms and median GPU render was 2.828 ms;
the instrumented run has no usable timing data. Counter hook injection now fails
if a WGSL pattern is stale. Fixed-tick Material Atelier counters cover hero,
metal-close, glass-close, subsurface-close and orthographic, plus a compact-HDR
optical-no-copy glass case; all six normal/diagnostic pairs are byte-identical and
report optical surface interactions. See
[optical camera coverage](measurements-o01-optical-counter-coverage.json) and its
[runner](../scripts/shading_counter_optical_coverage.py). Continuous visual review,
the native inspector and Session API expose the toggle and latest operation counters. The earlier fixed-tick native-window report at tick 120 records the 22 fields available in that build; current diagnostics also count soft-volume, inked-smoke and total volume-fragment invocations. The 4,608,000-byte scratch-target allocation is unchanged. Continuous playback, diagnostic performance and other-adapter checks remain open. See [native counter report](measurements-o01-shading-counter-native.json) and [runner](../scripts/shading_counter_native_study.py), plus
[counter profile/view evidence](measurements-o01-counter-profile-scope.json),
[path counter evidence](measurements-o01-counter-paths.json),
[optical route report](measurements-o01-optical-counter-route.json) and
[route runner](../scripts/shading_counter_optical_route.py).

## O08 resource and bandwidth inventory

The original 640×360 clearing/heavy inventory recorded 29,806,088 bytes. The current
renderer reports 22,808,600 known bytes before first camera-visible optical use and
24,651,800 bytes after live optical activation; the color snapshot adds 1,843,200 bytes. The
current Material Atelier capture reports 16,882,416 known bytes. These are
descriptor/structure-size estimates; driver alignment and transient/pipeline
storage are excluded.

At 640×360, the clearing/heavy frame has 15,904,768 bytes of modeled full-frame
attachment clear/write/load/store traffic before shader sampling with the current
Rg16Float effect target (the original RGBA16F estimate was 16,826,368 bytes):
shadow maps, opaque color/normal/depth, atmosphere HDR/effect target, and post output. Optical
frames add 3,686,400 logical bytes for the HDR snapshot copy read/write and
3,686,400 bytes of HDR optical attachment load/store. The normal/depth target stays
read-only as an optical shader input, removing its snapshot copy and optical
attachment writes. Seven shadow draws plus opaque geometry reference 84,317,760 bytes of vertex input if each draw fetches the full buffer;
optical geometry adds one more full-buffer reference. These quantities are API/
shader logical work estimates, not measured DRAM bandwidth. Metal tile storage,
caches, compression and overdraw can change external traffic substantially.

The smoke shader now stores density and temperature in adapter-gated Rg16Float
ping-pong volumes, requiring `TEXTURE_ADAPTER_SPECIFIC_FORMAT_FEATURES`; the
RGBA16F fallback remains. This saves 1,179,648 known bytes for the two 48×64×48
volumes. The full-format logical texel-request estimate falls from 20,054,016 to
10,027,008 bytes per fixed step. This is not physical bandwidth: the shader only
consumes x/y, and filtered sampling and cache behavior are hardware-dependent.
Reset uploads use the selected texel stride. GPU reset/replay checks passed, and
fixed-tick smoke/metal captures match the prior format byte-for-byte on this
M1 Max/Metal adapter. O01 measured smoke compute at about 0.0205 ms median,
compared with multi-millisecond post and atmosphere/fire stages; current evidence
does not justify active-region simulation. The soft-volume route measured 12.919 ms
median atmosphere/fire stage and 13.583 ms median GPU-render on M1 Max/Metal, with
mixed paired differences under three alternating 120-second runs; no cost benefit
or shader rewrite is established. See [soft-volume report](measurements-o01-soft-volume-route.json).
An O03 tiled-versus-exhaustive comparison on the same route then found +2.610 ms
paired median frame work, +2.202 ms GPU-render and +2.570 ms atmosphere/fire
when tile lists were disabled; tick-120 output matched exactly. This supports
tile lists for this measured M1 Max/Metal soft-volume workload. Native playback
and other adapters remain open. See
[the comparison report](measurements-o01-soft-volume-tile-lists.json).

A live M1 Max/Metal wgpu format query reported sampled, storage, render-attachment,
copy and filtering support for Rg16Float and the probed alternatives. The effect
depth/flame-coverage target now selects Rg16Float only when it is filterable and
supports render attachment plus texture binding; otherwise it falls back to
Rgba16Float. At 640×360 this saves 921,600 known bytes. Smoke ping-pong volumes
select Rg16Float only with the adapter-specific format feature and required
storage/sample support, falling back to Rgba16Float; they save 1,179,648 bytes.
Pure capability-selection tests cover the required usages/features and the
Rgba16Float fallback path. The diagnostic `--force-rg16-fallback` option also
forces that branch on a capable adapter. On M1 Max/Metal, fallback texture and
pipeline creation succeeded and two fixed-tick scenes matched the native RG16
images byte-for-byte. A 120-frame, 20 fps moving fire-camera route also matched
byte-for-byte at every sampled tick from 120 through 477. Known allocation rises
by 2,101,248 bytes at 640×360.
This exercises fallback rendering but does not replace physical validation on an
adapter without these capabilities or Windows/DX12 checks. See
[offscreen evidence](measurements-o08-rg16-fallback.json) and
[offscreen runner](../scripts/rg16_fallback_study.py). A native-window fallback
session also reached tick 120 and its capture matched the headless fallback
capture byte-for-byte; see [native evidence](measurements-o08-rg16-native-fallback.json)
and [native runner](../scripts/verify_native_rg16_fallback.py).
The live allocation estimate also includes the tile debug uniform (16 bytes)
and timestamp resolve/readback buffers (864 bytes when timing is enabled); the
opaque query-set storage remains excluded. Tile-stat buffers/readbacks were
already included in the existing 192-byte total.
The inventory was refreshed at seed 42/tick 300 on the current renderer:
22,809,480 known bytes for clearing before optical activation and 16,883,296
bytes for Material Atelier with its visible HDR snapshot. Capture sidecars are
in ignored `artifacts/o08-refresh/`; the values include no driver padding or
opaque query-set storage.
Matched images stayed pixel-identical, and reset/replay checks passed on this
M1 Max/Metal adapter. This is one adapter's result, not DX12 support. The HDR
snapshot now allocates only when a camera-visible optical batch first appears, saving
3,686,400 known bytes in diffuse scenes and optical scenes whose optical geometry
remains outside the camera. Frames without visible optical batches skip the HDR copy
and resolve; the snapshot remains resident after activation. Direct normal/depth sampling removes
another 1,843,200 bytes from the prior pair-of-snapshots design. Live material
activation, camera-away gating and fixed-tick capture parity were verified. Three
alternating 20-second pairs were followed by three 60-second material-orbit pairs. In the longer runs, median
paired optical-resolve delta was +0.0087 ms and whole GPU-render delta was
+0.0003 ms; frame-work deltas varied and do not establish GPU benefit. These
results support the memory and logical-traffic findings, not a timing claim.
Broader routes and Windows DX12/RTX acceptance remain open. Full provenance and
per-resource breakdown are in [measurements-o08.json](measurements-o08.json).
The required `python3 scripts/verify.py --gpu` run passed on this M1 Max/Metal
host, including Clippy, workspace tests, scene validation and GPU integration
checks. This verifies Rg16Float texture/pipeline creation and lazy snapshot lifetime on
Metal, not fallback execution on another adapter or cross-backend behavior. A valid 640×360 Material Atelier scene with an away-facing camera reported
zero visible objects, zero optical batches and zero snapshot bytes. A live reflectivity
edit remained unallocated while offscreen, then allocated one 1,843,200-byte HDR snapshot
when the camera switched to the edited geometry. Turning the camera away again reported
zero optical batches and no optical-resolve timestamp while retaining the snapshot. The
metal-close seed-42 tick-300 image remained byte-identical to the saved reference. This
is frustum visibility, not full occlusion detection. A paused native-window Session
now repeats the lifecycle at tick 0: offscreen edit stays at 0 snapshot bytes and
has no optical-resolve timestamp; first visibility creates one 1,843,200-byte
snapshot across nine optical batches; turning away skips resolve but retains the
allocation; returning to hero does not allocate again. Repeated away and hero
captures are byte-identical to each other and to same-adapter headless captures.
The same pixel parity holds across all seven visible views, including inside-glass
and near-plane stress cameras, with snapshot residency unchanged. Native
lifecycle is verified on M1 Max/Metal only;
other-adapter and DX12 behavior remain open. See
[native report](measurements-o08-lazy-optical-native.json) and
[runner](../scripts/lazy_optical_native_study.py).

The O08 simulation-config upload cleanup now skips the redundant render-time
write while preserving the per-tick compute config. Three alternating 120-second
clearing-orbit pairs show a stable 0.007–0.009 ms lower median CPU-upload span;
whole-frame medians improve slightly, p95 results vary, and GPU-render medians
remain flat. Tick-120 clearing and dual-emitter output match the prior build
byte-for-byte. This removes one 96-byte write per active emitter per rendered
frame without establishing a throughput or FPS gain. Dual-emitter sustained,
native-window and cross-adapter gates remain open. See
[the paired report](measurements-o08-smoke-config-upload.json).

O08 now also skips the render `Globals` uniform write before each fixed smoke
dispatch; `smoke.wgsl` reads per-tick state from the source-local config buffer.
The render path retains one `Globals` write per frame. Three alternating
120-second clearing-orbit pairs remove 848 bytes per simulation step (6,105,600
bytes per 7,200-step run) and lower median CPU-upload time by 0.012–0.053 ms.
Whole-frame deltas are mixed (-0.062/+0.087/-0.158 ms), and GPU-render deltas
remain near zero (-0.004/-0.018/+0.003 ms); this is an upload reduction, not an
established throughput gain. Baseline/candidate tick-120 images match
byte-for-byte. Additional-workload and cross-adapter acceptance remain open.
The native-window clearing route is measured separately below. See
[measurement report](measurements-o08-globals-upload.json);
the per-frame upload counters are included in `describe`, `get_metrics`, route
benchmarks and native benchmark samples.

Native-window comparisons now cover clearing, profiling-heavy, Material Atelier
and two-emitter routes on M1 Max/Metal, each with three alternating 120-second
optimized/legacy pairs and ten-second warm-ups. All runs exceed 99% render and
smoke-compute timestamp coverage when compute coverage is divided by actual fixed
ticks. Optimized-minus-legacy medians in route order are +0.124/-0.070/+0.069/
+0.044 FPS, -0.045/+0.001/+0.011/-0.019 ms CPU native frame,
-0.006/+0.004/-0.017/-0.004 ms CPU upload, -0.017/+0.014/-0.014/+0.008 ms CPU
simulation encode, and +0.006/-0.014/-0.007/-0.004 ms atmosphere/fire GPU.
Pair signs vary, so the evidence supports traffic reduction, not a whole-window
speedup. Profiling-heavy counters show about 1.38 fewer `Globals` writes and
1,173 fewer uploaded bytes per rendered frame. Windows/DX12 and other-adapter
validation remain open. See the
[clearing report](measurements-o08-globals-upload-native.json),
[profiling-heavy report](measurements-o08-globals-upload-native-profiling-heavy.json),
[Material Atelier report](measurements-o08-globals-upload-native-materials.json),
[two-emitter report](measurements-o08-globals-upload-native-two-emitter.json),
and [reproducible study](../scripts/globals_upload_native_study.py).

O08 also retargets smoke compute resources from group 1 to group 0 and removes
the unused render Globals group from the advection pipeline layout. This reduces
one bind-group set per smoke compute pass. Fixed-tick clearing and dual-emitter
captures are byte-identical, and the headless transactional reload rollback
study preserved the reference image when all 13 reloadable shader modules
rejected invalid source and after the restored successful reload. Four native
M1 Max/Metal three-pair studies now cover clearing, profiling-heavy, Material
Atelier and two-emitter workloads, each with >99% render and smoke-compute
timestamp coverage. Coverage uses the actual fixed-tick count as its denominator,
not the ideal route duration. Optimized-minus-legacy median FPS deltas are
+0.049/+0.097/+0.011/-0.033; CPU native-frame deltas +0.028/-0.066/-0.068/+0.041
ms; simulation-encode deltas -0.032/-0.061/-0.030/+0.014 ms; and atmosphere/fire
GPU deltas -0.0014/+0.0218/+0.0064/-0.0025 ms, respectively. Results vary by
route, including slower two-emitter FPS, so the supported conclusion remains
fewer encoded bind commands without a general throughput gain. More native
routes and playback review, Windows/DX12 and other-adapter validation remain
open. See the [layout report](measurements-o08-smoke-bind-layout.json), four
[native reports](measurements-o08-smoke-bind-layout-native.json),
[profiling-heavy](measurements-o08-smoke-bind-layout-native-profiling-heavy.json),
[materials](measurements-o08-smoke-bind-layout-native-materials.json),
[two-emitter](measurements-o08-smoke-bind-layout-native-two-emitter.json),
[native runner](../scripts/smoke_bind_layout_native_study.py) and ignored
[rollback report](../artifacts/o08-smoke-bind-shader-rollback.json).

The experimental `Rg11b10Ufloat` HDR target reduces the primary color target and
optical snapshot from 8 to 4 bytes per pixel when the adapter exposes the required
feature/usages. Three fixed-tick M1 Max stills looked very similar on visual review,
but 49–78% of pixels changed at low mean RGB error; sparse smoke pixels had a
30/255 maximum channel difference. Four additional fixed-camera captures over ticks
300–1200 show similar appearance and stable error (mean 0.362/255, maximum 9/255)
while fire/smoke evolve. Three alternating 120-second M1 Max/Metal material-orbit
pairs show a -0.0061 ms paired median GPU-render delta, about 0.24%; frame-work
deltas vary and no practical speedup is claimed. Eight sampled route camera poses
at fixed tick 1200 look similar, with mean RGB error 0.362–0.431/255 and maximum
channel error 10/255. The measured benefit is 1,843,200 fewer known target bytes at
640×360 on an optical scene. The format remains off by default. Fallback behavior,
DX12/other adapters and the HDR snapshot/pass-layout gate remain open. Full results are in
[measurements-o08.json](measurements-o08.json); local captures are under ignored
`artifacts/o08/compact-hdr-motion/` and `artifacts/o08/compact-hdr-route-captures/`.

A new 240-frame, 20 fps high-dynamic mixed fire/smoke/reflector/glass route
comparison quantifies compact-HDR temporal error against RGBA16F at the same
seed/tick/camera sequence. Mean frame error is 0.342/255, p95 frame mean
0.373/255, and maximum channel error 29/255. Mean per-frame temporal-change-
magnitude error is 0.418/255, p95 0.455/255, with maximum channel error 29/255.
This is one offscreen M1 Max/Metal route, not perceptual or human playback
acceptance. Three additional 120-frame, 20 fps routes now cover clearing, the
heavy plume/eight-light workload and Material Atelier. Their mean frame errors
were 0.341/0.384/0.372 per 255; temporal-change-magnitude errors were
0.190/0.212/0.043 per 255, with maximum channel errors 31/27/10. Sampled frames
look close, but continuous human playback acceptance remains open. Keep the format
experimental. Three alternating 120-second native-window pairs on the mixed route
measured FPS deltas +1.512/-0.769/+0.151 (median +0.151 fps), a median native
CPU-frame delta of -0.306 ms and near-zero mixed GPU-stage deltas. This does not
establish a reliable whole-window speedup. Native visual playback, physical
fallback and DX12 checks remain open. See
[single-route evidence](measurements-o08-compact-hdr-temporal.json) and
[multi-workload evidence](measurements-o08-compact-hdr-workloads.json), plus the
[native-window report](measurements-o08-compact-hdr-native.json).

The experimental `--optical-no-copy` overlay path keeps the source HDR immutable,
draws optical results to a separate color target plus R8Unorm coverage mask, and
selects covered pixels during post. Four seed-42 tick-300 image pairs (hero,
metal-close, glass-close, and compact-HDR glass-close) were pixel-identical on
M1 Max/Metal. At 640×360, RGBA16F coverage uses the output alpha channel and
replaces the 1,843,200-byte snapshot with an equally sized output, with no added
mask allocation. The known allocation matches the snapshot path. Its modeled
full-frame copy/attachment/post-read traffic is 5,529,600 bytes versus 7,372,800,
not a physical bandwidth measurement. Compact HDR retains a 230,400-byte R8 mask.
Three alternating 120-second route pairs found a -0.01817 ms median GPU-render
delta (~0.70%); frame-work deltas varied, so there is no practical speedup claim.
The option remains off by default. GPU verification
passed on M1 Max/Metal; native window, fallback adapters and Windows/DX12 remain
unverified. Full evidence is in [measurements-o08.json](measurements-o08.json),
with local captures and reports under `artifacts/o08/optical-no-copy-*`.
The RGBA16F alpha-coverage refinement and its refreshed timing reports are under
`artifacts/o08/optical-alpha-coverage/`.

The native-window no-copy comparison now has three alternating 120-second pairs
on the M1 Max/Metal using the mixed smoke/fire/reflector/glass orbit. The paired
optical-resolve deltas were -0.014, +0.023 and -0.043 ms; FPS deltas were
-0.155, +0.306 and +0.293. Median full native CPU-frame work was 0.028 ms
higher for no-copy. The route rendered with timestamp coverage in all six runs,
but the mixed deltas do not establish a reliable whole-frame gain. Known
allocation stayed equal at 24,997,024 bytes as the 1,843,200-byte snapshot was
replaced with an equal-sized output. Keep the option experimental and off by
default. This is one native Metal workload; broader optical motion, another
adapter, physical fallback formats and Windows/DX12 remain open. Full run
summaries and provenance are in
[measurements-o08-native-no-copy.json](measurements-o08-native-no-copy.json);
the runnable study is `scripts/optical_no_copy_native_study.py` and full native
frame traces are retained locally under `artifacts/o08/native-no-copy/`.

## O03 single-emitter tile lists

The renderer builds ordered 16×16 scene-pixel lists for fire primitives, ink-smoke
lobes, point lights and particle lights. Per-tile capacities are 64, 36, 8 and 12
respectively. Conservative projection handles camera-inside/near-plane/invalid
cases by including the viewport. Overflow flags select exhaustive shader evaluation
for the affected category; tiled evaluation is enabled by default in this build
and can be switched to exhaustive mode. `set_tile_lists`, capture flags and
benchmark flags also expose an exhaustive baseline and a forced-fallback
diagnostic. Asynchronous frame-tagged counters report candidate memberships,
maximum occupancy and overflow tiles. At 640×360, the buffers add 471,040 list
bytes and 192 counter bytes; the known-allocation estimate for clearing is
30,277,320 bytes.

An opt-in smoke-candidate cache computes deterministic parent bounds on the GPU
once per dirty rendered state and shares them between tile building and shading.
The direct path remains selected by default: two 120-second paired workloads
found small/mixed GPU-render changes, about 0.04 ms added CPU tile-list encoding,
and whole-frame regressions in the earlier implementation-revision comparison.
Exact same-tick direct/cached output matches on M1 Max/Metal. A current-release
native study completes three alternating 120-second pairs on the dual-emitter
clearing orbit; cached-minus-direct paired medians are +0.144 FPS, −0.004 ms CPU
native-frame work and +0.039 ms atmosphere/fire GPU time. These small mixed
deltas do not establish a whole-window win, so keep the cache disabled by default.
A tick-300 current-release capture confirms the cache is enabled in the candidate
and disabled in the baseline while both image and tile metrics match exactly.
Windows/DX12 and other-adapter qualification remain open. See
[candidate report](measurements-o03-smoke-candidates.json).
The 19 October current-build check adds seven matched direct/cached serve-session
checkpoints spanning fixed-step advance, emitter and linked-light edits,
successful shader reload, and reset/replay; fire state and pixels match at each
checkpoint. A separate live Session toggle returns the expected accepted
responses and is pixel-identical direct/cache/direct at a fixed tick. This is
sampled M1 Max/Metal correctness, not continuous playback or visual acceptance.
The known 2,304-byte candidate-buffer allocation is reserved even when disabled.
New frame metrics report six dispatch encodes across the six dirty cached states,
clean enabled skips, and one dispatch in the live enable/disable check. This
confirms command scheduling, not GPU completion time or performance benefit.
The fresh same-source release pairs below show small workload-specific changes,
not a consistent enough result for default promotion. See the
[current-build report](measurements-o03-smoke-candidate-invalidation-recheck.json)
and [reproduction runner](../scripts/smoke_candidate_invalidation_study.py).
The current instrumented release build has also been remeasured in same-source
paired variants: three 120-second pairs per route for two-emitter and heavy-plume
scenes, with complete 7,200/7,200 timing coverage and no skipped or late samples.
Median frame-work/GPU-render deltas were −0.016/−0.046 ms for two-emitter and
−0.398/−0.070 ms for heavy plume. CPU tile-list encoding increased +0.040 ms on
two-emitter and +0.012 ms on heavy plume; one heavy GPU-render pair regressed.
These offscreen M1 Max/Metal gains are modest and route-dependent. The separate
native report reaches the same disposition: the cache remains disabled by
default. See the [current sustained report](measurements-o03-smoke-candidate-sustained-current-build.json),
[native report](measurements-o03-smoke-candidate-native-current-build.json) and
[native runner](../scripts/smoke_candidate_native_study.py).

Four exact-tick view sets (hero perspective, close smoke, orthographic and glass
close-up) matched byte-for-byte among tiled, exhaustive and forced-fallback modes.
The hero clearing capture was visually inspected. Three alternating 10-second
serial pairs after 5-second warm-ups on M1 Max/Metal measured full-render GPU
medians from 3.017 to 2.575 ms for clearing, 3.878 to 3.393 ms for the heavy
single-plume/eight-light scene, and 2.984 to 2.478 ms for Material Atelier. Full
frame work paired median deltas were -2.202, -0.991 and -1.022 ms. List build cost
was 0.413–0.633 ms GPU median and 0.10–0.16 ms CPU encoding; the material case had
a +0.279 ms CPU encode delta even as full-frame work fell. Route runs recorded no
natural overflow. A deterministic diagnostic scene now produces fire-list
occupancy up to 101 against capacity 64, with fire fallback in 1.48% of sampled
16×16 tile frames and 0.56% in an experiment-only 8×8 build. Tiled/exhaustive
captures at both sizes are byte-identical. The 8×8 lists use 3.91× the storage
(1,843,200 vs 471,040 bytes); short unpaired timing is inconclusive and production
remains 16×16. Smoke and light categories did not overflow because their bounded
candidate counts fit their capacities. This does not establish route-scale fallback
cost, motion quality, native-window performance or cross-device support.
The sustained camera-inside hold route now measures the all-overflow edge case:
fire fallback occurs in all 920 tiles for every sample. Exhaustive evaluation
reduces paired median GPU render by 1.339 ms and frame work by 0.327 ms; tile-list
build costs 1.27–1.39 ms per frame, with mixed atmosphere/fire deltas. This is
pathological-view evidence, not a general tiled-rendering decision. See
[the report](measurements-o03-camera-inside-overflow.json).
An independent O03 path now precomputes each fire primitive's projected screen
bounds once per frame. Direct projection remains the default; the candidate is
available through `--precompute-fire-bounds` and the shared `set_tile_lists`
operation. Across 21 fixed-tick views in four workloads, pixels and all tile
membership/overflow/occupancy counters match exactly. Three paired 120-second
M1 Max/Metal routes per workload lower median GPU-render time by 0.292–0.763 ms
and tile-build time by 0.145–0.626 ms. Frame-work paired medians improve, while
Material Atelier p95 frame work regresses by 0.179 ms. A separate three-pair
native clearing-orbit comparison lowers atmosphere/fire GPU-stage median by
0.291–0.328 ms (paired median 0.319 ms) and native-frame CPU median by 0.056 ms.
FPS deltas vary (−0.029 to +0.205; paired median +0.202), so no reliable
whole-window win is established. Keep it opt-in; native M1 Max/Metal measurement
is recorded. A current-release native rerun uses three alternating 120-second
pairs on the same route: the paired median atmosphere/fire GPU change is −0.296 ms,
while FPS changes +0.009 and CPU native-frame work +0.003 ms. The candidate
remains opt-in without a whole-window frame-rate claim. A tick-300 `fire-study`
capture from the same release binary matches pixels and tile metrics exactly.
The owner accepted motion and visual continuity in the offscreen clearing-orbit
preview; it is not native playback acceptance. Windows/DX12 and other-adapter
behavior remain open. See the [offscreen report](measurements-o03-fire-projected-bounds.json),
[prior native report](measurements-o03-fire-projected-bounds-native.json),
[current-release native report](measurements-o03-fire-projected-bounds-native-current-build.json),
[offscreen runner](../scripts/fire_bounds_precompute_study.py), and
[native runner](../scripts/fire_bounds_native_study.py).
The 19 October current-build check also matches all 21 fixed-tick views and the
paused Session API toggle; camera-inside natural fire overflow remains 100%.
Its three two-second pairs validate capture/timestamp protocol only and are not
sustained-performance evidence. See the
[recheck report](measurements-o03-fire-projected-bounds-recheck.json).
The two-emitter maximum-budget correctness runner now generates separate
camera-inside-plume and near-plane-intersection scenes. Both tiled images match
exhaustive output exactly; the inside-plume view overflows the fire list in all
920 tiles. These are adversarial correctness captures, not art-review evidence.
The paused live-session matrix also matches tiled/exhaustive output at ticks 120
and 300, and after an emitter intensity edit at tick 300. The moving frames differ
from one another; the edit changes the image without advancing the tick. Fire
overflow occurs in 74–75 tiles. These checks exercise deterministic movement and
edit state, not continuous playback acceptance. See
[the report](measurements-multi-emitter-overflow.json).
Multi-emitter ownership, Windows/DX12 and other GPU vendors remain open. The
three-pair 120-second stress-scene orbit now records natural fire overflows at
1.95% of tile-frame samples (maximum occupancy 144) and zero smoke/light
overflow. On this route, tiled GPU render was consistently 1.42 ms slower while
full-frame work deltas ranged from -0.030 to +0.021 ms; the roughly 1.40 ms
tile-list build overlaps other GPU work, so these intervals must not be summed.
This diagnostic route provides no whole-frame speedup evidence. A three-pair
120-second 8×8 versus 16×16 comparison then reduced fire overflow from 1.95% to
1.36%, but used 1.37 MB more known allocation and showed only a 0.037 ms median
full-frame work improvement with inconsistent p95; retain 16×16. Same-tick
fixed-camera captures matched byte-for-byte. Continuous motion review and
other-adapter validation remain open. A native-window comparison ran three
alternating 120-second pairs after 10-second warm-ups. Exhaustive minus tiled
GPU atmosphere/fire medians were +1.216/+1.187/+1.196 ms (tiled is faster);
native FPS deltas were -0.133/-0.306/+0.049 FPS and native CPU-frame deltas were
-0.120/+0.066/+0.012 ms. The stage saving is repeatable, but whole-window
measures are small and mixed, so this does not establish an overall frame win.
Keep 16×16 tiles and the exhaustive fallback. Full per-run timing, source hashes
and the runner are in [measurements-o03-native-tile-lists.json](measurements-o03-native-tile-lists.json)
and [tile_lists_native_study.py](../scripts/tile_lists_native_study.py). Other-adapter
validation remains open. Results are in
[measurements-o03-overflow.json](measurements-o03-overflow.json) and
[measurements-o03-stress-route.json](measurements-o03-stress-route.json) and
[measurements-o03-tile-size-sustained.json](measurements-o03-tile-size-sustained.json);
raw reports and captures are in ignored `artifacts/o03/`.

**Two-emitter implementation update (18 October 2026):** scene validation and
the live renderer accept up to two emitters with explicit unique primary-light
IDs. Source-local simulation, shading, heat, ink, absorption, and six-face
primary-light shadow maps are exercised by fixed-tick Metal captures. Reversing
emitter order preserves the combined image hashes. Cache-versus-forced captures
also match after each source light, sun projection, caster, shadow material,
shader reload and reset change. Moving one fire light now dirties only its six
cube faces. The 8³ absorption cache was also toggled on/off/on at four fixed-tick
cameras: it used the existing 4,096-byte field, released it while disabled and
restored the exact direct image. Cache error was small in the sampled stills, but
this does not establish temporal quality or performance. A focused A/B found and
fixed the source-local opaque-heat gap: low terrain fell below the volume bounds
after the surface offset, so the shader skipped temperature samples. Sampling
now uses stable source origins and clamps only the sample height to the source's
lower heat slice; x/z bounds remain enforced. With only `watchfire` enabled,
seed 42/tick 300, and `earth.heat_response` 0 versus 0.8, all six still views
changed 168–5,695 pixels. The ground-focused still shows the clearest ring cue.
A full 120-second source-one heat-off/on `dual-wide` comparison samples 2,400
frames at 20 fps. Ticks, camera poses, fire counts and particle-light counts
match. Mean full-frame A/B MAE is 0.0084/255 (88 changed pixels on average), and
temporal-change difference MAE is 0.00087/255; the cue is sparse in this wide
route. In the focused watchfire orbit, mean A/B MAE is 0.7705/255 over 2,400
frames, with 9,331 changed pixels on average; temporal-change difference MAE is
0.0435/255. The inspected contact sheet shows the heat ring at each of five
sampled checkpoints. A native-window fixed-tick A/B now repeats the five focused
poses at tick 300 in one paused session; heat-on changes 5,776–7,715 pixels per
pose, and the inspected native contact sheet shows the ring in every heat-on
sample. This confirms native image contribution, not continuous playback or an
owner visual-acceptance decision. No performance conclusion is drawn. See the
[native report](measurements-multi-emitter-heat-response-native.json), [native contact sheet](measurements-multi-emitter-heat-response-native-contact.png) and [native runner](../scripts/two_emitter_heat_response_native_study.py), plus the [focused-route report](measurements-multi-emitter-heat-response-ground-orbit.json), [offscreen contact sheet](measurements-multi-emitter-heat-response-ground-orbit-contact.png),
[wide-route report](measurements-multi-emitter-heat-response-temporal.json),
[offscreen runner](../scripts/two_emitter_heat_response_temporal_study.py), fixed-tick
[`two_emitter_heat_response_study.py`](../scripts/two_emitter_heat_response_study.py)
and [opaque heat evidence](measurements-multi-emitter-opaque-heat.json). The
dual-source scene inventory reports 25,889,280 known bytes at
640×360; this is not a paired single-source delta. See [implementation plan](MULTI_EMITTER_PLAN.md),
[two-source review](measurements-multi-emitter-shadows.json), [shadow invalidation evidence](measurements-multi-emitter-shadow-invalidation.json)
and [cache evidence](measurements-multi-emitter-absorption-cache.json).

A matched temporal comparison now covers the direct and 8³ source-local
absorption paths over 120 frames at 20 fps with the fixed dual-wide camera.
Both emitters advance from the same seed and start tick; effect counts match on
every frame. Mean frame RGB error is 0.026/255 (p95 0.032/255), mean temporal-
change-magnitude error is 0.020/255, and maximum channel error is 21/255. The
contact sheet shows close sampled agreement with differences around the smoke.
A full 120-second moving-camera maximum-budget route now compares direct and 8³
cache over 2,400 frame pairs. Camera poses, effect counts and images match every
frame; temporal-change error is also zero for this workload. Contact-sheet review
shows matching smoke and fire through the orbit. This is offscreen M1 Max/Metal. A native-window session toggles the cache
at six fixed orbit poses; direct/cache/direct captures match pixel-for-pixel, with
verified cache toggles and residency. Continuous native playback and portability remain open. Three alternating
120-second native pairs show +0.263 median FPS, +0.083 ms CPU frame work and
-0.092 ms atmosphere/fire GPU time; surface acquisition varies, so there is no
robust whole-window win. Keep the cache disabled by default. See [native sustained
report](measurements-multi-emitter-absorption-native-sustained.json) and [runner]
(../scripts/two_emitter_absorption_native_sustained_study.py), plus [native report](measurements-multi-emitter-absorption-native.json)
and [native runner](../scripts/two_emitter_absorption_native_study.py), plus
[moving-route report](measurements-multi-emitter-absorption-moving-route.json) and
[runner](../scripts/two_emitter_absorption_moving_route_study.py).
See [temporal report](measurements-multi-emitter-absorption-temporal.json)
and [runner](../scripts/two_emitter_absorption_temporal_study.py). The 16³
comparison reports mean RGB error 0.014/255 (p95 0.019/255), mean temporal-change
error 0.015/255 and maximum channel difference 17/255; effect counts also match
at every frame. See [16³ temporal report](measurements-multi-emitter-absorption-temporal-cache16.json).

Three alternating 120-second pairs per cache size now measure dual-source cost.
Candidate-minus-direct paired medians were +0.027/+0.019 ms frame work and
+0.061/+0.081 ms GPU render for 8³/16³; cache build cost was 0.034/0.044 ms
GPU and 0.045/0.048 ms CPU per frame. No total-render win was measured. Cache
allocation is 4,096/32,768 bytes. See [sustained report](measurements-multi-emitter-absorption-sustained.json)
and [runner](../scripts/two_emitter_absorption_sustained_study.py).

The maximum-budget close-camera route exposed two indexing errors in the expanded
smoke tile buffer: the primary list used a 36-entry tile stride instead of the
72-entry reserved stride, and the secondary reader omitted its 36-entry segment
offset. Both are corrected. With 402 fire primitives, eight authored point lights
and the 12-light derived cap, tiled and exhaustive captures now match byte-for-byte
at seed 42/tick 300 across all six named cameras. Each isolated emitter, forced
fallback and reversed emitter order also match. The source-zero profiling-heavy
capture retains its prior hash. Natural overflow affects 74 fire-list tiles; smoke
lists do not overflow their per-source capacity. The fix changes addressing only:
it adds no allocation or dispatch. A separate three-pair, 120-second offscreen
comparison finds tiled serial frame-work lower by a median 0.715 ms in every pair.
The reported GPU-render metric is 1.922 ms higher for tiled; tile-build rises
2.468 ms while atmosphere/fire falls 0.495 ms. GPU intervals may overlap, so this
is a mixed, workload-specific result rather than a universal speedup. An ordinary
two-emitter review-scene route adds a second operating point: tiled/exhaustive
images match at tick 300, and three 120-second pairs save 1.199 ms median serial
frame work and 1.050 ms atmosphere/fire time, with 1.131 ms higher tile-list build
and 0.038 ms slower total reported GPU-render time. Additional scenes remain to
be measured. See [review-scene report](measurements-multi-emitter-review-tile-sustained.json).
Native-window fixed-tick
captures now match exhaustive shading across six cameras, source isolation and
reversed emitter order. A three-pair native maximum-budget tiled/exhaustive study
shows a median 0.393 ms atmosphere/fire GPU-stage reduction, with mixed whole-window
FPS and CPU results; it does not establish a full-window win. Continuous playback,
DX12 and other-adapter acceptance remain open. See [native report](measurements-multi-emitter-native.json),
[native runner](../scripts/two_emitter_native_study.py), [overflow report](measurements-multi-emitter-overflow.json),
[sustained report](measurements-multi-emitter-sustained.json),
[performance runner](../scripts/two_emitter_sustained_study.py),
[native tiled report](measurements-multi-emitter-tile-native.json),
[native tiled runner](../scripts/two_emitter_tile_native_study.py),
[review-scene sustained report](measurements-multi-emitter-review-tile-sustained.json),
[scene](../assets/scenes/two-emitter-overflow-stress.json) and
[runner](../scripts/two_emitter_overflow_study.py).
Transactional shader rollback now has fixed-tick headless coverage for all 13 runtime shader-directory modules: each invalid WGSL source reaches parsing, preserves the baseline PNG, and avoids shadow redraw; restoring all modules reloads successfully, keeps the same PNG, and redraws all 13 shadow maps. The embedded presentation shader is not hot-reloadable. The companion native-window run covers fire and volume failures plus a successful restored reload at the same tick; every capture matches the baseline image. Per-frame shadow invalidation metrics are omitted because rendering can occur between native requests. Cross-adapter behavior remains open. See [headless report](measurements-multi-emitter-shader-rollback.json), [native report](measurements-multi-emitter-shader-rollback-native.json) and [runner](../scripts/two_emitter_shader_reload_rollback_study.py).

`python3 scripts/verify.py --gpu` passed on this host: formatting, Clippy,
40 workspace tests, scene validation and material/fire GPU checks. The verifier
reports `native: false`; the separate native studies above cover selected capture,
performance and surface-resize paths. Windows/DX12 rendering remains unverified.

## O02 whole-map shadow cache

The single-source renderer keeps all seven shadow maps valid across frames with
unchanged casters, effective shadow transmission, sun projection and fire-light projection.
Camera and light color/power changes retain the maps. Sun projection edits redraw
the sun map; fire-light position/range edits redraw the point cube. Reset, successful
shader reload and uncertain key state redraw all seven maps. Cache metrics report
the dirty reason, per-face mask, redrawn map count, 5,767,168 resident map bytes and
CPU shadow-encoding time. `set_shadow_cache` forces redraw through the protocol;
benchmark reports also accept `--force-shadow-redraw`. Live `set_object_transform`
updates the draw transform, conservative bounds and baked reference vertices, and
returns a per-object transform revision. O02 per-face tracking uses old and new
conservative bounds against each map frustum. Shadow-
participation material edits test the bounds of affected objects. The renderer
redraws only marked faces and reports a `[sun,+X,-X,+Y,-Y,+Z,-Z]` mask through
`get_metrics`. The M1 Max protocol check moved `fire-ring-0` and dirtied three maps;
its capture was byte-identical to a forced seven-map redraw. Missing or uncertain
bounds and unsupported caster changes still take the full-map path.

The captures at 640×360 with seed 42/tick 0 were byte-identical for first cache
render, forced redraw and subsequent cache hit. Protocol checks confirmed hits on
camera/light-power changes and invalidation for sun movement, reset, successful
shader reload and material shadow-class change; unit checks cover caster, material,
sun and point projection/range revisions. O01's transactional shader rollback
checks still apply; failed reloads do not invalidate because the working pipelines
remain installed.

The live invalidation matrix covers a log transmission edit, sun projection move,
linked fire-light position move, point-light range edit, successful shader reload
and reset. All six captures matched forced redraw byte-for-byte. Material edits
dirtied the sun and affected cube face; sun movement dirtied only sun; point
position/range changes dirtied all six cube faces; reload and reset dirtied all
seven maps. The position edit moves its linked fire emitter atomically, preserving
the scene invariant and enabling this projection check through the shared API.
Per-event masks, reasons and CPU encoding samples are in
[measurements-o02-invalidation.json](measurements-o02-invalidation.json); rerun
with `python3 scripts/shadow_invalidation_study.py`. This remains discrete
correctness evidence, not continuous-motion cost or native/cross-platform
acceptance. The `camera_draw_preparation_keeps_unknown_bounds_and_culls_known_misses`
unit test now exercises the prepared camera draw list: unknown-bound objects stay
visible while a finite known miss is culled. This is still unit-level evidence,
not an end-to-end GPU image comparison for unknown-bound geometry.
Shadow transform/material invalidation now precomputes each face frustum once per
invalidation and obtains the face mask and full-fallback decision in the same
bounds traversal, avoiding repeated frustum extraction per caster.
The synthetic unknown-bound and invalid-frustum cases exercise this combined
production helper; valid scene assets still cannot induce the live fallback.

Three alternating serial pairs now cover a 120-second clearing orbit with a
radius-5 `fallen-log` orbit around the fire source, sampled at 60 Hz, after a
10-second warm-up. Each run contains 7,200 moved-caster frames. Forced redraw
submitted 50,400 shadow maps per run; per-face caching submitted 16,968 (66.3%
fewer), with zero cache-hit frames because the caster moved every frame. Median
CPU shadow encoding fell from 0.207 to 0.124 ms; the shadow-map GPU stage fell
from 0.434 to 0.169 ms. The whole-render GPU paired deltas were consistently near
−0.05 ms, while frame-work paired deltas straddled zero (−0.051, +0.026, −0.018
ms) and candidate p95 frame work was higher. Per-pass GPU intervals overlap; do
not sum them. This shows selective invalidation saves shadow work under motion,
but not a clear whole-frame benefit. Full provenance and paired values are in
[measurements-o02-moving-route.json](measurements-o02-moving-route.json); raw
per-frame reports remain under ignored `artifacts/o02/moving-route-120s/`. The
timed run did not capture images; six deterministic boundary-pose pairs match in
the moving-caster capture report above. Reproduce with
`python3 scripts/profile_compare.py --baseline assets/scenes/clearing.json --candidate assets/scenes/clearing.json --baseline-force-shadow-redraw --moving-caster fallen-log --duration 120 --warmup 10 --pairs 3 --output artifacts/o02/moving-route-120s`.
Native-window performance is characterized below; Windows/DX12 remains unverified.

Three alternating serial offscreen 120-second clearing-orbit pairs after 10-second
warm-up on Apple M1 Max/64 GB/Metal at 640×360 compared identical scene inputs.
Forced redraw versus cached medians of run medians were 6.365 versus 5.592 ms frame
work and 3.151 versus 2.672 ms whole-render GPU time; paired candidate-minus-control
median deltas were -0.769 and -0.479 ms. CPU shadow encoding was 0.558 ms versus
0.000083 ms; CPU upload was 0.345 versus 0.219 ms, as matrix writes stop with shadow
reuse. In the measured cached runs, all 7200 frames were hits and none redrew a map;
forced mode redrew seven maps each frame. These are M1 Max static-route results,
not native-window or Windows DX12 acceptance. Full pair/run provenance is in
[measurements-o02.json](measurements-o02.json), with raw samples under local ignored
`artifacts/o02/shadow-static/`.

A native-window version now runs three alternating 120-second cached/forced
pairs after ten-second warm-ups, with `rock-0` orbiting the fire light at radius
5 over 20 seconds. Forced redraw minus cached GPU shadow-stage medians were
+0.280/+0.286/+0.283 ms, and forced mode redrew 37,051–37,310 shadow passes per
run versus 7,416–7,474 with caching. Whole-window FPS deltas were
+0.988/+1.163/+0.763 in favor of forced redraw, despite its higher shadow-stage
cost; native CPU-frame deltas were +0.023/+0.123/+0.009 ms. The measurements
therefore confirm less shadow GPU work, but do not show a whole-window throughput
gain for caching on this route. Keep the cache for its measured stage reduction
and correctness behavior; do not present it as a native FPS optimization. Full
paired timing, counters, hashes and the reproducible runner are in
[measurements-o02-native-shadow-cache.json](measurements-o02-native-shadow-cache.json)
and [shadow_cache_native_study.py](../scripts/shadow_cache_native_study.py).
Windows/DX12 and other-adapter acceptance remain open.

A deterministic paused protocol route now moves `fallen-log` through six positions
around the point light, including +X/+Z and opposing-face transitions. At each
pose, the cached capture matched the forced seven-map redraw byte-for-byte. Each
move redrew three maps: the sun face plus the union of old and new point-light
faces. The unchanged follow-up was a cache hit with zero maps redrawn. Captures
and per-pose masks, dirty reasons and CPU shadow-encoding samples are recorded in
[measurements-o02-moving-caster.json](measurements-o02-moving-caster.json); rerun
with `python3 scripts/shadow_caster_study.py`. A separate wide orthographic study
keeps the mover visible through six paused poses. Every cached image matches forced
redraw byte-for-byte, with three maps redrawn per pose. See
[measurements-o02-visible-caster.json](measurements-o02-visible-caster.json) and
`python3 scripts/shadow_caster_visible_study.py`. The continuous-motion timing
route is recorded separately. Native-window performance and Windows/DX12 behavior
remain unverified; the six image pairs also match through the native
`run --agent-stdio` window at 2560×1600 physical size. See
[measurements-o02-visible-caster-native.json](measurements-o02-visible-caster-native.json).
Synthetic unit checks now prove that mixed missing bounds and invalid
shadow frusta dirty all seven maps; the diagnostic reason identifies conservative
fallback. Validated scene assets do not currently produce a live unknown-bound case.

Final `python3 scripts/verify.py --gpu` completed successfully on Apple M1 Max
with Metal (`verified: true`, `gpu: true`, `native: false`). Workspace formatting,
clippy, 34 unit tests, scene validation and material/fire GPU checks passed. Native
window lifecycle and Windows DX12 rendering remain unverified.

## O07 object bounds, culling and shared meshes

The renderer stores each geometry/material key once in local space and retains a
stable object/material identity, transform, range and conservative world AABB for
every scene object. Camera visibility and each of the seven shadow frusta are
computed independently; invalid/unknown bounds remain visible. Batching extends
only across consecutive compatible objects, preserving authored draw order. The
shared Session command and engine-lab flags independently select culling and
instancing, including the baked exhaustive reference mode.

On the 276-object clearing scene, 68 geometry/material keys use 143,454 shared
vertices (8,607,240 GPU bytes), versus 175,662 object-expanded vertices
(10,539,720 bytes). The selectable instance transform buffers use 247,296 bytes.
The normal shared path reduces geometry GPU storage by about 16% versus one
object-expanded vertex buffer. For exact comparison mode, the renderer lazily adds
the 10,539,720-byte unshared GPU buffer; it also retains 10,539,720 bytes of CPU
baked reference vertices so the setting can be switched during a Session.

Three alternating 6-second clearing-orbit pairs with 2-second warm-up on Apple
M1 Max/Metal compared culling disabled against culling enabled while instancing
stayed enabled. Median camera visibility fell from 276 to 157 objects; median
submitted vertices fell from 175,662 to 89,571 and camera draw batches from 69 to
26. Across the seven maps, median visible-object counts were 276/61/81/2/31/72/76;
the sun map retains all 276, including objects outside the camera view. Median CPU
culling cost was 0.023 ms (p95 0.063 ms). Paired whole-frame work delta was
-0.388 ms; GPU render delta was -0.018 ms, which is effectively unchanged within
three short pairs. A separate exhaustive-versus-shared/culling paired run also
showed nearly flat frame and GPU times. See the measurements report for all run
summaries and limits.

At 640×360, seed 42 and tick 0, the baked culling-off/instancing-off hero capture
matches the saved pre-change PNG byte-for-byte. Instanced GPU transforms change 1
hero pixel, 1 orthographic pixel, 4 smoke-close pixels and 12 glass-close pixels
against their baked references due to floating-point/raster quantization. In all
four inspected views, enabling culling adds zero further pixel differences versus
instancing-only. The four images were visually inspected. Bounds and frustum tests
cover GLB geometry, transformed positive nonuniform scale/rotation, perspective,
orthographic, behind-camera, side-plane and invalid-bound cases.

`python3 scripts/verify.py --gpu` passed on M1 Max/Metal: formatting, Clippy, 30
workspace tests, validation, material GPU and pixel-fire GPU checks. It reports
`native: false`; native window and Windows DX12 rendering remain unverified.
Live object transforms now update the model matrix, conservative bounds and baked
reference vertices, returning a per-object transform revision. Per-face invalidation
and its comparison are recorded in [measurements-o02.json](measurements-o02.json).
Full provenance and checksums are in
[measurements-o07-culling.json](measurements-o07-culling.json).

A deterministic scale study then compared the baked reference, instancing-only
and culling+instancing at 276, 552, 1,104 and 2,208 objects. Each direct or
adjacent comparison used three alternating 120-second pairs after a ten-second
warm-up at the same 640×360 grid and seed. Direct baked-to-culled+instanced paired
medians reduced GPU render by 0.009, 0.066, 0.135 and 0.151 ms; whole-frame work
fell by 0.031, 0.116, 0.053 and 0.025 ms. The reductions are small and not
monotonic. At 2,208 objects, culling reduced camera-visible objects from 2,208
to 868 and draw batches from 2,208 to 377, while median CPU culling cost was
0.739 ms. Keep the existing path; these results do not justify indirect drawing
or occlusion culling. The static route left lights and casters unchanged, so paired
shadow-map GPU timing was unavailable after cache warm-up. A matching moving-caster
four-tier study now covers baked, instancing-only and culling+instancing with three
alternating 120-second pairs per comparison. Across all 72 runs, the same 5-unit,
20-second rock orbit caused caster-change invalidation on every measured frame and
15,840 shadow-pass redraws per run. Comparing culling+instancing with
instancing-only, median GPU shadow-stage deltas were −0.022/−0.102/−0.215/−0.309 ms
at 276/552/1,104/2,208 objects; whole-frame deltas were −0.025/−0.361/−0.804/+0.202
ms. The 2,208-object GPU render stage improved by 0.096 ms while whole-frame work
increased by 0.202 ms. Keep the current path; no more complex draw submission is
justified. Full run summaries, paired deltas, shadow counters, scene hashes and
limitations are in [static scale evidence](measurements-o07-scale-study.json) and
[moving-caster evidence](measurements-o07-moving-caster.json). Native-window
measurement is complete on this Mac, with mixed whole-window results. The
fixed-tick moving-caster image route is recorded in
[continuous-motion evidence](measurements-o07-continuous-motion.json). A new
20-second, 400-frame offscreen moving-caster comparison covers all three geometry
modes; owner playback review is pending. Native performance and non-Metal
validation remain separate. See [review artifact report](measurements-o07-owner-continuous-current-build.json).

The native benchmark accepts culling/instancing modes and a moving caster, and
reports per-frame caster positions, shadow invalidation/redraws, GPU render stages
and presentation timings. A three-second baked Metal smoke route recorded 353
frames at 117.8 FPS; all sampled caster positions were 5 world units from the
fire-light center, and 177 frames redrew shadow maps. The full native matrix is
now complete: four object tiers, three geometry comparisons per tier, and three
alternating 120-second pairs per comparison after 10-second warm-ups (72 runs).
At 2,208 objects, the culling+instancing candidate reduced median shadow-stage
time versus instancing-only by 0.448 ms, while native CPU-frame work improved by
0.475 ms and median FPS fell by 4.199; other tiers and the baked comparison are
also mixed. Treat stage timings separately from native presentation and retain
the current path; the matrix does not establish a broad native-window win. Full
paired metrics, per-run summaries, scene hashes and limitations are in
[native scale evidence](measurements-o07-native-scale-study.json); the raw
resumable runner outputs remain under ignored `artifacts/o07/`. Continuous-motion
visual review and non-Metal acceptance remain open.

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

The O01–O08 completion audit remains open beyond M1 Max/Metal. Per-track measured
decisions and unresolved visual/backend gates are consolidated in the
[follow-up exit-gate table](O01-O08_FOLLOWUP_PLAN.md#current-exit-gate-dispositions-19-october-2026).

- **19 October 2026, Apple M1 Max / Metal:** `python3 scripts/verify.py --gpu`
  passed formatting, Clippy with warnings denied, 41 Rust unit tests, build,
  scene validation, baseline GPU verification, material GPU verification and
  pixel-fire GPU verification. The verifier reports `verified=true`, `gpu=true`,
  `native=false`. This validates the current host's renderer path; it
  does not close the O01–O08 moving-route, visual-review or cross-adapter gates.
  It was rerun at source revision `225a0342` after the camera-matrix causality
  investigation: formatting, warning-denied Clippy, all 42 Rust unit tests,
  workspace build, clearing/materials scene validation, headless GPU protocol
  and replay checks, material GPU verification and pixel-fire GPU verification
  passed. The [current-build report](measurements-gpu-verification-current-build.json)
  records the result and its headless, single-adapter scope.
  The full GPU verifier was rerun after adding O03 smoke-candidate dispatch/skip
  metrics and the on-demand fire-primitive fingerprint; all 42 Rust unit tests
  and the renderer checks passed on the instrumented build.
  A separate current-build RG16 fallback study also forced RGBA16F effect-depth
  and smoke targets: two scenes and all 120 sampled frames from tick 120 through
  477 matched native-RG16 output byte-for-byte, with 2,101,248 additional known
  bytes at 640×360. This tests fallback creation/rendering on an M1 Max that
  supports Rg16Float; physical unsupported-adapter and DX12 acceptance remain
  open. See [current-build report](measurements-o08-rg16-fallback-current-build.json).
  A same-device debug/release fixed-tick matrix matched 10 of 11 scenes/cameras
  byte-for-byte, including clearing, dual-emitter, smoke-candidate and projected-
  detail cases. Materials/hero is repeatable within each binary but differs
  across profiles: 87 pixels at tick 120, with a single 108/255 flame-edge
  outlier. Disabling the emitter reduces this to four one-level differences;
  setting smoke density to zero leaves the 87-pixel divergence unchanged. The
  `inspect_effects` FNV-1a fingerprint, counts and bounds match across profiles,
  locating the remaining difference downstream of CPU primitive generation. A
  direct Materials/hero matrix probe finds the view matrix identical but two
  perspective-projection slots different; the difference propagates to 7/16
  view-projection and 15/16 inverse-matrix slots in debug versus release. This
  is a profile-dependent camera input. Two-way substitution of the recorded
  debug and release matrix pairs into both builds confirms the camera matrices
  fully explain the 87-pixel difference: both builds produce byte-identical
  output, matching the corresponding profile's default capture. The normal
  builds remain profile-dependent, but the cause is isolated; no camera math,
  render defaults or pixel grid were changed.
  See [report](measurements-debug-release-profile-parity.json) and
  [contact sheet](measurements-debug-release-profile-parity-contact.png).
- **Native verification on 19 October, Mac unlocked:** `python3 scripts/verify.py
  --gpu --native` passed all GPU checks, then exited nonzero only at the
  minimization assertion. Native resize, fullscreen entry/exit, fixed tick-120
  capture, command handling and shutdown passed. The same minimization request
  was retried through the current release Session and by running that release
  binary from a temporary signed app bundle; both returned `minimized: false`
  and `occluded: false` after the request. A focus-instrumented release run,
  polled for eight seconds, showed `focused: true` after resize then
  `focused: false` with `minimized: false` and `occluded: false` after the
  minimize request. The owner reported concurrent desktop use during these
  checks, so focus may have changed due to other UI activity. Treat minimization
  as unresolved. After the owner confirmed the Mac was unlocked, the exact
  current release executable was rerun with the native lifecycle verifier.
  That exposed a fullscreen-exit size issue: macOS kept the fullscreen-sized
  window after the exit flag changed. The host now saves the windowed logical
  size and reapplies it after the fullscreen transition; a rebuilt release
  passed resize, fullscreen entry/exit, a stable 1800×1200 physical-size restore,
  tick-120 capture and shutdown. The owner then confirmed the desktop was free
  and the full `--gpu --native` verifier was rerun on the current debug build
  under macOS 27.0.1 (26A434).
  All GPU, resize, fullscreen, restore-size, capture and shutdown checks passed;
  minimization again remained false after five seconds, although focus was true
  after resize and false after the request. A direct Session probe reproduced
  the false state after `requested: true`. Concurrent desktop use alone does not
  explain the failure; the root cause of the programmatic minimize failure
  remains undetermined. A follow-up verifier now waits for the resized window to
  remain at 1800×1200 for 0.75 seconds and confirms it is focused before asking
  macOS to minimize it. On the same M1 Max/Metal build, this ruled out an
  unsettled resize as the cause: after another eight-second poll,
  `minimized: false` and `occluded: false` remained, while fullscreen entry/exit,
  stable size restoration, tick-120 capture and shutdown passed. The verifier
  change makes the lifecycle check more reliable but does not fix minimization.
  A new isolated probe with no resize or fullscreen transition confirms focus
  before the request and reports the native minimize button enabled, but still
  sees `minimized: false` and `occluded: false` after eight seconds. The restore
  request has no minimized state to reverse. This localizes the issue to the
  minimize request/window path without proving whether AppKit rejected it. A
  standalone AppKit reference window on the same macOS 27.0.1 host was active,
  key, visible and miniaturizable; both `miniaturize` and
  `performMiniaturize` still left `isMiniaturized` false. This supports a
  host/runtime limitation rather than an engine-only setup problem, but the OS
  version and local session policy are not separated. A CUA accessibility click
  on the active minimize-button element was attempted on 19 October, but the
  post-click screen-capture request failed and the Session still reported
  `minimized: false`; because a same-title packaged process was also present,
  the click target could not be tied to the current release window. Treat the
  UI attempt as inconclusive; another macOS version remains untested. Current hashes and raw
  output are in the measurement JSON. The tick-120 scene
  capture was inspected. Keep
  minimization open;
  do not substitute occlusion for minimization. The current release viewport was
  also inspected live at tick 423 with the 640×360 grid; the smoke reads as a
  tall regular stack of puffs in that sampled live view. The owner reviewed the
  6-second 20 fps `clearing-orbit` GIF/APNG and found its motion and visual
  continuity acceptable. This acceptance applies to the offscreen fixed-tick
  preview at the unchanged 640×360 grid; it does not establish native playback
  performance or review the opt-in renderer variants. See
  [preview metadata](measurements-owner-motion-review-preview.json). A separate
  current-release O04 comparison now captures 120 matched frames at 20 fps with
  baseline left and projected-detail LOD right. The owner accepted motion and
  continuity in a 20-second, 400-frame offscreen comparison spanning campfire,
  quiet and bonfire profiles. Native playback/performance and other-adapter
  acceptance remain open. The earlier six-second paired-motion metrics remain
  in [the short review report](measurements-o04-owner-motion-review-current-build.json);
  see the [accepted full-orbit report](measurements-o04-owner-full-orbit-current-build.json).
  The current idle-owner release lifecycle rerun passed resize, stable
  windowed-size restoration, fullscreen entry/exit, tick-120 capture and
  shutdown; macOS again returned `minimized: false` after eight seconds. Current
  `python3 scripts/verify.py --gpu` passed on M1 Max/Metal. See the new entries
  in [native verification](measurements-native-window-verification-current-build.json),
  which also links the tracked [tick-120 capture](measurements-native-window-verification-current-build.png).
  Raw frames remain under ignored `artifacts/`.
- The verifier used the selected 640×360 scene grid and same-device Metal
  rendering. It does not verify Windows/DX12, another adapter, or target-PC
  performance.
- macOS ARM64 and Windows x64 GNU release builds succeed. The current macOS
  release build and `engine-lab describe` protocol check, including the
  minimize-button field, are recorded in
  [the current macOS build report](measurements-macos-build-current.json). The current source,
  including the native minimize-button diagnostic, cross-checks and links as a
  Windows x64 PE executable; see [current Windows build report](measurements-windows-build-current.json).
  This Mac cross-build does not execute Windows or establish DX12 rendering,
  image/motion quality or target-hardware performance. Initial repository CI
  passed on both hosted platforms, but predates this current source revision.
- Matched stills were inspected. Original puff shapes and child bubbles remain;
  contact normals/ink and shared density-grid shadowing are approximate. The
  current art still has an overly regular stacked silhouette. Owner acceptance
  and motion review against the reference remain open. See SMOKE_DIRECTION.md.

## Measured performance

### O01 profiling characterization

M1 Max / 64 GB / Metal at 640×360. Each offscreen value is the median of three
120-second run medians after a 10-second warm-up. Baseline and candidate scene
inputs are identical within a workload. Pass intervals can overlap, so stage values
must not be summed; the whole-render measurement is separate.

| Workload | Frame work median / p95 ms | Whole-render GPU median / p95 ms | Leading GPU stage medians ms | Known GPU allocations |
|---|---:|---:|---|---:|
| Clearing orbit | 6.31 / 10.61 | 3.15 / 4.17 | post 2.53; atmosphere/fire 2.42; opaque 1.71 | 29.8 MB |
| Heavy plume + 8 lights | 6.75 / 11.97 | 3.87 / 5.04 | post 3.25; atmosphere/fire 3.13; opaque 2.40 | 29.8 MB |
| Material Atelier | 6.43 / 10.73 | 3.39 / 4.70 | post 2.75; optical resolve 2.65; atmosphere/fire 1.59 | 20.4 MB |

GPU timestamp instrumentation raised median frame work by 0.11–0.28 ms in the
paired timed/untimed controls. Timing-disabled exact-tick captures were byte-
identical to the timed capture. The separate native clearing route ran for 120 s
at 43.48 measured frames/s on this desktop, with 8.83 ms median / 70.28 ms p95
native CPU frame and 6.36 ms median / 64.79 ms p95 surface acquisition. These
native results include the active display and vsync path and must not be compared
directly with unpaced offscreen values. Exact queue time is null because wgpu
timestamps have no host-clock calibration; async readback completion latency is
reported separately. See [measurements-o01.json](measurements-o01.json) for source
hashes, paired deltas, coverage, workloads and report checksums.

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
  3060-class/16 GB PC. `cargo check --locked --workspace --target
  x86_64-pc-windows-gnu` passed on 19 October from the current worktree on this
  Mac; this verifies target compilation only, not Windows execution, DX12
  rendering, image/motion quality or performance.
- Base M1/16 GB measurement and native presentation/UI timing. The provisional
  target remains 60 fps at 1080p with a selected 480×270 scene buffer.
- Native programmatic minimization on the macOS 27.0.1 host is dispositioned as
  an unresolved host/runtime limitation: both the engine and a plain active
  AppKit reference window fail to report minimized after their native calls.
  The 19 October CUA traffic-light attempt was inconclusive because the
  post-click screen capture failed and an older same-title packaged process
  prevented reliable target attribution; see the [native verification report](measurements-native-window-verification-current-build.json).
  Another supported macOS version is still needed before treating the native
  minimization/restore gate as qualified.
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

## Simulation-driven surface heat cue

An opt-in material `heat_response` samples the existing temperature volume for
opaque shading and adds a stepped warm mark with a pixel edge cue. Zero response
preserves pixel output. Matched captures at seed 42/tick 300 were repeatable; the
active cue changed 220 pixels near the fire base. Three 120-second M1 Max/Metal
route pairs measured a 0.0112 ms median paired GPU-render increase. The prototype
remains opt-in; a follow-up fixed-tick check across hero, fire-study, smoke-close
and orthographic cameras changed 5–203 pixels, with the clearest mark in close
views and only five changed pixels in orthographic view. Repeated fire-study
output was pixel-identical. This is a style check; gameplay readability and
DX12 acceptance remain open. See
[RESEARCH.md](RESEARCH.md) and [measurements-heat-cue.json](measurements-heat-cue.json).

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
and material scene were visually inspected in the native window. On macOS
27.0.1, the acknowledged minimize request reaches Winit's AppKit
`NSWindow.miniaturize` path, but neither the engine window nor an independent
active AppKit reference window becomes miniaturized. No engine-specific cause is
identified; keep this host-limited gate open pending a repeat on another
supported macOS version or session. No full native-suite pass or Windows/DX12
visual validation is claimed.

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

The O06×O08 factorial used a high-dynamic mixed fire/smoke/reflector/glass orbit.
Reused opaque lighting reduced GPU render by 0.078 ms with RGBA16F copy and
0.108 ms with RGBA16F no-copy. Direct lighting plus no-copy reduced GPU time by
0.026 ms in RGBA16F and 0.013 ms in packed HDR; packed-HDR copy alone was within
run spread. No-copy captures were byte-identical to copy for both HDR formats.
Packed HDR saved 1.84 MB known allocation, but its high-output fixed-tick images
differed from RGBA16F by 0.21–0.72 mean RGB levels and up to 28 levels in a
channel. Packed-HDR no-copy adds a 0.23 MB mask. Keep these options independent
and opt-in; native, DX12, temporal and broader content gates remain open. See
[measurements-o06-o08-factorial.json](measurements-o06-o08-factorial.json).
