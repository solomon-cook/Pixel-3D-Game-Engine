@group(1) @binding(0) var hdr:texture_2d<f32>;
@group(1) @binding(1) var normal_depth:texture_2d<f32>;
@group(1) @binding(2) var effect_depth:texture_2d<f32>;
@group(1) @binding(3) var heat_field:texture_3d<f32>;
@group(1) @binding(4) var heat_sampler:sampler;
fn visible_depth(p:vec2<i32>)->f32 {
    let geometry=textureLoad(normal_depth,p,0).w;
    let effect=textureLoad(effect_depth,p,0).x;
    return min(select(1e20,geometry,geometry>0.),select(1e20,effect,effect>0.));
}
fn heat_pixel(pixel:vec2<i32>)->vec2<i32> {
    if g.fire_pixels.z<=0. || g.simulation.w<=0. || g.thermal.x<=0. {return pixel;}
    // Never refract the flame itself, including detached visible pieces.
    if textureLoad(effect_depth,pixel,0).y>0.05 {return pixel;}
    let uv=(vec2<f32>(pixel)+0.5)/g.resolution.xy;
    let clip=uv*vec2(2.,-2.)+vec2(-1.,1.);
    let a=g.inverse_view_proj*vec4(clip,0.,1.);let origin=a.xyz/a.w;
    let b=g.inverse_view_proj*vec4(clip,1.,1.);let direction=normalize(b.xyz/b.w-origin);
    let source=g.fire_position.xyz+vec3(0.,g.fire_shape.y*0.55,0.);
    let height=g.fire_pixels.w;let lean=g.wind_time.xyz*height*0.6;
    let radius=g.fire_shape.x*0.75+height*0.2;
    let box_lo=min(source,source+lean)+vec3(-radius,0.,-radius);
    let box_hi=max(source,source+lean)+vec3(radius,height,radius);
    let inv=1./(direction+vec3(0.0000001));let lo=(box_lo-origin)*inv;let hi=(box_hi-origin)*inv;
    let enter=max(max(max(min(lo,hi).x,min(lo,hi).y),min(lo,hi).z),0.);
    let exit=min(min(min(max(lo,hi).x,max(lo,hi).y),max(lo,hi).z),120.);
    if exit<=enter {return pixel;}
    let stop=visible_depth(pixel);var weight=0.;var hot=source;var heat_depth=1e20;
    // Fixed budget, only inside the bounded hot-air column. Heat is sampled
    // from the existing temperature volume; a source envelope bridges its grid.
    for(var i=0u;i<8u;i++) {
        let t=mix(enter,exit,(f32(i)+0.5)/8.);let p=origin+direction*t;
        let depth=length(p-g.camera.xyz);if depth>=stop-0.08 {break;}
        let y=(p.y-source.y)/height;
        if y<=0. || y>=1. {continue;}
        let center=source+g.wind_time.xyz*(p.y-source.y)*0.6;
        let width=g.fire_shape.x*0.65+(p.y-source.y)*0.16;
        let radial=length((p-center).xz)/width;
        let envelope=(1.-smoothstep(0.3,1.,radial))*smoothstep(0.,0.12,y)*(1.-smoothstep(0.55,1.,y));
        let field_uv=(p-g.volume_min.xyz)/(g.volume_max.xyz-g.volume_min.xyz);
        var heat=0.;
        if all(field_uv>=vec3(0.)) && all(field_uv<=vec3(1.)) {heat=textureSampleLevel(heat_field,heat_sampler,field_uv,0.).y;}
        let strength=envelope*(0.45+0.55*clamp(heat,0.,1.))*g.thermal.x/(1.+g.thermal.x);
        if strength>weight {weight=strength;hot=p;heat_depth=depth;}
    }
    if weight<=0. {return pixel;}
    let time=g.wind_time.w*0.8;
    let flow=vec2(sin(hot.y*8.-time*2.1+noise(hot*3.-vec3(0.,time,0.))*3.),sin(hot.x*5.+hot.z*3.+time*1.4)*0.45);
    let offset=vec2<i32>(round(flow*weight*g.fire_pixels.z*clamp(g.simulation.w,0.,1.)));
    let size=vec2<i32>(textureDimensions(hdr));let q=clamp(pixel+offset,vec2(0),size-vec2(1));
    // Do not drag a foreground object, smoke silhouette or flame into the warp.
    if visible_depth(q)<heat_depth-0.12 || textureLoad(effect_depth,q,0).y>0.05 {return pixel;}
    return q;
}
@vertex fn vs(@builtin(vertex_index) i:u32)->@builtin(position) vec4<f32>{let p=array<vec2<f32>,3>(vec2(-1.,-1.),vec2(3.,-1.),vec2(-1.,3.));return vec4(p[i],0.,1.);}
fn bayer(p:vec2<u32>)->f32 {
    let matrix=array<f32,16>(0.,8.,2.,10.,12.,4.,14.,6.,3.,11.,1.,9.,15.,7.,13.,5.);
    return matrix[(p.x%4u)+(p.y%4u)*4u]/16.-0.5;
}
@fragment fn fs(@builtin(position) pos:vec4<f32>)->@location(0) vec4<f32>{
    let source_pixel=vec2<i32>(pos.xy);let p=heat_pixel(source_pixel);
    let solid_flame=g.fire_pixels.x>0.5 && textureLoad(effect_depth,p,0).y>0.05;
    var color=textureLoad(hdr,p,0).rgb;
    if g.experiments.x>0.5 {
        let anchor=(p/2)*2;let nd=textureLoad(normal_depth,p,0);var total=vec3(0.);var count=0.;
        for(var y=0;y<2;y++){for(var x=0;x<2;x++){
            let q=anchor+vec2(x,y);let candidate=textureLoad(normal_depth,q,0);
            if dot(nd.xyz,candidate.xyz)>0.96 && abs(nd.w-candidate.w)<0.25 {
                total+=textureLoad(hdr,q,0).rgb;count+=1.;
            }
        }}
        if count>0. {let average=total/count;let l=max(dot(color,vec3(0.2126,0.7152,0.0722)),0.001);let a=dot(average,vec3(0.2126,0.7152,0.0722));color*=mix(1.,a/l,0.65);}
    }
    // Small bounded HDR glow, evaluated on the selected pixel grid. Threshold
    // removes ordinary diffuse colour; changing glow never changes simulation.
    if g.presentation.y>0. && !solid_flame {
        var glow=vec3(0.);let size=vec2<i32>(textureDimensions(hdr));
        for(var y=-1;y<=1;y++){for(var x=-1;x<=1;x++){
            let q=clamp(p+vec2(x,y)*2,vec2(0),size-vec2(1));
            glow+=max(textureLoad(hdr,q,0).rgb-vec3(1.),vec3(0.));
        }}
        color+=glow/9.*g.presentation.y;
    }
    color*=g.params.x;
    color=(color*(2.51*color+0.03))/(color*(2.43*color+0.59)+0.14);
    // Quantise luminance in display space while preserving coloured lighting.
    let display=pow(clamp(color,vec3(0.),vec3(1.)),vec3(1./2.2));
    let l=max(dot(display,vec3(0.2126,0.7152,0.0722)),0.001);
    let levels=g.params.y;let quantized=floor(l*levels+bayer(vec2<u32>(source_pixel))*g.resolution.z*select(1.,0.,solid_flame)+0.5)/levels;
    let result=clamp(display*mix(1.,quantized/l,g.presentation.x),vec3(0.),vec3(1.));
    // Output target is sRGB; the GPU applies the display transfer function.
    return vec4(pow(result,vec3(2.2)),1.);
}
