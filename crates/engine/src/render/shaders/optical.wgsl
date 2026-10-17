@group(2) @binding(0) var scene_color:texture_2d<f32>;
@group(2) @binding(1) var scene_normals:texture_2d<f32>;
@group(2) @binding(2) var optical_sampler:sampler;
@vertex fn optical_vs(v:VertexIn)->Varying {
    var result=world_vertex(v);
    if optical_strength(materials[v.material])<=0. {result.clip=vec4(2.,2.,2.,1.);}
    return result;
}
@vertex fn optical_vs_baked(@location(0) position:vec3<f32>, @location(1) normal:vec3<f32>, @location(2) color:vec3<f32>, @location(3) uv:vec2<f32>, @location(4) texture:f32, @location(5) emission:f32, @location(6) roughness:f32, @location(7) material:u32)->Varying {
    var result:Varying; result.clip=g.view_proj*vec4(position,1.);result.position=position;result.normal=normal;result.color=color;result.uv=uv;result.texture=texture;result.emission=emission;result.roughness=roughness;result.material=material;
    if optical_strength(materials[material])<=0. {result.clip=vec4(2.,2.,2.,1.);}
    return result;
}
fn project_uv(p:vec3<f32>)->vec3<f32> {
    let q=g.view_proj*vec4(p,1.);return vec3(q.xy/q.w*vec2(0.5,-0.5)+0.5,q.w);
}
fn environment_reflection(direction:vec3<f32>,rough:f32)->vec3<f32> {
    let upper=mix(g.horizon.rgb,g.sky.rgb,pow(clamp(direction.y*1.3,0.,1.),0.55));
    let ground=g.ambient.rgb*0.35;
    let sky=mix(ground,upper,smoothstep(-0.15,0.12,direction.y));
    let sun=pow(max(dot(direction,normalize(g.sun_direction.xyz)),0.),mix(512.,3.,rough*rough));
    return sky+g.sun_color.rgb*g.sun_color.w*sun*mix(2.,0.2,rough);
}
fn blurred_scene(uv:vec2<f32>,rough:f32)->vec3<f32> {
    let offset=vec2(rough*rough*7.)/g.resolution.xy;
    let middle=textureSampleLevel(scene_color,optical_sampler,uv,0.).rgb;
    if rough<0.08 {return middle;}
    return (middle*4.+textureSampleLevel(scene_color,optical_sampler,uv+vec2(offset.x,0.),0.).rgb+
        textureSampleLevel(scene_color,optical_sampler,uv-vec2(offset.x,0.),0.).rgb+
        textureSampleLevel(scene_color,optical_sampler,uv+vec2(0.,offset.y),0.).rgb+
        textureSampleLevel(scene_color,optical_sampler,uv-vec2(0.,offset.y),0.).rgb)/8.;
}
// Bounded single-bounce SSR. Missing/off-screen information fades to the sky.
// No history buffer: fixed-grid results do not accumulate temporal ghosting.
fn reflected_scene(p:vec3<f32>,n:vec3<f32>,view:vec3<f32>,rough:f32)->vec3<f32> {
    let direction=reflect(-view,n);let fallback=environment_reflection(direction,rough);
    if rough>0.72 || g.presentation.z<1. {return fallback;}
    var previous=-1.;var previous_t=0.07;
    for(var i=0;i<16;i++) {
        if f32(i)>=g.presentation.z {break;}
        let t=0.10+f32(i)*0.17+f32(i*i)*0.035;
        let q=p+n*0.06+direction*t;let screen=project_uv(q);
        if screen.z<=0. || any(screen.xy<vec2(0.)) || any(screen.xy>vec2(1.)) {break;}
        let data=textureSampleLevel(scene_normals,optical_sampler,screen.xy,0.);
        let delta=length(q-g.camera.xyz)-data.w;
        if data.w>0. && delta>0. && previous<0. && delta<0.45+t*0.025 && dot(data.xyz,-direction)>0.05 {
            // Four bisections prevent large ray steps turning into false hits.
            var low=previous_t;var high=t;
            for(var refine=0;refine<4;refine++) {
                let mid=(low+high)*0.5;let probe=p+n*0.06+direction*mid;
                let uv=project_uv(probe).xy;
                let depth=textureSampleLevel(scene_normals,optical_sampler,uv,0.).w;
                if depth>0. && length(probe-g.camera.xyz)>depth {high=mid;} else {low=mid;}
            }
            let uv=project_uv(p+n*0.06+direction*high).xy;
            let edge=smoothstep(0.,0.08,min(min(uv.x,uv.y),min(1.-uv.x,1.-uv.y)));
            return mix(fallback,blurred_scene(uv,rough),edge*(1.-smoothstep(0.35,0.72,rough)));
        }
        previous=select(-1.,delta,data.w>0.);previous_t=t;
    }
    return fallback;
}
@fragment fn optical_fs(v:Varying,@builtin(front_facing) front:bool)->Output {
    let tile=tile_index(v.clip.xy);
    let m=materials[v.material];
    if optical_strength(m)<=0. {discard;}
    // Closed glass uses the entry face only; nearest entries win the depth test.
    if transmission(m)>0. && !front {discard;}
    let n=normalize(v.normal);let view=surface_view(v);
    let rough=clamp(m.surface.x*v.roughness,0.,1.);let albedo=surface_albedo(v,m);
    let f=fresnel(material_f0(m,albedo),max(dot(n,view),0.));
    let foreground=atmosphere(v.clip,v.clip.z,tile);
    // An opaque foreground smoke lobe hides the complete optical surface.
    if foreground.a>0.985 {
        var hidden:Output;hidden.color=vec4(foreground.rgb,1.);hidden.normal_depth=textureLoad(scene_normals,vec2<i32>(v.clip.xy),0);return hidden;
    }
    var base_color:vec3<f32>;
    var base_normal_depth:vec4<f32>;
    if g.optical_settings.x>0.5 && transmission(m)<=0. {
        let pixel_coord=vec2<i32>(v.clip.xy);
        let composited=textureLoad(scene_color,pixel_coord,0).rgb;
        base_color=max(composited-foreground.rgb,vec3(0.))/max(1.-foreground.a,0.015);
        base_normal_depth=textureLoad(scene_normals,pixel_coord,0);
    } else {
        let base=shade_surface(v,tile);
        base_color=base.color.rgb;
        base_normal_depth=base.normal_depth;
    }
    var color=base_color;
    let reflection=reflected_scene(v.position,n,view,rough);
    color+=reflection*f*optical_strength(m);
    if transmission(m)>0. {
        let direction=refract(-view,n,1./m.optical.x);
        let path=m.optical.y/max(abs(dot(n,direction)),0.2);
        let straight=project_uv(v.position-view*path).xy;
        let refracted=project_uv(v.position+direction*path).xy;
        var uv=clamp(refracted,vec2(0.),vec2(1.));
        let behind=textureSampleLevel(scene_normals,optical_sampler,uv,0.).w;
        if behind>0. && behind<base_normal_depth.w {uv=straight;}
        // Remove the estimated foreground contribution before tinting the
        // transmitted background, then composite it once above the surface.
        let background=max(blurred_scene(uv,rough)-foreground.rgb,vec3(0.))/max(1.-foreground.a,0.015);
        color+=background*exp(-m.absorption.rgb*path)*clamp(albedo,vec3(0.),vec3(1.))*(vec3(1.)-f)*transmission(m);
    }
    color=foreground.rgb+color*(1.-foreground.a);
    var result:Output;result.color=vec4(color,1.);result.normal_depth=base_normal_depth;return result;
}
