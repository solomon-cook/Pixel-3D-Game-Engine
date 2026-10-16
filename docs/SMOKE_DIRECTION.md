# Procedural fire and smoke: reference direction

Design analysis, 16 October 2026. This describes the next art/rendering pass;
proposed controls and multi-scale emitters are not implemented schema fields.
Current capabilities and remaining qualification gates are in STATUS.md.

## What the supplied image shows

The car-fire reference is useful for its visual structure, not as a universal
smoke brightness or a prescribed camera/output size. The landscape references
continue to describe apparent pixel density only. No reference art is bundled.

- A connected, asymmetric cloud silhouette with a hierarchy of large billows,
  medium folds and a few small edge curls. Several round forms combine into a
  mass; smaller details are not evenly distributed around every parent.
- Deep dark pockets alongside broad orange/coral illuminated areas, with pale
  hot patches concentrated lower in the plume. Shadows make neighbouring lobes
  belong to one body, while a few selected contour lines preserve their form.
- Fire has a large, connected hot base and irregular forked tongues, holes and
  detached fragments. Its orange edges and smoke transition make the pale core
  readable. It is not just one uniformly pale candle shape.
- Halftone supports broad colour shapes; it is not a substitute for those shapes.
- This is a still. Curling forms suggest a useful motion direction, but the image
  alone does not establish an animation cadence or a simulation method.

## Where the current renderer differs

The latest baseline keeps the approved large puffs and attached smaller bubbles.
It adds local normal blending, reduced internal ink and approximate shared
firelight absorption. Those changes address contact shading, not the whole look.

The current generation still schedules three puffs at each common age/height,
with regular layer spacing. Parent proportions and child counts vary, but the
stacked cadence remains obvious. Children occupy roughly ring-like attachments.
Large dark front faces and narrow bright lower bands still read like shaded
balls. Smoke colour is mostly age/facing based. The point-source campfire does
not supply the broad and partly internal illumination visible in the car fire.
The fire silhouette is narrow and its light core occupies too much of its body.

## Next pass, in order

1. **Change the generation rhythm.** Keep round billows but emit coherent groups
   at staggered seeded times/positions. Use a small number of dominant billows,
   varied proportions and offset overlap, without periodic horizontal tiers.
   Give each billow persistent identity, growth, velocity and a curl direction.
   Avoid randomising shape anew each frame or spraying disconnected small blobs.
2. **Attach structure to flow.** Place medium folds and small bubbles preferentially
   on rolling/shearing edges. Let them grow with and rotate around their parent.
   Derive large/small scales from the emitter and coarse flow, rather than adding
   equal bead rings to all spheres. Blend locally at contacts; preserve the
   readable large rounded forms the owner liked.
3. **Separate lighting causes.** Keep per-billow rounded normals, shared smoke
   occlusion, sky fill and temperature-driven internal emission as separate
   inputs. Use broad warm patches, cooler dark pockets and selective interior
   lines. Do not average every normal or make the whole plume uniformly glow.
   Large fires need a few shared emitter-area light samples rather than scaling
   a single point source indefinitely. External firelight must still be blocked
   in folds even if a surface's local normal faces the fire.
4. **Connect fire to smoke.** Use heat/soot signals from the same emitter and wind
   field. Produce a connected flame base, varied tongues and a few peel-off
   fragments. Keep yellow/pale cores, orange edges and cooling smoke readable.
   Let the flame-to-smoke transition carry heat upward instead of separating a
   pale flame from an unrelated purple puff stack.
5. **Review all scales together.** Establish the small campfire first, then test
   a bonfire and a wide burning source. Keep the same style grammar, but author
   distinct source geometry, density, billow rhythm and lighting balance.

## Scale is a family of behaviours

| Source | Shape and generation | Light/colour behaviour |
|---|---|---|
| Small campfire | Narrow, intermittent source; a few restrained billows and small curls; modest smoke opacity | Distinct tongues, limited lower-smoke warmth, sky visible through thinner regions |
| Bonfire | Wider connected base; denser overlapping billow groups; stronger upward roll and spreading crown | More lower-plume illumination, dark folds, occasional hot pockets |
| Broad burning object/area | Several correlated source patches; coalescing columns and a broad irregular crown | Distributed firelight, locally hot smoke, deep cooler interior and upper soot |

A clean hot campfire should not be forced to emit car-fire quantities of soot.
Keep smoke production and heat independently authorable. Source width changes
birth locations, billow sizes and merge distance; it must not simply scale the
same narrow candle mesh. Larger billows should have a deliberate slower motion
cadence unless overridden. Wind, heat and the art preset can alter that choice.

Proposed authoring controls: source shape/extent, heat, soot yield, billow size
range/growth, emission cadence, cohesion, curl, wind response, palette and internal
emission. These are a design proposal, not valid scene fields until added to
`describe`, schema validation, shared Session operations and inspector controls.
Presets should be explicit JSON data with stable emitter IDs and deterministic
seeds. Physical scale and artistic exaggeration should be separate controls.

## Keep the rendering cost bounded

The near-term path remains analytic puff caps, local normal blending and coarse
shared smoke lighting. This is a metaball-like appearance, not exact reconstructed
metaball geometry. Do not add an all-puffs SDF search for every screen pixel.

For many sources, move puff transforms into bounded instance buffers and cull
emitters/tiles before drawing. Rasterise ellipsoid bounds into depth/normal data
and resolve local contacts/lighting only where smoke is visible. Maintain depth
ordering and depth discontinuities so unrelated distant clouds do not fuse.
A coarser shared density/light representation can provide internal occlusion;
its cost and approximation need separate measurement. Neither screen blending
nor low-resolution lighting should hide camera-dependent artifacts.

Choose smaller-lobe detail from projected size, with stable thresholds/hysteresis;
keep important silhouette lobes. Reduce detail/light samples independently of
the chosen pixel grid. Cap instance counts, active simulation cells and local
lights explicitly. Add counters so agents can identify which budget is exceeded.
The current one-emitter benchmark cannot establish many-emitter scalability.

## Evidence required before calling the next pass successful

- Matched seed/tick views: full silhouette, close contact shading, side/backlight.
- Motion: growth and curl without popping, bead-ring rotation or noisy crawling;
  slow camera orbit to expose contact and depth artifacts.
- Three source scales with a fixed selected pixel density and explicit settings.
- Controlled comparisons for hierarchy, contact blending, self-shadow and glow.
- A many-source stress scene as well as a smoke-filled close view; median/p95
  CPU/GPU timings, visible instance counts and pixel coverage where available.
- Actual Metal and DX12 renders and owner art review. Treat faster timing and
  visual resemblance as separate acceptance criteria.


The proposed heat/motion coupling is detailed in [HEAT_SYSTEM.md](HEAT_SYSTEM.md).
It reuses the existing temperature-like volume and makes visible billows respond
to it. It is design work; no new heat API is claimed by this document.
