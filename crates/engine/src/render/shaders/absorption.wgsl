@group(1) @binding(0) var density:texture_3d<f32>;
@group(1) @binding(1) var density_sampler:sampler;
@group(1) @binding(2) var absorption_out:texture_storage_3d<rgba16float,write>;
@group(1) @binding(3) var secondary_density:texture_3d<f32>;

@compute @workgroup_size(4,4,4)
fn build_absorption(@builtin(global_invocation_id) id:vec3<u32>) {
    let dimensions=textureDimensions(absorption_out);
    if any(id>=dimensions) {return;}
    let primary_enabled=g.light_info.x>0u && g.point_lights[0].color_power.w>0.;
    let secondary_enabled=fire.source_origins[1].w>0.5 && fire.presentations[1].controls.x>0.;
    if !primary_enabled && !secondary_enabled {
        textureStore(absorption_out,vec3<i32>(id),vec4(0.));
        return;
    }
    let uv=(vec3<f32>(id)+vec3(0.5))/vec3<f32>(dimensions);
    var optical_depth=0.;
    if primary_enabled {
        let surface=mix(g.volume_min.xyz,g.volume_max.xyz,uv);
        let delta=g.point_lights[0].position_range.xyz-surface;
        let full_distance=length(delta);
        let distance=max(full_distance-0.25,0.);
        let direction=delta/max(full_distance,0.001);
        let ds=distance/8.;
        for(var i=0u;i<8u;i++) {
            let p=surface+direction*(f32(i)+0.5)*ds;
            let sample_uv=(p-g.volume_min.xyz)/(g.volume_max.xyz-g.volume_min.xyz);
            if all(sample_uv>=vec3(0.)) && all(sample_uv<=vec3(1.)) {
                optical_depth+=textureSampleLevel(density,density_sampler,sample_uv,0.).x*ds;
            }
        }
    }
    var secondary_optical_depth=0.;
    if secondary_enabled {
        let source=fire.source_origins[1].xyz;
        let source_min=source+vec3(-3.,-0.6,-3.);
        let source_max=source+vec3(3.,7.4,3.);
        let secondary_surface=mix(source_min,source_max,uv);
        let secondary_delta=source-secondary_surface;
        let secondary_full_distance=length(secondary_delta);
        let secondary_distance=max(secondary_full_distance-0.25,0.);
        let secondary_direction=secondary_delta/max(secondary_full_distance,0.001);
        let secondary_ds=secondary_distance/8.;
        for(var i=0u;i<8u;i++) {
            let p=secondary_surface+secondary_direction*(f32(i)+0.5)*secondary_ds;
            let sample_uv=(p-source_min)/(source_max-source_min);
            if all(sample_uv>=vec3(0.)) && all(sample_uv<=vec3(1.)) {
                secondary_optical_depth+=textureSampleLevel(secondary_density,density_sampler,sample_uv,0.).x*secondary_ds;
            }
        }
    }
    textureStore(absorption_out,vec3<i32>(id),vec4(optical_depth,secondary_optical_depth,0.,0.));
}
