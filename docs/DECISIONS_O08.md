# O08 candidate decisions

18 October 2026. This record separates the O08 memory/layout candidates so an
allocation or traffic reduction is not mistaken for a frame-time win. Measurements
are M1 Max/Metal unless stated otherwise. Known allocation excludes driver
padding, opaque query-set storage and transient implementation details; logical
traffic is a model, not measured DRAM bandwidth.

| Candidate | Current disposition | M1 Max/Metal evidence | Open acceptance |
|---|---|---|---|
| Lazy optical HDR snapshot | Retain as the normal allocation policy. Allocate on the first camera-visible optical batch; skip snapshot/copy/resolve before that point. Keep the resident texture after activation for later camera/material edits. | Saves 3,686,400 known bytes before visible optical use at 640×360. Offscreen optical edits do not allocate; turning the camera to the material allocates once. Matched fixed-tick output and reset/replay checks passed. | Native-window behavior and DX12/other-adapter resource lifetime and output. This is frustum gating, not occlusion culling. |
| Read-only opaque normal/depth reuse | Retain the direct read-only input; do not restore a second normal/depth snapshot or optical attachment. | Removes 1,843,200 known bytes from the prior snapshot pair and 7,372,800 modeled logical bytes per optical frame. Fixed-tick parity passed on the measured adapter. | Native-window and non-Metal pass ordering/resource validation; broader camera-inside and near-plane optics. |
| Adapter-gated Rg16Float targets | Retain capability-gated selection with Rgba16Float fallback. This includes effect-depth/flame coverage and smoke density/temperature volumes. | At 640×360, saves 921,600 bytes for effect coverage and 1,179,648 bytes for the two smoke volumes. M1 Max/Metal texture/pipeline creation, replay and matched image checks passed. Capability-selection tests cover the fallback branch logic. | Physical fallback rendering on an adapter lacking required features, plus DX12/other-adapter parity and timing. Unit tests do not prove fallback resource creation. |
| Compact Rg11b10Ufloat HDR | Keep experimental and disabled by default. | Saves 1,843,200 known bytes at 640×360. Material-route timing was only about 0.24% faster and does not establish a practical win. The O06×O08 high-output contact sheet looked close, but mean error was 0.21–0.72/255 and a sparse maximum reached 28/255. | Continuous temporal tolerance, more workloads, native-window and physical fallback/DX12 validation. |
| Optical no-copy overlay | Keep experimental and disabled by default, independently selectable from lighting reuse and HDR format. | RGBA16F fixed-tick captures were byte-identical to copy; the overlay replaces the snapshot with an equal-size output and alpha coverage. Earlier offscreen evidence found small GPU deltas. Three native 120-second pairs completed on M1 Max/Metal: paired optical-resolve deltas were -0.014, +0.023 and -0.043 ms; native FPS deltas were -0.155, +0.306 and +0.293 fps. Full native CPU-frame delta median was +0.028 ms. The signs vary and do not establish a reliable whole-frame improvement. The 1,843,200-byte snapshot is replaced by an equal-size output, so known allocation is unchanged. | Broader material/pass ordering, continuous visual review, other-adapter and DX12 validation. Compact HDR retains a 230,400-byte mask. Native measurement detail: [measurements-o08-native-no-copy.json](measurements-o08-native-no-copy.json). |

## Decision summary

Keep lazy allocation, direct normal/depth reuse and capability-gated Rg16Float
selection in the implemented path because they have exact fixed-tick evidence and
reduce known allocations without depending on a timing claim. Keep compact HDR and
the optical overlay as independent opt-in experiments. Do not combine their
individual deltas into a promoted default: the O06×O08 factorial is one high-output
scene on one adapter, and its temporal and portability gates remain open.

Evidence: [measurements-o08.json](measurements-o08.json),
[measurements-o06-o08-factorial.json](measurements-o06-o08-factorial.json), and
[O01-O08 follow-up plan](O01-O08_FOLLOWUP_PLAN.md). The O08 umbrella remains open
until native-window and target-adapter fallback/render checks are complete.
