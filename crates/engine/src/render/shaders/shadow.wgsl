@group(0) @binding(0) var<uniform> light_matrix: mat4x4<f32>;
struct ShadowVarying { @builtin(position) clip:vec4<f32>, @location(0) @interpolate(flat) material:u32 };
@vertex fn shadow_vs(@location(0) position:vec3<f32>, @location(7) material:u32)->ShadowVarying {
    var v:ShadowVarying;v.clip=light_matrix*vec4(position,1.);v.material=material;return v;
}
@fragment fn shadow_fs(v:ShadowVarying) {
    // Single-layer glass does not cast an opaque shadow. Coloured/caustic
    // shadows require a separate light-transmission representation.
    if transmission(materials[v.material])>0. {discard;}
}
