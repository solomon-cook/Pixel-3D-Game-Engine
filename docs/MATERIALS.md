# Materials in the pixel world

Materials are evaluated in linear HDR on real 3D surfaces, before palette
quantisation, dithering, glow and integer presentation. Those style controls stay
independent. This is an original, deliberately bounded raster implementation;
material values are artistic controls rather than a calibrated spectral model.

Run the comparison scene:

```sh
cargo run --release -p engine-lab -- run --scene assets/scenes/materials.json
cargo run --release -p engine-lab -- capture --scene assets/scenes/materials.json --camera glass-close --tick 300
cargo run --release -p engine-lab -- benchmark --scene assets/scenes/materials.json --route material-orbit --duration 120 --warmup 10
python3 scripts/material_study.py
```

The back row, left to right, is chrome / copper / green wax. The front row is
blue glazed ceramic / clear glass / amber frosted glass. A thin green panel
beside the wax compares backlighting on a flat surface. Striped emissive panels
behind the glass give refraction an actual scene to distort. The dark floor also
reflects scene objects. Named cameras: `hero`, `metal-close`, `glass-close`,
`subsurface-close`, `orthographic`. This diagnostic scene is not final game art.

## Authoring

Every scene material has these live fields, with old V1 scenes receiving defaults:

| Field | Default / bounds | Effect |
|---|---|---|
| `color` | required, linear RGB 0..64 | Diffuse colour, conductor reflection tint, transmission tint |
| `roughness` | 0.8 / 0..1 | Highlight width, reflected/transmitted image blur |
| `emission` | 0 / 0..64 | HDR self illumination; does not itself create a point light |
| `metallic` | 0 / 0..1 | Suppresses diffuse; makes specular reflection take the base colour |
| `reflectivity` | 0 / 0..1 | Environment/screen reflection strength on non-metals |
| `transmission` | 0 / 0..1 | Replaces diffuse with refracted background; suppressed by metallic |
| `ior` | 1.5 / 1..2.5 | Dielectric Fresnel and refraction; 1 gives no bending |
| `thickness` | 0.25 / 0..10 world units | Approximate optical path for refraction, absorption and backlight |
| `absorption` | [0,0,0] / RGB 0..64 | Per-world-unit colour extinction, exponential with path length |
| `subsurface` | 0 / 0..1 | Wrapped diffuse plus transmitted backlight |
| `scatter_color` | [1,1,1] / RGB 0..64 | Colour of faux subsurface light |
| `heat_response` | 0 / 0..1 | Opt-in stepped warm tint and pixel edge cue from the existing simulated temperature field |

Thickness is authored, not measured from back faces, and does not automatically
change when an object's scale changes. Use material variants for different
thicknesses. The inspector's Materials section and JSON operations use the same
validated transaction. Material edits upload a small GPU table once on change;
they do not reload meshes/textures or reset simulation. IDs, texture paths and
material/geometry topology remain startup data. The table supports 256 authored
materials plus an internal procedural bark entry.

```json
{"id":"bottle-green","color":[0.85,1,0.9],"roughness":0.12,"transmission":0.95,"ior":1.5,"thickness":0.6,"absorption":[0.9,0.08,0.5]}
```

```json
{"id":1,"method":"set_parameter","params":{"path":"materials.glass.thickness","value":0.8}}
{"id":2,"method":"set_parameter","params":{"path":"materials.copper.roughness","value":0.5}}
{"id":3,"method":"set_parameter","params":{"path":"render.reflection_steps","value":8}}
{"id":4,"method":"set_parameter","params":{"path":"materials.earth.heat_response","value":0.8}}
```

`heat_response` applies only to opaque world shading. It samples the existing
smoke temperature volume 0.45 world units above the surface; it is an artistic
gameplay cue, not a calibrated temperature or damage value. Zero skips the sample and
preserves the previous material appearance. Positive values add a stepped warm
shift and a small edge accent before palette quantisation. The field and pixel
grid are shared with the existing simulation and presentation passes.

