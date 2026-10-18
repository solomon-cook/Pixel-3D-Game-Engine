@group(1) @binding(0) var<storage,read_write> smoke_candidates_out:array<vec4<f32>>;

@compute @workgroup_size(64)
fn build_smoke_candidates(@builtin(global_invocation_id) id:vec3<u32>) {
    if id.x>=72u {return;}
    if id.x<36u {
        smoke_candidates_out[id.x]=smoke_lobe_bounds(id.x);
    } else {
        smoke_candidates_out[id.x]=smoke_lobe_bounds_for_source(id.x-36u,1u);
    }
}
