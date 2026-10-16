# Game-authored fire effects

An emitter chooses a stable `effect_profile` ID from the scene's `effects` array.
Profiles are data: a game can change their proportions, pace, emission, palette
and thermal behaviour without changing engine shaders. The example scene supplies
`effect-campfire`, `effect-quiet` and `effect-bonfire`. These are starting points,
not approved final art or different physical solvers.

```sh
cargo run --release -p engine-lab -- run --effect-profile effect-quiet
cargo run --release -p engine-lab -- capture --effect-profile effect-bonfire --camera hero --tick 300
python3 scripts/capture_motion.py --profile effect-campfire --gif
```

Motion capture writes fixed-tick PNG frames, complete capture provenance and a
sequence manifest. Optional GIF/APNG previews require Pillow; the PNG sequence
has no Python image-library dependency. Default previews are six seconds at
20 fps, not a seamless loop or evidence of native frame pacing.

## Authoring contract

Use `engine-lab describe` for the authoritative schema and ranges. Profile fields
can be changed live through the same Session operations as the inspector:

```json
{"id":1,"method":"set_parameter","params":{"path":"effects.effect-campfire.fire.motion_speed","value":0.4}}
{"id":2,"method":"set_parameter","params":{"path":"effects.effect-campfire.fire.fragment_rate","value":0.8}}
{"id":3,"method":"set_parameter","params":{"path":"effects.effect-campfire.palette.hot","value":[5,2.8,0.75]}}
{"id":4,"method":"set_parameter","params":{"path":"effects.effect-campfire.thermal.cooling_rate","value":1.1}}
{"id":5,"method":"set_parameter","params":{"path":"emitters.campfire.effect_profile","value":"effect-quiet"}}
{"id":6,"method":"reset","params":{"seed":42}}
```

| Group | Controls | Purpose |
|---|---|---|
| `fire` | `width`, `height`, `motion_speed`, `curl` | Nominal world-space proportions and slower/faster licking motion |
| `fire` | `edge_breakup`, `tip_breakup`, `fragment_size` | Advected silhouette erosion, upper-tongue pinching and detached-piece proportions |
| `fire` | `tongues`, `segments` | Curve detail budget, independent of pixel resolution |
| `fire` | `fragment_rate`, `fragment_lifetime` | Pieces leaving the flame tips and cooling as they drift |
| `fire` | `ember_rate`, `ember_lifetime` | Seeded ember births, drag/drift, cooling and fade |
| `fire` | `emission` | HDR flame radiance before tone mapping |
| `palette` | `outer`, `warm`, `hot` | Linear HDR RGB colours, including values above one |
| `thermal` | `heat_output`, `cooling_rate`, `lift` | Source heat and advected thermal buoyancy, separate from smoke density dissipation |

`motion_speed` scales fire/fragment/ember effect time, not the engine's 60 Hz
clock or the rest of the scene. Rates and particle lifetimes use effect seconds.
Point-light flicker and source-heat modulation share the fire's slower envelope.
Steady wind affects all effects; the connected-motion experiment adds shared gusts.
Reset after heat/profile changes for reproducible A/B comparisons: live edits
preserve the already-advected smoke field. Existing version-1 scenes without
profiles receive a default profile; unknown IDs and invalid fields fail validation.

Pixel treatment is separately authored in `render`: selected scene resolution,
`palette_strength`, `shading_steps`, `dither_strength`, `bloom_strength` and exposure.
The world, camera, depth and simulation remain 3D. HDR lighting is evaluated before
colour treatment and nearest-neighbour presentation. Output is tone-mapped SDR;
this is not an HDR-display output mode. No automatic resolution change is made.
The small bloom kernel uses nine HDR taps at a fixed radius on the selected grid.

## Smoke light gradients

Point lights supply a continuous radial falloff from their world-space position,
with softened inverse-square attenuation and a smooth cutoff at `range`.
Scenes accept one directional light and 1..8 point lights. The point light at the
emitter position is the primary fire light and casts geometry shadows. Additional
point lights illuminate geometry and smoke but do not have geometry shadow maps.
Smoke chooses its nearest two active in-range sources at each shading sample;
each contribution is attenuated along its path through the shared density grid.
Six absorption samples per selected light are used for inked smoke, three for
soft volume smoke. This is a bounded approximation, not multiple scattering.
Light selection can change when three or more sources compete; no temporal
filtering/transition guarantee is claimed for that case yet.

Rounded puff normals modulate local form, while brightness/colour follow light
position, intensity and range instead of smoke age. Shared absorption and contact
shading darken folds. Optional internal emission now samples advected heat rather
than adding a uniform glow to the whole plume. `lights.<id>.position`, `range`,
`color` and `intensity` are validated live controls. The primary source position
must stay bound to the fire emitter; auxiliary sources can be repositioned.

## Runtime design and limits

`effects.rs` samples bounded world-space flame curves and event trajectories from
profile, seed, source, wind and fixed tick. It reconstructs deterministic state
rather than reading pixels or depending on presentation FPS. Source parameters
and per-event seeds remain stable during an effect. A cache uploads one compact
storage buffer when those inputs change; repeated paused renders/camera moves
reuse it. Event birth positions follow the corresponding tongue tip at birth.
Fragments retain their launch direction; embers relax towards wind with drag.

Rendering analytically intersects elongated ellipsoid segments and particles.
Bounds reject missed effects/segments, and opaque world/smoke depth clips them.
A continuous radial heat profile avoids a separate hot spot at each segment join.
Material-space noise moves slowly up the flame to erode its outer edges; upper
segments also pinch over time. This breakup is coherent in world space and can
be disabled per profile. Detached pieces flicker separately from the slower
main tongue motion. Emission is accumulated with a homogeneous-medium approximation rather than an
expensive per-pixel flame surface search. Inked and soft-smoke treatments share
this fire path. Shared simulation data is independent of both camera projection
and the selected pixel buffer.

Limits: 16 tongues × 10 segments, 16 fragments and 64 embers, within a 256-record
buffer (12,336 bytes). When requested event occupancy exceeds a pool, birth rate
is reduced to preserve full lifetimes. Quality choices are explicit; the engine
does not silently change pixel density. Diagnostics expose primitive/fragment/
ember counts, capped event occupancy and the last effect-update CPU duration.

This is a procedural thermal approximation, not combustion chemistry or a full
fluid solver. Smoke heat now cools separately from density and contributes to
advection lift. The stylised smoke billows still follow their existing paths;
heat-driven persistent billow motion remains further work. Soft-volume fire/
smoke compositing uses coarse absorption and approximate emission ordering.
The current scene contract still supports one emitter. Many-emitter batching,
tile culling and shared sparse simulation require their own implementation and
stress qualification; the fixed pool alone does not prove large-world scalability.
