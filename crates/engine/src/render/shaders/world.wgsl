@group(1) @binding(0) var sun_shadow: texture_depth_2d;
@group(1) @binding(1) var point_shadow: texture_depth_cube;
@group(1) @binding(2) var shadow_sampler: sampler_comparison;
@group(1) @binding(3) var atlas: texture_2d_array<f32>;
@group(1) @binding(4) var atlas_sampler: sampler;

fn sun_visibility(p:vec3<f32>, n:vec3<f32>) -> f32 {
    let q=g.sun_matrix*vec4<f32>(p+n*0.025,1.); let uv=q.xy/q.w*vec2<f32>(0.5,-0.5)+0.5;
    if any(uv<vec2(0.)) || any(uv>vec2(1.)) {return 1.;}
    return textureSampleCompareLevel(sun_shadow,shadow_sampler,uv,q.z/q.w-0.0015);
}
fn fire_visibility(p:vec3<f32>) -> f32 {
    let d=p-g.fire_position.xyz; let major=max(max(abs(d.x),abs(d.y)),abs(d.z));
    let far=g.point_lights[0].position_range.w;
    let depth=far/(far-0.05)-(far*0.05)/((far-0.05)*max(major,0.051));
    return textureSampleCompareLevel(point_shadow,shadow_sampler,d,depth-0.004);
}
struct VertexIn { @location(0) position:vec3<f32>, @location(1) normal:vec3<f32>, @location(2) color:vec3<f32>, @location(3) uv:vec2<f32>, @location(4) texture:f32, @location(5) emission:f32, @location(6) roughness:f32 };
struct Varying { @builtin(position) clip:vec4<f32>, @location(0) position:vec3<f32>, @location(1) normal:vec3<f32>, @location(2) color:vec3<f32>, @location(3) uv:vec2<f32>, @location(4) @interpolate(flat) texture:f32, @location(5) emission:f32, @location(6) roughness:f32 };
@vertex fn vs(v:VertexIn)->Varying {
    var o:Varying; o.clip=g.view_proj*vec4(v.position,1.);o.position=v.position;o.normal=v.normal;o.color=v.color;o.uv=v.uv;o.texture=v.texture;o.emission=v.emission;o.roughness=v.roughness;return o;
}
struct Output { @location(0) color:vec4<f32>, @location(1) normal_depth:vec4<f32> };
@fragment fn fs(v:Varying)->Output {
    let n=normalize(v.normal);let view=normalize(g.camera.xyz-v.position);
    let sun=max(dot(n,normalize(g.sun_direction.xyz)),0.0)*sun_visibility(v.position,n);
    var local_light=vec3(0.);var specular=vec3(0.);
    for(var i=0u;i<8u;i++) {if i>=g.light_info.x {break;}
        let point=g.point_lights[i];let l=normalize(point.position_range.xyz-v.position+vec3(0.00001));
        var visibility=1.;if i==0u {visibility=fire_visibility(v.position+n*0.025);}
        let energy=point.color_power.w*point_falloff(v.position,point)*visibility;
        local_light+=point.color_power.xyz*energy*max(dot(n,l),0.);
        let h=normalize(l+view);
        specular+=point.color_power.xyz*pow(max(dot(n,h),0.),mix(48.,6.,v.roughness))*(1.-v.roughness)*energy;
    }
    var albedo=v.color*textureSample(atlas,atlas_sampler,v.uv,i32(v.texture)).rgb;
    // Surface-anchored clusters make material detail survive camera rotation.
    // Detail frequency is bounded by the projected world footprint.
    let footprint=max(length(dpdx(v.position)),length(dpdy(v.position)));
    let frequency=min(9.,0.65/max(footprint,0.001));
    let mottle=noise(v.position*2.3);let grain=hash(floor(v.position*frequency));
    if v.roughness>0.93 && n.y>0.6 && v.emission<0.01 {
        let moss=step(0.58,mottle);let fleck=step(0.78,grain);
        albedo*=mix(vec3(0.72,0.7,0.64),vec3(1.02,1.12,0.83),moss);
        albedo*=mix(0.85,1.15,fleck);
    } else if v.roughness>0.84 && v.emission<0.01 {
        albedo*=0.84+floor((mottle*0.7+grain*0.3)*4.)*0.085;
    }
    let ambient=g.ambient.xyz*mix(0.55,1.1,n.y*0.5+0.5);
    var o:Output;
    o.color=vec4(albedo*(ambient+g.sun_color.xyz*sun*g.sun_color.w+local_light)+specular+albedo*v.emission,1.);
    o.normal_depth=vec4(n,length(g.camera.xyz-v.position));return o;
}
