@group(0) @binding(0) var<uniform> light_matrix: mat4x4<f32>;
@vertex fn vs(@location(0) position: vec3<f32>) -> @builtin(position) vec4<f32> {
    return light_matrix * vec4<f32>(position, 1.0);
}
