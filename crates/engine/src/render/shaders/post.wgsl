@group(1) @binding(0) var hdr:texture_2d<f32>;
@group(1) @binding(1) var normal_depth:texture_2d<f32>;
@vertex fn vs(@builtin(vertex_index) i:u32)->@builtin(position) vec4<f32>{let p=array<vec2<f32>,3>(vec2(-1.,-1.),vec2(3.,-1.),vec2(-1.,3.));return vec4(p[i],0.,1.);}
fn bayer(p:vec2<u32>)->f32 {
    let matrix=array<f32,16>(0.,8.,2.,10.,12.,4.,14.,6.,3.,11.,1.,9.,15.,7.,13.,5.);
    return matrix[(p.x%4u)+(p.y%4u)*4u]/16.-0.5;
}
@fragment fn fs(@builtin(position) pos:vec4<f32>)->@location(0) vec4<f32>{
    let p=vec2<i32>(pos.xy);var color=textureLoad(hdr,p,0).rgb;
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
    color*=g.params.x;
    color=(color*(2.51*color+0.03))/(color*(2.43*color+0.59)+0.14);
    // Quantise luminance in display space while preserving coloured lighting.
    let display=pow(clamp(color,vec3(0.),vec3(1.)),vec3(1./2.2));
    let l=max(dot(display,vec3(0.2126,0.7152,0.0722)),0.001);
    let levels=g.params.y;let quantized=floor(l*levels+bayer(vec2<u32>(p))*g.resolution.z+0.5)/levels;
    let result=clamp(display*mix(1.,quantized/l,0.55),vec3(0.),vec3(1.));
    // Output target is sRGB; the GPU applies the display transfer function.
    return vec4(pow(result,vec3(2.2)),1.);
}
