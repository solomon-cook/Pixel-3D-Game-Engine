// World-space effect geometry is prepared once per fixed tick. No surface-search
// ray march, frame noise or camera-dependent simulation lives in this pass.
struct FireSample {color:vec3<f32>,alpha:f32,depth:f32};
fn sample_fire(origin:vec3<f32>,direction:vec3<f32>,limit:f32,tile:u32)->FireSample {
    var result=FireSample(vec3(0.),0.,limit);
    if (fire.sources[0].counts.x+fire.sources[1].counts.x)==0u || g.simulation.w<=0. || g.fire_outer.w<=0. {return result;}
    var optical=0.;var energy=vec3(0.);var peak_heat=0.;
    let inv=1./(direction+vec3(0.0000001));
    let header=tile_headers[tile];let overflow=(header.flags.x&1u)!=0u;
    for(var source_index=0u;source_index<2u;source_index++) {
        if fire.sources[source_index].counts.x==0u {continue;}
        let a=(fire.sources[source_index].bounds_min.xyz-origin)*inv;let b=(fire.sources[source_index].bounds_max.xyz-origin)*inv;
        let lo=min(a,b);let hi=max(a,b);
        if min(min(min(hi.x,hi.y),hi.z),limit)<=max(max(max(lo.x,lo.y),lo.z),0.) {continue;}
        let candidate_count=select(header.counts.x,fire.sources[source_index].counts.x,overflow);
        for(var candidate=0u;candidate<512u;candidate++) {
            if candidate>=candidate_count {break;}
            let flat_index=select(fire_tile_indices[tile*FIRE_TILE_CAPACITY+candidate],candidate,overflow);
            if !overflow && flat_index/256u!=source_index {continue;}
            let primitive_index=select(flat_index%256u,flat_index,overflow);
            let p=fire.sources[source_index].primitives[primitive_index];let center=p.center_radius.xyz;let radius=p.center_radius.w;
        let axis=p.axis_length.xyz;let axial=p.axis_length.w;
        let ro=origin-center;let along=dot(center-origin,direction);let bound=max(radius,axial);
        if along+bound<0. || along-bound>limit || length(ro+direction*max(along,0.))>bound {continue;}
        let stretch=1./axial-1./radius;
        let qro=ro/radius+axis*dot(ro,axis)*stretch;
        let qrd=direction/radius+axis*dot(direction,axis)*stretch;
        let qa=dot(qrd,qrd);let qb=dot(qro,qrd);let qc=dot(qro,qro)-1.;
        let discriminant=qb*qb-qa*qc;if discriminant<=0. {continue;}
        let enter=max((-qb-sqrt(discriminant))/qa,0.);let exit=min((-qb+sqrt(discriminant))/qa,limit);
        if exit<=enter {continue;}

        // Heat follows the continuous tongue axis; using the ellipsoid's axial
        // coordinate here would put a separate hot bead in every curve segment.
        let radial_ray=direction-axis*dot(direction,axis);
        let radial_origin=ro-axis*dot(ro,axis);
        let closest_t=clamp(-dot(radial_origin,radial_ray)/max(dot(radial_ray,radial_ray),0.0001),enter,exit);
        let local=ro+direction*closest_t;
        let radial=(local-axis*dot(local,axis))/radius;
        let core=pow(clamp(1.-dot(radial,radial),0.,1.),1.4);
        let heat=p.heat_kind.x*(0.4+0.6*core);
        var color=mix(g.fire_outer.xyz,g.fire_warm.xyz,smoothstep(0.15,0.7,heat));
        color=mix(color,g.fire_hot.xyz,smoothstep(0.7,0.98,heat));
        var coverage=1.;
        if g.fire_warm.w>0. || g.fire_hot.w>0. {
            let source_origin=select(g.fire_position.xyz,fire.source_origins[source_index].xyz,source_index>0u);
            let world=origin+direction*closest_t-source_origin;
            let material=world/vec3(g.fire_shape.x,g.fire_shape.y,g.fire_shape.x)*vec3(18.,22.,18.)-vec3(0.,g.wind_time.w*g.fire_shape.z*2.5,0.);
            let detail=noise(material+vec3(g.params.z*0.01));
            let rim=g.fire_warm.w*(0.04+detail*0.55)*(1.-core);
            let tip=select(g.fire_hot.w*max(p.heat_kind.w-0.4,0.)*detail*0.7,0.,p.heat_kind.z>0.5);
            coverage=smoothstep(max(rim,tip),max(rim,tip)+0.035,core);
        }
        if g.fire_pixels.x>0.5 {coverage=step(0.5,coverage);}
        if coverage<0.001 {continue;}
        result.depth=min(result.depth,enter);
        let depth=(exit-enter)/max(radius*2.,0.002)*p.heat_kind.y*g.simulation.w*coverage;
            optical+=depth;energy+=color*depth;peak_heat=max(peak_heat,heat);
        }
    }
    // An order-independent homogeneous-emission approximation within the flame.
    // Opaque world/smoke depth clips intersections before this accumulation.
    result.alpha=1.-exp(-optical);
    result.color=energy/max(optical,0.0001)*result.alpha*g.fire_outer.w;
    if g.fire_pixels.x>0.5 {
        result.alpha=step(0.08,optical);
        let bands=g.fire_pixels.y;
        let heat=floor(clamp(peak_heat,0.,0.9999)*bands)/(bands-1.);
        var paint=mix(g.fire_outer.rgb,g.fire_warm.rgb,clamp(heat*1.5,0.,1.));
        paint=mix(paint,g.fire_hot.rgb,clamp((heat-0.6667)*3.,0.,1.));
        result.color=paint*result.alpha*g.fire_outer.w;
        if result.alpha<0.5 {result.depth=limit;}
    }
    return result;
}