Procedural `sphere` keeps existing faceted rocks. `smooth_sphere` provides smooth
vertex normals for material studies. PNG/GLB base-colour textures still use the
128² nearest-filtered atlas. Static GLB base-colour and roughness factors multiply
the scene material; the advanced parameters come from scene JSON. Importing
KHR material extension data, metal/roughness/normal maps and alpha coverage is
outside this implementation. A GLB with an OPAQUE alpha mode can use a scene
transmission material; alpha BLEND/MASK assets remain rejected explicitly.

## Rendering and cost

1. Render directional/primary point shadows. Transmissive materials skip opaque
   shadow casting; opaque scenes keep the cheaper vertex-only shadow pipeline.
2. Render opaque material lighting, including optional subsurface wrap/backlight.
   Direct specular uses a GGX-style microfacet response and Schlick Fresnel for
   optical materials; unchanged diffuse materials keep the original response.
3. Composite fire/smoke, then snapshot HDR colour and opaque normal/depth.
4. Resolve optical surfaces against that snapshot. The vertex shader clips
   non-optical materials out of this pass. Metals/dielectrics use bounded SSR
   with sky/ground/sun fallback. Glass samples a refracted background with
   roughness blur and Beer-Lambert absorption. Foreground atmosphere is evaluated
   to the surface, removed approximately from the transmitted image, then
   composited once over the result. Opaque foreground smoke hides the surface.
5. Apply the existing pixel treatment and nearest-neighbour presentation.

`render.reflection_steps` is 0..16; zero uses only environment reflections. A hit
uses at most four refinements. Rough surfaces above 0.72 bypass SSR. Blur uses at
most five colour reads. No temporal history, ray tracing acceleration structure,
full-resolution effect buffer or diffusion simulation is needed. Two HDR-sized
snapshot buffers cost 16 bytes per scene pixel (about 3.52 MiB at 640×360).
The extra draw and copies are skipped when all metallic/reflectivity/transmission
values are zero. Subsurface alone stays in the opaque pass. No automatic change
to the chosen pixel grid occurs. Foreground atmosphere work grows with covered
optical pixels; compare costs with the supplied fixed-route study.

## Deliberate limits

- SSR sees only the first opaque layer visible on screen and a finite ray length.
  Missing geometry fades to an analytic environment, not an off-screen scene
  probe. Fire is represented in that colour snapshot but has no opaque geometry
  depth for an SSR hit. Its local light still creates specular highlights.
- Roughness blur and environment filtering are approximations. Screen edges and
  newly exposed geometry can cause reflection changes during camera movement.
  Fixed-grid rendering has no history ghosting, but also no temporal denoising.
- Transmission resolves the nearest front-facing entry surface of closed meshes.
  Other transparent objects are not present in its background. Nested glass,
  camera-inside-glass and arbitrary intersecting transparent shells need a future
  layered solution. There are no caustics, dispersion or coloured glass shadows.
  Partial transmission currently skips opaque shadows entirely.
- Foreground atmospheric subtraction uses the current pixel's integral. Strong
  refraction across a smoke silhouette can still have compositing artefacts.
  This is not a refracted volumetric ray integration.
- Faux subsurface uses authored thickness and a few existing shadow lookups, not
  multiple scattering or spatial diffusion. Offset shadow tests approximate thin
  body backlighting; large thicknesses can admit light around nearby occluders.
- Metal captures/checks do not verify Windows DX12 images or target base-M1/RTX
  3060 performance. Human approval of material style remains open.

## Prior methods

These references informed the independently implemented models, not copied engine
code: [Filament material/BRDF documentation](https://google.github.io/filament/main/filament.html),
[Khronos transmission](https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_materials_transmission)
and [Khronos volume attenuation](https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_materials_volume).
Our bounded SSR, artistic subsurface approximation and composition limits are
engine decisions; these references do not certify this renderer as glTF compliant.
