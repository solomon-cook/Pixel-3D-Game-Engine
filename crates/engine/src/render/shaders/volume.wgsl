// World lighting declarations are shared with world.wgsl.
@group(2) @binding(0) var scene_depth:texture_depth_2d;
@group(2) @binding(1) var smoke:texture_3d<f32>;
@group(2) @binding(2) var volume_sampler:sampler;
@group(2) @binding(8) var smoke_absorption:texture_3d<f32>;
@group(2) @binding(9) var secondary_smoke:texture_3d<f32>;

@vertex fn fullscreen(@builtin(vertex_index) i:u32)->@builtin(position) vec4<f32> {
    let p=array<vec2<f32>,3>(vec2(-1.,-1.),vec2(3.,-1.),vec2(-1.,3.));return vec4(p[i],0.,1.);
}
fn sky_color(direction:vec3<f32>)->vec3<f32> {
    let sky=mix(g.horizon.xyz,g.sky.xyz,pow(clamp(direction.y*1.3,0.,1.),0.55));
    let sun=pow(max(dot(direction,normalize(g.sun_direction.xyz)),0.),512.);
    return sky+g.sun_color.xyz*sun*0.7;
}
struct AtmosphereSample {color:vec4<f32>,depth:f32,flame:f32};
struct AtmosphereOutput {@location(0) color:vec4<f32>,@location(1) effects:vec4<f32>};
@fragment fn volume_fs(@builtin(position) pixel:vec4<f32>)->AtmosphereOutput {
    let tile=tile_index(pixel.xy);
    let sample=atmosphere_info(pixel,textureLoad(scene_depth,vec2<i32>(pixel.xy),0),tile);
    var o:AtmosphereOutput;o.color=sample.color;o.effects=vec4(sample.depth,sample.flame,0.,0.);return o;
}
fn atmosphere(pixel:vec4<f32>,z:f32,tile:u32)->vec4<f32> {return atmosphere_info(pixel,z,tile).color;}
fn atmosphere_info(pixel:vec4<f32>,z:f32,tile:u32)->AtmosphereSample {
    let uv=pixel.xy/g.resolution.xy;let clip=uv*vec2(2.,-2.)+vec2(-1.,1.);
    let near4=g.inverse_view_proj*vec4(clip,0.,1.);let near=near4.xyz/near4.w;
    let far4=g.inverse_view_proj*vec4(clip,1.,1.);let far=far4.xyz/far4.w;
    let direction=normalize(far-near);let surface4=g.inverse_view_proj*vec4(clip,z,1.);
    let distance=min(length(surface4.xyz/surface4.w-near),120.);
    if g.experiments.w>0.5 {return ink_volume(pixel,near,direction,distance,z,tile);}
    let inv=1./(direction+vec3(0.0000001));
    let a=(g.volume_min.xyz-near)*inv;let b=(g.volume_max.xyz-near)*inv;
    let lo=min(a,b);let hi=max(a,b);let enter=max(max(max(lo.x,lo.y),lo.z),0.);let exit=min(min(min(hi.x,hi.y),hi.z),distance);
    var radiance=vec3(0.);var transmittance=1.;var first_smoke=distance;
    if exit>enter {
        let steps=u32(g.params.w);let ds=(exit-enter)/f32(steps);
        let screen_jitter=hash(vec3(floor(pixel.xy),17.));
        for(var i=0u;i<128u;i++){if i>=steps {break;}
            let t=enter+(f32(i)+mix(screen_jitter,0.5,g.experiments.y))*ds;
            let p=near+direction*t;let volume_uv=(p-g.volume_min.xyz)/(g.volume_max.xyz-g.volume_min.xyz);
            let sample=textureSampleLevel(smoke,volume_sampler,volume_uv,0.);
            let detail=noise(p*5.-vec3(0.,g.wind_time.w*0.6,0.));
            let density=sample.x*mix(0.75+detail*0.5,smoothstep(0.2,0.75,detail)*1.4,g.experiments.y);
            let extinction=density*2.6;let alpha=1.-exp(-extinction*ds);
            let fire_light=smoke_local_lights(p,vec3(0.),3u,tile)*0.55;
            // A few density samples toward the sun approximate internal shading.
            var optical=0.;for(var j=1u;j<=4u;j++){
                let q=volume_uv+normalize(g.sun_direction.xyz)*f32(j)*0.025;
                optical+=textureSampleLevel(smoke,volume_sampler,q,0.).x*0.25;
            }
            let light=g.ambient.xyz*1.5+g.sun_color.xyz*g.sun_color.w*exp(-optical*2.)*sun_visibility(p,vec3(0.))+fire_light;
            radiance+=transmittance*light*vec3(0.67,0.7,0.76)*alpha;
            transmittance*=1.-alpha;
            if transmittance<0.85 && first_smoke==distance {first_smoke=t;}
            if transmittance<0.015 {break;}
        }
    }
    // A second source keeps its own fixed world-space domain and smoke field.
    // This branch is absent for v1 scenes, preserving their original integral.
    if fire.sources[1].counts.x>0u {
        let source=fire.source_origins[1].xyz;
        let source_min=source+vec3(-3.,-0.6,-3.);
        let source_max=source+vec3(3.,7.4,3.);
        let source_a=(source_min-near)*inv;let source_b=(source_max-near)*inv;
        let source_lo=min(source_a,source_b);let source_hi=max(source_a,source_b);
        let source_enter=max(max(max(source_lo.x,source_lo.y),source_lo.z),0.);
        let source_exit=min(min(min(source_hi.x,source_hi.y),source_hi.z),distance);
        if source_exit>source_enter {
            let steps=u32(g.params.w);let ds=(source_exit-source_enter)/f32(steps);
            let screen_jitter=hash(vec3(floor(pixel.xy),17.));
            for(var i=0u;i<128u;i++){if i>=steps {break;}
                let t=source_enter+(f32(i)+mix(screen_jitter,0.5,g.experiments.y))*ds;
                let p=near+direction*t;let volume_uv=(p-source_min)/(source_max-source_min);
                let sample=textureSampleLevel(secondary_smoke,volume_sampler,volume_uv,0.);
                let detail=noise(p*5.-vec3(0.,g.wind_time.w*0.6,0.));
                let density=sample.x*mix(0.75+detail*0.5,smoothstep(0.2,0.75,detail)*1.4,g.experiments.y);
                let extinction=density*2.6;let alpha=1.-exp(-extinction*ds);
                let fire_light=smoke_local_lights(p,vec3(0.),3u,tile)*0.55;
                var optical=0.;for(var j=1u;j<=4u;j++){
                    let q=volume_uv+normalize(g.sun_direction.xyz)*f32(j)*0.025;
                    optical+=textureSampleLevel(secondary_smoke,volume_sampler,q,0.).x*0.25;
                }
                let light=g.ambient.xyz*1.5+g.sun_color.xyz*g.sun_color.w*exp(-optical*2.)*sun_visibility(p,vec3(0.))+fire_light;
                radiance+=transmittance*light*vec3(0.67,0.7,0.76)*alpha;
                transmittance*=1.-alpha;
                if transmittance<0.85 && first_smoke==distance {first_smoke=t;}
                if transmittance<0.015 {break;}
            }
        }
    }
    let flame=sample_fire(near,direction,distance,tile);
    // Approximate camera-to-flame smoke absorption with a bounded six-sample
    // integral. The soft-volume renderer does not claim exact per-lobe sorting.
    var absorption=0.;
    if flame.alpha>0. {
        let span=max(0.,min(flame.depth,exit)-enter);
        for(var j=0u;j<6u;j++) {
            let p=near+direction*(enter+(f32(j)+0.5)*span/6.);
            let uv=(p-g.volume_min.xyz)/(g.volume_max.xyz-g.volume_min.xyz);
            absorption+=textureSampleLevel(smoke,volume_sampler,clamp(uv,vec3(0.),vec3(1.)),0.).x*span/6.*2.6;
        }
        if fire.sources[1].counts.x>0u {
            let source=fire.source_origins[1].xyz;
            let source_min=source+vec3(-3.,-0.6,-3.);let source_max=source+vec3(3.,7.4,3.);
            let source_a=(source_min-near)*inv;let source_b=(source_max-near)*inv;
            let source_lo=min(source_a,source_b);let source_hi=max(source_a,source_b);
            let source_enter=max(max(max(source_lo.x,source_lo.y),source_lo.z),0.);
            let source_exit=min(min(min(source_hi.x,source_hi.y),source_hi.z),min(flame.depth,distance));
            let source_span=max(0.,source_exit-source_enter);
            for(var j=0u;j<6u;j++) {
                let p=near+direction*(source_enter+(f32(j)+0.5)*source_span/6.);
                let uv=(p-source_min)/(source_max-source_min);
                absorption+=textureSampleLevel(secondary_smoke,volume_sampler,clamp(uv,vec3(0.),vec3(1.)),0.).x*source_span/6.*2.6;
            }
        }
    }
    let visibility=exp(-absorption);
    radiance=flame.color*visibility+radiance*(1.-flame.alpha*visibility);
    transmittance*=1.-flame.alpha*visibility;
    let atmospheric=exp(-g.horizon.w*min(distance,flame.depth));
    let nearest=min(first_smoke,flame.depth);
    let visible_depth=select(0.,length(near+direction*nearest-g.camera.xyz),nearest<distance);
    if z>=0.99999 {return AtmosphereSample(vec4(radiance+transmittance*sky_color(direction),1.),visible_depth,flame.alpha*visibility);}
    radiance=radiance*atmospheric+sky_color(direction)*(1.-atmospheric);
    return AtmosphereSample(vec4(radiance,1.-transmittance*atmospheric),visible_depth,flame.alpha*visibility);
}


