struct FirePrimitive {center_radius:vec4<f32>,axis_length:vec4<f32>,heat_kind:vec4<f32>};
struct ParticleLight {position_range:vec4<f32>,color_power:vec4<f32>,identity:vec4<u32>};
struct FireFrame {counts:vec4<u32>,bounds_min:vec4<f32>,bounds_max:vec4<f32>,lighting:vec4<u32>,lights:array<ParticleLight,12>,primitives:array<FirePrimitive,256>};
struct FirePresentation {outer:vec4<f32>,warm:vec4<f32>,hot:vec4<f32>,shape:vec4<f32>,pixels:vec4<f32>,controls:vec4<f32>};
struct FireFrameStorage {sources:array<FireFrame,2>,source_origins:array<vec4<f32>,2>,presentations:array<FirePresentation,2>};
@group(0) @binding(1) var<storage,read> fire:FireFrameStorage;

struct PointLight {position_range:vec4<f32>,color_power:vec4<f32>};
struct Globals {
    view_proj: mat4x4<f32>, inverse_view_proj: mat4x4<f32>, sun_matrix: mat4x4<f32>,
    camera: vec4<f32>, sun_direction: vec4<f32>, sun_color: vec4<f32>,
    ambient: vec4<f32>, fire_position: vec4<f32>, fire_color: vec4<f32>,
    sky: vec4<f32>, horizon: vec4<f32>, wind_time: vec4<f32>,
    volume_min: vec4<f32>, volume_max: vec4<f32>, params: vec4<f32>,
    resolution: vec4<f32>, experiments: vec4<f32>, simulation: vec4<f32>, effect_settings: vec4<f32>,
    thermal:vec4<f32>,fire_outer:vec4<f32>,fire_warm:vec4<f32>,fire_hot:vec4<f32>,presentation:vec4<f32>,optical_settings:vec4<f32>,
    fire_shape:vec4<f32>,fire_pixels:vec4<f32>,light_info:vec4<u32>,point_lights:array<PointLight,8>,
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

// Shared bounds for the deterministic ink-smoke parent candidates. This is
// consumed by both the per-pixel intersection path and the tile-list builder.
fn smoke_lobe_bounds(index:u32)->vec4<f32> {
    let layer=f32(index/3u);let branch=f32(index%3u);
    let time=g.wind_time.w;let source=g.fire_position.xyz;
    let age=fract(time*0.125-layer/12.)*8.;
    let phase=hash(vec3(layer,branch,g.params.z))*6.28318;
    let spread=0.12+age*0.09;let rising=age*(g.simulation.x*0.72+0.2);
    let gust=select(g.wind_time.xyz,wind_at(source+vec3(0.,rising,0.)),g.experiments.z>0.5);
    let parent=source+vec3(cos(phase+age*0.35)*spread,rising+0.65,sin(phase+age*0.35)*spread)+gust*age*0.72;
    let bound=(0.27+age*0.095)*1.12*max(1.1,0.93+g.effect_settings.y*1.16);
    return vec4(parent,bound);
}

fn point_falloff(p:vec3<f32>,light:PointLight)->f32 {
    let d=length(p-light.position_range.xyz);let edge=clamp(1.-pow(d/light.position_range.w,4.),0.,1.);
    return edge*edge/(1.+d*d*0.65);
}

fn particle_light_point(i:u32)->PointLight {return PointLight(fire.sources[0].lights[i].position_range,fire.sources[0].lights[i].color_power);}
