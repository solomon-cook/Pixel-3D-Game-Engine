// Original implementation using standard metallic/roughness and Fresnel models.
// The table is shared by world, optical and shadow passes.
struct Material {
    color_emission:vec4<f32>, surface:vec4<f32>, optical:vec4<f32>,
    absorption:vec4<f32>, scatter:vec4<f32>,
};
@group(1) @binding(5) var<storage,read> materials:array<Material>;
fn transmission(m:Material)->f32 {return m.surface.w*(1.-m.surface.y);}
fn optical_strength(m:Material)->f32 {return max(max(m.surface.y,m.surface.z),transmission(m));}
fn fresnel(f0:vec3<f32>,cosine:f32)->vec3<f32> {
    return f0+(vec3(1.)-f0)*pow(clamp(1.-cosine,0.,1.),5.);
}
fn material_f0(m:Material,albedo:vec3<f32>)->vec3<f32> {
    let dielectric=pow((m.optical.x-1.)/(m.optical.x+1.),2.);
    return mix(vec3(dielectric),clamp(albedo,vec3(0.),vec3(1.)),m.surface.y);
}
fn microfacet(n:vec3<f32>,v:vec3<f32>,l:vec3<f32>,f0:vec3<f32>,rough:f32)->vec3<f32> {
    let h=normalize(v+l+vec3(0.00001));
    let nv=max(dot(n,v),0.001);let nl=max(dot(n,l),0.);let nh=max(dot(n,h),0.);
    let a=pow(max(rough,0.08),2.);let a2=a*a;
    let denominator=nh*nh*(a2-1.)+1.;
    let d=a2/(3.14159265*denominator*denominator);
    let k=pow(rough+1.,2.)/8.;
    let visibility=(nv/(nv*(1.-k)+k))*(nl/(nl*(1.-k)+k));
    return fresnel(f0,max(dot(v,h),0.))*d*visibility/(4.*nv)*nl/max(nl,0.001);
}
