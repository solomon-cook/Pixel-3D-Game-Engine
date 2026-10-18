@group(1) @binding(0) var sun_shadow: texture_depth_2d;
@group(1) @binding(1) var point_shadow: texture_depth_cube;
@group(1) @binding(2) var shadow_sampler: sampler_comparison;
@group(1) @binding(3) var atlas: texture_2d_array<f32>;
@group(1) @binding(4) var atlas_sampler: sampler;
@group(2) @binding(5) var heat_volume:texture_3d<f32>;
@group(2) @binding(6) var heat_sampler:sampler;

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
struct VertexIn { @location(0) position:vec3<f32>, @location(1) normal:vec3<f32>, @location(2) color:vec3<f32>, @location(3) uv:vec2<f32>, @location(4) texture:f32, @location(5) emission:f32, @location(6) roughness:f32, @location(7) material:u32,
    @location(8) model_0:vec4<f32>, @location(9) model_1:vec4<f32>, @location(10) model_2:vec4<f32>, @location(11) model_3:vec4<f32>,
    @location(12) normal_0:vec4<f32>, @location(13) normal_1:vec4<f32>, @location(14) normal_2:vec4<f32> };
struct Varying { @builtin(position) clip:vec4<f32>, @location(0) position:vec3<f32>, @location(1) normal:vec3<f32>, @location(2) color:vec3<f32>, @location(3) uv:vec2<f32>, @location(4) @interpolate(flat) texture:f32, @location(5) emission:f32, @location(6) roughness:f32, @location(7) @interpolate(flat) material:u32 };
@vertex fn vs(v:VertexIn)->Varying {return world_vertex(v);}
@vertex fn vs_baked(@location(0) position:vec3<f32>, @location(1) normal:vec3<f32>, @location(2) color:vec3<f32>, @location(3) uv:vec2<f32>, @location(4) texture:f32, @location(5) emission:f32, @location(6) roughness:f32, @location(7) material:u32)->Varying {
    var o:Varying; o.clip=g.view_proj*vec4(position,1.);o.position=position;o.normal=normal;o.color=color;o.uv=uv;o.texture=texture;o.emission=emission;o.roughness=roughness;o.material=material;return o;
}
fn world_vertex(v:VertexIn)->Varying {
    let model=mat4x4<f32>(v.model_0,v.model_1,v.model_2,v.model_3);
    let normal_matrix=mat3x3<f32>(v.normal_0.xyz,v.normal_1.xyz,v.normal_2.xyz);
    let position=(model*vec4(v.position,1.)).xyz;
    var o:Varying; o.clip=g.view_proj*vec4(position,1.);o.position=position;o.normal=normal_matrix*v.normal;o.color=v.color;o.uv=v.uv;o.texture=v.texture;o.emission=v.emission;o.roughness=v.roughness;o.material=v.material;return o;
}
struct Output { @location(0) color:vec4<f32>, @location(1) normal_depth:vec4<f32> };
fn surface_view(v:Varying)->vec3<f32> {
    if g.camera.w>0.5 {
        let a=g.inverse_view_proj*vec4(0.,0.,0.,1.);let b=g.inverse_view_proj*vec4(0.,0.,1.,1.);
        return normalize(a.xyz/a.w-b.xyz/b.w);
    }
    return normalize(g.camera.xyz-v.position);
}
fn surface_albedo(v:Varying,m:Material)->vec3<f32> {
    return v.color*m.color_emission.rgb*textureSampleLevel(atlas,atlas_sampler,v.uv,i32(v.texture),0.).rgb;
}
fn scattered(m:Material,n:vec3<f32>,l:vec3<f32>)->vec3<f32> {
    // Authorable thin-body approximation: wrap around the terminator and
    // transmit backlight through an optical thickness. No diffusion solver.
    let wrap=pow(clamp((dot(n,l)+0.45)/1.45,0.,1.),1.5)*0.35;
    let back=pow(max(dot(-n,l),0.),1.5);
    let attenuation=exp(-(m.absorption.rgb+vec3(0.7))*m.optical.y);
    return m.scatter.rgb*m.optical.z*(vec3(wrap)+attenuation*back);
}
fn shade_surface(v:Varying,tile:u32)->Output {
    let m=materials[v.material];let rough=clamp(m.surface.x*v.roughness,0.,1.);
    let emission=m.color_emission.w*v.emission;
    let n=normalize(v.normal);let view=surface_view(v);
    var albedo=surface_albedo(v,m);
    let footprint=max(length(dpdx(v.position)),length(dpdy(v.position)));
    let frequency=min(9.,0.65/max(footprint,0.001));
    let mottle=noise(v.position*2.3);let grain=hash(floor(v.position*frequency));
    if rough>0.93 && n.y>0.6 && emission<0.01 {
        let moss=step(0.58,mottle);let fleck=step(0.78,grain);
        albedo*=mix(vec3(0.72,0.7,0.64),vec3(1.02,1.12,0.83),moss);
        albedo*=mix(0.85,1.15,fleck);
    } else if rough>0.84 && emission<0.01 {
        albedo*=0.84+floor((mottle*0.7+grain*0.3)*4.)*0.085;
    }
    let f0=material_f0(m,albedo);let advanced=optical_strength(m)>0.;
    let sun_l=normalize(g.sun_direction.xyz);let sun_vis=sun_visibility(v.position,n);
    let sun=max(dot(n,sun_l),0.)*sun_vis;
    var local_light=vec3(0.);var specular=vec3(0.);var scatter=vec3(0.);
    if advanced {specular+=microfacet(n,view,sun_l,f0,rough)*g.sun_color.rgb*g.sun_color.w*sun_vis;}
    if m.optical.z>0. {
        scatter+=scattered(m,n,sun_l)*g.sun_color.rgb*g.sun_color.w*sun_visibility(v.position+sun_l*m.optical.y,n);
    }
    let tile_header=tile_headers[tile];
    let point_overflow=(tile_header.flags.x&4u)!=0u;
    let point_count=select(tile_header.counts.z,g.light_info.x,point_overflow);
    for(var candidate=0u;candidate<8u;candidate++) {if candidate>=point_count {break;}
        let i=select(point_tile_indices[tile*POINT_TILE_CAPACITY+candidate],candidate,point_overflow);
        let point=g.point_lights[i];let l=normalize(point.position_range.xyz-v.position+vec3(0.00001));
        var visibility=1.;if i==0u {visibility=fire_visibility(v.position+n*0.025);}
        let power=point.color_power.w*point_falloff(v.position,point);
        let energy=power*visibility;
        local_light+=point.color_power.xyz*energy*max(dot(n,l),0.);
        if advanced {specular+=point.color_power.rgb*energy*microfacet(n,view,l,f0,rough);}
        else {specular+=point.color_power.xyz*pow(max(dot(n,normalize(l+view)),0.),mix(48.,6.,rough))*(1.-rough)*energy;}
        if m.optical.z>0. {
            var scatter_vis=1.;if i==0u {scatter_vis=fire_visibility(v.position+l*m.optical.y);}
            scatter+=point.color_power.rgb*power*scattered(m,n,l)*scatter_vis;
        }
    }
    // Bounded moving emission sources; no per-particle shadow maps.
    let particle_overflow=(tile_header.flags.x&8u)!=0u;
    let particle_count=select(tile_header.counts.w,fire.sources[0].lighting.x,particle_overflow);
    for(var candidate=0u;candidate<12u;candidate++) {if candidate>=particle_count {break;}
        let i=select(particle_tile_indices[tile*PARTICLE_TILE_CAPACITY+candidate],candidate,particle_overflow);
        let point=particle_light_point(i);let l=normalize(point.position_range.xyz-v.position+vec3(0.00001));
        let energy=point.color_power.w*point_falloff(v.position,point);
        local_light+=point.color_power.rgb*energy*max(dot(n,l),0.);
        if advanced {specular+=point.color_power.rgb*energy*microfacet(n,view,l,f0,rough);}
        else {specular+=point.color_power.rgb*energy*pow(max(dot(n,normalize(l+view)),0.),mix(48.,6.,rough))*(1.-rough);}
        if m.optical.z>0. {scatter+=point.color_power.rgb*energy*scattered(m,n,l);}
    }
    let ambient=g.ambient.xyz*mix(0.55,1.1,n.y*0.5+0.5);
    var diffuse=albedo*(ambient+g.sun_color.xyz*sun*g.sun_color.w+local_light);
    if advanced {diffuse*= (1.-m.surface.y)*(1.-transmission(m))*(vec3(1.)-fresnel(f0,max(dot(n,view),0.)));}
    var o:Output;o.color=vec4(diffuse+specular+scatter+albedo*emission,1.);
    o.normal_depth=vec4(n,length(g.camera.xyz-v.position));return o;
}
@fragment fn fs(v:Varying)->Output {
    var result=shade_surface(v,tile_index(v.clip.xy));
    let m=materials[v.material];
    if m.optical.w>0. {
        let heat_position=v.position+vec3(0.,0.45,0.);
        let heat_uv=(heat_position-g.volume_min.xyz)/(g.volume_max.xyz-g.volume_min.xyz);
        if all(heat_uv>=vec3(0.)) && all(heat_uv<=vec3(1.)) {
            let temperature=clamp(textureSampleLevel(heat_volume,heat_sampler,heat_uv,0.).y,0.,1.);
            let heat_level=floor(clamp(temperature*16.,0.,0.9999)*4.)/3.;
            let response=clamp(heat_level*m.optical.w,0.,1.);
            let edge=select(0.,1.,abs(dpdx(heat_level))+abs(dpdy(heat_level))>0.2 && heat_level>0.);
            result.color=vec4(mix(result.color.rgb,g.fire_warm.rgb,response*0.22),result.color.a);
            result.color=vec4(mix(result.color.rgb,g.fire_hot.rgb,edge*m.optical.w*0.18),result.color.a);
        }
    }
    if transmission(materials[v.material])>0. {discard;}
    return result;
}
