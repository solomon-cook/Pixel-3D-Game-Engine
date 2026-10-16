struct Globals {
    view_proj: mat4x4<f32>, inverse_view_proj: mat4x4<f32>, sun_matrix: mat4x4<f32>,
    camera: vec4<f32>, sun_direction: vec4<f32>, sun_color: vec4<f32>,
    ambient: vec4<f32>, fire_position: vec4<f32>, fire_color: vec4<f32>,
    sky: vec4<f32>, horizon: vec4<f32>, wind_time: vec4<f32>,
    volume_min: vec4<f32>, volume_max: vec4<f32>, params: vec4<f32>,
    resolution: vec4<f32>, experiments: vec4<f32>, simulation: vec4<f32>, effect_settings: vec4<f32>,
};
@group(0) @binding(0) var<uniform> g: Globals;

fn hash(p: vec3<f32>) -> f32 { return fract(sin(dot(p, vec3<f32>(127.1,311.7,74.7))) * 43758.5453); }
fn noise(p:vec3<f32>) -> f32 {
    let i=floor(p); let f=fract(p); let u=f*f*(3.0-2.0*f);
    return mix(mix(mix(hash(i),hash(i+vec3(1.,0.,0.)),u.x),mix(hash(i+vec3(0.,1.,0.)),hash(i+vec3(1.,1.,0.)),u.x),u.y),mix(mix(hash(i+vec3(0.,0.,1.)),hash(i+vec3(1.,0.,1.)),u.x),mix(hash(i+vec3(0.,1.,1.)),hash(i+vec3(1.,1.,1.)),u.x),u.y),u.z);
}
fn wind_at(p:vec3<f32>) -> vec3<f32> {
    let t=g.wind_time.w;
    return g.wind_time.xyz + vec3<f32>(sin(p.y*1.7+t*1.9)*0.15,0.,cos(p.y*1.3+t)*0.12);
}
