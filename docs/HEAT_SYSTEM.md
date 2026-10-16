# A small thermal model for procedural smoke

Design proposal, 16 October 2026. Existing code carries a temperature-like scalar;
the model and authoring controls below are next work, not shipped schema fields.

## Start from what already exists

`smoke.wgsl` stores density and a temperature-like value in a 48×64×48 texture.
Both are advected; the latter adds upward velocity. They currently share one
dissipation rate. The inked billows are generated mostly from age, a global
buoyancy setting and wind, using grid density to gate presence. Their visible
motion and growth do not yet follow the evolving local heat.

Use relative excess heat above ambient, not Kelvin/Celsius or claims of physical
fire accuracy. Independent cooling and smoke-dissipation rates are essential:
cooling smoke should remain visible while its upward acceleration diminishes.

## Minimal behaviour model

1. Emit density and heat from the same authored source region. Keep heat output
   and soot yield independent so a hot clean fire and a dirty fire can differ.
2. Advect heat with smoke and wind. Cool heat towards ambient over time; mixing
   with surrounding air accelerates that cooling. Density dissipates separately.
3. Sample local heat for each persistent large billow. Heat adds upward
   acceleration; drag bounds speed and draws motion towards the shared wind.
   A cooling billow can keep rising through inertia before drifting more with
   wind. Do not force it to sink as soon as heat reaches ambient.
4. Entrain air as billows move. Increase radius gradually and reduce opacity as
   the same smoke mass occupies more volume. Keep density loss distinct from
   expansion, and keep artist controls for silhouette exaggeration.
5. Give the shared flow a few coherent rolling motions. Heat and motion can
   influence curl strength, while each billow and its attached children retain
   stable identities. This emulates characteristic motion; it is not a pressure
   solve, turbulence model or complete combustion simulation.
6. Light the visible body with external firelight, sky fill and shared occlusion.
   Heat can enable limited near-flame emission above an artistic threshold;
   warm smoke colour should usually come from firelight. Cooling must not make
   the whole plume switch abruptly from glowing orange to flat purple.

Illustrative update, with tunable artistic coefficients:

    heat *= exp(-cooling_rate * dt)
    velocity += up * buoyancy * sampled_excess_heat * dt
    velocity = mix(velocity, local_wind, 1 - exp(-drag * dt))
    position += velocity * dt
    radius += entrainment_rate * dt
    density = smoke_mass / billow_volume

These equations explain the model rather than prescribe exact implementation.
The grid and visible billows should use the same source/heat convention. Avoid
cooling twice by independently treating both a sampled grid heat and a second
unrelated heat clock as authoritative. Retain finite bounds and fixed steps.

## Cheap engine implementation

Keep the existing coarse density/heat grid. Add separate validated cooling,
thermal buoyancy, drag and entrainment settings through schema/Session/inspector.
First validate that the grid creates the intended rise/cool/spread behaviour.

Then move parent billow state into a bounded GPU storage buffer. Update it once
per simulation tick in a small compute pass: position, velocity, radius, age and
cached local heat/density. Render from those records instead of rebuilding all
billow positions for every pixel. Small attached lobes can inherit their parent
state and use stable seeded offsets; they need not each run a thermal simulation.
No per-frame GPU-to-CPU field readback is required. Captures retain fixed ticks,
seed and source data, and reset clears both the grid and billow buffers.

The render path keeps bounded ellipsoid tests/local normal blending initially.
Many-source scaling additionally requires emitter/instance culling and rasterised
bounds or tile lists. Heat alone does not solve that cost. Expose active cells,
parent/child counts and compute/render timings; keep the selected pixel grid.
Measure the new pass before claiming an acceptable budget.

## Different fire sizes

- Campfire: small heat/soot source, intermittent billow groups, restrained
  expansion and lower-plume glow. Smoke can be thin even when flame is bright.
- Bonfire: larger source area and thermal input, larger coherent billows and
  stronger rolling rise. Wider lighting and more dense overlap.
- Burning area/object: several correlated source regions feeding a shared
  atmosphere, coalescing groups, broad crown and local hot pockets. Preserve
  dark folds and cooler upper smoke rather than scaling a single candle.

Expose source extent and heat/soot production separately from effect quality.
Use presets in JSON, not scale-specific branches spread through shaders.
The current runtime supports one emitter; multiple source regions/presets are
part of this proposal and require implementation and validation.

## Acceptance

Use fixed-seed tests for zero heat, high heat, strong cooling, wind and expanded
sources. Confirm cooling changes lift while smoke remains; growth thins smoke;
wind and children stay coherent; reset/replay remains repeatable. Review motion
and silhouettes at three fire scales, then measure close high-coverage smoke
and many sources separately. Check actual Metal and DX12 rendering. This model
is intended to emulate useful thermal behaviour cheaply, not certify physics.
