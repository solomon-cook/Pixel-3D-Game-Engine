@group(1) @binding(0) var<storage,read_write> projected_bounds_out:array<vec4<f32>>;

fn project_fire_bounds(center:vec3<f32>,radius:f32)->vec4<f32> {
    let full_view=vec4<f32>(0.,0.,g.resolution.x,g.resolution.y);
    if !all(center==center) || !all(abs(center)<vec3(1e20)) || !(radius>=0.) || !(radius<1e20) {return full_view;}
    if g.camera.w<0.5 && distance(center,g.camera.xyz)<=radius {return full_view;}
    var min_pixel=vec2<f32>(1e20);var max_pixel=vec2<f32>(-1e20);
    for(var corner=0u;corner<8u;corner++) {
        let sign=vec3<f32>(select(-1.,1.,(corner&1u)!=0u),select(-1.,1.,(corner&2u)!=0u),select(-1.,1.,(corner&4u)!=0u));
        let clip=g.view_proj*vec4(center+sign*radius,1.);
        if !(clip.w>0.) {return full_view;}
        let ndc=clip.xy/clip.w;
        if !all(abs(ndc)<vec2(1e20)) {return full_view;}
        let pixel=vec2((ndc.x*0.5+0.5)*g.resolution.x,(0.5-ndc.y*0.5)*g.resolution.y);
        min_pixel=min(min_pixel,pixel);max_pixel=max(max_pixel,pixel);
    }
    return vec4(min_pixel,max_pixel);
}

@compute @workgroup_size(64)
fn build_fire_projected_bounds(@builtin(global_invocation_id) id:vec3<u32>) {
    if id.x>=512u {return;}
    let source=id.x/256u;let index=id.x%256u;
    if index>=fire.sources[source].counts.x {
        projected_bounds_out[id.x]=vec4<f32>(0.);
        return;
    }
    let primitive=fire.sources[source].primitives[index];
    projected_bounds_out[id.x]=project_fire_bounds(
        primitive.center_radius.xyz,
        max(primitive.center_radius.w,primitive.axis_length.w)
    );
}
