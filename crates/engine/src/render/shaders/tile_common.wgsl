const TILE_SIZE:u32=16u;
const FIRE_TILE_CAPACITY:u32=64u;
const SMOKE_TILE_CAPACITY:u32=36u;
const POINT_TILE_CAPACITY:u32=8u;
const PARTICLE_TILE_CAPACITY:u32=12u;
struct TileHeader {counts:vec4<u32>,flags:vec4<u32>};
fn tile_index(pixel:vec2<f32>)->u32 {
    let tiles_x=u32(ceil(g.resolution.x/f32(TILE_SIZE)));
    let x=min(u32(max(pixel.x,0.))/TILE_SIZE,tiles_x-1u);
    let y=min(u32(max(pixel.y,0.))/TILE_SIZE,u32(ceil(g.resolution.y/f32(TILE_SIZE)))-1u);
    return y*tiles_x+x;
}
