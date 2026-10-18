struct TileConfig {force_overflow:vec4<u32>};
struct TileStats {values:array<atomic<u32>,12>};
@group(1) @binding(0) var<storage,read_write> tile_headers_out:array<TileHeader>;
@group(1) @binding(1) var<storage,read_write> fire_tile_indices_out:array<u32>;
@group(1) @binding(2) var<storage,read_write> smoke_tile_indices_out:array<u32>;
@group(1) @binding(3) var<storage,read_write> point_tile_indices_out:array<u32>;
@group(1) @binding(4) var<storage,read_write> particle_tile_indices_out:array<u32>;
@group(1) @binding(5) var<uniform> tile_config:TileConfig;
@group(1) @binding(6) var<storage,read_write> tile_stats_out:TileStats;

fn overlaps_tile(center:vec3<f32>,radius:f32,tile:vec2<u32>)->bool {
    if !all(center==center) || !all(abs(center)<vec3(1e20)) || !(radius>=0.) || !(radius<1e20) {return true;}
    if g.camera.w<0.5 && distance(center,g.camera.xyz)<=radius {return true;}
    let tile_min=vec2<f32>(tile*TILE_SIZE)-vec2(1.);
    let tile_max=min(vec2<f32>((tile+vec2<u32>(1u))*TILE_SIZE)+vec2(1.),g.resolution.xy);
    let pixel_min=vec2(1e20);var min_pixel=pixel_min;var max_pixel=vec2(-1e20);
    for(var corner=0u;corner<8u;corner++) {
        let sign=vec3<f32>(select(-1.,1.,(corner&1u)!=0u),select(-1.,1.,(corner&2u)!=0u),select(-1.,1.,(corner&4u)!=0u));
        let clip=g.view_proj*vec4(center+sign*radius,1.);
        if !(clip.w>0.) {return true;}
        let ndc=clip.xy/clip.w;
        if !all(abs(ndc)<vec2(1e20)) {return true;}
        let pixel=vec2((ndc.x*0.5+0.5)*g.resolution.x,(0.5-ndc.y*0.5)*g.resolution.y);
        min_pixel=min(min_pixel,pixel);max_pixel=max(max_pixel,pixel);
    }
    return all(max_pixel>=tile_min) && all(min_pixel<=tile_max);
}

@compute @workgroup_size(1)
fn build_tile_lists(@builtin(global_invocation_id) id:vec3<u32>) {
    let tiles_x=u32(ceil(g.resolution.x/f32(TILE_SIZE)));
    let tiles_y=u32(ceil(g.resolution.y/f32(TILE_SIZE)));
    if id.x>=tiles_x || id.y>=tiles_y {return;}
    let tile_index=id.y*tiles_x+id.x;
    let fire_base=tile_index*FIRE_TILE_CAPACITY;
    let smoke_base=tile_index*SMOKE_TILE_CAPACITY;
    let point_base=tile_index*POINT_TILE_CAPACITY;
    let particle_base=tile_index*PARTICLE_TILE_CAPACITY;
    var counts=vec4<u32>(0u);var flags=vec4<u32>(0u);
    if tile_config.force_overflow.x!=0u {flags.x=15u;}
    if tile_config.force_overflow.x==0u {
        for(var source=0u;source<2u;source++) {
            for(var i=0u;i<256u;i++) {
                if i>=fire.sources[source].counts.x {break;}
                let primitive=fire.sources[source].primitives[i];
                if overlaps_tile(primitive.center_radius.xyz,max(primitive.center_radius.w,primitive.axis_length.w),id.xy) {
                    if counts.x<FIRE_TILE_CAPACITY {fire_tile_indices_out[fire_base+counts.x]=source*256u+i;} else {flags.x|=1u;}
                    counts.x++;
                }
            }
        }
        if g.experiments.w>0.5 {
            for(var i=0u;i<36u;i++) {
                let lobe=smoke_lobe_bounds(i);
                let time=g.wind_time.w;let layer=f32(i/3u);
                let age=fract(time*0.125-layer/12.)*8.;
                if age>time || age<0.12 {continue;}
                if overlaps_tile(lobe.xyz,lobe.w,id.xy) {
                    if counts.y<SMOKE_TILE_CAPACITY {smoke_tile_indices_out[smoke_base+counts.y]=i;} else {flags.x|=2u;}
                    counts.y++;
                }
            }
        }
        for(var i=0u;i<8u;i++) {
            if i>=g.light_info.x {break;}
            let light=g.point_lights[i];
            if light.color_power.w>0. && overlaps_tile(light.position_range.xyz,light.position_range.w,id.xy) {
                if counts.z<POINT_TILE_CAPACITY {point_tile_indices_out[point_base+counts.z]=i;} else {flags.x|=4u;}
                counts.z++;
            }
        }
        for(var i=0u;i<12u;i++) {
            if i>=fire.sources[0].lighting.x {break;}
            let light=fire.sources[0].lights[i];
            if light.color_power.w>0. && overlaps_tile(light.position_range.xyz,light.position_range.w,id.xy) {
                if counts.w<PARTICLE_TILE_CAPACITY {particle_tile_indices_out[particle_base+counts.w]=i;} else {flags.x|=8u;}
                counts.w++;
            }
        }
    }
    tile_headers_out[tile_index]=TileHeader(counts,flags);
    atomicAdd(&tile_stats_out.values[0],counts.x);
    atomicAdd(&tile_stats_out.values[1],counts.y);
    atomicAdd(&tile_stats_out.values[2],counts.z);
    atomicAdd(&tile_stats_out.values[3],counts.w);
    atomicAdd(&tile_stats_out.values[4],select(0u,1u,(flags.x&1u)!=0u));
    atomicAdd(&tile_stats_out.values[5],select(0u,1u,(flags.x&2u)!=0u));
    atomicAdd(&tile_stats_out.values[6],select(0u,1u,(flags.x&4u)!=0u));
    atomicAdd(&tile_stats_out.values[7],select(0u,1u,(flags.x&8u)!=0u));
    atomicMax(&tile_stats_out.values[8],counts.x);
    atomicMax(&tile_stats_out.values[9],counts.y);
    atomicMax(&tile_stats_out.values[10],counts.z);
    atomicMax(&tile_stats_out.values[11],counts.w);
}
