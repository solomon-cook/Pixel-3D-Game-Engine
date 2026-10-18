# O08 candidate decisions

18 October 2026. This record separates the O08 memory/layout candidates so an
allocation or traffic reduction is not mistaken for a frame-time win. Measurements
are M1 Max/Metal unless stated otherwise. Known allocation excludes driver
padding, opaque query-set storage and transient implementation details; logical
traffic is a model, not measured DRAM bandwidth.

| Candidate | Current disposition | M1 Max/Metal evidence | Open acceptance |
|---|---|---|---|
| Lazy optical HDR snapshot | Retain as the normal allocation policy. Allocate on the first camera-visible optical batch; skip snapshot/copy/resolve before that point. Keep the resident texture after activation for later camera/material edits. | Saves 3,686,400 known bytes before visible optical use at 640×360. Offscreen optical edits do not allocate; turning the camera to the material allocates once. Matched fixed-tick output and reset/replay checks passed. A paused native Session confirms 0 bytes and no optical resolve while away, exactly one 1,843,200-byte snapshot on first visibility, no reallocation across seven named/stress views, and all eight native camera captures byte-identical to same-adapter headless captures, including inside-glass and near-plane views. | DX12/other-adapter resource lifetime and output remain open. Native lifecycle was checked on M1 Max/Metal only. This is frustum gating, not occlusion culling. See [native report](measurements-o08-lazy-optical-native.json) and [runner](../scripts/lazy_optical_native_study.py). |
| Read-only opaque normal/depth reuse | Retain the direct read-only input; do not restore a second normal/depth snapshot or optical attachment. | Removes 1,843,200 known bytes from the prior snapshot pair and 7,372,800 modeled logical bytes per optical frame. Fixed-tick parity passed on the measured adapter. | Native-window and non-Metal pass ordering/resource validation; broader camera-inside and near-plane optics. |
| Adapter-gated Rg16Float targets | Retain capability-gated selection with Rgba16Float fallback. This includes effect-depth/flame coverage and smoke density/temperature volumes. | At 640×360, saves 921,600 bytes for effect coverage and 1,179,648 bytes for the two smoke volumes. M1 Max/Metal texture/pipeline creation, replay and matched image checks passed. Capability-selection tests cover the fallback branch logic. | Physical fallback rendering on an adapter lacking required features, plus DX12/other-adapter parity and timing. Unit tests do not prove fallback resource creation. |
| Compact Rg11b10Ufloat HDR | Keep experimental and disabled by default. | Saves 1,843,200 known bytes at 640×360. Material-route timing was only about 0.24% faster and does not establish a practical win. The O06×O08 high-output contact sheet looked close, but mean error was 0.21–0.72/255 and a sparse maximum reached 28/255. A 240-frame, 20 fps high-dynamic orbit comparison measured 0.342/255 mean frame error and 0.418/255 mean temporal-change-magnitude error (29/255 maximum channel error). Three additional 120-frame, 20 fps routes measured mean frame error 0.341/0.384/0.372 and temporal-change error 0.190/0.212/0.043 for clearing/heavy plume/materials; sampled frames look close. Three alternating 120-second native-window pairs on the mixed route measured FPS deltas of +1.512/-0.769/+0.151, with a median +0.151 fps; native CPU-frame delta was -0.306 ms and GPU-stage deltas were small/mixed. No whole-window speedup is established; see [native results](measurements-o08-compact-hdr-native.json). | More routes/workloads, human playback review in the native window, physical fallback and DX12 validation. |
| Optical no-copy overlay | Keep experimental and disabled by default, independently selectable from lighting reuse and HDR format. | RGBA16F fixed-tick captures were byte-identical to copy; the overlay replaces the snapshot with an equal-size output and alpha coverage. Earlier offscreen evidence found small GPU deltas. Three native 120-second pairs completed on M1 Max/Metal: paired optical-resolve deltas were -0.014, +0.023 and -0.043 ms; native FPS deltas were -0.155, +0.306 and +0.293 fps. Full native CPU-frame delta median was +0.028 ms. The signs vary and do not establish a reliable whole-frame improvement. The 1,843,200-byte snapshot is replaced by an equal-size output, so known allocation is unchanged. | Broader material/pass ordering, continuous visual review, other-adapter and DX12 validation. Compact HDR retains a 230,400-byte mask. Native measurement detail: [measurements-o08-native-no-copy.json](measurements-o08-native-no-copy.json). |
| Render `Globals` upload during smoke simulation | Keep the upload removed. The compute shader has no group-0 resource bindings; simulation state comes from each tick's source-local group-1 config. Preserve the render-time upload and the separate serial/batched simulation paths. | Tick-120 clearing output is byte-identical. Three alternating 120-second clearing-orbit pairs removed one 848-byte write per fixed step (7,200 steps / 6,105,600 bytes per run). CPU-upload deltas were -0.012/-0.053/-0.022 ms; whole-frame deltas were -0.062/+0.087/-0.158 ms; GPU-render deltas were -0.004/-0.018/+0.003 ms. This confirms less queued upload traffic, not a reliable full-frame gain. See [measurement report](measurements-o08-globals-upload.json). | Additional workloads, native-window timing, Windows/DX12 and other-adapter validation. The current M1 Max/Metal runs do not establish cross-backend performance or correctness. |
| Smoke compute bind-group layout | Keep the source-local compute layout at group 0 and omit render `Globals` from the advection pipeline layout. This removes one bind-group set command per compute pass; keep the claimed benefit to fewer encoded commands. | Clearing, dual-emitter, profiling-heavy and Material Atelier tick-120 output all match byte-for-byte. Three clearing-orbit pairs lower median simulation CPU encoding by 0.005–0.015 ms. Profiling-heavy, materials and two-emitter three-pair routes do not repeat a stable CPU or frame-work gain. Two-emitter paired simulation-encode deltas were -0.007/-0.016/+0.004 ms; frame-work was +0.012/-0.061/+0.044 ms; GPU-render was +0.001/-0.004/+0.006 ms. No general frame-time win is established. See [measurement report](measurements-o08-smoke-bind-layout.json). | Native-window timing, Windows/DX12 and another-adapter pipeline/layout validation. |

