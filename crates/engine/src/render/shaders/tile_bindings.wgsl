@group(7) @binding(0) var<storage,read> tile_headers:array<TileHeader>;
@group(7) @binding(1) var<storage,read> fire_tile_indices:array<u32>;
@group(7) @binding(2) var<storage,read> smoke_tile_indices:array<u32>;
@group(7) @binding(3) var<storage,read> point_tile_indices:array<u32>;
@group(7) @binding(4) var<storage,read> particle_tile_indices:array<u32>;
