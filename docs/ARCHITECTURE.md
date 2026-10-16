# Architecture

## Ownership and data flow

`pixel-engine` owns validated scene data, asset decoding, simulation signals,
GPU resources and shared Session operations. `engine-lab` owns process arguments,
native window lifecycle, the inspector and stdin/stdout transport.

Scene JSON -> validation -> static mesh/texture upload -> Session.
Each fixed step submits smoke advection into ping-pong density/temperature volumes.
Each render submits directional/point shadow maps, HDR opaque geometry,
volumetric fire/smoke/embers, then colour treatment into an sRGB pixel buffer.
The native host presents that buffer at an integer physical-pixel scale and draws
the inspector at display resolution. Captures read the same pixel buffer.

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

## Interface contract

`Session::execute` is the shared authoring API. UI controls and JSON requests
call it rather than directly editing render state. Live mutations are validated
against a cloned scene before committing. Topology and resource changes require
a restart in v1. Stable IDs address objects within scene arrays.

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
Timestamp writes use render-pass boundaries supported by Apple GPUs.

Backend selection is native Metal on macOS and DX12 on Windows. Dependency lock
and toolchain files make local and CI builds reproducible. CI tests compile and
package both hosts; hardware visual/performance acceptance is a separate gate.