## Decision summary

Keep lazy allocation, direct normal/depth reuse and capability-gated Rg16Float
selection in the implemented path because they have exact fixed-tick evidence and
reduce known allocations without depending on a timing claim. Keep compact HDR and
the optical overlay as independent opt-in experiments. Do not combine their
individual deltas into a promoted default: the O06×O08 factorial is one high-output
scene on one adapter, and its temporal and portability gates remain open.

The per-emitter smoke configuration is now uploaded only for simulation
dispatches; render-only global updates no longer rewrite the config ring. Exact
tick-120 output parity and three alternating 120-second clearing-orbit pairs
confirm the cleanup. Median CPU-upload time is lower by 0.007–0.009 ms, while
whole-frame p95 varies and GPU-render time is flat, so this is not recorded as a
throughput gain. See [the upload study](measurements-o08-smoke-config-upload.json).

The render `Globals` buffer is also no longer rewritten during smoke simulation:
the compute shader reads its tick inputs from the source-local configuration and
does not consume group 0. The render pass still uploads `Globals` once per frame.
Three alternating 120-second clearing-orbit pairs and a byte-identical tick-120
capture confirm reduced upload work without a consistent full-frame or GPU-render
improvement. Keep this cleanup, but make no throughput claim. See
[the Globals upload study](measurements-o08-globals-upload.json).

Evidence: [measurements-o08.json](measurements-o08.json),
[measurements-o06-o08-factorial.json](measurements-o06-o08-factorial.json), and
[O01-O08 follow-up plan](O01-O08_FOLLOWUP_PLAN.md). The O08 umbrella remains open
until native-window and target-adapter fallback/render checks are complete.