// Sculpted, opaque pyro lobes are a 3D presentation of the advected smoke field.
// All lobes ray-intersect in world space, so contours survive camera rotation.
fn ink_volume(pixel:vec4<f32>,origin:vec3<f32>,direction:vec3<f32>,distance:f32,z:f32,tile:u32)->AtmosphereSample {
    var nearest=distance;var second=distance;var second_normal=vec3(0.,1.,0.);var hit_normal=vec3(0.,1.,0.);var hit_position=vec3(0.);var smoke_hit=false;var secondary_hit=false;var hit_radius=0.3;
    let time=g.wind_time.w;
    // Keep the original parent-puff motion and silhouette. Small attached
    // satellites enrich each puff rather than replacing it with noisy detail.
    let bounds_inv=1./(direction+vec3(0.0000001));
    let bounds_a=(g.volume_min.xyz-origin)*bounds_inv;let bounds_b=(g.volume_max.xyz-origin)*bounds_inv;
    let bounds_lo=min(bounds_a,bounds_b);let bounds_hi=max(bounds_a,bounds_b);
    let bounds_enter=max(max(max(bounds_lo.x,bounds_lo.y),bounds_lo.z),0.);
    let bounds_exit=min(min(min(bounds_hi.x,bounds_hi.y),bounds_hi.z),distance);
    let tile_header=tile_headers[tile];
    let smoke_overflow=(tile_header.flags.x&2u)!=0u;
    let smoke_candidate_count=select(tile_header.counts.y,36u,smoke_overflow);
    if bounds_exit>bounds_enter {for(var candidate=0u;candidate<36u;candidate++) {
        if candidate>=smoke_candidate_count {break;}
        let i=select(smoke_tile_indices[tile*SMOKE_TILE_CAPACITY+candidate],candidate,smoke_overflow);
        let layer=f32(i/3u);let branch=f32(i%3u);let age=fract(time*0.125-layer/12.)*8.;
        if age>time || age<0.12 {continue;}
        let phase=hash(vec3(layer,branch,g.params.z))*6.28318;
        let lobe=smoke_lobe_bounds(i);let parent=lobe.xyz;
        // Conservative parent/children bound: most rays never need child tests.
        let bound=lobe.w;
        let along=dot(parent-origin,direction);
        if along+bound<0. || along-bound>distance || length(origin+direction*max(along,0.)-parent)>bound {continue;}
        let uv=(parent-g.volume_min.xyz)/(g.volume_max.xyz-g.volume_min.xyz);
        let field=textureSampleLevel(smoke,volume_sampler,clamp(uv,vec3(0.),vec3(1.)),0.).x;
        let presence=smoothstep(0.002,0.025,field);
        let size_variation=0.84+0.28*hash(vec3(layer,branch,g.params.z+17.));
        let radius=(0.27+age*0.095)*size_variation*smoothstep(0.,0.65,age)*(1.-smoothstep(6.5,8.,age))*presence;
        if radius<0.035 {continue;}
        let axes=vec3(0.94+0.14*sin(phase),0.87+0.14*sin(phase+age),0.91+0.1*cos(phase));
        let maximum=u32(g.effect_settings.x);
        let child_count=select(0u,1u+u32(layer+branch*3.)%max(maximum,1u),maximum>0u);
        for(var bubble=0u;bubble<9u;bubble++) {
            if bubble>child_count {break;}
            var center=parent;var size=radius;var local_axes=axes;
            if bubble>0u {
                let index=f32(bubble-1u);let angle=phase+index*6.28318/max(f32(child_count),1.);
                let attachment=normalize(vec3(cos(angle),0.28*sin(angle*1.3+phase),sin(angle)));
                // Centres overlap the parent. Only the little outer caps show,
                // making secondary bubbles part of the main billow.
                size=radius*g.effect_settings.y*(0.82+0.34*hash(vec3(layer,index,branch+21.)));
                center=parent+attachment*radius*0.93;
                local_axes=vec3(1.,0.95,1.);
            }
            let ro=(origin-center)/local_axes;let rd=direction/local_axes;
            let qa=dot(rd,rd);let qb=dot(ro,rd);let qc=dot(ro,ro)-size*size;let discriminant=qb*qb-qa*qc;
            if discriminant<=0. {continue;}
            let t=(-qb-sqrt(discriminant))/qa;
            if t>0. && t<nearest {
                second=nearest;second_normal=hit_normal;nearest=t;hit_position=origin+direction*t;
                let normal=normalize((hit_position-center)/(local_axes*local_axes));
                let parent_normal=normalize((hit_position-parent)/(axes*axes));
                hit_normal=select(normal,normalize(mix(parent_normal,normal,0.72)),bubble>0u);
                smoke_hit=true;secondary_hit=bubble>0u;hit_radius=radius;
            } else if t>0. && t<second {
                second=t;
                let point=origin+direction*t;
                let normal=normalize((point-center)/(local_axes*local_axes));
                let parent_normal=normalize((point-parent)/(axes*axes));
                second_normal=select(normal,normalize(mix(parent_normal,normal,0.72)),bubble>0u);
            }
        }
    }
    }
    var color=vec3(0.);var transmittance=1.;
    if smoke_hit {
        // Local metaball-like normal blending, using intersections already found.
        // It rounds only contact regions, without a per-pixel SDF surface search.
        let contact=1.-smoothstep(0.,hit_radius*0.45,second-nearest);
        let crease=contact*(1.-max(dot(hit_normal,second_normal),0.));
        hit_normal=normalize(mix(hit_normal,second_normal,contact*0.45));
        let n=hit_normal;
        let eye=max(dot(hit_normal,-direction),0.);
        let pattern=select(hash(vec3(floor(pixel.xy/2.),31.)),hash(floor((hit_position-vec3(0.,time*0.3,0.))*14.)),g.experiments.y>0.5);
        let soot=vec3(0.052,0.014,0.035);
        let scattering=smoke_local_lights(hit_position,n,6u,tile)*(1.-crease*0.45);
        var paint=soot+scattering*vec3(0.24,0.22,0.22)*(0.98+pattern*0.04);
        let overlap=1.-smoothstep(0.025,hit_radius*0.65,second-nearest);
        if eye<0.30 {
            let ink=select(vec3(0.014,0.003,0.007),vec3(0.04,0.008,0.018),secondary_hit);
            // Keep external silhouette ink; soften the line when another puff
            // is immediately behind it, so internal overlaps read as one body.
            paint=mix(paint,ink,(1.-overlap*0.88)*select(1.,0.7,secondary_hit));
        }
        let uv=(hit_position-g.volume_min.xyz)/(g.volume_max.xyz-g.volume_min.xyz);
        let heat=textureSampleLevel(smoke,volume_sampler,clamp(uv,vec3(0.),vec3(1.)),0.).y;
        let internal=g.fire_warm.xyz*g.effect_settings.w*heat*0.12;
        color=paint+internal;
        transmittance=0.;
    }
    let flame=sample_fire(origin,direction,nearest,tile);
    color=flame.color+color*(1.-flame.alpha);
    transmittance*=1.-flame.alpha;
    nearest=min(nearest,flame.depth);
    let fog=exp(-g.horizon.w*min(nearest,distance));
    color=color*fog+sky_color(direction)*(1.-fog)*(1.-transmittance);
    let visible_depth=select(0.,length(origin+direction*nearest-g.camera.xyz),nearest<distance);
    if z>=0.99999 {return AtmosphereSample(vec4(color+transmittance*sky_color(direction),1.),visible_depth,flame.alpha);}
    return AtmosphereSample(vec4(color,1.-transmittance),visible_depth,flame.alpha);
}



