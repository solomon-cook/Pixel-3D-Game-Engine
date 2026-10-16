// World lighting declarations are shared with world.wgsl.
@group(2) @binding(0) var scene_depth:texture_depth_2d;
@group(2) @binding(1) var smoke:texture_3d<f32>;
@group(2) @binding(2) var volume_sampler:sampler;

@vertex fn fullscreen(@builtin(vertex_index) i:u32)->@builtin(position) vec4<f32> {
    let p=array<vec2<f32>,3>(vec2(-1.,-1.),vec2(3.,-1.),vec2(-1.,3.));return vec4(p[i],0.,1.);
}
fn sky_color(direction:vec3<f32>)->vec3<f32> {
    let sky=mix(g.horizon.xyz,g.sky.xyz,pow(clamp(direction.y*1.3,0.,1.),0.55));
    let sun=pow(max(dot(direction,normalize(g.sun_direction.xyz)),0.),512.);
    return sky+g.sun_color.xyz*sun*0.7;
}
@fragment fn volume_fs(@builtin(position) pixel:vec4<f32>)->@location(0) vec4<f32> {
    let uv=pixel.xy/g.resolution.xy;let clip=uv*vec2(2.,-2.)+vec2(-1.,1.);
    let z=textureLoad(scene_depth,vec2<i32>(pixel.xy),0);
    let near4=g.inverse_view_proj*vec4(clip,0.,1.);let near=near4.xyz/near4.w;
    let far4=g.inverse_view_proj*vec4(clip,1.,1.);let far=far4.xyz/far4.w;
    let direction=normalize(far-near);let surface4=g.inverse_view_proj*vec4(clip,z,1.);
    let distance=min(length(surface4.xyz/surface4.w-near),120.);
    if g.experiments.w>0.5 {return ink_volume(pixel,near,direction,distance,z);}
    let inv=1./(direction+vec3(0.0000001));
    let a=(g.volume_min.xyz-near)*inv;let b=(g.volume_max.xyz-near)*inv;
    let lo=min(a,b);let hi=max(a,b);let enter=max(max(max(lo.x,lo.y),lo.z),0.);let exit=min(min(min(hi.x,hi.y),hi.z),distance);
    var radiance=vec3(0.);var transmittance=1.;
    if exit>enter {
        let steps=u32(g.params.w);let ds=(exit-enter)/f32(steps);
        let screen_jitter=hash(vec3(floor(pixel.xy),17.));
        for(var i=0u;i<128u;i++){if i>=steps {break;}
            let t=enter+(f32(i)+mix(screen_jitter,0.5,g.experiments.y))*ds;
            let p=near+direction*t;let volume_uv=(p-g.volume_min.xyz)/(g.volume_max.xyz-g.volume_min.xyz);
            let sample=textureSampleLevel(smoke,volume_sampler,volume_uv,0.);
            let detail=noise(p*5.-vec3(0.,g.wind_time.w*0.6,0.));
            let density=sample.x*mix(0.75+detail*0.5,smoothstep(0.2,0.75,detail)*1.4,g.experiments.y);
            let local=p-g.fire_position.xyz;
            let bend=select(vec3(0.),wind_at(p)*max(local.y,0.)*0.3,g.experiments.z>0.5);
            let flame_p=local-bend;
            let flame_noise=noise(flame_p*vec3(5.,3.,5.)-vec3(0.,g.wind_time.w*4.,0.));
            let height=flame_p.y;
            let radius=0.31*max(1.-height*0.9,0.);
            let flame=max(0.,1.-length(flame_p.xz)/(radius+0.001)+(flame_noise-0.5)*0.9)*smoothstep(-0.35,-0.12,height)*(1.-smoothstep(0.55,1.35,height))*g.simulation.w;
            let extinction=density*2.6+flame*3.;let alpha=1.-exp(-extinction*ds);
            let light_distance=length(local);
            let fire_light=g.fire_color.xyz*g.fire_color.w/(1.+light_distance*light_distance*0.8)*fire_visibility(p)*0.55;
            // A few density samples toward the sun approximate internal shading.
            var optical=0.;for(var j=1u;j<=4u;j++){
                let q=volume_uv+normalize(g.sun_direction.xyz)*f32(j)*0.025;
                optical+=textureSampleLevel(smoke,volume_sampler,q,0.).x*0.25;
            }
            let light=g.ambient.xyz*1.5+g.sun_color.xyz*g.sun_color.w*exp(-optical*2.)*sun_visibility(p,vec3(0.))+fire_light;
            let flame_color=mix(vec3(1.,0.08,0.006),vec3(1.,0.72,0.18),clamp(flame*1.2-height*0.4,0.,1.));
            radiance+=transmittance*(light*vec3(0.67,0.7,0.76)*alpha+flame_color*flame*ds*9.);
            transmittance*=1.-alpha;if transmittance<0.015 {break;}
        }
    }
    // Deterministic ember trajectories share wind when the experiment is enabled.
    for(var i=0u;i<24u;i++) {
        let h=hash(vec3(f32(i),g.params.z,7.));let age=fract(g.wind_time.w*(0.17+h*0.14)+h);
        let life=age*4.;let ember_wind=select(vec3(0.13,0.,0.04),wind_at(g.fire_position.xyz),g.experiments.z>0.5);
        let center=g.fire_position.xyz+vec3(sin(h*80.+life)*0.12,life*0.8,cos(h*60.+life)*0.12)+ember_wind*life*0.55;
        let t=dot(center-near,direction);let d=length(near+direction*t-center);
        if t>0. && t<distance {radiance+=vec3(3.5,0.7,0.07)*(1.-smoothstep(0.009,0.022,d))*(1.-age)*g.simulation.w;}
    }
    let atmospheric=exp(-g.horizon.w*distance);
    if z>=0.99999 {return vec4(radiance+transmittance*sky_color(direction),1.);}
    radiance=radiance*atmospheric+sky_color(direction)*(1.-atmospheric);
    return vec4(radiance,1.-transmittance*atmospheric);
}


