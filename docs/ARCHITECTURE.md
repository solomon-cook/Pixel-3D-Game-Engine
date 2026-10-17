# Architecture

## Ownership and data flow

`pixel-engine` owns validated scene data, asset decoding, simulation signals,
GPU resources and shared Session operations. `engine-lab` owns process arguments,
native window lifecycle, the inspector and stdin/stdout transport.

Scene JSON -> validation -> shared local mesh/texture upload -> Session.
Asset loading keys reusable non-indexed meshes by complete geometry description
and material ID. Stable per-object identities, local-to-world transforms and
conservative world-space bounds remain alongside those shared ranges. Each camera
and each shadow frustum culls independently; unknown bounds stay visible, so an
object outside the camera can still cast a visible shadow. Consecutive compatible
instances batch in scene order. The Session exposes independent culling and
instancing switches for exhaustive reference comparisons.
Each fixed step submits smoke advection into ping-pong density/temperature volumes.
Each render reuses valid directional/point shadow maps or redraws them after a
relevant scene revision, builds bounded screen-tile candidate lists with an
exhaustive overflow fallback, then submits HDR opaque geometry, volumetric
fire/smoke/embers, and colour treatment into an sRGB pixel buffer.
The native host presents that buffer at an integer physical-pixel scale and draws
the inspector at display resolution. Captures read the same pixel buffer.

Opaque materials may opt into a bounded gameplay heat cue through
`heat_response`. The world shader samples the current fixed-step temperature
volume 0.45 world units above the surface only for responsive materials, then
applies a stepped warm shift and pixel edge accent before the existing colour
treatment. It shares the simulation volume and render pass: no GPU readback,
extra solver, or pixel-grid change.

GPU resource ownership is explicit in Renderer. Device/queue never live in a
global singleton. Render passes are explicit and ordered; a general render graph
will be added only when effects require one.

## Simulation

The simulation rate is 60 Hz. Seeded signals drive flicker and optional wind gusts.
Smoke uses semi-Lagrangian advection, buoyancy, turbulence, source injection and
exponential dissipation in a bounded GPU grid. This is an artistic simulation,
not a full incompressible fluid solve. Flames and embers are procedural functions
of seed/time and emitter state; wind coupling is independently switchable. The default inked renderer represents smoke with the
original large ellipsoid puffs plus a bounded set of smaller attached spheres.
Their presence follows the evolving density field. Child geometry overlaps each
parent and shares its shading to read as a single billow. Parent and child sizes
vary deterministically. Nearby surface intersections blend normals locally and
reduce internal ink. Each puff retains rounded shading, while six density samples
toward the fire estimate shared self-shadowing. Cool soot colour remains when
firelight is occluded; internal emission is separately controllable. This is a
bounded approximation to metaball contacts, not exact smooth-union geometry.
Volume bounds and conservative parent/child bounds skip missed intersections. This is an artistic
surface representation of the volume, not a replacement fluid solver.

## Reusable effect profiles

Scene `effects` profiles own fire motion/budget, thermal settings and HDR palette;
emitters refer to them by stable ID. `effects.rs` reconstructs bounded world-space
curves/fragments/embers from seed and fixed tick. A cached storage buffer is
shared by the inked and soft volume render paths, with analytic intersections
and bounds/depth rejection. Fire geometry is not rebuilt by a ray-march search
inside every pixel. This remains a one-emitter prototype, with explicit budgets
and counters rather than a claim of arbitrary source scalability.

Smoke density and heat advect together but dissipate/cool independently. Source
heat and light flicker follow the same slow fire envelope. Profile switching
preserves the smoke field until reset. Colour bands, dither, exposure and bounded
HDR glow are presentation operations after world lighting. Up to eight local
point lights illuminate geometry; smoke evaluates radial falloff and volume
absorption from its two nearest active lights. Only the primary fire point
light has a geometry shadow map. See EFFECTS.md for
the public authoring contract and current approximations.

## Interface contract

`Session::execute` is the shared authoring API. UI controls and JSON requests
call it rather than directly editing render state. Live mutations are validated
against a cloned scene before committing. `set_object_transform` changes a stable
object ID by position, XYZ Euler rotation or positive scale, and advances that draw
range's transform revision. Topology, assets and resource changes still require a
restart in v1.

Commands in the window are drained between frames from both user events and
redraw events, so minimization cannot strand the command queue. Captures submit rendering and await readback before returning success.
Malformed requests return errors without ending the session. The window host
also accepts `shutdown`; headless serving exits on stdin EOF.

Shaders are loaded from an explicit directory; bundled releases include their
sources. Reload builds a replacement pipeline set inside a GPU validation scope.
Only a fully successful replacement is installed.

## Performance and portability

Frame reports distinguish CPU encoding, simulation submission, GPU rendering and
full offscreen work including GPU completion. GPU timestamps are optional;
unsupported adapters report absence rather than fabricated zero timings.
Timestamp writes use render-pass boundaries supported by Apple GPUs. Tile lists
currently target one bounded fire emitter and four candidate categories; a
compute-pass overflow flag switches each affected category to the exhaustive
shader loop. The renderer exposes a runtime exhaustive mode and forced-overflow
diagnostic, plus frame-tagged list-build and occupancy measurements. Multi-emitter
ownership and Windows DX12 validation remain open.

Backend selection is native Metal on macOS and DX12 on Windows. Dependency lock
and toolchain files make local and CI builds reproducible. CI tests compile and
package both hosts; hardware visual/performance acceptance is a separate gate.

## Optical materials

Scene materials now use a shared GPU storage table. Geometry stores a stable
material index plus relative vertex/GLB tint and roughness. Authoring changes
upload the table on the next render boundary; topology stays immutable. The
opaque pass preserves legacy material defaults. Optional optical surfaces use an
HDR/normal-depth snapshot, bounded SSR/environment fallback and single-layer
refractive background sampling. Their foreground smoke/fire integral is shared
with the atmosphere shader. All optical/material/shadow pipelines participate
in transactional reload. See MATERIALS.md for pass order and limitations.

The fire buffer also owns a capped derived-light list with stable particle event
identities. Flame geometry, particle movement and emission come from the same
fixed-tick reconstruction. Parent curves can sweep broad rounded lobes and grow
upward branch curves. Secondary geometry has an explicit budget that reserves
particle capacity. Geometry consumes at most 12 moving lights; smoke selects two
of these in addition to its two authored sources, using shared density absorption.
No GPU readback or additional per-particle shadow maps are required.

Solid flame coverage and colour bands are presentation controls on the existing
analytic curve intersections. An auxiliary atmosphere target records visible
effect depth and flame coverage. The post pass uses this plus world depth and
the current ping-pong temperature volume for bounded, integer-pixel heat
refraction. Its eight-sample hot-air column is world-space and wind-leaned;
depth checks protect foreground silhouettes and the visible fire. This shares
heat history without changing flame/particle reconstruction or allocating a
second thermal solver. The additional target participates in normal rendering,
capture and transactional shader reload.