// Shared smoke absorption along the path to any local point light.
fn smoke_light_transmittance(surface:vec3<f32>,normal:vec3<f32>,light:vec3<f32>,steps:u32,cached:bool)->f32 {
    if g.effect_settings.z<=0. {return 1.;}
    let surface_uv=(surface-g.volume_min.xyz)/(g.volume_max.xyz-g.volume_min.xyz);
    if cached && g.presentation.w>0.5 && all(surface_uv>=vec3(0.)) && all(surface_uv<=vec3(1.)) {
        let optical_depth=textureSampleLevel(smoke_absorption,volume_sampler,surface_uv,0.).x;
        return exp(-optical_depth*g.effect_settings.z*2.);
    }
    let origin=surface+normal*0.035;let delta=light-origin;let full_distance=length(delta);
    let distance=max(full_distance-0.25,0.);let direction=delta/max(full_distance,0.001);
    let ds=distance/f32(steps);var optical_depth=0.;
    for(var i=0u;i<6u;i++) {if i>=steps {break;}
        let p=origin+direction*((f32(i)+0.5)*ds);
        let uv=(p-g.volume_min.xyz)/(g.volume_max.xyz-g.volume_min.xyz);
        if all(uv>=vec3(0.)) && all(uv<=vec3(1.)) {optical_depth+=textureSampleLevel(smoke,volume_sampler,uv,0.).x*ds;}
    }
    return exp(-optical_depth*g.effect_settings.z*2.);
}
fn smoke_local_lights(p:vec3<f32>,normal:vec3<f32>,steps:u32,tile:u32)->vec3<f32> {
    let tile_header=tile_headers[tile];
    let point_overflow=(tile_header.flags.x&4u)!=0u;
    var first=8u;var second=8u;var near=1e20;var next=1e20;
    // Select two nearby active sources, then spend absorption samples only on
    // those lights. Distance falloff is continuous, independent of puff age.
    let point_count=select(tile_header.counts.z,g.light_info.x,point_overflow);
    for(var candidate=0u;candidate<8u;candidate++) {if candidate>=point_count {break;}
        let i=select(point_tile_indices[tile*POINT_TILE_CAPACITY+candidate],candidate,point_overflow);
        let light=g.point_lights[i];let delta=light.position_range.xyz-p;let d=dot(delta,delta);
        if light.color_power.w<=0. || max(max(light.color_power.x,light.color_power.y),light.color_power.z)<=0. || d>=light.position_range.w*light.position_range.w {continue;}
        if d<near {second=first;next=near;first=i;near=d;} else if d<next {second=i;next=d;}
    }
    var radiance=vec3(0.);
    for(var slot=0u;slot<2u;slot++) {
        let index=select(first,second,slot==1u);if index>=8u {continue;}
        let light=g.point_lights[index];let direction=normalize(light.position_range.xyz-p+vec3(0.00001));
        let form=floor(clamp(dot(normal,direction)*0.5+0.5,0.,1.)*3.+0.5)/3.;
        let shape=select(0.22+form*0.78,1.,dot(normal,normal)<0.1);
        var shadow=smoke_light_transmittance(p,normal,light.position_range.xyz,steps,index==0u);
        if index==0u {shadow*=fire_visibility(p);}
        radiance+=light.color_power.xyz*light.color_power.w*point_falloff(p,light)*shadow*shape;
    }
    // Keep authored fire/fill lighting, then budget two local particle sources
    // by estimated received energy. Hot fragments can light smoke from within.
    var best=12u;var runner=12u;var score=0.;var next_score=0.;
    let particle_overflow=(tile_header.flags.x&8u)!=0u;
    let particle_count=select(tile_header.counts.w,fire.sources[0].lighting.x,particle_overflow);
    for(var candidate=0u;candidate<12u;candidate++) {if candidate>=particle_count {break;}
        let i=select(particle_tile_indices[tile*PARTICLE_TILE_CAPACITY+candidate],candidate,particle_overflow);
        let light=particle_light_point(i);
        let importance=light.color_power.w*point_falloff(p,light);
        if importance>score {runner=best;next_score=score;best=i;score=importance;}
        else if importance>next_score {runner=i;next_score=importance;}
    }
    for(var slot=0u;slot<2u;slot++) {
        let index=select(best,runner,slot==1u);if index>=12u {continue;}
        let light=particle_light_point(index);let direction=normalize(light.position_range.xyz-p+vec3(0.00001));
        let form=clamp(dot(normal,direction)*0.5+0.5,0.,1.);
        let shape=select(0.2+form*0.8,1.,dot(normal,normal)<0.1);
        radiance+=light.color_power.rgb*light.color_power.w*point_falloff(p,light)*
            smoke_light_transmittance(p,normal,light.position_range.xyz,6u,false)*shape;
    }
    return radiance;
}