// Sculpted, opaque pyro lobes are a 3D presentation of the advected smoke field.
// All lobes ray-intersect in world space, so contours survive camera rotation.
fn ink_volume(pixel:vec4<f32>,origin:vec3<f32>,direction:vec3<f32>,distance:f32,z:f32)->vec4<f32> {
    var nearest=distance;var second=distance;var second_normal=vec3(0.,1.,0.);var hit_normal=vec3(0.,1.,0.);var hit_position=vec3(0.);var hit_age=0.;var smoke_hit=false;var secondary_hit=false;var hit_radius=0.3;
    let time=g.wind_time.w;let source=g.fire_position.xyz;
    // Keep the original parent-puff motion and silhouette. Small attached
    // satellites enrich each puff rather than replacing it with noisy detail.
    let bounds_inv=1./(direction+vec3(0.0000001));
    let bounds_a=(g.volume_min.xyz-origin)*bounds_inv;let bounds_b=(g.volume_max.xyz-origin)*bounds_inv;
    let bounds_lo=min(bounds_a,bounds_b);let bounds_hi=max(bounds_a,bounds_b);
    let bounds_enter=max(max(max(bounds_lo.x,bounds_lo.y),bounds_lo.z),0.);
    let bounds_exit=min(min(min(bounds_hi.x,bounds_hi.y),bounds_hi.z),distance);
    if bounds_exit>bounds_enter {for(var i=0u;i<36u;i++) {
        let layer=f32(i/3u);let branch=f32(i%3u);let age=fract(time*0.125-layer/12.)*8.;
        if age>time || age<0.12 {continue;}
        let phase=hash(vec3(layer,branch,g.params.z))*6.28318;
        let spread=0.12+age*0.09;let rising=age*(g.simulation.x*0.72+0.2);
        let gust=select(g.wind_time.xyz,wind_at(source+vec3(0.,rising,0.)),g.experiments.z>0.5);
        let parent=source+vec3(cos(phase+age*0.35)*spread,rising+0.65,sin(phase+age*0.35)*spread)+gust*age*0.72;
        // Conservative parent/children bound: most rays never need child tests.
        let bound=(0.27+age*0.095)*1.12*max(1.1,0.93+g.effect_settings.y*1.16);
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
                hit_age=age;smoke_hit=true;secondary_hit=bubble>0u;hit_radius=radius;
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
        let light=normalize(source-hit_position);
        let warm=clamp(1.-hit_age/7.,0.,1.);
        let form=dot(n,light)*0.55+dot(n,normalize(g.sun_direction.xyz))*0.15+warm*0.5;
        let pattern=select(hash(vec3(floor(pixel.xy/2.),31.)),hash(floor((hit_position-vec3(0.,time*0.3,0.))*14.)),g.experiments.y>0.5);
        let band=floor(clamp(form+pattern*0.035,0.,1.)*4.);
        let soot=vec3(0.052,0.014,0.035);let red=vec3(0.18,0.032,0.041);let ember=vec3(0.62,0.10,0.025);let orange=vec3(1.05,0.25,0.042);
        var paint=soot;
        if band>=1. {paint=red;}
        if band>=2. {paint=ember;}
        if band>=3. {paint=orange;}
        let overlap=1.-smoothstep(0.025,hit_radius*0.65,second-nearest);
        if eye<0.30 {
            let ink=select(vec3(0.014,0.003,0.007),vec3(0.04,0.008,0.018),secondary_hit);
            // Keep external silhouette ink; soften the line when another puff
            // is immediately behind it, so internal overlaps read as one body.
            paint=mix(paint,ink,(1.-overlap*0.88)*select(1.,0.7,secondary_hit));
        }
        let visibility=smoke_fire_transmittance(hit_position,hit_normal)*fire_visibility(hit_position)*(1.-crease*0.45);
        // Occlusion removes firelight while retaining the cool soot/sky floor.
        let shadowed=mix(min(paint,soot),paint,visibility);
        let internal=vec3(0.8,0.13,0.025)*g.effect_settings.w*(1.-visibility);
        color=(shadowed+internal)*mix(0.8,1.15,clamp(g.fire_color.w/10.,0.,1.));
        transmittance=0.;
    }
    // Front-to-back flame isosurfaces: hard tongues and a hot yellow core.
    let inv=1./(direction+vec3(0.0000001));let a=(source+vec3(-1.,-0.5,-1.)-origin)*inv;let b=(source+vec3(1.,2.1,1.)-origin)*inv;
    let lo=min(a,b);let hi=max(a,b);let enter=max(max(max(lo.x,lo.y),lo.z),0.);let exit=min(min(min(hi.x,hi.y),hi.z),nearest);
    if exit>enter && g.simulation.w>0. {
        let steps=u32(g.params.w);let ds=(exit-enter)/f32(steps);
        for(var i=0u;i<128u;i++) {
            if i>=steps {break;}
            let t=enter+(f32(i)+0.5)*ds;let p=origin+direction*t;let local=p-source;let h=local.y;
            var maximum=-10.;var core=0.;
            for(var tongue=0u;tongue<7u;tongue++) {
                let phase=f32(tongue)*2.39996;let offset=vec2(cos(phase),sin(phase))*select(0.24,0.0,tongue==0u);
                let height=0.85+0.4*sin(phase+time*3.1)+select(0.,0.3,tongue==0u);
                let bend=select(vec2(0.),wind_at(p).xz*h*0.35,g.experiments.z>0.5);
                let wave=vec2(sin(h*4.5-time*4.+phase),cos(h*3.8-time*3.2+phase))*max(h,0.)*0.15+vec2(cos(phase),sin(phase))*pow(max(h,0.),1.7)*0.22;
                let radius=(0.19+select(0.,0.13,tongue==0u))*max(1.-max(h,0.)/height,0.);
                let radial=length(local.xz-offset-bend-wave);
                let value=(radius-radial)*smoothstep(-0.4,-0.2,h)*(1.-smoothstep(height-0.12,height,h));
                maximum=max(maximum,value);core=max(core,value/max(radius,0.001));
            }
            if maximum>0.008 {
                core=max(core,0.68*(1.-clamp(h/1.45,0.,1.))+0.1*sin(h*6.-time*3.+local.x*4.));
                var flame=vec3(1.6,0.16,0.006);
                if core>0.22 {flame=vec3(3.,0.72,0.015);}
                if core>0.48 {flame=vec3(4.,2.2,0.22);}
                color=flame*g.simulation.w;transmittance=0.;nearest=t;break;
            }
        }
    }
    // Crisp, short-lived embers; no soft particle halo.
    for(var i=0u;i<32u;i++) {
        let seed=hash(vec3(f32(i),g.params.z,7.));let age=fract(time*(0.22+seed*0.15)+seed);let life=age*3.;
        let wind=select(vec3(0.13,0.,0.04),wind_at(source),g.experiments.z>0.5);
        let center=source+vec3(sin(seed*80.+life)*0.23,life*0.9,cos(seed*60.+life)*0.23)+wind*life*0.7;
        let t=dot(center-origin,direction);let d=length(origin+direction*t-center);
        if d<0.012 && t>0. && t<nearest && g.simulation.w>0. {color=vec3(3.,1.,0.04);transmittance=0.;}
    }
    let fog=exp(-g.horizon.w*min(nearest,distance));
    color=color*fog+sky_color(direction)*(1.-fog)*(1.-transmittance);
    if z>=0.99999 {return vec4(color+transmittance*sky_color(direction),1.);}
    return vec4(color,1.-transmittance);
}



// Fixed-cost shared occlusion from the existing simulation density grid.
// Six midpoint samples replace rebuilding/intersecting every puff toward the
// fire. This is a coarse light-transport approximation, not exact surface CSG.
fn smoke_fire_transmittance(surface:vec3<f32>,normal:vec3<f32>)->f32 {
    if g.effect_settings.z<=0. {return 1.;}
    let origin=surface+normal*0.035;
    let delta=g.fire_position.xyz-origin;let full_distance=length(delta);
    let distance=max(full_distance-0.35,0.);let direction=delta/max(full_distance,0.001);
    let ds=distance/6.;var optical_depth=0.;
    for(var i=0u;i<6u;i++) {
        let p=origin+direction*((f32(i)+0.5)*ds);
        let uv=(p-g.volume_min.xyz)/(g.volume_max.xyz-g.volume_min.xyz);
        if all(uv>=vec3(0.)) && all(uv<=vec3(1.)) {
            optical_depth+=textureSampleLevel(smoke,volume_sampler,uv,0.).x*ds;
        }
    }
    return exp(-optical_depth*g.effect_settings.z*2.);
}
