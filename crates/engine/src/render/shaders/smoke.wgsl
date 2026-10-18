@group(0) @binding(0) var previous: texture_3d<f32>;
@group(0) @binding(1) var next: texture_storage_3d<rgba16float,write>;
@group(0) @binding(2) var linear_sampler: sampler;
struct SmokeSimulationConfig {
    volume_min:vec4<f32>,volume_max:vec4<f32>,fire_position:vec4<f32>,
    simulation:vec4<f32>,thermal:vec4<f32>,wind_time:vec4<f32>,
};
@group(0) @binding(3) var<uniform> source:SmokeSimulationConfig;
fn simulation_wind_at(p:vec3<f32>)->vec3<f32> {
    let t=source.wind_time.w;
    return source.wind_time.xyz+vec3<f32>(sin(p.y*1.7+t*1.9)*0.15,0.,cos(p.y*1.3+t)*0.12);
}
@compute @workgroup_size(4,4,4)
fn advect(@builtin(global_invocation_id) id:vec3<u32>) {
    let size=textureDimensions(next);if any(id>=size){return;}
    let uv=(vec3<f32>(id)+0.5)/vec3<f32>(size);
    let p=mix(source.volume_min.xyz,source.volume_max.xyz,uv);
    let old=textureSampleLevel(previous,linear_sampler,uv,0.);
    let wind=simulation_wind_at(p);
    let velocity=wind+vec3<f32>(sin(p.y*2.5+source.wind_time.w)*0.25, source.simulation.x+old.y*source.thermal.z, cos(p.x*2.+source.wind_time.w)*0.2);
    let back=uv-velocity*(1./60.)/(source.volume_max.xyz-source.volume_min.xyz);
    var density=textureSampleLevel(previous,linear_sampler,back,0.).xy;
    if any(back<vec3(0.)) || any(back>vec3(1.)) {density=vec2(0.);}
    density*=exp(-vec2(source.simulation.y,source.thermal.y)/60.);
    let delta=p-source.fire_position.xyz+vec3<f32>(0.,-0.1,0.);
    let source_scale=0.85/max(source.fire_position.w,0.05);
    let emission=exp(-dot(delta.xz,delta.xz)*14.*source_scale*source_scale-delta.y*delta.y*14.);
    density+=vec2(emission*source.simulation.z,emission*source.thermal.x*source.thermal.w)*source.simulation.w/60.;
    let boundary=smoothstep(0.,0.06,min(min(uv.x,1.-uv.x),min(uv.z,1.-uv.z)))*(1.-smoothstep(0.94,1.,uv.y));
    textureStore(next,id,vec4(density*boundary,0.,0.));
}
