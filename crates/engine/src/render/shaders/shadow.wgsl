@group(0) @binding(0) var<uniform> light_matrix: mat4x4<f32>;
struct ShadowVarying { @builtin(position) clip:vec4<f32>, @location(0) @interpolate(flat) material:u32 };
@vertex fn shadow_vs(@location(0) position:vec3<f32>, @location(7) material:u32,
    @location(8) model_0:vec4<f32>, @location(9) model_1:vec4<f32>, @location(10) model_2:vec4<f32>, @location(11) model_3:vec4<f32>)->ShadowVarying {
    let model=mat4x4<f32>(model_0,model_1,model_2,model_3);
    var v:ShadowVarying;v.clip=light_matrix*model*vec4(position,1.);v.material=material;return v;
}
@vertex fn shadow_vs_baked(@location(0) position:vec3<f32>, @location(7) material:u32)->ShadowVarying {
    var v:ShadowVarying;v.clip=light_matrix*vec4(position,1.);v.material=material;return v;
}
@fragment fn shadow_fs(v:ShadowVarying) {
    // Single-layer glass does not cast an opaque shadow. Coloured/caustic
    // shadows require a separate light-transmission representation.
    if transmission(materials[v.material])>0. {discard;}
}
