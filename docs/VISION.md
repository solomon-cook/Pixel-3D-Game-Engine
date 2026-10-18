# Pixel Engine vision

Pixel Engine aims to be a standalone game engine for games whose identity comes
from deliberate pixel-scale 3D, expressive effects and authored simulation. The
goal is to find engine designs that make those styles efficient to create and
run, rather than treating them as a post-processing look applied to a generic
renderer.

## Design direction

### Pixel density is an artistic choice

Game makers should be able to choose the scene pixel density that fits their
game, and change it deliberately as part of the game's visual design. The
selected grid remains stable while rendering and effect quality are tuned;
performance work must not silently lower it. Effect budgets and detail can be
scaled independently.

### Rendering and simulation serve the style

The look is built into the engine's design. A selected low-resolution scene
buffer feeds 3D lighting, smoke, fire, materials and heat shimmer. These parts
should work together as one visual system, with game-authored controls for their
appearance and behaviour.

Artistic simulation and physics are part of the intended engine, not just visual
decoration. They should give developers expressive, predictable controls over
motion and interaction, while supporting the style of each game. The current
smoke, fire and ember systems are early examples, not the scope of the finished
simulation or physics model.

### The engine should be inspectable and reproducible

Readable scene data, named cameras, seeded fixed-tick simulation, captures and
benchmarks should make scenes understandable and results reproducible. The
headless renderer and native window should use the same session operations so
that inspection, automation and hands-on authoring describe the same engine.

Procedural generation should be a first-class engine capability. Developers
should be able to build rich, coherent game content from rules and parameters,
guide the results toward an authored style, and reproduce or inspect generated
results from their inputs and seeds. Generation should work with the rendering
and simulation systems as a whole, and remain practical to profile and optimize
at game scale.

### Novel approaches must earn their place

The engine should explore new ways to organize rendering, simulation, data and
authoring around the kinds of games it is meant to support. The aim is a highly
optimized system that delivers those visual styles, not novelty for its own
sake. Compare experiments against independently selectable baselines; record
visual changes, costs and limitations before adopting them.

## How to read this vision

This document describes direction, not a feature-completion claim. [Architecture](ARCHITECTURE.md)
and [status](STATUS.md) describe what exists and what remains unverified;
[research](RESEARCH.md) records experiments and their evidence; [TODO.md](../TODO.md)
tracks implementation work.
