@group(0) @binding(0) var pixels:texture_2d<f32>;
@group(0) @binding(1) var point_sampler:sampler;
@group(0) @binding(2) var<uniform> dimensions:vec4<f32>;
struct V { @builtin(position) pos:vec4<f32>, @location(0) uv:vec2<f32> };
@vertex fn vs(@builtin(vertex_index) i:u32)->V {
    let p=array<vec2<f32>,3>(vec2(-1.,-1.),vec2(3.,-1.),vec2(-1.,3.));var v:V;v.pos=vec4(p[i],0.,1.);v.uv=p[i]*vec2(0.5,-0.5)+0.5;return v;
}
@fragment fn fs(v:V)->@location(0) vec4<f32>{
    let scale=max(floor(min(dimensions.x/dimensions.z,dimensions.y/dimensions.w)),1.);
    let offset=floor((dimensions.xy-dimensions.zw*scale)*0.5);
    let pixel=vec2<i32>(floor((v.pos.xy-offset)/scale));
    if any(pixel<vec2(0)) || any(pixel>=vec2<i32>(dimensions.zw)) {return vec4(0.,0.,0.,1.);}
    return textureLoad(pixels,pixel,0);
}
