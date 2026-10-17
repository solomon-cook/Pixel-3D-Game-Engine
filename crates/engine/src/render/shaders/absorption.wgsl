@group(1) @binding(0) var density:texture_3d<f32>;
@group(1) @binding(1) var density_sampler:sampler;
@group(1) @binding(2) var absorption_out:texture_storage_3d<rgba16float,write>;

@compute @workgroup_size(4,4,4)
fn build_absorption(@builtin(global_invocation_id) id:vec3<u32>) {
    let dimensions=textureDimensions(absorption_out);
    if any(id>=dimensions) {return;}
    if g.light_info.x==0u || g.point_lights[0].color_power.w<=0. {
        textureStore(absorption_out,vec3<i32>(id),vec4(0.));
        return;
    }
    let uv=(vec3<f32>(id)+vec3(0.5))/vec3<f32>(dimensions);
    let surface=mix(g.volume_min.xyz,g.volume_max.xyz,uv);
    let delta=g.point_lights[0].position_range.xyz-surface;
    let full_distance=length(delta);
    let distance=max(full_distance-0.25,0.);
    let direction=delta/max(full_distance,0.001);
    let ds=distance/8.;
    var optical_depth=0.;
    for(var i=0u;i<8u;i++) {
        let p=surface+direction*(f32(i)+0.5)*ds;
        let sample_uv=(p-g.volume_min.xyz)/(g.volume_max.xyz-g.volume_min.xyz);
        if all(sample_uv>=vec3(0.)) && all(sample_uv<=vec3(1.)) {
            optical_depth+=textureSampleLevel(density,density_sampler,sample_uv,0.).x*ds;
        }
    }
    textureStore(absorption_out,vec3<i32>(id),vec4(optical_depth,0.,0.,0.));
}
