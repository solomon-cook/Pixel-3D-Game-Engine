use crate::{
    assets::{self, Vertex},
    diagnostics::FrameMetrics,
    effects,
    effects::{
        FireFrame, FireFrameStorage, FireKey, FirePresentation, MAX_FIRE_PRIMITIVES,
        MAX_PARTICLE_LIGHTS,
    },
    platform,
    scene::{Camera, LightKind, Material, Object, Scene},
    simulation,
};
use anyhow::{anyhow, bail, Context, Result};
use bytemuck::{Pod, Zeroable};
use glam::{EulerRot, Mat3, Mat4, Quat, Vec3, Vec4};
use std::{
    collections::{BTreeMap, VecDeque},
    path::{Path, PathBuf},
    sync::mpsc,
    time::Instant,
};
use wgpu::util::DeviceExt;

pub const PIXEL_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8UnormSrgb;
const HDR: wgpu::TextureFormat = wgpu::TextureFormat::Rgba16Float;
const DEPTH: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;
const VOLUME: [u32; 3] = [48, 64, 48];

#[derive(Clone, serde::Serialize)]
pub struct GpuTimingSample {
    pub frame: u64,
    pub total_ms: f64,
    pub readback_latency_ms: f64,
    pub passes_ms: BTreeMap<String, f64>,
}

#[derive(Clone, serde::Serialize)]
pub struct GpuComputeTimingSample {
    pub tick: u64,
    pub elapsed_ms: f64,
    pub readback_latency_ms: f64,
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct PointLightGpu {
    position_range: [f32; 4],
    color_power: [f32; 4],
}

// Five vec4s match materials.wgsl. One table upload only when authoring changes.
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct MaterialGpu {
    color_emission: [f32; 4],
    surface: [f32; 4],
    optical: [f32; 4],
    absorption: [f32; 4],
    scatter: [f32; 4],
}
fn material_table(scene: &Scene) -> Vec<MaterialGpu> {
    let mut table = scene
        .materials
        .iter()
        .map(|m| MaterialGpu {
            color_emission: [m.color[0], m.color[1], m.color[2], m.emission],
            surface: [m.roughness, m.metallic, m.reflectivity, m.transmission],
            optical: [m.ior, m.thickness, m.subsurface, m.heat_response],
            absorption: [m.absorption[0], m.absorption[1], m.absorption[2], 0.],
            scatter: [
                m.scatter_color[0],
                m.scatter_color[1],
                m.scatter_color[2],
                0.,
            ],
        })
        .collect::<Vec<_>>();
    // Procedural pine trunks keep their independent bark tint.
    table.push(MaterialGpu {
        color_emission: [1., 1., 1., 0.],
        surface: [0.8, 0., 0., 0.],
        optical: [1.5, 0.25, 0., 0.],
        absorption: [0.; 4],
        scatter: [1.; 4],
    });
    table
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct Globals {
    view_proj: [[f32; 4]; 4],
    inverse_view_proj: [[f32; 4]; 4],
    sun_matrix: [[f32; 4]; 4],
    camera: [f32; 4],
    sun_direction: [f32; 4],
    sun_color: [f32; 4],
    ambient: [f32; 4],
    fire_position: [f32; 4],
    fire_color: [f32; 4],
    sky: [f32; 4],
    horizon: [f32; 4],
    wind_time: [f32; 4],
    volume_min: [f32; 4],
    volume_max: [f32; 4],
    params: [f32; 4],
    resolution: [f32; 4],
    experiments: [f32; 4],
    simulation: [f32; 4],
    effect_settings: [f32; 4],
    thermal: [f32; 4],
    fire_outer: [f32; 4],
    fire_warm: [f32; 4],
    fire_hot: [f32; 4],
    presentation: [f32; 4],
    optical_settings: [f32; 4],
    fire_shape: [f32; 4],
    fire_pixels: [f32; 4],
    light_info: [u32; 4],
    point_lights: [PointLightGpu; 8],
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct TileConfigGpu {
    force_overflow: [u32; 4],
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable, PartialEq)]
struct SmokeSimulationConfig {
    volume_min: [f32; 4],
    volume_max: [f32; 4],
    fire_position: [f32; 4],
    simulation: [f32; 4],
    thermal: [f32; 4],
}

struct Pipelines {
    mesh: wgpu::RenderPipeline,
    mesh_baked: wgpu::RenderPipeline,
    mesh_diagnostic: wgpu::RenderPipeline,
    mesh_baked_diagnostic: wgpu::RenderPipeline,
    optical: wgpu::RenderPipeline,
    optical_baked: wgpu::RenderPipeline,
    optical_diagnostic: wgpu::RenderPipeline,
    optical_baked_diagnostic: wgpu::RenderPipeline,
    optical_overlay: wgpu::RenderPipeline,
    optical_overlay_baked: wgpu::RenderPipeline,
    optical_overlay_alpha: wgpu::RenderPipeline,
    optical_overlay_alpha_baked: wgpu::RenderPipeline,
    optical_overlay_diagnostic: wgpu::RenderPipeline,
    optical_overlay_baked_diagnostic: wgpu::RenderPipeline,
    optical_overlay_alpha_diagnostic: wgpu::RenderPipeline,
    optical_overlay_alpha_baked_diagnostic: wgpu::RenderPipeline,
    volume: wgpu::RenderPipeline,
    volume_diagnostic: wgpu::RenderPipeline,
    post: wgpu::RenderPipeline,
    post_alpha: wgpu::RenderPipeline,
    shadow: wgpu::RenderPipeline,
    shadow_opaque: wgpu::RenderPipeline,
    shadow_baked: wgpu::RenderPipeline,
    shadow_opaque_baked: wgpu::RenderPipeline,
    smoke: wgpu::ComputePipeline,
    absorption: wgpu::ComputePipeline,
    tile_build: wgpu::ComputePipeline,
}
struct Timing {
    slots: Vec<TimingSlot>,
    compute_slots: Vec<ComputeTimingSlot>,
    next_slot: usize,
    next_compute_slot: usize,
}
struct TimingSlot {
    query: wgpu::QuerySet,
    resolve: wgpu::Buffer,
    read: wgpu::Buffer,
    pending: Option<mpsc::Receiver<std::result::Result<(), wgpu::BufferAsyncError>>>,
    frame: u64,
    optical: bool,
    shadow_rendered: bool,
    absorption_cache: bool,
    submitted_at: Option<Instant>,
}
struct ComputeTimingSlot {
    query: wgpu::QuerySet,
    resolve: wgpu::Buffer,
    read: wgpu::Buffer,
    pending: Option<mpsc::Receiver<std::result::Result<(), wgpu::BufferAsyncError>>>,
    tick: u64,
    submitted_at: Option<Instant>,
}
struct TileStatsReadback {
    read: wgpu::Buffer,
    pending: Option<mpsc::Receiver<std::result::Result<(), wgpu::BufferAsyncError>>>,
    frame: u64,
}
const TIMING_SLOTS: usize = 3;
const COMPUTE_TIMING_SLOTS: usize = 6;
const GPU_QUERY_COUNT: u32 = 14;
const GPU_QUERY_BYTES: u64 = GPU_QUERY_COUNT as u64 * 8;
const COMPUTE_QUERY_BYTES: u64 = 16;
const TILE_SIZE: u32 = 16;
const FIRE_TILE_CAPACITY: u32 = 64;
const SMOKE_TILE_CAPACITY: u32 = 36;
const POINT_TILE_CAPACITY: u32 = 8;
const PARTICLE_TILE_CAPACITY: u32 = 12;

pub struct Renderer {
    pub device: wgpu::Device,
    pub queue: wgpu::Queue,
    pub adapter: wgpu::Adapter,
    pub pixels: wgpu::TextureView,
    pub metrics: FrameMetrics,
    pixel_texture: wgpu::Texture,
    resolution: [u32; 2],
    uniform: wgpu::Buffer,
    fire_buffer: wgpu::Buffer,
    fire_storage: FireFrameStorage,
    fire_key: Option<FireKey>,
    multi_fire_keys: Vec<(String, FireKey)>,
    multi_fire_tiers: Vec<(String, u8)>,
    fire_frame: FireFrame,
    fire_lod_tier: u8,
    fire_render_segments: u32,
    globals: wgpu::BindGroup,
    global_layout: wgpu::BindGroupLayout,
    textures: wgpu::BindGroup,
    texture_layout: wgpu::BindGroupLayout,
    material_buffer: wgpu::Buffer,
    shadow_materials: wgpu::BindGroup,
    shadow_material_layout: wgpu::BindGroupLayout,
    material_cache: Vec<Material>,
    optical_layout: wgpu::BindGroupLayout,
    optical_group: wgpu::BindGroup,
    optical_smoke_groups: [wgpu::BindGroup; 2],
    optical_smoke_layout: wgpu::BindGroupLayout,
    optical_sampler: wgpu::Sampler,
    scene_color: Option<wgpu::Texture>,
    optical_output: Option<wgpu::Texture>,
    optical_mask: Option<wgpu::Texture>,
    optical_post_groups: Option<[wgpu::BindGroup; 2]>,
    optical_no_copy_enabled: bool,
    optical_mask_required: bool,
    absorption_texture: Option<wgpu::Texture>,
    absorption_cache_resolution: u32,
    absorption_layout: wgpu::BindGroupLayout,
    absorption_groups: Option<[wgpu::BindGroup; 2]>,
    absorption_cache_active: bool,
    absorption_cache_dirty: bool,
    hdr_texture: wgpu::Texture,
    hdr_color_format: wgpu::TextureFormat,
    effect_depth_format: wgpu::TextureFormat,
    smoke_volume_format: wgpu::TextureFormat,
    volume_groups: [wgpu::BindGroup; 2],
    volume_layout: wgpu::BindGroupLayout,
    shading_diagnostic_buffer: wgpu::Buffer,
    shading_diagnostics_enabled: bool,
    smoke_groups: Vec<[wgpu::BindGroup; 2]>,
    smoke_source_buffers: Vec<wgpu::Buffer>,
    smoke_config_cache: Vec<SmokeSimulationConfig>,
    smoke_layout: wgpu::BindGroupLayout,
    post_groups: [wgpu::BindGroup; 2],
    effect_depth: wgpu::TextureView,
    post_layout: wgpu::BindGroupLayout,
    shadow_groups: Vec<wgpu::BindGroup>,
    shadow_buffers: Vec<wgpu::Buffer>,
    shadow_layout: wgpu::BindGroupLayout,
    sun_view: wgpu::TextureView,
    point_faces: Vec<wgpu::TextureView>,
    hdr: wgpu::TextureView,
    normals: wgpu::TextureView,
    depth: wgpu::TextureView,
    smoke_textures: Vec<[wgpu::Texture; 2]>,
    smoke_index: usize,
    vertex: wgpu::Buffer,
    unshared_vertices: Vec<Vertex>,
    unshared_vertex_buffer: Option<wgpu::Buffer>,
    vertex_count: u32,
    object_draws: Vec<assets::ObjectDrawRange>,
    mesh_draws: Vec<assets::MeshDrawRange>,
    instance_buffers: Vec<wgpu::Buffer>,
    geometry_culling_enabled: bool,
    geometry_instancing_enabled: bool,
    tile_list_layout: wgpu::BindGroupLayout,
    tile_build_layout: wgpu::BindGroupLayout,
    tile_build_group: wgpu::BindGroup,
    tile_list_groups: [wgpu::BindGroup; 2],
    tile_headers: wgpu::Buffer,
    fire_tile_indices: wgpu::Buffer,
    smoke_tile_indices: wgpu::Buffer,
    point_tile_indices: wgpu::Buffer,
    particle_tile_indices: wgpu::Buffer,
    tile_config_buffer: wgpu::Buffer,
    tile_stats_buffer: wgpu::Buffer,
    tile_stats_readbacks: Vec<TileStatsReadback>,
    next_tile_stats_readback: usize,
    tile_count: u32,
    tile_force_overflow: bool,
    tile_lists_enabled: bool,
    pipelines: Pipelines,
    timing: Option<Timing>,
    completed_gpu_timings: VecDeque<GpuTimingSample>,
    completed_compute_timings: VecDeque<GpuComputeTimingSample>,
    resource_inventory: serde_json::Value,
    shadow_cache_key: Option<ShadowCacheKey>,
    shadow_invalidation_reason: Option<&'static str>,
    shadow_transform_changes: Vec<(String, Option<assets::Bounds3>, Option<assets::Bounds3>)>,
    shadow_dirty_faces: [bool; 7],
    shadow_visible_cache: [u32; 7],
    shadow_batch_cache: [u32; 7],
    shadow_vertex_cache: [u64; 7],
    force_shadow_redraw: bool,
    pub shader_directory: PathBuf,
}

#[derive(Clone, PartialEq)]
struct ShadowCacheKey {
    casters: Vec<crate::scene::Object>,
    shadow_materials: Vec<(String, f32)>,
    sun_position: [f32; 3],
    fire_position: [f32; 3],
    fire_range: f32,
}

fn shadow_cache_key(scene: &Scene) -> Option<ShadowCacheKey> {
    let sun = scene
        .lights
        .iter()
        .find(|light| light.kind == LightKind::Directional)?;
    let emitter = scene.emitters.first()?;
    let fire = scene.light_for_emitter(emitter)?;
    Some(ShadowCacheKey {
        casters: scene.objects.clone(),
        shadow_materials: scene
            .materials
            .iter()
            .map(|material| {
                (
                    material.id.clone(),
                    material.transmission * (1. - material.metallic),
                )
            })
            .collect(),
        sun_position: sun.position,
        fire_position: fire.position,
        fire_range: fire.range,
    })
}

fn shadow_dirty_reason(previous: Option<&ShadowCacheKey>, next: &ShadowCacheKey) -> &'static str {
    let Some(previous) = previous else {
        return "resource_initialization";
    };
    if previous.casters != next.casters {
        "casters_changed"
    } else if previous.shadow_materials != next.shadow_materials {
        "shadow_materials_changed"
    } else if previous.sun_position != next.sun_position {
        "directional_light_projection_changed"
    } else if previous.fire_position != next.fire_position {
        "point_light_projection_changed"
    } else if previous.fire_range != next.fire_range {
        "point_light_range_changed"
    } else {
        "unchanged"
    }
}

fn shadow_face_mask_for_bounds(
    bounds: &[Option<assets::Bounds3>],
    matrices: &[Mat4; 7],
) -> [bool; 7] {
    let mut dirty = [false; 7];
    for bound in bounds {
        let Some(bound) = bound else {
            return [true; 7];
        };
        for (index, matrix) in matrices.iter().enumerate() {
            let Some(frustum) = Frustum::from_view_projection(*matrix) else {
                return [true; 7];
            };
            dirty[index] |= frustum.intersects(bound);
        }
    }
    dirty
}

fn shadow_bounds_require_full_fallback(
    bounds: &[Option<assets::Bounds3>],
    matrices: &[Mat4; 7],
) -> bool {
    bounds.iter().any(Option::is_none)
        || matrices
            .iter()
            .any(|matrix| Frustum::from_view_projection(*matrix).is_none())
}

fn only_object_transforms_changed(previous: &ShadowCacheKey, next: &ShadowCacheKey) -> bool {
    if previous.casters.len() != next.casters.len() {
        return false;
    }
    previous
        .casters
        .iter()
        .zip(&next.casters)
        .all(|(old, new)| {
            old.id == new.id
                && old.material == new.material
                && old.geometry == new.geometry
                && (old.position != new.position
                    || old.rotation != new.rotation
                    || old.scale != new.scale
                    || old == new)
        })
}

fn texture(
    device: &wgpu::Device,
    label: &str,
    size: [u32; 3],
    format: wgpu::TextureFormat,
    usage: wgpu::TextureUsages,
    dimension: wgpu::TextureDimension,
) -> wgpu::Texture {
    device.create_texture(&wgpu::TextureDescriptor {
        label: Some(label),
        size: wgpu::Extent3d {
            width: size[0],
            height: size[1],
            depth_or_array_layers: size[2],
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension,
        format,
        usage,
        view_formats: &[],
    })
}

fn format_capability(adapter: &wgpu::Adapter, format: wgpu::TextureFormat) -> serde_json::Value {
    let features = adapter.get_texture_format_features(format);
    serde_json::json!({
        "format": format!("{format:?}"),
        "allowed_usages": {
            "texture_binding": features.allowed_usages.contains(wgpu::TextureUsages::TEXTURE_BINDING),
            "storage_binding": features.allowed_usages.contains(wgpu::TextureUsages::STORAGE_BINDING),
            "render_attachment": features.allowed_usages.contains(wgpu::TextureUsages::RENDER_ATTACHMENT),
            "copy_src": features.allowed_usages.contains(wgpu::TextureUsages::COPY_SRC),
            "copy_dst": features.allowed_usages.contains(wgpu::TextureUsages::COPY_DST),
        },
        "filterable": features.flags.contains(wgpu::TextureFormatFeatureFlags::FILTERABLE),
        "storage_write_only": features.flags.contains(wgpu::TextureFormatFeatureFlags::STORAGE_WRITE_ONLY),
    })
}

fn select_effect_depth_format(features: wgpu::TextureFormatFeatures) -> wgpu::TextureFormat {
    if features
        .allowed_usages
        .contains(wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING)
        && features
            .flags
            .contains(wgpu::TextureFormatFeatureFlags::FILTERABLE)
    {
        wgpu::TextureFormat::Rg16Float
    } else {
        HDR
    }
}

fn select_smoke_volume_format(
    features: wgpu::TextureFormatFeatures,
    adapter_specific_formats: bool,
) -> wgpu::TextureFormat {
    if adapter_specific_formats
        && features
            .allowed_usages
            .contains(wgpu::TextureUsages::STORAGE_BINDING | wgpu::TextureUsages::TEXTURE_BINDING)
        && features
            .flags
            .contains(wgpu::TextureFormatFeatureFlags::FILTERABLE)
        && features
            .flags
            .contains(wgpu::TextureFormatFeatureFlags::STORAGE_WRITE_ONLY)
    {
        wgpu::TextureFormat::Rg16Float
    } else {
        HDR
    }
}
fn binding(
    binding: u32,
    visibility: wgpu::ShaderStages,
    ty: wgpu::BindingType,
) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility,
        ty,
        count: None,
    }
}
fn sampled(
    dimension: wgpu::TextureViewDimension,
    sample_type: wgpu::TextureSampleType,
) -> wgpu::BindingType {
    wgpu::BindingType::Texture {
        sample_type,
        view_dimension: dimension,
        multisampled: false,
    }
}
fn group(
    device: &wgpu::Device,
    layout: &wgpu::BindGroupLayout,
    resources: &[wgpu::BindingResource<'_>],
) -> wgpu::BindGroup {
    device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: None,
        layout,
        entries: &resources
            .iter()
            .enumerate()
            .map(|(i, r)| wgpu::BindGroupEntry {
                binding: i as u32,
                resource: r.clone(),
            })
            .collect::<Vec<_>>(),
    })
}
fn color_target(
    format: wgpu::TextureFormat,
    blend: Option<wgpu::BlendState>,
) -> Option<wgpu::ColorTargetState> {
    Some(wgpu::ColorTargetState {
        format,
        blend,
        write_mask: wgpu::ColorWrites::ALL,
    })
}
fn shader(device: &wgpu::Device, label: &str, source: String) -> wgpu::ShaderModule {
    device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some(label),
        source: wgpu::ShaderSource::Wgsl(source.into()),
    })
}
const ATTRIBUTES: [wgpu::VertexAttribute; 8] = wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x3,2=>Float32x3,3=>Float32x2,4=>Float32,5=>Float32,6=>Float32,7=>Uint32];
const INSTANCE_ATTRIBUTES: [wgpu::VertexAttribute; 7] = wgpu::vertex_attr_array![8=>Float32x4,9=>Float32x4,10=>Float32x4,11=>Float32x4,12=>Float32x4,13=>Float32x4,14=>Float32x4];
fn vertex_layout() -> wgpu::VertexBufferLayout<'static> {
    wgpu::VertexBufferLayout {
        array_stride: std::mem::size_of::<Vertex>() as u64,
        step_mode: wgpu::VertexStepMode::Vertex,
        attributes: &ATTRIBUTES,
    }
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct InstanceGpu {
    model: [[f32; 4]; 4],
    normal: [[f32; 4]; 3],
}

impl InstanceGpu {
    fn from_transform(columns: [[f32; 4]; 4]) -> Self {
        let model = Mat4::from_cols_array_2d(&columns);
        let normal = Mat3::from_mat4(model).inverse().transpose();
        Self {
            model: columns,
            normal: [
                normal.x_axis.extend(0.).to_array(),
                normal.y_axis.extend(0.).to_array(),
                normal.z_axis.extend(0.).to_array(),
            ],
        }
    }
}

fn instance_layout() -> wgpu::VertexBufferLayout<'static> {
    wgpu::VertexBufferLayout {
        array_stride: std::mem::size_of::<InstanceGpu>() as u64,
        step_mode: wgpu::VertexStepMode::Instance,
        attributes: &INSTANCE_ATTRIBUTES,
    }
}

#[derive(Clone, Copy, Debug)]
struct Frustum {
    planes: [Vec4; 6],
}

impl Frustum {
    /// Extracts the WebGPU 0..1 clip-depth planes. Invalid matrices disable culling.
    fn from_view_projection(matrix: Mat4) -> Option<Self> {
        if !matrix.is_finite() {
            return None;
        }
        let c = matrix.to_cols_array_2d();
        let row = |r: usize| Vec4::new(c[0][r], c[1][r], c[2][r], c[3][r]);
        let r0 = row(0);
        let r1 = row(1);
        let r2 = row(2);
        let r3 = row(3);
        let raw = [r3 + r0, r3 - r0, r3 + r1, r3 - r1, r2, r3 - r2];
        let mut planes = [Vec4::ZERO; 6];
        for (out, plane) in planes.iter_mut().zip(raw) {
            let normal_len = plane.truncate().length();
            if !normal_len.is_finite() || normal_len <= 1e-8 {
                return None;
            }
            *out = plane / normal_len;
        }
        Some(Self { planes })
    }

    fn intersects(&self, bounds: &assets::Bounds3) -> bool {
        let min = Vec3::from(bounds.min);
        let max = Vec3::from(bounds.max);
        if !min.is_finite() || !max.is_finite() || !min.cmple(max).all() {
            return true;
        }
        let center = (min + max) * 0.5;
        let half = (max - min) * 0.5;
        self.planes.iter().all(|plane| {
            let normal = plane.truncate();
            let distance = normal.dot(center) + plane.w;
            let radius = normal.abs().dot(half);
            distance + radius >= 0.
        })
    }
}

#[derive(Clone, Copy, Debug)]
struct DrawBatch {
    mesh_index: usize,
    first_vertex: u32,
    vertex_count: u32,
    first_instance: u32,
    instance_count: u32,
    optical: bool,
}

#[derive(Default)]
struct PreparedDraws {
    instances: Vec<InstanceGpu>,
    batches: Vec<DrawBatch>,
    visible_objects: u32,
}

fn submitted_vertices(draws: &PreparedDraws) -> u64 {
    draws
        .batches
        .iter()
        .map(|batch| u64::from(batch.vertex_count) * u64::from(batch.instance_count))
        .sum()
}

fn prepare_draws(
    objects: &[assets::ObjectDrawRange],
    meshes: &[assets::MeshDrawRange],
    materials: &[Material],
    frustum: Option<Frustum>,
    culling_enabled: bool,
    instancing_enabled: bool,
) -> PreparedDraws {
    let mut result = PreparedDraws::default();
    for (object_index, object) in objects.iter().enumerate() {
        let visible = !culling_enabled
            || frustum
                .as_ref()
                .zip(object.bounds.as_ref())
                .is_none_or(|(frustum, bounds)| frustum.intersects(bounds));
        if !visible {
            continue;
        }
        let Some(mesh) = meshes.get(object.mesh_index) else {
            continue;
        };
        let optical = materials
            .iter()
            .find(|material| material.id == object.material_id)
            .is_some_and(|material| {
                material.metallic > 0. || material.reflectivity > 0. || material.transmission > 0.
            });
        let instance_index = if instancing_enabled {
            let instance_index = result.instances.len() as u32;
            result
                .instances
                .push(InstanceGpu::from_transform(object.transform));
            instance_index
        } else {
            0
        };
        result.visible_objects += 1;
        let can_extend = instancing_enabled
            && result.batches.last().is_some_and(|batch| {
                batch.mesh_index == object.mesh_index
                    && batch.optical == optical
                    && batch.first_instance + batch.instance_count == instance_index
            });
        if can_extend {
            result.batches.last_mut().unwrap().instance_count += 1;
        } else {
            result.batches.push(DrawBatch {
                mesh_index: if instancing_enabled {
                    object.mesh_index
                } else {
                    object_index
                },
                first_vertex: if instancing_enabled {
                    mesh.first_vertex
                } else {
                    object.baked_first_vertex
                },
                vertex_count: if instancing_enabled {
                    mesh.vertex_count
                } else {
                    object.vertex_count
                },
                first_instance: instance_index,
                instance_count: 1,
                optical,
            });
        }
    }
    result
}

fn shadow_matrices(scene: &Scene) -> [Mat4; 7] {
    let sun = scene
        .lights
        .iter()
        .find(|light| light.kind == LightKind::Directional)
        .expect("validated scene has a directional light");
    let fire = scene
        .light_for_emitter(&scene.emitters[0])
        .expect("validated scene has an emitter point light");
    let sun_direction = Vec3::from(sun.position).normalize();
    let mut result = [Mat4::IDENTITY; 7];
    result[0] = Mat4::orthographic_rh(-24., 24., -24., 24., 0.1, 100.)
        * Mat4::look_at_rh(
            sun_direction * 40.,
            Vec3::ZERO,
            if sun_direction.dot(Vec3::Y).abs() > 0.99 {
                Vec3::Z
            } else {
                Vec3::Y
            },
        );
    let position = Vec3::from(fire.position);
    for (index, (direction, up)) in [
        (Vec3::X, Vec3::NEG_Y),
        (Vec3::NEG_X, Vec3::NEG_Y),
        (Vec3::Y, Vec3::Z),
        (Vec3::NEG_Y, Vec3::NEG_Z),
        (Vec3::Z, Vec3::NEG_Y),
        (Vec3::NEG_Z, Vec3::NEG_Y),
    ]
    .into_iter()
    .enumerate()
    {
        result[index + 1] = Mat4::perspective_rh(std::f32::consts::FRAC_PI_2, 1., 0.05, fire.range)
            * Mat4::look_at_rh(position, position + direction, up);
    }
    result
}

impl Renderer {
    pub async fn new(
        instance: &wgpu::Instance,
        surface: Option<&wgpu::Surface<'_>>,
        scene: &Scene,
        base: &Path,
        shader_directory: PathBuf,
    ) -> Result<Self> {
        Self::new_with_timing(instance, surface, scene, base, shader_directory, true).await
    }

    pub async fn new_with_timing(
        instance: &wgpu::Instance,
        surface: Option<&wgpu::Surface<'_>>,
        scene: &Scene,
        base: &Path,
        shader_directory: PathBuf,
        enable_timestamps: bool,
    ) -> Result<Self> {
        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                compatible_surface: surface,
                force_fallback_adapter: false,
            })
            .await
            .context("no compatible desktop GPU adapter")?;
        let compact_hdr_format = wgpu::TextureFormat::Rg11b10Ufloat;
        let compact_hdr_features = adapter.get_texture_format_features(compact_hdr_format);
        let compact_hdr_render_feature = adapter
            .features()
            .contains(wgpu::Features::RG11B10UFLOAT_RENDERABLE);
        let compact_hdr_supported = compact_hdr_render_feature
            && compact_hdr_features.allowed_usages.contains(
                wgpu::TextureUsages::RENDER_ATTACHMENT
                    | wgpu::TextureUsages::TEXTURE_BINDING
                    | wgpu::TextureUsages::COPY_SRC
                    | wgpu::TextureUsages::COPY_DST,
            )
            && compact_hdr_features
                .flags
                .contains(wgpu::TextureFormatFeatureFlags::FILTERABLE);
        let hdr_color_format = if scene.render.compact_hdr && compact_hdr_supported {
            compact_hdr_format
        } else {
            HDR
        };
        let optical_mask_format = wgpu::TextureFormat::R8Unorm;
        let optical_mask_features = adapter.get_texture_format_features(optical_mask_format);
        let optical_mask_required = hdr_color_format == compact_hdr_format;
        let optical_no_copy_supported = if optical_mask_required {
            optical_mask_features.allowed_usages.contains(
                wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
            )
        } else {
            adapter
                .get_texture_format_features(HDR)
                .allowed_usages
                .contains(
                    wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
                )
        };
        let optical_no_copy_enabled = scene.render.optical_no_copy && optical_no_copy_supported;
        let rg16_features = adapter.get_texture_format_features(wgpu::TextureFormat::Rg16Float);
        let effect_depth_format = select_effect_depth_format(rg16_features);
        let adapter_format_feature = wgpu::Features::TEXTURE_ADAPTER_SPECIFIC_FORMAT_FEATURES;
        let adapter_format_feature_available = adapter.features().contains(adapter_format_feature);
        let smoke_volume_format =
            select_smoke_volume_format(rg16_features, adapter_format_feature_available);
        let smoke_rg16_supported = smoke_volume_format == wgpu::TextureFormat::Rg16Float;
        let timestamp =
            enable_timestamps && adapter.features().contains(wgpu::Features::TIMESTAMP_QUERY);
        let mut required_features = wgpu::Features::empty();
        if timestamp {
            required_features |= wgpu::Features::TIMESTAMP_QUERY;
        }
        if smoke_rg16_supported {
            required_features |= adapter_format_feature;
        }
        if hdr_color_format == compact_hdr_format {
            required_features |= wgpu::Features::RG11B10UFLOAT_RENDERABLE;
        }
        let (device, queue) = adapter
            .request_device(
                &wgpu::DeviceDescriptor {
                    label: Some("Pixel Engine"),
                    required_features,
                    required_limits: wgpu::Limits::default(),
                    memory_hints: wgpu::MemoryHints::Performance,
                },
                None,
            )
            .await?;
        let global_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("globals"),
            entries: &[
                binding(
                    0,
                    wgpu::ShaderStages::VERTEX_FRAGMENT | wgpu::ShaderStages::COMPUTE,
                    wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                ),
                binding(
                    1,
                    wgpu::ShaderStages::FRAGMENT | wgpu::ShaderStages::COMPUTE,
                    wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                ),
                binding(
                    2,
                    wgpu::ShaderStages::FRAGMENT,
                    wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: false },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                ),
            ],
        });
        let shading_diagnostic_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("opt-in shading diagnostic counters"),
            size: 22 * 4,
            usage: wgpu::BufferUsages::STORAGE
                | wgpu::BufferUsages::COPY_SRC
                | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let fire_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("bounded fire primitives"),
            contents: bytemuck::bytes_of(&FireFrameStorage::zeroed()),
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
        });
        let uniform = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("globals"),
            contents: bytemuck::bytes_of(&Globals::zeroed()),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        let globals = group(
            &device,
            &global_layout,
            &[
                uniform.as_entire_binding(),
                fire_buffer.as_entire_binding(),
                shading_diagnostic_buffer.as_entire_binding(),
            ],
        );
        let material_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("live material table"),
            contents: bytemuck::cast_slice(&material_table(scene)),
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
        });
        // Shadow passes must not bind the depth textures they are writing.
        let shadow_material_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("shadow materials only"),
                entries: &[binding(
                    5,
                    wgpu::ShaderStages::VERTEX_FRAGMENT,
                    wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                )],
            });
        let shadow_materials = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("shadow materials only"),
            layout: &shadow_material_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 5,
                resource: material_buffer.as_entire_binding(),
            }],
        });
        let texture_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("lighting/materials"),
            entries: &[
                binding(
                    0,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D2,
                        wgpu::TextureSampleType::Depth,
                    ),
                ),
                binding(
                    1,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::Cube,
                        wgpu::TextureSampleType::Depth,
                    ),
                ),
                binding(
                    2,
                    wgpu::ShaderStages::FRAGMENT,
                    wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Comparison),
                ),
                binding(
                    3,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D2Array,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    4,
                    wgpu::ShaderStages::FRAGMENT,
                    wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                ),
                binding(
                    5,
                    wgpu::ShaderStages::VERTEX_FRAGMENT,
                    wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                ),
            ],
        });
        let sun = texture(
            &device,
            "sun shadow",
            [1024, 1024, 1],
            DEPTH,
            wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
            wgpu::TextureDimension::D2,
        );
        let sun_view = sun.create_view(&Default::default());
        let point = texture(
            &device,
            "fire shadows",
            [256, 256, 6],
            DEPTH,
            wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
            wgpu::TextureDimension::D2,
        );
        let point_view = point.create_view(&wgpu::TextureViewDescriptor {
            dimension: Some(wgpu::TextureViewDimension::Cube),
            ..Default::default()
        });
        let point_faces = (0..6)
            .map(|i| {
                point.create_view(&wgpu::TextureViewDescriptor {
                    dimension: Some(wgpu::TextureViewDimension::D2),
                    base_array_layer: i,
                    array_layer_count: Some(1),
                    ..Default::default()
                })
            })
            .collect();
        let comparison = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("shadow sampler"),
            compare: Some(wgpu::CompareFunction::LessEqual),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        let mesh = assets::load(scene, base)?;
        if mesh.textures.len() > device.limits().max_texture_array_layers as usize {
            anyhow::bail!("materials: texture count exceeds adapter array-layer limit");
        }
        if (mesh.vertices.len() * std::mem::size_of::<Vertex>()) as u64
            > device.limits().max_buffer_size
        {
            anyhow::bail!("objects: geometry exceeds adapter buffer-size limit");
        }
        let atlas = texture(
            &device,
            "material atlas",
            [128, 128, mesh.textures.len() as u32],
            wgpu::TextureFormat::Rgba8UnormSrgb,
            wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            wgpu::TextureDimension::D2,
        );
        for (i, image) in mesh.textures.iter().enumerate() {
            let resized =
                image::imageops::resize(image, 128, 128, image::imageops::FilterType::Nearest);
            queue.write_texture(
                wgpu::TexelCopyTextureInfo {
                    texture: &atlas,
                    mip_level: 0,
                    origin: wgpu::Origin3d {
                        x: 0,
                        y: 0,
                        z: i as u32,
                    },
                    aspect: wgpu::TextureAspect::All,
                },
                &resized,
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(512),
                    rows_per_image: Some(128),
                },
                wgpu::Extent3d {
                    width: 128,
                    height: 128,
                    depth_or_array_layers: 1,
                },
            );
        }
        let atlas_view = atlas.create_view(&wgpu::TextureViewDescriptor {
            dimension: Some(wgpu::TextureViewDimension::D2Array),
            ..Default::default()
        });
        let atlas_sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            address_mode_u: wgpu::AddressMode::Repeat,
            address_mode_v: wgpu::AddressMode::Repeat,
            ..Default::default()
        });
        let textures = group(
            &device,
            &texture_layout,
            &[
                wgpu::BindingResource::TextureView(&sun_view),
                wgpu::BindingResource::TextureView(&point_view),
                wgpu::BindingResource::Sampler(&comparison),
                wgpu::BindingResource::TextureView(&atlas_view),
                wgpu::BindingResource::Sampler(&atlas_sampler),
                material_buffer.as_entire_binding(),
            ],
        );
        let [w, h] = scene.render.resolution;
        let tiles_x = w.div_ceil(TILE_SIZE);
        let tiles_y = h.div_ceil(TILE_SIZE);
        let tile_count = tiles_x * tiles_y;
        let storage = |read_only| wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Storage { read_only },
            has_dynamic_offset: false,
            min_binding_size: None,
        };
        let tile_list_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("per-tile effect lists"),
            entries: &[
                binding(0, wgpu::ShaderStages::FRAGMENT, storage(true)),
                binding(1, wgpu::ShaderStages::FRAGMENT, storage(true)),
                binding(2, wgpu::ShaderStages::FRAGMENT, storage(true)),
                binding(3, wgpu::ShaderStages::FRAGMENT, storage(true)),
                binding(4, wgpu::ShaderStages::FRAGMENT, storage(true)),
                binding(
                    5,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D3,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    6,
                    wgpu::ShaderStages::FRAGMENT,
                    wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                ),
            ],
        });
        let tile_build_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("tile-list build outputs"),
            entries: &[
                binding(0, wgpu::ShaderStages::COMPUTE, storage(false)),
                binding(1, wgpu::ShaderStages::COMPUTE, storage(false)),
                binding(2, wgpu::ShaderStages::COMPUTE, storage(false)),
                binding(3, wgpu::ShaderStages::COMPUTE, storage(false)),
                binding(4, wgpu::ShaderStages::COMPUTE, storage(false)),
                binding(
                    5,
                    wgpu::ShaderStages::COMPUTE,
                    wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                ),
                binding(6, wgpu::ShaderStages::COMPUTE, storage(false)),
            ],
        });
        let make_storage = |label, size| {
            device.create_buffer(&wgpu::BufferDescriptor {
                label: Some(label),
                size,
                usage: wgpu::BufferUsages::STORAGE,
                mapped_at_creation: false,
            })
        };
        let tile_headers = make_storage("tile headers", u64::from(tile_count) * 32);
        let fire_tile_indices = make_storage(
            "fire indices per tile",
            u64::from(tile_count) * u64::from(FIRE_TILE_CAPACITY) * 4,
        );
        let smoke_tile_indices = make_storage(
            "smoke indices per tile",
            u64::from(tile_count) * u64::from(SMOKE_TILE_CAPACITY) * 4,
        );
        let point_tile_indices = make_storage(
            "point-light indices per tile",
            u64::from(tile_count) * u64::from(POINT_TILE_CAPACITY) * 4,
        );
        let particle_tile_indices = make_storage(
            "particle-light indices per tile",
            u64::from(tile_count) * u64::from(PARTICLE_TILE_CAPACITY) * 4,
        );
        let tile_config_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("tile-list debug configuration"),
            contents: bytemuck::bytes_of(&TileConfigGpu::zeroed()),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        let tile_stats_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("tile-list occupancy counters"),
            size: 48,
            usage: wgpu::BufferUsages::STORAGE
                | wgpu::BufferUsages::COPY_DST
                | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        });
        let tile_stats_readbacks = (0..3)
            .map(|_| TileStatsReadback {
                read: device.create_buffer(&wgpu::BufferDescriptor {
                    label: Some("tile-list statistics readback"),
                    size: 48,
                    usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
                    mapped_at_creation: false,
                }),
                pending: None,
                frame: 0,
            })
            .collect::<Vec<_>>();
        let tile_build_group = group(
            &device,
            &tile_build_layout,
            &[
                tile_headers.as_entire_binding(),
                fire_tile_indices.as_entire_binding(),
                smoke_tile_indices.as_entire_binding(),
                point_tile_indices.as_entire_binding(),
                particle_tile_indices.as_entire_binding(),
                tile_config_buffer.as_entire_binding(),
                tile_stats_buffer.as_entire_binding(),
            ],
        );
        let use_color =
            wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING;
        let hdr_texture = texture(
            &device,
            "HDR",
            [w, h, 1],
            hdr_color_format,
            use_color
                | if optical_no_copy_enabled {
                    wgpu::TextureUsages::empty()
                } else {
                    wgpu::TextureUsages::COPY_SRC
                },
            wgpu::TextureDimension::D2,
        );
        let hdr = hdr_texture.create_view(&Default::default());
        let normals_texture = texture(
            &device,
            "normal/depth",
            [w, h, 1],
            HDR,
            use_color | wgpu::TextureUsages::COPY_SRC,
            wgpu::TextureDimension::D2,
        );
        let normals = normals_texture.create_view(&Default::default());
        let depth = texture(
            &device,
            "depth",
            [w, h, 1],
            DEPTH,
            use_color,
            wgpu::TextureDimension::D2,
        )
        .create_view(&Default::default());
        let pixel_texture = texture(
            &device,
            "pixel output",
            [w, h, 1],
            PIXEL_FORMAT,
            use_color | wgpu::TextureUsages::COPY_SRC,
            wgpu::TextureDimension::D2,
        );
        let pixels = pixel_texture.create_view(&Default::default());
        let mut smoke_emitters = scene.emitters.iter().collect::<Vec<_>>();
        smoke_emitters.sort_by(|left, right| left.id.cmp(&right.id));
        let smoke_textures = smoke_emitters
            .iter()
            .map(|source| {
                std::array::from_fn(|_| {
                    texture(
                        &device,
                        &format!("smoke density/temperature source {}", source.id),
                        VOLUME,
                        smoke_volume_format,
                        wgpu::TextureUsages::TEXTURE_BINDING
                            | wgpu::TextureUsages::STORAGE_BINDING
                            | wgpu::TextureUsages::COPY_DST,
                        wgpu::TextureDimension::D3,
                    )
                })
            })
            .collect::<Vec<_>>();
        let smoke_views: Vec<[wgpu::TextureView; 2]> = smoke_textures
            .iter()
            .map(|textures| std::array::from_fn(|i| textures[i].create_view(&Default::default())))
            .collect::<Vec<_>>();
        let smoke_source_buffers = smoke_emitters
            .iter()
            .map(|_| {
                device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                    label: Some("per-emitter smoke simulation config"),
                    contents: bytemuck::bytes_of(&SmokeSimulationConfig::zeroed()),
                    usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                })
            })
            .collect::<Vec<_>>();
        let absorption_cache_resolution = scene.render.absorption_cache_resolution;
        let absorption_cache_enabled = scene.render.experiments.smoke_absorption_cache;
        let absorption_texture = absorption_cache_enabled.then(|| {
            texture(
                &device,
                "coarse fire-light smoke transmittance",
                [absorption_cache_resolution; 3],
                HDR,
                wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::STORAGE_BINDING,
                wgpu::TextureDimension::D3,
            )
        });
        let absorption_view = absorption_texture
            .as_ref()
            .map(|texture| texture.create_view(&Default::default()));
        let linear = device.create_sampler(&wgpu::SamplerDescriptor {
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        let tile_list_groups = std::array::from_fn(|i| {
            group(
                &device,
                &tile_list_layout,
                &[
                    tile_headers.as_entire_binding(),
                    fire_tile_indices.as_entire_binding(),
                    smoke_tile_indices.as_entire_binding(),
                    point_tile_indices.as_entire_binding(),
                    particle_tile_indices.as_entire_binding(),
                    wgpu::BindingResource::TextureView(&smoke_views[0][i]),
                    wgpu::BindingResource::Sampler(&linear),
                ],
            )
        });
        let scene_color = None;
        let optical_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("single-layer optical surfaces"),
            entries: &[
                binding(
                    0,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D2,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    1,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D2,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    2,
                    wgpu::ShaderStages::FRAGMENT,
                    wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                ),
            ],
        });
        let optical_group = group(
            &device,
            &optical_layout,
            &[
                wgpu::BindingResource::TextureView(&hdr),
                wgpu::BindingResource::TextureView(&normals),
                wgpu::BindingResource::Sampler(&linear),
            ],
        );
        let volume_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("volumetrics"),
            entries: &[
                binding(
                    0,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D2,
                        wgpu::TextureSampleType::Depth,
                    ),
                ),
                binding(
                    1,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D3,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    2,
                    wgpu::ShaderStages::FRAGMENT,
                    wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                ),
                binding(
                    3,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D3,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
            ],
        });
        let volume_groups = std::array::from_fn(|i| {
            group(
                &device,
                &volume_layout,
                &[
                    wgpu::BindingResource::TextureView(&depth),
                    wgpu::BindingResource::TextureView(&smoke_views[0][i]),
                    wgpu::BindingResource::Sampler(&linear),
                    wgpu::BindingResource::TextureView(
                        absorption_view.as_ref().unwrap_or(&smoke_views[0][i]),
                    ),
                ],
            )
        });
        // Optical shading reuses the atmosphere integral to preserve foreground
        // smoke/fire. Do not bind the active depth attachment in this pass.
        let optical_smoke_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("optical foreground atmosphere"),
                entries: &[
                    binding(
                        1,
                        wgpu::ShaderStages::FRAGMENT,
                        sampled(
                            wgpu::TextureViewDimension::D3,
                            wgpu::TextureSampleType::Float { filterable: true },
                        ),
                    ),
                    binding(
                        2,
                        wgpu::ShaderStages::FRAGMENT,
                        wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    ),
                    binding(3, wgpu::ShaderStages::FRAGMENT, storage(true)),
                    binding(4, wgpu::ShaderStages::FRAGMENT, storage(true)),
                    binding(5, wgpu::ShaderStages::FRAGMENT, storage(true)),
                    binding(6, wgpu::ShaderStages::FRAGMENT, storage(true)),
                    binding(7, wgpu::ShaderStages::FRAGMENT, storage(true)),
                    binding(
                        8,
                        wgpu::ShaderStages::FRAGMENT,
                        sampled(
                            wgpu::TextureViewDimension::D3,
                            wgpu::TextureSampleType::Float { filterable: true },
                        ),
                    ),
                ],
            });
        let optical_smoke_groups = std::array::from_fn(|i| {
            device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("optical foreground atmosphere"),
                layout: &optical_smoke_layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::TextureView(&smoke_views[0][i]),
                    },
                    wgpu::BindGroupEntry {
                        binding: 2,
                        resource: wgpu::BindingResource::Sampler(&linear),
                    },
                    wgpu::BindGroupEntry {
                        binding: 3,
                        resource: tile_headers.as_entire_binding(),
                    },
                    wgpu::BindGroupEntry {
                        binding: 4,
                        resource: fire_tile_indices.as_entire_binding(),
                    },
                    wgpu::BindGroupEntry {
                        binding: 5,
                        resource: smoke_tile_indices.as_entire_binding(),
                    },
                    wgpu::BindGroupEntry {
                        binding: 6,
                        resource: point_tile_indices.as_entire_binding(),
                    },
                    wgpu::BindGroupEntry {
                        binding: 7,
                        resource: particle_tile_indices.as_entire_binding(),
                    },
                    wgpu::BindGroupEntry {
                        binding: 8,
                        resource: wgpu::BindingResource::TextureView(
                            absorption_view.as_ref().unwrap_or(&smoke_views[0][i]),
                        ),
                    },
                ],
            })
        });
        let smoke_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("advection"),
            entries: &[
                binding(
                    0,
                    wgpu::ShaderStages::COMPUTE,
                    sampled(
                        wgpu::TextureViewDimension::D3,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    1,
                    wgpu::ShaderStages::COMPUTE,
                    wgpu::BindingType::StorageTexture {
                        access: wgpu::StorageTextureAccess::WriteOnly,
                        format: smoke_volume_format,
                        view_dimension: wgpu::TextureViewDimension::D3,
                    },
                ),
                binding(
                    2,
                    wgpu::ShaderStages::COMPUTE,
                    wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                ),
                binding(
                    3,
                    wgpu::ShaderStages::COMPUTE,
                    wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                ),
            ],
        });
        let smoke_groups = (0..scene.emitters.len())
            .map(|source| {
                std::array::from_fn(|i| {
                    group(
                        &device,
                        &smoke_layout,
                        &[
                            wgpu::BindingResource::TextureView(&smoke_views[source][i]),
                            wgpu::BindingResource::TextureView(&smoke_views[source][1 - i]),
                            wgpu::BindingResource::Sampler(&linear),
                            smoke_source_buffers[source].as_entire_binding(),
                        ],
                    )
                })
            })
            .collect::<Vec<_>>();
        let absorption_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("coarse smoke absorption build"),
            entries: &[
                binding(
                    0,
                    wgpu::ShaderStages::COMPUTE,
                    sampled(
                        wgpu::TextureViewDimension::D3,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    1,
                    wgpu::ShaderStages::COMPUTE,
                    wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                ),
                binding(
                    2,
                    wgpu::ShaderStages::COMPUTE,
                    wgpu::BindingType::StorageTexture {
                        access: wgpu::StorageTextureAccess::WriteOnly,
                        format: HDR,
                        view_dimension: wgpu::TextureViewDimension::D3,
                    },
                ),
            ],
        });
        let absorption_groups = absorption_view.as_ref().map(|absorption_view| {
            std::array::from_fn(|i| {
                group(
                    &device,
                    &absorption_layout,
                    &[
                        wgpu::BindingResource::TextureView(&smoke_views[0][i]),
                        wgpu::BindingResource::Sampler(&linear),
                        wgpu::BindingResource::TextureView(absorption_view),
                    ],
                )
            })
        });
        let effect_depth = texture(
            &device,
            "visible atmosphere depth and flame mask",
            [w, h, 1],
            effect_depth_format,
            use_color,
            wgpu::TextureDimension::D2,
        )
        .create_view(&Default::default());
        let post_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("pixel treatment / heat"),
            entries: &[
                binding(
                    0,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D2,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    1,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D2,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    2,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D2,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    3,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D3,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    4,
                    wgpu::ShaderStages::FRAGMENT,
                    wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                ),
                binding(
                    5,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D2,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    6,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D2,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
            ],
        });
        let post_groups = std::array::from_fn(|i| {
            group(
                &device,
                &post_layout,
                &[
                    wgpu::BindingResource::TextureView(&hdr),
                    wgpu::BindingResource::TextureView(&normals),
                    wgpu::BindingResource::TextureView(&effect_depth),
                    wgpu::BindingResource::TextureView(&smoke_views[0][i]),
                    wgpu::BindingResource::Sampler(&linear),
                    wgpu::BindingResource::TextureView(&hdr),
                    wgpu::BindingResource::TextureView(&effect_depth),
                ],
            )
        });
        let shadow_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("shadow camera"),
            entries: &[binding(
                0,
                wgpu::ShaderStages::VERTEX,
                wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
            )],
        });
        let shadow_buffers = (0..7)
            .map(|_| {
                device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                    label: Some("shadow camera"),
                    contents: bytemuck::cast_slice(&Mat4::IDENTITY.to_cols_array()),
                    usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                })
            })
            .collect::<Vec<_>>();
        let shadow_groups = shadow_buffers
            .iter()
            .map(|b| group(&device, &shadow_layout, &[b.as_entire_binding()]))
            .collect();
        let vertex = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("scene geometry"),
            contents: bytemuck::cast_slice(&mesh.vertices),
            usage: wgpu::BufferUsages::VERTEX,
        });
        let instance_capacity = mesh.object_draws.len().max(1) as u64;
        let instance_buffer_bytes =
            instance_capacity * std::mem::size_of::<InstanceGpu>() as u64 * 8;
        let instance_buffers = (0..8)
            .map(|pass| {
                device.create_buffer(&wgpu::BufferDescriptor {
                    label: Some(if pass == 7 {
                        "camera mesh instances"
                    } else {
                        "shadow mesh instances"
                    }),
                    size: instance_capacity * std::mem::size_of::<InstanceGpu>() as u64,
                    usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
                    mapped_at_creation: false,
                })
            })
            .collect::<Vec<_>>();
        let pipelines = Self::pipelines(
            &device,
            &global_layout,
            &texture_layout,
            &optical_layout,
            &optical_smoke_layout,
            &volume_layout,
            &smoke_layout,
            &absorption_layout,
            &post_layout,
            &shadow_layout,
            &shadow_material_layout,
            &tile_list_layout,
            &tile_build_layout,
            effect_depth_format,
            smoke_volume_format,
            hdr_color_format,
            &shader_directory,
        )?;
        let timing = timestamp.then(|| Timing {
            slots: (0..TIMING_SLOTS)
                .map(|_| TimingSlot {
                    query: device.create_query_set(&wgpu::QuerySetDescriptor {
                        label: Some("render stage timestamps"),
                        ty: wgpu::QueryType::Timestamp,
                        count: GPU_QUERY_COUNT,
                    }),
                    resolve: device.create_buffer(&wgpu::BufferDescriptor {
                        label: Some("render stage timestamp resolve"),
                        size: GPU_QUERY_BYTES,
                        usage: wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
                        mapped_at_creation: false,
                    }),
                    read: device.create_buffer(&wgpu::BufferDescriptor {
                        label: Some("render stage timestamp readback"),
                        size: GPU_QUERY_BYTES,
                        usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
                        mapped_at_creation: false,
                    }),
                    pending: None,
                    frame: 0,
                    optical: false,
                    shadow_rendered: false,
                    absorption_cache: false,
                    submitted_at: None,
                })
                .collect(),
            compute_slots: (0..COMPUTE_TIMING_SLOTS)
                .map(|_| ComputeTimingSlot {
                    query: device.create_query_set(&wgpu::QuerySetDescriptor {
                        label: Some("smoke compute timestamps"),
                        ty: wgpu::QueryType::Timestamp,
                        count: 2,
                    }),
                    resolve: device.create_buffer(&wgpu::BufferDescriptor {
                        label: Some("smoke compute timestamp resolve"),
                        size: COMPUTE_QUERY_BYTES,
                        usage: wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
                        mapped_at_creation: false,
                    }),
                    read: device.create_buffer(&wgpu::BufferDescriptor {
                        label: Some("smoke compute timestamp readback"),
                        size: COMPUTE_QUERY_BYTES,
                        usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
                        mapped_at_creation: false,
                    }),
                    pending: None,
                    tick: 0,
                    submitted_at: None,
                })
                .collect(),
            next_slot: 0,
            next_compute_slot: 0,
        });
        let pixel_count =
            u64::from(scene.render.resolution[0]) * u64::from(scene.render.resolution[1]);
        let effect_depth_bytes_per_pixel = if effect_depth_format == wgpu::TextureFormat::Rg16Float
        {
            4
        } else {
            8
        };
        let hdr_color_bytes_per_pixel = if hdr_color_format == wgpu::TextureFormat::Rg11b10Ufloat {
            4
        } else {
            8
        };
        let render_targets_bytes =
            pixel_count * (8 + hdr_color_bytes_per_pixel + effect_depth_bytes_per_pixel + 4 + 4);
        let smoke_bytes_per_voxel = if smoke_volume_format == wgpu::TextureFormat::Rg16Float {
            4
        } else {
            8
        };
        let smoke_bytes = u64::from(VOLUME[0])
            * u64::from(VOLUME[1])
            * u64::from(VOLUME[2])
            * smoke_bytes_per_voxel
            * 2
            * scene.emitters.len() as u64;
        let shadow_bytes = 1024u64 * 1024 * 4 + 256 * 256 * 6 * 4;
        let atlas_bytes = 128u64 * 128 * 4 * mesh.textures.len() as u64;
        let tile_list_bytes = u64::from(tile_count)
            * (32
                + 4 * u64::from(
                    FIRE_TILE_CAPACITY
                        + SMOKE_TILE_CAPACITY
                        + POINT_TILE_CAPACITY
                        + PARTICLE_TILE_CAPACITY,
                ));
        let tile_stats_buffer_bytes = 48;
        let tile_stats_readback_bytes = 3 * 48;
        let tile_stats_bytes = tile_stats_buffer_bytes + tile_stats_readback_bytes;
        let tile_config_bytes = std::mem::size_of::<TileConfigGpu>() as u64;
        let timing_staging_bytes = if timestamp {
            TIMING_SLOTS as u64 * GPU_QUERY_BYTES * 2
                + COMPUTE_TIMING_SLOTS as u64 * COMPUTE_QUERY_BYTES * 2
        } else {
            0
        };
        let geometry_bytes = mesh.vertices.len() as u64 * std::mem::size_of::<Vertex>() as u64;
        let unshared_geometry_bytes = mesh
            .object_draws
            .iter()
            .map(|object| object.vertex_count as u64 * std::mem::size_of::<Vertex>() as u64)
            .sum::<u64>();
        let geometry_object_count = mesh.object_draws.len();
        let shared_mesh_count = mesh.mesh_draws.len();
        let bounded_object_count = mesh
            .object_draws
            .iter()
            .filter(|object| object.bounds.is_some())
            .count();
        let geometry_range_count = mesh
            .object_draws
            .iter()
            .filter(|object| object.vertex_count > 0)
            .count();
        let material_bytes =
            (scene.materials.len() as u64 + 1) * std::mem::size_of::<MaterialGpu>() as u64;
        let fixed_buffer_bytes = std::mem::size_of::<Globals>() as u64
            + std::mem::size_of::<FireFrameStorage>() as u64
            + 7 * 64
            + 22 * std::mem::size_of::<u32>() as u64
            + std::mem::size_of::<SmokeSimulationConfig>() as u64 * scene.emitters.len() as u64;
        let format_support = [
            wgpu::TextureFormat::Rgba16Float,
            wgpu::TextureFormat::Rg16Float,
            wgpu::TextureFormat::R32Float,
            wgpu::TextureFormat::Rg32Float,
            wgpu::TextureFormat::Rg11b10Ufloat,
            wgpu::TextureFormat::Rgba8Unorm,
            wgpu::TextureFormat::R8Unorm,
        ]
        .into_iter()
        .map(|format| format_capability(&adapter, format))
        .collect::<Vec<_>>();
        let known_gpu_bytes = render_targets_bytes
            + smoke_bytes
            + if scene.render.experiments.smoke_absorption_cache {
                (scene.render.absorption_cache_resolution as u64).pow(3) * 8
            } else {
                0
            }
            + shadow_bytes
            + atlas_bytes
            + tile_list_bytes
            + tile_stats_bytes
            + tile_config_bytes
            + timing_staging_bytes
            + geometry_bytes
            + instance_buffer_bytes
            + material_bytes
            + fixed_buffer_bytes;
        let resource_inventory = serde_json::json!({
            "estimate_kind":"known resource buffer/texture sizes; excludes driver alignment, transient capture/surface buffers, pipelines, bind groups and opaque timestamp query-set storage",
            "render_targets_bytes":render_targets_bytes,
            "effect_depth_format":format!("{effect_depth_format:?}"),
            "effect_depth_bytes":pixel_count*effect_depth_bytes_per_pixel,
            "hdr_color_format":format!("{hdr_color_format:?}"),
            "hdr_color_requested_compact":scene.render.compact_hdr,
            "compact_hdr_supported":compact_hdr_supported,
            "rg11b10_renderable_feature_available":compact_hdr_render_feature,
            "optical_no_copy_requested":scene.render.optical_no_copy,
            "optical_no_copy_enabled":optical_no_copy_enabled,
            "optical_no_copy_supported":optical_no_copy_supported,
            "optical_mask_required":optical_mask_required,
            "optical_mask_format":format!("{optical_mask_format:?}"),
            "smoke_volume_format":format!("{smoke_volume_format:?}"),
            "smoke_rg16_storage_enabled":smoke_rg16_supported,
            "optical_snapshot_bytes":0,
            "optical_output_bytes":0,
            "optical_mask_bytes":0,
            "smoke_volumes_bytes":smoke_bytes,
            "smoke_absorption_cache_bytes":if scene.render.experiments.smoke_absorption_cache {(scene.render.absorption_cache_resolution as u64).pow(3)*8}else{0},
            "shadow_maps_bytes":shadow_bytes,
            "material_atlas_bytes":atlas_bytes,
            "geometry_buffer_bytes":geometry_bytes,
            "unshared_geometry_bytes":unshared_geometry_bytes,
            "unshared_vertex_buffer_bytes":0,
            "unshared_vertex_cpu_bytes":unshared_geometry_bytes,
            "instance_transform_buffer_bytes":instance_buffer_bytes,
            "shared_mesh_count":shared_mesh_count,
            "tile_list_bytes":tile_list_bytes,
            "tile_stats_bytes":tile_stats_bytes,
            "tile_stats_buffer_bytes":tile_stats_buffer_bytes,
            "tile_config_bytes":tile_config_bytes,
            "tile_stats_readback_bytes":tile_stats_readback_bytes,
            "shading_diagnostic_counter_bytes":22 * std::mem::size_of::<u32>() as u64,
            "gpu_timestamp_staging_bytes":timing_staging_bytes,
            "gpu_timestamp_query_set_count":if timestamp { TIMING_SLOTS + COMPUTE_TIMING_SLOTS } else { 0 },
            "tile_count":tile_count,
            "geometry_object_count":geometry_object_count,
            "geometry_draw_range_count":geometry_range_count,
            "geometry_bounded_object_count":bounded_object_count,
            "geometry_uncullable_object_count":geometry_object_count-bounded_object_count,
            "material_buffer_bytes":material_bytes,
            "other_fixed_buffers_bytes":fixed_buffer_bytes,
            "known_gpu_allocation_bytes":known_gpu_bytes,
            "format_support":format_support,
            "resolution":scene.render.resolution,
            "smoke_grid":VOLUME,
            "atlas_layers":mesh.textures.len(),
            "vertices":mesh.vertices.len()
        });
        let mut renderer = Self {
            device,
            queue,
            adapter,
            effect_depth_format,
            smoke_volume_format,
            pixels,
            pixel_texture,
            resolution: scene.render.resolution,
            metrics: FrameMetrics {
                gpu_timestamp_supported: timestamp,
                ..Default::default()
            },
            uniform,
            fire_buffer,
            fire_storage: FireFrameStorage::zeroed(),
            fire_key: None,
            multi_fire_keys: Vec::new(),
            multi_fire_tiers: Vec::new(),
            fire_frame: FireFrame::zeroed(),
            fire_lod_tier: 0,
            fire_render_segments: 0,
            globals,
            global_layout,
            textures,
            texture_layout,
            material_buffer,
            shadow_materials,
            shadow_material_layout,
            material_cache: scene.materials.clone(),
            optical_layout,
            optical_group,
            optical_smoke_groups,
            optical_smoke_layout,
            optical_sampler: linear,
            scene_color,
            optical_output: None,
            optical_mask: None,
            optical_post_groups: None,
            optical_no_copy_enabled,
            optical_mask_required,
            absorption_texture,
            absorption_cache_resolution,
            absorption_layout,
            absorption_groups,
            absorption_cache_active: absorption_cache_enabled,
            absorption_cache_dirty: true,
            hdr_texture,
            hdr_color_format,
            volume_groups,
            volume_layout,
            shading_diagnostic_buffer,
            shading_diagnostics_enabled: false,
            smoke_groups,
            smoke_source_buffers,
            smoke_config_cache: vec![SmokeSimulationConfig::zeroed(); scene.emitters.len()],
            smoke_layout,
            post_groups,
            effect_depth,
            post_layout,
            shadow_groups,
            shadow_buffers,
            shadow_layout,
            sun_view,
            point_faces,
            hdr,
            normals,
            depth,
            smoke_textures,
            smoke_index: 0,
            vertex,
            unshared_vertices: mesh.baked_vertices,
            unshared_vertex_buffer: None,
            vertex_count: mesh.vertices.len() as u32,
            object_draws: mesh.object_draws,
            mesh_draws: mesh.mesh_draws,
            instance_buffers,
            geometry_culling_enabled: true,
            geometry_instancing_enabled: true,
            tile_list_layout,
            tile_build_layout,
            tile_build_group,
            tile_list_groups,
            tile_headers,
            fire_tile_indices,
            smoke_tile_indices,
            point_tile_indices,
            particle_tile_indices,
            tile_config_buffer,
            tile_stats_buffer,
            tile_stats_readbacks,
            next_tile_stats_readback: 0,
            tile_count,
            tile_force_overflow: false,
            tile_lists_enabled: true,
            pipelines,
            timing,
            completed_gpu_timings: VecDeque::new(),
            completed_compute_timings: VecDeque::new(),
            resource_inventory,
            shadow_cache_key: None,
            shadow_invalidation_reason: Some("resource_initialization"),
            shadow_transform_changes: Vec::new(),
            shadow_dirty_faces: [true; 7],
            shadow_visible_cache: [0; 7],
            shadow_batch_cache: [0; 7],
            shadow_vertex_cache: [0; 7],
            force_shadow_redraw: false,
            shader_directory,
        };
        renderer.reset_smoke();
        renderer.shadow_invalidation_reason = Some("resource_initialization");
        renderer.update_globals(scene, &scene.cameras[0], 0, 42);
        Ok(renderer)
    }

    fn ensure_optical_targets(&mut self) {
        if (self.optical_no_copy_enabled && self.optical_output.is_some())
            || (!self.optical_no_copy_enabled && self.scene_color.is_some())
        {
            return;
        }
        let [width, height] = self.resolution;
        let optical_color = texture(
            &self.device,
            if self.optical_no_copy_enabled {
                "optical resolved color"
            } else {
                "opaque + atmosphere snapshot"
            },
            [width, height, 1],
            self.hdr_color_format,
            if self.optical_no_copy_enabled {
                wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING
            } else {
                wgpu::TextureUsages::COPY_DST | wgpu::TextureUsages::TEXTURE_BINDING
            },
            wgpu::TextureDimension::D2,
        );
        let color_view = optical_color.create_view(&Default::default());
        let mask = (self.optical_no_copy_enabled && self.optical_mask_required).then(|| {
            texture(
                &self.device,
                "optical coverage mask",
                [width, height, 1],
                wgpu::TextureFormat::R8Unorm,
                wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
                wgpu::TextureDimension::D2,
            )
        });
        self.optical_group = group(
            &self.device,
            &self.optical_layout,
            &[
                wgpu::BindingResource::TextureView(if self.optical_no_copy_enabled {
                    &self.hdr
                } else {
                    &color_view
                }),
                wgpu::BindingResource::TextureView(&self.normals),
                wgpu::BindingResource::Sampler(&self.optical_sampler),
            ],
        );
        if self.optical_no_copy_enabled {
            let mask_view = mask
                .as_ref()
                .map(|texture| texture.create_view(&Default::default()));
            let coverage_view = mask_view.as_ref().unwrap_or(&color_view);
            let smoke_views = self.smoke_textures[0]
                .each_ref()
                .map(|texture| texture.create_view(&Default::default()));
            self.optical_post_groups = Some(std::array::from_fn(|i| {
                group(
                    &self.device,
                    &self.post_layout,
                    &[
                        wgpu::BindingResource::TextureView(&self.hdr),
                        wgpu::BindingResource::TextureView(&self.normals),
                        wgpu::BindingResource::TextureView(&self.effect_depth),
                        wgpu::BindingResource::TextureView(&smoke_views[i]),
                        wgpu::BindingResource::Sampler(&self.optical_sampler),
                        wgpu::BindingResource::TextureView(&color_view),
                        wgpu::BindingResource::TextureView(coverage_view),
                    ],
                )
            }));
            self.optical_mask = mask;
            self.optical_output = Some(optical_color);
        } else {
            self.scene_color = Some(optical_color);
        }
        let bytes_per_pixel = if self.hdr_color_format == wgpu::TextureFormat::Rg11b10Ufloat {
            4
        } else {
            8
        };
        let bytes = u64::from(width) * u64::from(height) * bytes_per_pixel;
        let mask_bytes = if self.optical_mask_required && self.optical_no_copy_enabled {
            u64::from(width) * u64::from(height)
        } else {
            0
        };
        self.resource_inventory["optical_snapshot_bytes"] = if self.optical_no_copy_enabled {
            0.into()
        } else {
            bytes.into()
        };
        self.resource_inventory["optical_output_bytes"] = if self.optical_no_copy_enabled {
            bytes.into()
        } else {
            0.into()
        };
        self.resource_inventory["optical_mask_bytes"] = mask_bytes.into();
        for key in ["render_targets_bytes", "known_gpu_allocation_bytes"] {
            let current = self.resource_inventory[key].as_u64().unwrap_or(0);
            self.resource_inventory[key] = (current + bytes + mask_bytes).into();
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn pipelines(
        device: &wgpu::Device,
        global: &wgpu::BindGroupLayout,
        textures: &wgpu::BindGroupLayout,
        optical: &wgpu::BindGroupLayout,
        optical_smoke: &wgpu::BindGroupLayout,
        volumes: &wgpu::BindGroupLayout,
        smoke: &wgpu::BindGroupLayout,
        absorption: &wgpu::BindGroupLayout,
        post: &wgpu::BindGroupLayout,
        shadow: &wgpu::BindGroupLayout,
        shadow_materials: &wgpu::BindGroupLayout,
        tile_lists: &wgpu::BindGroupLayout,
        tile_build: &wgpu::BindGroupLayout,
        effect_depth_format: wgpu::TextureFormat,
        smoke_volume_format: wgpu::TextureFormat,
        hdr_color_format: wgpu::TextureFormat,
        dir: &Path,
    ) -> Result<Pipelines> {
        let read = |name: &str| {
            std::fs::read_to_string(dir.join(name))
                .with_context(|| format!("shader {}", dir.join(name).display()))
        };
        let common = read("common.wgsl")?;
        let tile_common = read("tile_common.wgsl")?;
        let tile_bindings = read("tile_bindings.wgsl")?;
        let tile_build_source = read("tile_build.wgsl")?;
        let world = format!("{}\n{}", read("materials.wgsl")?, read("world.wgsl")?);
        let optical_source = read("optical.wgsl")?;
        let volume_source = read("volume.wgsl")?;
        let fire_source = read("fire.wgsl")?;
        let post_source = read("post.wgsl")?;
        let smoke_source = read("smoke.wgsl")?;
        let absorption_source = read("absorption.wgsl")?;
        let shadow_source = format!("{}\n{}", read("materials.wgsl")?, read("shadow.wgsl")?);
        device.push_error_scope(wgpu::ErrorFilter::Validation);
        let tile_group2 = tile_bindings.replace("@group(7)", "@group(2)");
        let tile_group3 = tile_bindings.replace("@group(7)", "@group(3)");
        let tile_group3_optical = tile_bindings
            .replace("@group(7)", "@group(3)")
            .replace("@binding(4)", "@binding(7)")
            .replace("@binding(3)", "@binding(6)")
            .replace("@binding(2)", "@binding(5)")
            .replace("@binding(1)", "@binding(4)")
            .replace("@binding(0)", "@binding(3)");
        let mesh_module = shader(
            device,
            "world",
            format!("{common}\n{tile_common}\n{tile_group2}\n{world}"),
        );
        let optical_module = shader(
            device,
            "optical surfaces",
            format!(
                "{common}\n{tile_common}\n{tile_group3_optical}\n{world}\n{fire_source}\n{}\n{optical_source}",
                volume_source.replace("@group(2)", "@group(3)")
            ),
        );
        let volume_module = shader(
            device,
            "volumetrics",
            format!(
                "{common}\n{tile_common}\n{tile_group3}\n{world}\n{fire_source}\n{}",
                volume_source.replace("@group(2) @binding(8)", "@group(2) @binding(3)")
            ),
        );
        let diagnostic_preamble = "@group(0) @binding(2) var<storage, read_write> shading_diag: array<atomic<u32>,22>; fn diag_add(i:u32) { atomicAdd(&shading_diag[i],1u); }";
        let diagnostic_world = world
            .replace("return textureSampleCompareLevel(sun_shadow,shadow_sampler,uv,q.z/q.w-0.0015);", "diag_add(9u); return textureSampleCompareLevel(sun_shadow,shadow_sampler,uv,q.z/q.w-0.0015);")
            .replace("return textureSampleCompareLevel(point_shadow,shadow_sampler,d,depth-0.004);", "diag_add(10u); return textureSampleCompareLevel(point_shadow,shadow_sampler,d,depth-0.004);")
            .replace("fn shade_surface(v:Varying,tile:u32)->Output {", "fn shade_surface(v:Varying,tile:u32)->Output { diag_add(14u);")
            .replace("for(var candidate=0u;candidate<8u;candidate++) {if candidate>=point_count {break;}", "for(var candidate=0u;candidate<8u;candidate++) {if candidate>=point_count {break;} diag_add(15u);")
            .replace("for(var candidate=0u;candidate<12u;candidate++) {if candidate>=particle_count {break;}", "for(var candidate=0u;candidate<12u;candidate++) {if candidate>=particle_count {break;} diag_add(16u);")
            .replace("let temperature=clamp(textureSampleLevel(heat_volume,heat_sampler,heat_uv,0.).y,0.,1.);", "diag_add(17u); let temperature=clamp(textureSampleLevel(heat_volume,heat_sampler,heat_uv,0.).y,0.,1.);");
        let diagnostic_mesh_module = shader(
            device,
            "instrumented opaque world",
            format!(
                "{common}\n{tile_common}\n{tile_group2}\n{diagnostic_preamble}\n{diagnostic_world}"
            ),
        );
        let diagnostic_fire = fire_source
            .replace("if candidate>=candidate_count {break;}", "if candidate>=candidate_count {break;} diag_add(0u);")
            .replace("if along+bound<0. || along-bound>limit || length(ro+direction*max(along,0.))>bound {continue;}", "diag_add(1u); if along+bound<0. || along-bound>limit || length(ro+direction*max(along,0.))>bound {continue;}")
            .replace("let discriminant=qb*qb-qa*qc;", "diag_add(2u); let discriminant=qb*qb-qa*qc;");
        let diagnostic_volume = volume_source
            .replace("if candidate>=smoke_candidate_count {break;}", "if candidate>=smoke_candidate_count {break;} diag_add(3u);")
            .replace("if along+bound<0. || along-bound>distance || length(origin+direction*max(along,0.)-parent)>bound {continue;}", "diag_add(4u); if along+bound<0. || along-bound>distance || length(origin+direction*max(along,0.)-parent)>bound {continue;}")
            .replace("if bubble>child_count {break;}", "if bubble>child_count {break;} diag_add(5u);")
            .replace("let sample=textureSampleLevel(smoke,volume_sampler,volume_uv,0.);", "diag_add(6u); let sample=textureSampleLevel(smoke,volume_sampler,volume_uv,0.);")
            .replace("let field=textureSampleLevel(smoke,volume_sampler,clamp(uv,vec3(0.),vec3(1.)),0.).x;", "diag_add(6u); let field=textureSampleLevel(smoke,volume_sampler,clamp(uv,vec3(0.),vec3(1.)),0.).x;")
            .replace("let heat=textureSampleLevel(smoke,volume_sampler,clamp(uv,vec3(0.),vec3(1.)),0.).y;", "diag_add(6u); let heat=textureSampleLevel(smoke,volume_sampler,clamp(uv,vec3(0.),vec3(1.)),0.).y;")
            .replace("optical+=textureSampleLevel(smoke,volume_sampler,q,0.).x*0.25;", "diag_add(6u); optical+=textureSampleLevel(smoke,volume_sampler,q,0.).x*0.25;")
            .replace("absorption+=textureSampleLevel(smoke,volume_sampler,clamp(uv,vec3(0.),vec3(1.)),0.).x*span/6.*2.6;", "diag_add(6u); diag_add(13u); absorption+=textureSampleLevel(smoke,volume_sampler,clamp(uv,vec3(0.),vec3(1.)),0.).x*span/6.*2.6;")
            .replace("let optical_depth=textureSampleLevel(smoke_absorption,volume_sampler,surface_uv,0.).x;", "diag_add(8u); let optical_depth=textureSampleLevel(smoke_absorption,volume_sampler,surface_uv,0.).x;")
            .replace("optical_depth+=textureSampleLevel(smoke,volume_sampler,uv,0.).x*ds;", "diag_add(6u); diag_add(7u); optical_depth+=textureSampleLevel(smoke,volume_sampler,uv,0.).x*ds;")
            .replace("for(var candidate=0u;candidate<8u;candidate++) {if candidate>=point_count {break;}", "for(var candidate=0u;candidate<8u;candidate++) {if candidate>=point_count {break;} diag_add(11u);")
            .replace("for(var candidate=0u;candidate<12u;candidate++) {if candidate>=particle_count {break;}", "for(var candidate=0u;candidate<12u;candidate++) {if candidate>=particle_count {break;} diag_add(12u);");
        let diagnostic_volume_module = shader(device, "instrumented volumetrics", format!(
            "{common}\n{tile_common}\n{tile_group3}\n{diagnostic_preamble}\n{diagnostic_world}\n{diagnostic_fire}\n{}",
            diagnostic_volume.replace("@group(2) @binding(8)", "@group(2) @binding(3)")
        ));
        let diagnostic_optical_source = optical_source
            .replace(
                "if optical_strength(m)<=0. {discard;}",
                "if optical_strength(m)<=0. {discard;} diag_add(18u);",
            )
            .replace(
                "if f32(i)>=g.presentation.z {break;}",
                "if f32(i)>=g.presentation.z {break;} diag_add(19u);",
            )
            .replace(
                "for(var refine=0;refine<4;refine++) {",
                "for(var refine=0;refine<4;refine++) { diag_add(20u);",
            )
            .replace(
                "if transmission(m)>0. && dot(transmitted_direction,transmitted_direction)>=0.000001 {",
                "if transmission(m)>0. && dot(transmitted_direction,transmitted_direction)>=0.000001 { diag_add(21u);",
            );
        let diagnostic_optical_volume = diagnostic_volume.replace("@group(2)", "@group(3)");
        let diagnostic_optical_module = shader(
            device,
            "instrumented optical surfaces",
            format!(
                "{common}\n{tile_common}\n{tile_group3_optical}\n{diagnostic_preamble}\n{diagnostic_world}\n{diagnostic_fire}\n{diagnostic_optical_volume}\n{diagnostic_optical_source}"
            ),
        );
        let tile_build_module = shader(
            device,
            "effect tile-list builder",
            format!("{common}\n{tile_common}\n{tile_build_source}"),
        );
        let post_module = shader(
            device,
            "pixel treatment",
            format!("{common}\n{}", post_source),
        );
        let smoke_module = shader(
            device,
            "smoke advection",
            format!(
                "{common}\n{}",
                smoke_source.replace(
                    "texture_storage_3d<rgba16float,write>",
                    match smoke_volume_format {
                        wgpu::TextureFormat::Rg16Float => "texture_storage_3d<rg16float,write>",
                        _ => "texture_storage_3d<rgba16float,write>",
                    },
                )
            ),
        );
        let absorption_module = shader(
            device,
            "coarse smoke absorption",
            format!("{common}\n{}", absorption_source),
        );
        let shadow_module = shader(device, "shadow", shadow_source);
        let layout = |groups: &[&wgpu::BindGroupLayout]| {
            device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                label: None,
                bind_group_layouts: groups,
                push_constant_ranges: &[],
            })
        };
        let mesh_layout = layout(&[global, textures, tile_lists]);
        let volume_layout = layout(&[global, textures, volumes, tile_lists]);
        let diagnostic_volume_layout = layout(&[global, textures, volumes, tile_lists]);
        let optical_layout = layout(&[global, textures, optical, optical_smoke]);
        let tile_build_pipeline_layout = layout(&[global, tile_build]);
        let post_layout = layout(&[global, post]);
        let smoke_layout = layout(&[global, smoke]);
        let absorption_layout = layout(&[global, absorption]);
        let shadow_layout = layout(&[shadow, shadow_materials]);
        let vertex_buffers = [vertex_layout(), instance_layout()];
        let baked_vertex_buffers = [vertex_layout()];
        let render = |label: &str,
                      module: &wgpu::ShaderModule,
                      layout: &wgpu::PipelineLayout,
                      vs: &str,
                      fs: Option<&str>,
                      targets: &[Option<wgpu::ColorTargetState>],
                      depth: bool,
                      vertices: bool,
                      instanced_vertices: bool| {
            device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: Some(label),
                layout: Some(layout),
                vertex: wgpu::VertexState {
                    module,
                    entry_point: Some(vs),
                    compilation_options: Default::default(),
                    buffers: if instanced_vertices {
                        &vertex_buffers
                    } else if vertices {
                        &baked_vertex_buffers
                    } else {
                        &[]
                    },
                },
                fragment: fs.map(|entry| wgpu::FragmentState {
                    module,
                    entry_point: Some(entry),
                    compilation_options: Default::default(),
                    targets,
                }),
                primitive: wgpu::PrimitiveState {
                    cull_mode: None,
                    ..Default::default()
                },
                depth_stencil: depth.then_some(wgpu::DepthStencilState {
                    format: DEPTH,
                    depth_write_enabled: true,
                    depth_compare: wgpu::CompareFunction::LessEqual,
                    stencil: Default::default(),
                    bias: wgpu::DepthBiasState {
                        constant: if label.starts_with("shadow") { 2 } else { 0 },
                        slope_scale: if label.starts_with("shadow") { 2. } else { 0. },
                        clamp: 0.,
                    },
                }),
                multisample: Default::default(),
                multiview: None,
                cache: None,
            })
        };
        let mesh = render(
            "world",
            &mesh_module,
            &mesh_layout,
            "vs",
            Some("fs"),
            &[
                color_target(hdr_color_format, None),
                color_target(HDR, None),
            ],
            true,
            true,
            true,
        );
        let mesh_baked = render(
            "world baked reference",
            &mesh_module,
            &mesh_layout,
            "vs_baked",
            Some("fs"),
            &[
                color_target(hdr_color_format, None),
                color_target(HDR, None),
            ],
            true,
            true,
            false,
        );
        let mesh_diagnostic = render(
            "instrumented world",
            &diagnostic_mesh_module,
            &mesh_layout,
            "vs",
            Some("fs"),
            &[
                color_target(hdr_color_format, None),
                color_target(HDR, None),
            ],
            true,
            true,
            true,
        );
        let mesh_baked_diagnostic = render(
            "instrumented world baked reference",
            &diagnostic_mesh_module,
            &mesh_layout,
            "vs_baked",
            Some("fs"),
            &[
                color_target(hdr_color_format, None),
                color_target(HDR, None),
            ],
            true,
            true,
            false,
        );
        let optical = render(
            "optical surfaces",
            &optical_module,
            &optical_layout,
            "optical_vs",
            Some("optical_fs"),
            &[color_target(hdr_color_format, None)],
            true,
            true,
            true,
        );
        let optical_baked = render(
            "optical surfaces baked reference",
            &optical_module,
            &optical_layout,
            "optical_vs_baked",
            Some("optical_fs"),
            &[color_target(hdr_color_format, None)],
            true,
            true,
            false,
        );
        let optical_diagnostic = render(
            "instrumented optical surfaces",
            &diagnostic_optical_module,
            &optical_layout,
            "optical_vs",
            Some("optical_fs"),
            &[color_target(hdr_color_format, None)],
            true,
            true,
            true,
        );
        let optical_baked_diagnostic = render(
            "instrumented optical surfaces baked reference",
            &diagnostic_optical_module,
            &optical_layout,
            "optical_vs_baked",
            Some("optical_fs"),
            &[color_target(hdr_color_format, None)],
            true,
            true,
            false,
        );
        let optical_overlay = render(
            "optical surfaces no-copy overlay",
            &optical_module,
            &optical_layout,
            "optical_vs",
            Some("optical_overlay_fs"),
            &[
                color_target(hdr_color_format, None),
                color_target(wgpu::TextureFormat::R8Unorm, None),
            ],
            true,
            true,
            true,
        );
        let optical_overlay_baked = render(
            "optical surfaces no-copy overlay baked reference",
            &optical_module,
            &optical_layout,
            "optical_vs_baked",
            Some("optical_overlay_fs"),
            &[
                color_target(hdr_color_format, None),
                color_target(wgpu::TextureFormat::R8Unorm, None),
            ],
            true,
            true,
            false,
        );
        let optical_overlay_alpha = render(
            "optical surfaces no-copy alpha coverage",
            &optical_module,
            &optical_layout,
            "optical_vs",
            Some("optical_overlay_alpha_fs"),
            &[color_target(HDR, None)],
            true,
            true,
            true,
        );
        let optical_overlay_alpha_baked = render(
            "optical surfaces no-copy alpha coverage baked reference",
            &optical_module,
            &optical_layout,
            "optical_vs_baked",
            Some("optical_overlay_alpha_fs"),
            &[color_target(HDR, None)],
            true,
            true,
            false,
        );
        let optical_overlay_diagnostic = render(
            "instrumented optical no-copy overlay",
            &diagnostic_optical_module,
            &optical_layout,
            "optical_vs",
            Some("optical_overlay_fs"),
            &[
                color_target(hdr_color_format, None),
                color_target(wgpu::TextureFormat::R8Unorm, None),
            ],
            true,
            true,
            true,
        );
        let optical_overlay_baked_diagnostic = render(
            "instrumented optical no-copy overlay baked reference",
            &diagnostic_optical_module,
            &optical_layout,
            "optical_vs_baked",
            Some("optical_overlay_fs"),
            &[
                color_target(hdr_color_format, None),
                color_target(wgpu::TextureFormat::R8Unorm, None),
            ],
            true,
            true,
            false,
        );
        let optical_overlay_alpha_diagnostic = render(
            "instrumented optical no-copy alpha coverage",
            &diagnostic_optical_module,
            &optical_layout,
            "optical_vs",
            Some("optical_overlay_alpha_fs"),
            &[color_target(HDR, None)],
            true,
            true,
            true,
        );
        let optical_overlay_alpha_baked_diagnostic = render(
            "instrumented optical no-copy alpha coverage baked reference",
            &diagnostic_optical_module,
            &optical_layout,
            "optical_vs_baked",
            Some("optical_overlay_alpha_fs"),
            &[color_target(HDR, None)],
            true,
            true,
            false,
        );
        let volume = render(
            "volumetrics",
            &volume_module,
            &volume_layout,
            "fullscreen",
            Some("volume_fs"),
            &[
                color_target(
                    hdr_color_format,
                    Some(wgpu::BlendState::PREMULTIPLIED_ALPHA_BLENDING),
                ),
                color_target(effect_depth_format, None),
            ],
            false,
            false,
            false,
        );
        let volume_diagnostic = render(
            "volumetrics with operation counters",
            &diagnostic_volume_module,
            &diagnostic_volume_layout,
            "fullscreen",
            Some("volume_fs"),
            &[
                color_target(
                    hdr_color_format,
                    Some(wgpu::BlendState::PREMULTIPLIED_ALPHA_BLENDING),
                ),
                color_target(effect_depth_format, None),
            ],
            false,
            false,
            false,
        );
        let post = render(
            "pixel treatment",
            &post_module,
            &post_layout,
            "vs",
            Some("fs"),
            &[color_target(PIXEL_FORMAT, None)],
            false,
            false,
            false,
        );
        let post_alpha = render(
            "pixel treatment with overlay alpha coverage",
            &post_module,
            &post_layout,
            "vs",
            Some("fs_alpha_coverage"),
            &[color_target(PIXEL_FORMAT, None)],
            false,
            false,
            false,
        );
        let shadow = render(
            "shadow",
            &shadow_module,
            &shadow_layout,
            "shadow_vs",
            Some("shadow_fs"),
            &[],
            true,
            true,
            true,
        );
        let shadow_opaque = render(
            "shadow",
            &shadow_module,
            &shadow_layout,
            "shadow_vs",
            None,
            &[],
            true,
            true,
            true,
        );
        let shadow_baked = render(
            "shadow baked reference",
            &shadow_module,
            &shadow_layout,
            "shadow_vs_baked",
            Some("shadow_fs"),
            &[],
            true,
            true,
            false,
        );
        let shadow_opaque_baked = render(
            "shadow opaque baked reference",
            &shadow_module,
            &shadow_layout,
            "shadow_vs_baked",
            None,
            &[],
            true,
            true,
            false,
        );
        let smoke = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("advection"),
            layout: Some(&smoke_layout),
            module: &smoke_module,
            entry_point: Some("advect"),
            compilation_options: Default::default(),
            cache: None,
        });
        let absorption = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("coarse smoke absorption"),
            layout: Some(&absorption_layout),
            module: &absorption_module,
            entry_point: Some("build_absorption"),
            compilation_options: Default::default(),
            cache: None,
        });
        let tile_build = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("effect tile-list build"),
            layout: Some(&tile_build_pipeline_layout),
            module: &tile_build_module,
            entry_point: Some("build_tile_lists"),
            compilation_options: Default::default(),
            cache: None,
        });
        if let Some(error) = pollster::block_on(device.pop_error_scope()) {
            return Err(anyhow!(error.to_string()));
        }
        Ok(Pipelines {
            mesh,
            mesh_baked,
            mesh_diagnostic,
            mesh_baked_diagnostic,
            optical,
            optical_baked,
            optical_diagnostic,
            optical_baked_diagnostic,
            optical_overlay,
            optical_overlay_baked,
            optical_overlay_alpha,
            optical_overlay_alpha_baked,
            optical_overlay_diagnostic,
            optical_overlay_baked_diagnostic,
            optical_overlay_alpha_diagnostic,
            optical_overlay_alpha_baked_diagnostic,
            volume,
            volume_diagnostic,
            post,
            post_alpha,
            shadow,
            shadow_opaque,
            shadow_baked,
            shadow_opaque_baked,
            smoke,
            absorption,
            tile_build,
        })
    }

    pub fn reload_shaders(&mut self) -> Result<()> {
        let replacement = Self::pipelines(
            &self.device,
            &self.global_layout,
            &self.texture_layout,
            &self.optical_layout,
            &self.optical_smoke_layout,
            &self.volume_layout,
            &self.smoke_layout,
            &self.absorption_layout,
            &self.post_layout,
            &self.shadow_layout,
            &self.shadow_material_layout,
            &self.tile_list_layout,
            &self.tile_build_layout,
            self.effect_depth_format,
            self.smoke_volume_format,
            self.hdr_color_format,
            &self.shader_directory,
        )?;
        self.pipelines = replacement;
        self.invalidate_shadow_cache("shader_reload");
        Ok(())
    }

    fn invalidate_shadow_cache(&mut self, reason: &'static str) {
        self.shadow_cache_key = None;
        self.shadow_invalidation_reason = Some(reason);
    }

    pub fn set_force_shadow_redraw(&mut self, force: bool) {
        self.force_shadow_redraw = force;
    }

    pub fn force_shadow_redraw(&self) -> bool {
        self.force_shadow_redraw
    }

    pub fn set_geometry_rendering(&mut self, culling: bool, instancing: bool) {
        let changed = self.geometry_culling_enabled != culling
            || self.geometry_instancing_enabled != instancing;
        self.geometry_culling_enabled = culling;
        if self.geometry_instancing_enabled != instancing {
            if instancing {
                self.unshared_vertex_buffer = None;
                self.resource_inventory["unshared_vertex_buffer_bytes"] = 0.into();
                let current = self.resource_inventory["known_gpu_allocation_bytes"]
                    .as_u64()
                    .unwrap_or(0);
                let released = self.resource_inventory["unshared_geometry_bytes"]
                    .as_u64()
                    .unwrap_or(0);
                self.resource_inventory["known_gpu_allocation_bytes"] =
                    current.saturating_sub(released).into();
            } else {
                self.unshared_vertex_buffer = Some(self.device.create_buffer_init(
                    &wgpu::util::BufferInitDescriptor {
                        label: Some("world-baked comparison geometry"),
                        contents: bytemuck::cast_slice(&self.unshared_vertices),
                        usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
                    },
                ));
                let bytes =
                    self.unshared_vertices.len() as u64 * std::mem::size_of::<Vertex>() as u64;
                self.resource_inventory["unshared_vertex_buffer_bytes"] = bytes.into();
                let current = self.resource_inventory["known_gpu_allocation_bytes"]
                    .as_u64()
                    .unwrap_or(0);
                self.resource_inventory["known_gpu_allocation_bytes"] =
                    current.saturating_add(bytes).into();
            }
            self.geometry_instancing_enabled = instancing;
        }
        if changed {
            self.invalidate_shadow_cache("geometry_rendering_changed");
        }
    }

    /// Updates one validated scene object's model, conservative bounds, and baked
    /// reference vertices, retaining old/new bounds for per-face shadow invalidation.
    pub fn set_object_transform(&mut self, object: &Object) -> Result<u64> {
        let index = self
            .object_draws
            .iter()
            .position(|draw| draw.object_id == object.id)
            .with_context(|| format!("object '{}': no renderer draw range", object.id))?;
        let next_transform = Mat4::from_scale_rotation_translation(
            object.scale.into(),
            Quat::from_euler(
                EulerRot::XYZ,
                object.rotation[0],
                object.rotation[1],
                object.rotation[2],
            ),
            object.position.into(),
        );
        if !next_transform.is_finite() {
            bail!("object '{}': transform matrix is not finite", object.id);
        }
        let previous_columns = self.object_draws[index].transform;
        if next_transform.to_cols_array_2d() == previous_columns {
            return Ok(self.object_draws[index].transform_revision);
        }

        let previous_transform = Mat4::from_cols_array_2d(&previous_columns);
        let previous_inverse = previous_transform.inverse();
        let delta = next_transform * previous_inverse;
        let normal_delta = Mat3::from_mat4(delta).inverse().transpose();
        if !previous_inverse.is_finite() || !delta.is_finite() || !normal_delta.is_finite() {
            bail!("object '{}': transform delta is not finite", object.id);
        }
        let local_bounds = self.object_draws[index].local_bounds.clone();
        let old_bounds = self.object_draws[index].bounds.clone();
        let start = self.object_draws[index].baked_first_vertex as usize;
        let end = start + self.object_draws[index].vertex_count as usize;
        let bounds = local_bounds.and_then(|bounds| bounds.transformed(next_transform));
        self.shadow_transform_changes
            .push((object.id.clone(), old_bounds, bounds.clone()));
        let (first_vertex, revision) = {
            let draw = &mut self.object_draws[index];
            draw.transform = next_transform.to_cols_array_2d();
            draw.bounds = bounds;
            draw.transform_revision = draw.transform_revision.wrapping_add(1);
            (draw.baked_first_vertex, draw.transform_revision)
        };
        for vertex in &mut self.unshared_vertices[start..end] {
            vertex.position = delta
                .transform_point3(Vec3::from(vertex.position))
                .to_array();
            vertex.normal = (normal_delta * Vec3::from(vertex.normal))
                .normalize_or_zero()
                .to_array();
        }
        if let Some(buffer) = &self.unshared_vertex_buffer {
            let offset = u64::from(first_vertex) * std::mem::size_of::<Vertex>() as u64;
            self.queue.write_buffer(
                buffer,
                offset,
                bytemuck::cast_slice(&self.unshared_vertices[start..end]),
            );
        }
        Ok(revision)
    }

    pub fn set_tile_lists(&mut self, enabled: bool, force_overflow: bool) {
        self.tile_lists_enabled = enabled;
        self.tile_force_overflow = force_overflow;
        let config = TileConfigGpu {
            force_overflow: [u32::from(!enabled || force_overflow), 0, 0, 0],
        };
        self.queue
            .write_buffer(&self.tile_config_buffer, 0, bytemuck::bytes_of(&config));
    }

    pub fn set_shading_diagnostics(&mut self, enabled: bool) {
        self.shading_diagnostics_enabled = enabled;
        self.metrics.shading_counters = None;
    }

    pub fn read_shading_counters(&mut self) -> Result<crate::diagnostics::ShadingCounters> {
        let read = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("shading counter sample readback"),
            size: 22 * 4,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let mut encoder = self.device.create_command_encoder(&Default::default());
        encoder.copy_buffer_to_buffer(&self.shading_diagnostic_buffer, 0, &read, 0, 22 * 4);
        self.queue.submit([encoder.finish()]);
        let (send, receive) = mpsc::channel();
        read.slice(..)
            .map_async(wgpu::MapMode::Read, move |result| {
                let _ = send.send(result);
            });
        self.device.poll(wgpu::Maintain::Wait);
        receive.recv()??;
        let bytes = read.slice(..).get_mapped_range();
        let c = |i: usize| u32::from_le_bytes(bytes[i * 4..i * 4 + 4].try_into().unwrap());
        let counters = crate::diagnostics::ShadingCounters {
            fire_primitive_candidates: c(0),
            fire_bounds_tests: c(1),
            fire_ellipsoid_tests: c(2),
            smoke_lobe_candidates: c(3),
            smoke_parent_bounds_tests: c(4),
            smoke_bubble_intersection_tests: c(5),
            smoke_density_samples: c(6),
            direct_absorption_samples: c(7),
            cached_absorption_samples: c(8),
            sun_shadow_lookups: c(9),
            fire_shadow_lookups: c(10),
            point_light_candidates: c(11),
            particle_light_candidates: c(12),
            camera_to_flame_absorption_samples: c(13),
            world_shading_invocations: c(14),
            world_point_light_candidates: c(15),
            world_particle_light_candidates: c(16),
            world_heat_samples: c(17),
            optical_surface_interactions: c(18),
            optical_reflection_steps: c(19),
            optical_reflection_refinement_steps: c(20),
            optical_transmission_interactions: c(21),
        };
        self.metrics.shading_counters = Some(counters.clone());
        drop(bytes);
        read.unmap();
        Ok(counters)
    }

    fn update_shadow_matrices(&mut self, scene: &Scene, dirty_faces: [bool; 7]) {
        let matrices = shadow_matrices(scene);
        for (index, matrix) in matrices.into_iter().enumerate() {
            if !dirty_faces[index] {
                continue;
            }
            let upload_started = Instant::now();
            self.queue.write_buffer(
                &self.shadow_buffers[index],
                0,
                bytemuck::cast_slice(&matrix.to_cols_array()),
            );
            self.metrics.cpu_upload_ms += upload_started.elapsed().as_secs_f64() * 1000.;
        }
    }

    pub fn update_globals(&mut self, scene: &Scene, camera: &Camera, tick: u64, seed: u32) {
        let sun = scene
            .lights
            .iter()
            .find(|light| light.kind == LightKind::Directional)
            .unwrap();
        let emitter = &scene.emitters[0];
        let fire = scene.light_for_emitter(emitter).unwrap();
        let sun_direction = Vec3::from(sun.position).normalize();
        let sun_matrix = Mat4::orthographic_rh(-24., 24., -24., 24., 0.1, 100.)
            * Mat4::look_at_rh(
                sun_direction * 40.,
                Vec3::ZERO,
                if sun_direction.dot(Vec3::Y).abs() > 0.99 {
                    Vec3::Z
                } else {
                    Vec3::Y
                },
            );
        let vp = camera.matrix(self.resolution[0] as f32 / self.resolution[1] as f32);
        let vec4 = |v: [f32; 3], w: f32| [v[0], v[1], v[2], w];
        let wind = simulation::wind(
            scene.environment.wind,
            tick,
            seed,
            scene.render.experiments.connected_motion,
        );
        let origin = Vec3::from(emitter.position);
        let enabled = if emitter.enabled {
            emitter.intensity
        } else {
            0.
        };
        let profile = scene
            .effects
            .iter()
            .find(|p| p.id == emitter.effect_profile)
            .unwrap();
        let key = FireKey {
            tick,
            seed,
            source: emitter.position,
            wind,
            enabled,
            profile: profile.clone(),
        };
        let multi_emitter = scene.emitters.len() > 1;
        let mut multi_source_keys = if multi_emitter {
            scene
                .emitters
                .iter()
                .map(|source| {
                    let source_profile = scene
                        .effects
                        .iter()
                        .find(|candidate| candidate.id == source.effect_profile)
                        .expect("validated emitter profile exists");
                    (
                        source.id.clone(),
                        FireKey {
                            tick,
                            seed,
                            source: source.position,
                            wind,
                            enabled: if source.enabled { source.intensity } else { 0. },
                            profile: source_profile.clone(),
                        },
                    )
                })
                .collect::<Vec<_>>()
        } else {
            Vec::new()
        };
        multi_source_keys.sort_by(|left, right| left.0.cmp(&right.0));
        let primary_source_slot = multi_source_keys
            .iter()
            .position(|(id, _)| id == &emitter.id);
        let multi_source_tiers = multi_source_keys
            .iter()
            .map(|(id, source_key)| {
                let height = effects::projected_fire_height_px(
                    camera,
                    self.resolution,
                    source_key.source,
                    &source_key.profile,
                );
                let previous_tier = self
                    .multi_fire_tiers
                    .iter()
                    .find(|(previous_id, _)| previous_id == id)
                    .map_or(0, |(_, previous_tier)| *previous_tier);
                (
                    id.clone(),
                    effects::advance_projected_detail_tier(
                        previous_tier,
                        height,
                        scene.render.experiments.projected_detail_lod,
                    ),
                )
            })
            .collect::<Vec<_>>();
        if !multi_emitter && !self.multi_fire_keys.is_empty() {
            // Keep the fixed two-slot shader ABI safe if a future session
            // replaces a multi-source scene with a single-source scene while
            // retaining this renderer instance.
            self.fire_key = None;
            self.multi_fire_keys.clear();
            self.multi_fire_tiers.clear();
            self.fire_storage.sources[1] = FireFrame::zeroed();
            self.fire_storage.source_origins[1] = [0.; 4];
            self.fire_storage.presentations[1] = FirePresentation::zeroed();
        }
        let fire_changed = self.fire_key.as_ref() != Some(&key);
        if fire_changed {
            self.fire_key = Some(key.clone());
            if !multi_emitter {
                let started = Instant::now();
                self.fire_frame = FireFrame::sample(&key);
                self.metrics.effect_update_cpu_ms = started.elapsed().as_secs_f64() * 1000.;
                self.metrics.effect_events_dropped = self.fire_frame.bounds_max[3] as u32;
                self.metrics.particle_lights = self.fire_frame.lighting[0];
                self.metrics.particle_lights_dropped = self.fire_frame.lighting[1];
                self.metrics.branch_segments_dropped = self.fire_frame.lighting[2];
            }
        }
        let detail_started = Instant::now();
        let projected_height =
            effects::projected_fire_height_px(camera, self.resolution, emitter.position, profile);
        let lod_enabled = scene.render.experiments.projected_detail_lod;
        let tier = effects::advance_projected_detail_tier(
            self.fire_lod_tier,
            projected_height,
            lod_enabled,
        );
        let rendered_segments = effects::projected_detail_segments(profile.fire.segments, tier);
        if fire_changed || rendered_segments != self.fire_render_segments {
            if !multi_emitter {
                let render_frame =
                    effects::render_frame_with_detail(&key, &self.fire_frame, rendered_segments);
                let upload_started = Instant::now();
                self.fire_storage.sources[0] = render_frame;
                self.fire_storage.source_origins[0] = [origin.x, origin.y, origin.z, 0.];
                self.fire_storage.presentations[0] =
                    FirePresentation::from_profile(profile, enabled);
                self.queue.write_buffer(
                    &self.fire_buffer,
                    0,
                    bytemuck::bytes_of(&self.fire_storage),
                );
                self.metrics.cpu_upload_ms += upload_started.elapsed().as_secs_f64() * 1000.;
                self.metrics.fire_primitives = render_frame.counts[0];
                self.metrics.fire_primitives_rendered = render_frame.counts[0];
                self.metrics.flame_fragments = render_frame.counts[2];
                self.metrics.embers = render_frame.counts[3];
            }
            self.fire_render_segments = rendered_segments;
        }
        if multi_emitter
            && (multi_source_keys != self.multi_fire_keys
                || multi_source_tiers != self.multi_fire_tiers)
        {
            let update_started = Instant::now();
            let mut storage = FireFrameStorage::sample_emitters(&multi_source_keys)
                .expect("validated scene has at most two uniquely identified emitters");
            let full_primitive_count = storage.sources.iter().map(|frame| frame.counts[0]).sum();
            for (slot, (id, key)) in multi_source_keys.iter().enumerate() {
                let mut render_key = key.clone();
                render_key.seed = effects::stable_emitter_seed(render_key.seed, id);
                let tier = multi_source_tiers
                    .iter()
                    .find(|(tier_id, _)| tier_id == id)
                    .map_or(0, |(_, tier)| *tier);
                let segments = effects::projected_detail_segments(key.profile.fire.segments, tier);
                storage.sources[slot] = effects::render_frame_with_detail(
                    &render_key,
                    &storage.sources[slot],
                    segments,
                );
            }
            self.metrics.effect_update_cpu_ms = update_started.elapsed().as_secs_f64() * 1000.;
            self.metrics.effect_events_dropped = storage
                .sources
                .iter()
                .map(|frame| frame.bounds_max[3] as u32)
                .sum();
            self.metrics.particle_lights = storage.sources[0].lighting[0];
            self.metrics.particle_lights_dropped = storage.sources[0].lighting[1];
            self.metrics.branch_segments_dropped = storage.sources[0].lighting[2];
            self.metrics.fire_primitives = storage.sources.iter().map(|f| f.counts[0]).sum();
            self.metrics.fire_primitives_rendered = self.metrics.fire_primitives;
            self.metrics.fire_primitives_full = full_primitive_count;
            self.metrics.flame_fragments = storage.sources.iter().map(|f| f.counts[2]).sum();
            self.metrics.embers = storage.sources.iter().map(|f| f.counts[3]).sum();
            let upload_started = Instant::now();
            self.fire_storage = storage;
            self.queue
                .write_buffer(&self.fire_buffer, 0, bytemuck::bytes_of(&self.fire_storage));
            self.metrics.cpu_upload_ms += upload_started.elapsed().as_secs_f64() * 1000.;
            self.multi_fire_keys = multi_source_keys;
            self.multi_fire_tiers = multi_source_tiers;
        }
        self.fire_lod_tier = tier;
        self.metrics.projected_detail_cpu_ms = detail_started.elapsed().as_secs_f64() * 1000.;
        self.metrics.projected_detail_lod_enabled = lod_enabled;
        self.metrics.projected_fire_height_px = projected_height;
        self.metrics.fire_lod_level = u32::from(tier);
        self.metrics.fire_segments_full = profile.fire.segments;
        self.metrics.fire_segments_rendered = rendered_segments;
        self.metrics.fire_primitives_full = if multi_emitter {
            self.metrics.fire_primitives_full
        } else {
            self.fire_frame.counts[0]
        };
        let power = if multi_emitter {
            let primary_slot =
                primary_source_slot.expect("primary emitter is present in the sorted source set");
            self.fire_storage.sources[primary_slot].bounds_min[3]
        } else {
            self.fire_frame.bounds_min[3]
        };
        let mut smoke_emitters = [emitter, emitter];
        let smoke_emitter_count = if multi_emitter {
            smoke_emitters[0] = &scene.emitters[0];
            smoke_emitters[1] = &scene.emitters[1];
            smoke_emitters.sort_by(|left, right| left.id.cmp(&right.id));
            2
        } else {
            1
        };
        let smoke_config_upload_started = Instant::now();
        for (slot, source) in smoke_emitters[..smoke_emitter_count].iter().enumerate() {
            let source_profile = scene
                .effects
                .iter()
                .find(|candidate| candidate.id == source.effect_profile)
                .expect("validated emitter profile exists");
            let source_power = if multi_emitter {
                let frame_slot = self
                    .multi_fire_keys
                    .iter()
                    .position(|(id, _)| id == &source.id)
                    .expect("emitter is present in the sorted fire source set");
                self.fire_storage.sources[frame_slot].bounds_min[3]
            } else {
                power
            };
            let source_origin = Vec3::from(source.position);
            let source_enabled = if source.enabled { source.intensity } else { 0. };
            let config = SmokeSimulationConfig {
                volume_min: vec4((source_origin + Vec3::new(-3., -0.6, -3.)).into(), 0.),
                volume_max: vec4((source_origin + Vec3::new(3., 7.4, 3.)).into(), 0.),
                fire_position: vec4(source.position, source_profile.fire.width),
                simulation: [
                    source.buoyancy,
                    source.dissipation,
                    source.smoke_density,
                    source_enabled,
                ],
                thermal: [
                    source_profile.thermal.heat_output,
                    source_profile.thermal.cooling_rate,
                    source_profile.thermal.lift,
                    source_power,
                ],
            };
            if self.smoke_config_cache[slot] != config {
                self.queue.write_buffer(
                    &self.smoke_source_buffers[slot],
                    0,
                    bytemuck::bytes_of(&config),
                );
                self.smoke_config_cache[slot] = config;
            }
        }
        self.metrics.cpu_upload_ms += smoke_config_upload_started.elapsed().as_secs_f64() * 1000.;
        let mut point_lights = [PointLightGpu::zeroed(); 8];
        let ordered = std::iter::once(fire).chain(
            scene
                .lights
                .iter()
                .filter(|l| l.kind == LightKind::Point && l.id != fire.id),
        );
        let mut light_count = 0;
        for (i, light) in ordered.enumerate() {
            let intensity = if i == 0 {
                light.intensity * (1. - light.flicker + light.flicker * power) * enabled
            } else {
                light.intensity
                    * (1. - light.flicker
                        + light.flicker * simulation::flicker(tick, seed.wrapping_add(i as u32)))
            };
            point_lights[i] = PointLightGpu {
                position_range: vec4(light.position, light.range),
                color_power: vec4(light.color, intensity),
            };
            light_count += 1;
        }
        let g = Globals {
            view_proj: vp.to_cols_array_2d(),
            inverse_view_proj: vp.inverse().to_cols_array_2d(),
            sun_matrix: sun_matrix.to_cols_array_2d(),
            camera: vec4(
                camera.position,
                if matches!(
                    camera.projection,
                    crate::scene::Projection::Orthographic { .. }
                ) {
                    1.
                } else {
                    0.
                },
            ),
            sun_direction: vec4(sun_direction.into(), 0.),
            sun_color: vec4(sun.color, sun.intensity),
            ambient: vec4(scene.environment.ambient, 0.),
            fire_position: vec4(emitter.position, profile.fire.width),
            fire_color: vec4(
                fire.color,
                fire.intensity * (1. - fire.flicker + fire.flicker * power) * enabled,
            ),
            sky: vec4(scene.environment.sky_color, 0.),
            horizon: vec4(
                scene.environment.horizon_color,
                scene.environment.fog_density,
            ),
            wind_time: vec4(wind, tick as f32 * simulation::FIXED_DT),
            volume_min: vec4((origin + Vec3::new(-3., -0.6, -3.)).into(), 0.),
            volume_max: vec4((origin + Vec3::new(3., 7.4, 3.)).into(), 0.),
            params: [
                scene.render.exposure,
                scene.render.shading_steps as f32,
                seed as f32,
                scene.render.smoke_steps as f32,
            ],
            resolution: [
                self.resolution[0] as f32,
                self.resolution[1] as f32,
                scene.render.dither_strength,
                0.,
            ],
            experiments: [
                u32::from(scene.render.experiments.pixel_cluster_lighting) as f32,
                u32::from(scene.render.experiments.stable_smoke_detail) as f32,
                u32::from(scene.render.experiments.connected_motion) as f32,
                if emitter.style == crate::scene::EffectStyle::Ink {
                    1.
                } else {
                    0.
                },
            ],
            simulation: [
                emitter.buoyancy,
                emitter.dissipation,
                emitter.smoke_density,
                enabled,
            ],
            effect_settings: [
                emitter.secondary_bubbles as f32,
                emitter.bubble_scale,
                emitter.self_shadow_strength,
                emitter.internal_glow,
            ],
            thermal: [
                profile.thermal.heat_output,
                profile.thermal.cooling_rate,
                profile.thermal.lift,
                power,
            ],
            fire_outer: vec4(profile.palette.outer, profile.fire.emission),
            fire_warm: vec4(profile.palette.warm, profile.fire.edge_breakup),
            fire_hot: vec4(profile.palette.hot, profile.fire.tip_breakup),
            fire_shape: [
                profile.fire.width,
                profile.fire.height,
                profile.fire.motion_speed,
                profile.fire.curl,
            ],
            fire_pixels: [
                u32::from(profile.fire.solid) as f32,
                profile.fire.color_bands as f32,
                profile.fire.heat_distortion,
                profile.fire.heat_distortion_height,
            ],
            light_info: [light_count, 0, 0, 0],
            point_lights,
            presentation: [
                scene.render.palette_strength,
                scene.render.bloom_strength,
                scene.render.reflection_steps as f32,
                u32::from(scene.render.experiments.smoke_absorption_cache) as f32,
            ],
            optical_settings: [
                u32::from(scene.render.experiments.optical_surface_reuse) as f32,
                0.,
                0.,
                0.,
            ],
        };
        let upload_started = Instant::now();
        self.queue
            .write_buffer(&self.uniform, 0, bytemuck::bytes_of(&g));
        self.metrics.cpu_upload_ms += upload_started.elapsed().as_secs_f64() * 1000.;
    }

    pub fn effect_state(&self) -> serde_json::Value {
        serde_json::json!({"counts":self.fire_frame.counts,"bounds_min":self.fire_frame.bounds_min,
            "bounds_max":self.fire_frame.bounds_max,"lighting":self.fire_frame.lighting,
            "projected_detail":{"enabled":self.metrics.projected_detail_lod_enabled,
                "projected_height_px":self.metrics.projected_fire_height_px,
                "tier":self.metrics.fire_lod_level,
                "segments_full":self.metrics.fire_segments_full,
                "segments_rendered":self.metrics.fire_segments_rendered,
                "primitives_full":self.metrics.fire_primitives_full,
                "primitives_rendered":self.metrics.fire_primitives_rendered},
            "particle_lights":&self.fire_frame.lights[..self.fire_frame.lighting[0] as usize]})
    }
    pub fn reset_smoke(&mut self) {
        self.invalidate_shadow_cache("reset");
        self.absorption_cache_dirty = true;
        let bytes_per_voxel = if self.smoke_volume_format == wgpu::TextureFormat::Rg16Float {
            4
        } else {
            8
        };
        let bytes = vec![0u8; (VOLUME[0] * VOLUME[1] * VOLUME[2] * bytes_per_voxel) as usize];
        for source in &self.smoke_textures {
            for texture in source {
                self.queue.write_texture(
                    wgpu::TexelCopyTextureInfo {
                        texture,
                        mip_level: 0,
                        origin: wgpu::Origin3d::ZERO,
                        aspect: wgpu::TextureAspect::All,
                    },
                    &bytes,
                    wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some(VOLUME[0] * bytes_per_voxel),
                        rows_per_image: Some(VOLUME[1]),
                    },
                    wgpu::Extent3d {
                        width: VOLUME[0],
                        height: VOLUME[1],
                        depth_or_array_layers: VOLUME[2],
                    },
                );
            }
        }
        self.smoke_index = 0;
    }
    pub fn simulate(&mut self, scene: &Scene, camera: &Camera, tick: u64, seed: u32) {
        let started = Instant::now();
        self.update_globals(scene, camera, tick, seed);
        let compute_slot = self.timing.as_mut().and_then(|timing| {
            let count = timing.compute_slots.len();
            let index = (0..count)
                .map(|offset| (timing.next_compute_slot + offset) % count)
                .find(|&index| timing.compute_slots[index].pending.is_none());
            if let Some(index) = index {
                timing.next_compute_slot = (index + 1) % count;
            }
            index
        });
        if compute_slot.is_none() && self.timing.is_some() {
            self.metrics.gpu_compute_samples_skipped += 1;
        }
        let mut encoder = self.device.create_command_encoder(&Default::default());
        {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("smoke simulation"),
                timestamp_writes: compute_slot.map(|index| wgpu::ComputePassTimestampWrites {
                    query_set: &self.timing.as_ref().unwrap().compute_slots[index].query,
                    beginning_of_pass_write_index: Some(0),
                    end_of_pass_write_index: Some(1),
                }),
            });
            pass.set_pipeline(&self.pipelines.smoke);
            pass.set_bind_group(0, &self.globals, &[]);
            for source_groups in &self.smoke_groups {
                pass.set_bind_group(1, &source_groups[self.smoke_index], &[]);
                pass.dispatch_workgroups(VOLUME[0] / 4, VOLUME[1] / 4, VOLUME[2] / 4);
            }
        }
        if let Some(index) = compute_slot {
            let slot = &self.timing.as_ref().unwrap().compute_slots[index];
            encoder.resolve_query_set(&slot.query, 0..2, &slot.resolve, 0);
            encoder.copy_buffer_to_buffer(&slot.resolve, 0, &slot.read, 0, COMPUTE_QUERY_BYTES);
        }
        let command_buffer = encoder.finish();
        let submit_started = Instant::now();
        self.queue.submit([command_buffer]);
        let submit_ms = submit_started.elapsed().as_secs_f64() * 1000.;
        if let Some(index) = compute_slot {
            let slot = &mut self.timing.as_mut().unwrap().compute_slots[index];
            let (sender, receiver) = mpsc::channel();
            slot.read
                .slice(..)
                .map_async(wgpu::MapMode::Read, move |result| {
                    let _ = sender.send(result);
                });
            slot.tick = tick;
            slot.submitted_at = Some(Instant::now());
            slot.pending = Some(receiver);
        }
        self.smoke_index = 1 - self.smoke_index;
        self.absorption_cache_dirty = true;
        let simulation_cpu_ms = started.elapsed().as_secs_f64() * 1000.;
        self.metrics.cpu_simulation_submit_ms += simulation_cpu_ms;
        self.metrics.cpu_simulation_encode_ms += (simulation_cpu_ms - submit_ms).max(0.);
        self.metrics.cpu_queue_submit_ms += submit_ms;
        self.metrics.cpu_steps_this_frame = self.metrics.cpu_steps_this_frame.saturating_add(1);
    }

    pub fn poll_timing(&mut self, wait: bool) {
        self.device.poll(if wait {
            wgpu::Maintain::Wait
        } else {
            wgpu::Maintain::Poll
        });
        if let Some(timing) = &mut self.timing {
            for slot in &mut timing.compute_slots {
                let Some(receiver) = &slot.pending else {
                    continue;
                };
                match receiver.try_recv() {
                    Ok(result) => {
                        if result.is_ok() {
                            let view = slot.read.slice(..).get_mapped_range();
                            let numbers: &[u64] = bytemuck::cast_slice(&view);
                            let elapsed = numbers[1].saturating_sub(numbers[0]) as f64
                                * self.queue.get_timestamp_period() as f64
                                / 1_000_000.;
                            self.metrics.gpu_smoke_compute_ms = Some(elapsed);
                            self.metrics.gpu_smoke_tick = Some(slot.tick);
                            if self.completed_compute_timings.len() == 64 {
                                self.completed_compute_timings.pop_front();
                            }
                            self.completed_compute_timings
                                .push_back(GpuComputeTimingSample {
                                    tick: slot.tick,
                                    elapsed_ms: elapsed,
                                    readback_latency_ms: slot
                                        .submitted_at
                                        .map(|submitted| submitted.elapsed().as_secs_f64() * 1000.)
                                        .unwrap_or(0.),
                                });
                            drop(view);
                            slot.read.unmap();
                        }
                        slot.pending = None;
                    }
                    Err(mpsc::TryRecvError::Empty) => {}
                    Err(mpsc::TryRecvError::Disconnected) => {
                        slot.pending = None;
                        self.metrics.gpu_compute_samples_skipped += 1;
                    }
                }
            }
            for slot in &mut timing.slots {
                let Some(receiver) = &slot.pending else {
                    continue;
                };
                let result = match receiver.try_recv() {
                    Ok(result) => result,
                    Err(mpsc::TryRecvError::Empty) => continue,
                    Err(mpsc::TryRecvError::Disconnected) => {
                        slot.pending = None;
                        self.metrics.gpu_samples_skipped += 1;
                        continue;
                    }
                };
                if result.is_ok() {
                    let view = slot.read.slice(..).get_mapped_range();
                    let numbers: &[u64] = bytemuck::cast_slice(&view);
                    let period = self.queue.get_timestamp_period() as f64 / 1_000_000.;
                    let elapsed = |start: usize, end: usize| {
                        numbers[end].saturating_sub(numbers[start]) as f64 * period
                    };
                    let render_ms = if slot.shadow_rendered {
                        elapsed(0, 9)
                    } else {
                        elapsed(2, 9)
                    };
                    let tile_ms = elapsed(10, 11);
                    let absorption_ms = if slot.absorption_cache {
                        elapsed(12, 13)
                    } else {
                        0.
                    };
                    let total_ms = render_ms + tile_ms + absorption_ms;
                    let readback_latency_ms = slot
                        .submitted_at
                        .map(|submitted| submitted.elapsed().as_secs_f64() * 1000.)
                        .unwrap_or(0.);
                    let mut passes_ms = BTreeMap::new();
                    if slot.shadow_rendered {
                        passes_ms.insert("shadow_maps".into(), elapsed(0, 1));
                    }
                    passes_ms.insert("opaque_geometry".into(), elapsed(2, 3));
                    passes_ms.insert("atmosphere_fire".into(), elapsed(4, 5));
                    if slot.optical {
                        passes_ms.insert("optical_resolve".into(), elapsed(6, 7));
                    }
                    passes_ms.insert("post".into(), elapsed(8, 9));
                    passes_ms.insert("tile_list_build".into(), tile_ms);
                    if slot.absorption_cache {
                        passes_ms.insert("smoke_absorption_cache".into(), absorption_ms);
                        self.metrics.gpu_absorption_cache_ms = Some(absorption_ms);
                    }
                    self.metrics.gpu_tile_list_ms = Some(tile_ms);
                    self.metrics.gpu_ms = Some(total_ms);
                    self.metrics.gpu_passes_ms.clone_from(&passes_ms);
                    self.metrics.gpu_timing_frame = Some(slot.frame);
                    if slot.frame < self.metrics.frame {
                        self.metrics.gpu_samples_late += 1;
                    }
                    if self.completed_gpu_timings.len() == 64 {
                        self.completed_gpu_timings.pop_front();
                    }
                    self.completed_gpu_timings.push_back(GpuTimingSample {
                        frame: slot.frame,
                        total_ms,
                        readback_latency_ms,
                        passes_ms,
                    });
                    drop(view);
                    slot.read.unmap();
                }
                slot.pending = None;
            }
        }
        self.poll_tile_stats();
    }

    pub fn begin_measurement_frame(&mut self) {
        self.metrics.begin_frame();
    }

    pub fn take_gpu_timing_samples(&mut self) -> Vec<GpuTimingSample> {
        self.completed_gpu_timings.drain(..).collect()
    }

    pub fn take_gpu_compute_timing_samples(&mut self) -> Vec<GpuComputeTimingSample> {
        self.completed_compute_timings.drain(..).collect()
    }

    fn ensure_absorption_cache(&mut self, enabled: bool) {
        if self.absorption_cache_active == enabled {
            return;
        }
        let smoke_views = self.smoke_textures[0]
            .each_ref()
            .map(|texture| texture.create_view(&Default::default()));
        let cache_bytes = (self.absorption_cache_resolution as u64).pow(3) * 8;
        if enabled {
            let texture = texture(
                &self.device,
                "coarse fire-light smoke transmittance",
                [self.absorption_cache_resolution; 3],
                HDR,
                wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::STORAGE_BINDING,
                wgpu::TextureDimension::D3,
            );
            let view = texture.create_view(&Default::default());
            self.absorption_groups = Some(std::array::from_fn(|i| {
                group(
                    &self.device,
                    &self.absorption_layout,
                    &[
                        wgpu::BindingResource::TextureView(&smoke_views[i]),
                        wgpu::BindingResource::Sampler(&self.optical_sampler),
                        wgpu::BindingResource::TextureView(&view),
                    ],
                )
            }));
            self.volume_groups = std::array::from_fn(|i| {
                group(
                    &self.device,
                    &self.volume_layout,
                    &[
                        wgpu::BindingResource::TextureView(&self.depth),
                        wgpu::BindingResource::TextureView(&smoke_views[i]),
                        wgpu::BindingResource::Sampler(&self.optical_sampler),
                        wgpu::BindingResource::TextureView(&view),
                    ],
                )
            });
            self.optical_smoke_groups = std::array::from_fn(|i| {
                self.device.create_bind_group(&wgpu::BindGroupDescriptor {
                    label: Some("optical foreground atmosphere"),
                    layout: &self.optical_smoke_layout,
                    entries: &[
                        wgpu::BindGroupEntry {
                            binding: 1,
                            resource: wgpu::BindingResource::TextureView(&smoke_views[i]),
                        },
                        wgpu::BindGroupEntry {
                            binding: 2,
                            resource: wgpu::BindingResource::Sampler(&self.optical_sampler),
                        },
                        wgpu::BindGroupEntry {
                            binding: 3,
                            resource: self.tile_headers.as_entire_binding(),
                        },
                        wgpu::BindGroupEntry {
                            binding: 4,
                            resource: self.fire_tile_indices.as_entire_binding(),
                        },
                        wgpu::BindGroupEntry {
                            binding: 5,
                            resource: self.smoke_tile_indices.as_entire_binding(),
                        },
                        wgpu::BindGroupEntry {
                            binding: 6,
                            resource: self.point_tile_indices.as_entire_binding(),
                        },
                        wgpu::BindGroupEntry {
                            binding: 7,
                            resource: self.particle_tile_indices.as_entire_binding(),
                        },
                        wgpu::BindGroupEntry {
                            binding: 8,
                            resource: wgpu::BindingResource::TextureView(&view),
                        },
                    ],
                })
            });
            self.absorption_texture = Some(texture);
            let allocation = self.resource_inventory["known_gpu_allocation_bytes"]
                .as_u64()
                .unwrap_or(0);
            self.resource_inventory["known_gpu_allocation_bytes"] =
                (allocation + cache_bytes).into();
            self.resource_inventory["smoke_absorption_cache_bytes"] = cache_bytes.into();
        } else {
            self.volume_groups = std::array::from_fn(|i| {
                group(
                    &self.device,
                    &self.volume_layout,
                    &[
                        wgpu::BindingResource::TextureView(&self.depth),
                        wgpu::BindingResource::TextureView(&smoke_views[i]),
                        wgpu::BindingResource::Sampler(&self.optical_sampler),
                        // This slot is unused by direct sampling; bind an existing volume.
                        wgpu::BindingResource::TextureView(&smoke_views[i]),
                    ],
                )
            });
            self.optical_smoke_groups = std::array::from_fn(|i| {
                self.device.create_bind_group(&wgpu::BindGroupDescriptor {
                    label: Some("optical foreground atmosphere"),
                    layout: &self.optical_smoke_layout,
                    entries: &[
                        wgpu::BindGroupEntry {
                            binding: 1,
                            resource: wgpu::BindingResource::TextureView(&smoke_views[i]),
                        },
                        wgpu::BindGroupEntry {
                            binding: 2,
                            resource: wgpu::BindingResource::Sampler(&self.optical_sampler),
                        },
                        wgpu::BindGroupEntry {
                            binding: 3,
                            resource: self.tile_headers.as_entire_binding(),
                        },
                        wgpu::BindGroupEntry {
                            binding: 4,
                            resource: self.fire_tile_indices.as_entire_binding(),
                        },
                        wgpu::BindGroupEntry {
                            binding: 5,
                            resource: self.smoke_tile_indices.as_entire_binding(),
                        },
                        wgpu::BindGroupEntry {
                            binding: 6,
                            resource: self.point_tile_indices.as_entire_binding(),
                        },
                        wgpu::BindGroupEntry {
                            binding: 7,
                            resource: self.particle_tile_indices.as_entire_binding(),
                        },
                        wgpu::BindGroupEntry {
                            binding: 8,
                            resource: wgpu::BindingResource::TextureView(&smoke_views[i]),
                        },
                    ],
                })
            });
            self.absorption_groups = None;
            self.absorption_texture = None;
            let allocation = self.resource_inventory["known_gpu_allocation_bytes"]
                .as_u64()
                .unwrap_or(0);
            self.resource_inventory["known_gpu_allocation_bytes"] =
                allocation.saturating_sub(cache_bytes).into();
            self.resource_inventory["smoke_absorption_cache_bytes"] = 0.into();
        }
        self.absorption_cache_active = enabled;
        self.absorption_cache_dirty = true;
    }

    pub fn invalidate_absorption_cache(&mut self) {
        self.absorption_cache_dirty = true;
    }

    pub fn render(&mut self, scene: &Scene, camera: &Camera, tick: u64, seed: u32) {
        self.poll_timing(false);
        if self.shading_diagnostics_enabled {
            self.queue
                .write_buffer(&self.shading_diagnostic_buffer, 0, &[0; 22 * 4]);
            self.metrics.shading_counters = None;
        }
        self.ensure_absorption_cache(scene.render.experiments.smoke_absorption_cache);
        let started = Instant::now();
        if self.material_cache != scene.materials {
            let upload_started = Instant::now();
            self.queue.write_buffer(
                &self.material_buffer,
                0,
                bytemuck::cast_slice(&material_table(scene)),
            );
            self.metrics.cpu_upload_ms += upload_started.elapsed().as_secs_f64() * 1000.;
            self.material_cache.clone_from(&scene.materials);
        }
        self.update_globals(scene, camera, tick, seed);
        let timing_slot = self.timing.as_mut().and_then(|timing| {
            let count = timing.slots.len();
            let index = (0..count)
                .map(|offset| (timing.next_slot + offset) % count)
                .find(|&index| timing.slots[index].pending.is_none());
            if let Some(index) = index {
                timing.next_slot = (index + 1) % count;
            }
            index
        });
        let timed = timing_slot.is_some();
        if !timed && self.timing.is_some() {
            self.metrics.gpu_samples_skipped += 1;
        }
        let tile_stats_slot = (0..self.tile_stats_readbacks.len())
            .map(|offset| {
                (self.next_tile_stats_readback + offset) % self.tile_stats_readbacks.len()
            })
            .find(|&index| self.tile_stats_readbacks[index].pending.is_none());
        if let Some(index) = tile_stats_slot {
            self.next_tile_stats_readback = (index + 1) % self.tile_stats_readbacks.len();
        } else {
            self.metrics.tile_stats_samples_skipped += 1;
        }
        let next_shadow_key = shadow_cache_key(scene);
        let compared_reason = next_shadow_key
            .as_ref()
            .map(|key| shadow_dirty_reason(self.shadow_cache_key.as_ref(), key));
        let invalidation_reason = self.shadow_invalidation_reason.take();
        let dirty_reason = invalidation_reason
            .or(compared_reason)
            .unwrap_or("unknown_shadow_state");
        let mut dirty_faces = [false; 7];
        let mut reported_reason = dirty_reason;
        let full_invalidation = self.force_shadow_redraw
            || invalidation_reason.is_some()
            || next_shadow_key.is_none()
            || self.shadow_cache_key.is_none();
        if full_invalidation {
            dirty_faces = [true; 7];
            if self.force_shadow_redraw {
                reported_reason = "forced_redraw";
            }
        } else if dirty_reason != "unchanged" {
            let previous = self.shadow_cache_key.as_ref().unwrap();
            let next = next_shadow_key.as_ref().unwrap();
            if previous.sun_position != next.sun_position {
                dirty_faces[0] = true;
            }
            if previous.fire_position != next.fire_position
                || previous.fire_range != next.fire_range
            {
                dirty_faces[1..].fill(true);
            }
            if previous.casters != next.casters {
                if only_object_transforms_changed(previous, next) {
                    let changed_ids = previous
                        .casters
                        .iter()
                        .zip(&next.casters)
                        .filter(|(old, new)| {
                            old.position != new.position
                                || old.rotation != new.rotation
                                || old.scale != new.scale
                        })
                        .map(|(old, _)| old.id.as_str())
                        .collect::<Vec<_>>();
                    let tracked = changed_ids.iter().all(|id| {
                        self.shadow_transform_changes
                            .iter()
                            .any(|(changed_id, _, _)| changed_id == id)
                    });
                    if tracked {
                        let bounds = self
                            .shadow_transform_changes
                            .iter()
                            .filter(|(id, _, _)| changed_ids.contains(&id.as_str()))
                            .flat_map(|(_, old, new)| [old.clone(), new.clone()])
                            .collect::<Vec<_>>();
                        let matrices = shadow_matrices(scene);
                        let transform_faces = shadow_face_mask_for_bounds(&bounds, &matrices);
                        if shadow_bounds_require_full_fallback(&bounds, &matrices) {
                            reported_reason = "unknown_caster_bounds";
                        }
                        for (dirty, transform_dirty) in dirty_faces.iter_mut().zip(transform_faces)
                        {
                            *dirty |= transform_dirty;
                        }
                        if !transform_faces.iter().any(|dirty| *dirty) {
                            reported_reason = "casters_changed_outside_shadow_frusta";
                        }
                    } else {
                        dirty_faces = [true; 7];
                        reported_reason = "unknown_caster_bounds";
                    }
                } else {
                    dirty_faces = [true; 7];
                }
            }
            if previous.shadow_materials != next.shadow_materials {
                let mut changed_material_ids = Vec::new();
                if previous.shadow_materials.len() != next.shadow_materials.len() {
                    dirty_faces = [true; 7];
                    reported_reason = "unknown_shadow_material_bounds";
                }
                for (id, old_value) in &previous.shadow_materials {
                    if dirty_faces.iter().any(|dirty| *dirty) {
                        break;
                    }
                    match next
                        .shadow_materials
                        .iter()
                        .find(|(new_id, _)| new_id == id)
                    {
                        Some((_, new_value)) if old_value == new_value => {}
                        Some(_) => changed_material_ids.push(id.as_str()),
                        None => {
                            dirty_faces = [true; 7];
                            reported_reason = "unknown_shadow_material_bounds";
                            break;
                        }
                    }
                }
                if reported_reason != "unknown_shadow_material_bounds" {
                    let bounds = self
                        .object_draws
                        .iter()
                        .filter(|draw| changed_material_ids.contains(&draw.material_id.as_str()))
                        .map(|draw| draw.bounds.clone())
                        .collect::<Vec<_>>();
                    if bounds.is_empty() && !changed_material_ids.is_empty() {
                        dirty_faces = [true; 7];
                        reported_reason = "unknown_shadow_material_bounds";
                    } else {
                        let matrices = shadow_matrices(scene);
                        let material_faces = shadow_face_mask_for_bounds(&bounds, &matrices);
                        if shadow_bounds_require_full_fallback(&bounds, &matrices) {
                            reported_reason = "unknown_shadow_material_bounds";
                        }
                        for (dirty, material_dirty) in dirty_faces.iter_mut().zip(material_faces) {
                            *dirty |= material_dirty;
                        }
                    }
                }
            }
        }
        let shadow_redrawn = dirty_faces.iter().any(|dirty| *dirty);
        self.shadow_dirty_faces = dirty_faces;
        self.metrics.shadow_cache_hit = !shadow_redrawn && next_shadow_key.is_some();
        self.metrics.shadow_redrawn = shadow_redrawn;
        self.metrics.shadow_cache_resident = next_shadow_key.is_some();
        self.metrics.shadow_maps_redrawn =
            dirty_faces.iter().filter(|dirty| **dirty).count() as u32;
        self.metrics.shadow_dirty_faces = dirty_faces;
        self.metrics.shadow_dirty_reason = Some(reported_reason.to_string());
        self.shadow_cache_key = next_shadow_key;
        self.shadow_transform_changes.clear();
        let culling_started = Instant::now();
        let camera_vp = camera.matrix(self.resolution[0] as f32 / self.resolution[1] as f32);
        let camera_draws = prepare_draws(
            &self.object_draws,
            &self.mesh_draws,
            &scene.materials,
            Frustum::from_view_projection(camera_vp),
            self.geometry_culling_enabled,
            self.geometry_instancing_enabled,
        );
        // Only snapshot and shade optical geometry that survives camera culling.
        // Scene materials can remain optical while all their objects are offscreen.
        let optical_active = camera_draws.batches.iter().any(|batch| batch.optical);
        if optical_active {
            self.ensure_optical_targets();
        }
        let shadow_draws = if shadow_redrawn {
            shadow_matrices(scene)
                .into_iter()
                .enumerate()
                .map(|(index, matrix)| {
                    dirty_faces[index].then(|| {
                        prepare_draws(
                            &self.object_draws,
                            &self.mesh_draws,
                            &scene.materials,
                            Frustum::from_view_projection(matrix),
                            self.geometry_culling_enabled,
                            self.geometry_instancing_enabled,
                        )
                    })
                })
                .collect::<Vec<_>>()
        } else {
            Vec::new()
        };
        self.metrics.cpu_object_culling_ms = culling_started.elapsed().as_secs_f64() * 1000.;
        self.metrics.object_culling_enabled = self.geometry_culling_enabled;
        self.metrics.object_instancing_enabled = self.geometry_instancing_enabled;
        self.metrics.camera_objects_considered = self.object_draws.len() as u32;
        self.metrics.camera_objects_visible = camera_draws.visible_objects;
        self.metrics.camera_draw_batches = camera_draws.batches.len() as u32;
        self.metrics.camera_vertices_submitted = submitted_vertices(&camera_draws);
        self.metrics.optical_draw_batches = camera_draws
            .batches
            .iter()
            .filter(|batch| batch.optical)
            .count() as u32;
        self.metrics.optical_surface_reuse_enabled = scene.render.experiments.optical_surface_reuse;
        let upload_started = Instant::now();
        if !camera_draws.instances.is_empty() {
            self.queue.write_buffer(
                &self.instance_buffers[7],
                0,
                bytemuck::cast_slice(&camera_draws.instances),
            );
        }
        for (index, draws) in shadow_draws.iter().enumerate() {
            let Some(draws) = draws else { continue };
            self.shadow_visible_cache[index] = draws.visible_objects;
            self.shadow_batch_cache[index] = draws.batches.len() as u32;
            self.shadow_vertex_cache[index] = submitted_vertices(draws);
            if !draws.instances.is_empty() {
                self.queue.write_buffer(
                    &self.instance_buffers[index],
                    0,
                    bytemuck::cast_slice(&draws.instances),
                );
            }
        }
        self.metrics.shadow_objects_visible = self.shadow_visible_cache;
        self.metrics.shadow_draw_batches = self.shadow_batch_cache;
        self.metrics.shadow_vertices_submitted = self.shadow_vertex_cache;
        self.metrics.cpu_upload_ms += upload_started.elapsed().as_secs_f64() * 1000.;
        let mut encoder = self.device.create_command_encoder(&Default::default());
        self.queue.write_buffer(
            &self.tile_stats_buffer,
            0,
            bytemuck::cast_slice(&[0u32; 12]),
        );
        let tile_build_started = Instant::now();
        {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("effect tile-list build"),
                timestamp_writes: timing_slot.map(|index| wgpu::ComputePassTimestampWrites {
                    query_set: &self.timing.as_ref().unwrap().slots[index].query,
                    beginning_of_pass_write_index: Some(10),
                    end_of_pass_write_index: Some(11),
                }),
            });
            pass.set_pipeline(&self.pipelines.tile_build);
            pass.set_bind_group(0, &self.globals, &[]);
            pass.set_bind_group(1, &self.tile_build_group, &[]);
            let tiles_x = self.resolution[0].div_ceil(TILE_SIZE);
            let tiles_y = self.resolution[1].div_ceil(TILE_SIZE);
            pass.dispatch_workgroups(tiles_x, tiles_y, 1);
        }
        if let Some(index) = tile_stats_slot {
            encoder.copy_buffer_to_buffer(
                &self.tile_stats_buffer,
                0,
                &self.tile_stats_readbacks[index].read,
                0,
                48,
            );
        }
        self.metrics.cpu_tile_list_encode_ms = tile_build_started.elapsed().as_secs_f64() * 1000.;
        self.metrics.tile_count = self.tile_count;
        self.metrics.tile_lists_enabled = self.tile_lists_enabled;
        self.metrics.tile_overflow_forced = self.tile_force_overflow || !self.tile_lists_enabled;
        self.metrics.tile_list_bytes = self.resource_inventory["tile_list_bytes"]
            .as_u64()
            .unwrap_or(0);
        self.metrics.smoke_absorption_cache_enabled =
            scene.render.experiments.smoke_absorption_cache;
        self.metrics.gpu_absorption_cache_ms = None;
        let absorption_cache_build =
            scene.render.experiments.smoke_absorption_cache && self.absorption_cache_dirty;
        if absorption_cache_build {
            self.metrics.absorption_cache_builds += 1;
            let absorption_encode_started = Instant::now();
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("coarse fire-light smoke absorption"),
                timestamp_writes: timing_slot.map(|index| wgpu::ComputePassTimestampWrites {
                    query_set: &self.timing.as_ref().unwrap().slots[index].query,
                    beginning_of_pass_write_index: Some(12),
                    end_of_pass_write_index: Some(13),
                }),
            });
            pass.set_pipeline(&self.pipelines.absorption);
            pass.set_bind_group(0, &self.globals, &[]);
            pass.set_bind_group(
                1,
                &self
                    .absorption_groups
                    .as_ref()
                    .expect("enabled cache has build bind groups")[self.smoke_index],
                &[],
            );
            pass.dispatch_workgroups(
                self.absorption_cache_resolution / 4,
                self.absorption_cache_resolution / 4,
                self.absorption_cache_resolution / 4,
            );
            drop(pass);
            self.metrics.cpu_absorption_cache_ms =
                absorption_encode_started.elapsed().as_secs_f64() * 1000.;
        } else {
            self.metrics.cpu_absorption_cache_ms = 0.;
            if scene.render.experiments.smoke_absorption_cache {
                self.metrics.absorption_cache_skips += 1;
            }
        }
        let shadow_encode_started = Instant::now();
        if shadow_redrawn {
            self.update_shadow_matrices(scene, dirty_faces);
            let first_dirty = dirty_faces.iter().position(|dirty| *dirty);
            let last_dirty = dirty_faces.iter().rposition(|dirty| *dirty);
            for (i, draws) in shadow_draws.iter().enumerate() {
                let Some(draws) = draws else { continue };
                let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("shadow"),
                    color_attachments: &[],
                    depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                        view: if i == 0 {
                            &self.sun_view
                        } else {
                            &self.point_faces[i - 1]
                        },
                        depth_ops: Some(wgpu::Operations {
                            load: wgpu::LoadOp::Clear(1.),
                            store: wgpu::StoreOp::Store,
                        }),
                        stencil_ops: None,
                    }),
                    timestamp_writes: if timed && (Some(i) == first_dirty || Some(i) == last_dirty)
                    {
                        Some(wgpu::RenderPassTimestampWrites {
                            query_set: &self.timing.as_ref().unwrap().slots[timing_slot.unwrap()]
                                .query,
                            beginning_of_pass_write_index: (Some(i) == first_dirty).then_some(0),
                            end_of_pass_write_index: (Some(i) == last_dirty).then_some(1),
                        })
                    } else {
                        None
                    },
                    occlusion_query_set: None,
                });
                let transparent_shadows = scene
                    .materials
                    .iter()
                    .any(|m| m.transmission * (1. - m.metallic) > 0.);
                pass.set_pipeline(
                    match (self.geometry_instancing_enabled, transparent_shadows) {
                        (true, true) => &self.pipelines.shadow,
                        (true, false) => &self.pipelines.shadow_opaque,
                        (false, true) => &self.pipelines.shadow_baked,
                        (false, false) => &self.pipelines.shadow_opaque_baked,
                    },
                );
                pass.set_bind_group(0, &self.shadow_groups[i], &[]);
                pass.set_bind_group(1, &self.shadow_materials, &[]);
                let vertex_buffer = if self.geometry_instancing_enabled {
                    &self.vertex
                } else {
                    self.unshared_vertex_buffer
                        .as_ref()
                        .expect("baked reference buffer is allocated when instancing is disabled")
                };
                pass.set_vertex_buffer(0, vertex_buffer.slice(..));
                let instance_buffer = &self.instance_buffers[i];
                for batch in &draws.batches {
                    if self.geometry_instancing_enabled {
                        let offset = u64::from(batch.first_instance)
                            * std::mem::size_of::<InstanceGpu>() as u64;
                        pass.set_vertex_buffer(1, instance_buffer.slice(offset..));
                    }
                    pass.draw(
                        batch.first_vertex..batch.first_vertex + batch.vertex_count,
                        0..batch.instance_count,
                    );
                }
            }
        }
        self.metrics.cpu_shadow_encode_ms = shadow_encode_started.elapsed().as_secs_f64() * 1000.;

        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("opaque world"),
                color_attachments: &[clear_attachment(&self.hdr), clear_attachment(&self.normals)],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.depth,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: timing_slot.map(|index| wgpu::RenderPassTimestampWrites {
                    query_set: &self.timing.as_ref().unwrap().slots[index].query,
                    beginning_of_pass_write_index: Some(2),
                    end_of_pass_write_index: Some(3),
                }),
                occlusion_query_set: None,
            });
            pass.set_pipeline(if self.shading_diagnostics_enabled {
                if self.geometry_instancing_enabled {
                    &self.pipelines.mesh_diagnostic
                } else {
                    &self.pipelines.mesh_baked_diagnostic
                }
            } else if self.geometry_instancing_enabled {
                &self.pipelines.mesh
            } else {
                &self.pipelines.mesh_baked
            });
            pass.set_bind_group(0, &self.globals, &[]);
            pass.set_bind_group(1, &self.textures, &[]);
            pass.set_bind_group(2, &self.tile_list_groups[self.smoke_index], &[]);
            let vertex_buffer = if self.geometry_instancing_enabled {
                &self.vertex
            } else {
                self.unshared_vertex_buffer
                    .as_ref()
                    .expect("baked reference buffer is allocated when instancing is disabled")
            };
            pass.set_vertex_buffer(0, vertex_buffer.slice(..));
            let instance_buffer = &self.instance_buffers[7];
            for batch in &camera_draws.batches {
                if self.geometry_instancing_enabled {
                    let offset =
                        u64::from(batch.first_instance) * std::mem::size_of::<InstanceGpu>() as u64;
                    pass.set_vertex_buffer(1, instance_buffer.slice(offset..));
                }
                pass.draw(
                    batch.first_vertex..batch.first_vertex + batch.vertex_count,
                    0..batch.instance_count,
                );
            }
        }
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("fire smoke embers"),
                color_attachments: &[
                    Some(wgpu::RenderPassColorAttachment {
                        view: &self.hdr,
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Load,
                            store: wgpu::StoreOp::Store,
                        },
                    }),
                    clear_attachment(&self.effect_depth),
                ],
                depth_stencil_attachment: None,
                timestamp_writes: timing_slot.map(|index| wgpu::RenderPassTimestampWrites {
                    query_set: &self.timing.as_ref().unwrap().slots[index].query,
                    beginning_of_pass_write_index: Some(4),
                    end_of_pass_write_index: Some(5),
                }),
                occlusion_query_set: None,
            });
            pass.set_pipeline(if self.shading_diagnostics_enabled {
                &self.pipelines.volume_diagnostic
            } else {
                &self.pipelines.volume
            });
            pass.set_bind_group(0, &self.globals, &[]);
            pass.set_bind_group(1, &self.textures, &[]);
            pass.set_bind_group(2, &self.volume_groups[self.smoke_index], &[]);
            pass.set_bind_group(3, &self.tile_list_groups[self.smoke_index], &[]);
            pass.draw(0..3, 0..1);
        }
        // Skip the copies and extra draw entirely for existing diffuse scenes.
        if optical_active {
            let mut attachments = Vec::with_capacity(2);
            let optical_output_view = self
                .optical_output
                .as_ref()
                .map(|texture| texture.create_view(&Default::default()));
            let optical_mask_view = self
                .optical_mask
                .as_ref()
                .map(|texture| texture.create_view(&Default::default()));
            if self.optical_no_copy_enabled {
                attachments.push(Some(wgpu::RenderPassColorAttachment {
                    view: optical_output_view
                        .as_ref()
                        .expect("optical output is allocated before the optical pass"),
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                        store: wgpu::StoreOp::Store,
                    },
                }));
                if self.optical_mask_required {
                    attachments.push(Some(wgpu::RenderPassColorAttachment {
                        view: optical_mask_view
                            .as_ref()
                            .expect("optical mask is allocated before the optical pass"),
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                            store: wgpu::StoreOp::Store,
                        },
                    }));
                }
            } else {
                let scene_color = self
                    .scene_color
                    .as_ref()
                    .expect("optical snapshot is allocated before the optical pass");
                encoder.copy_texture_to_texture(
                    self.hdr_texture.as_image_copy(),
                    scene_color.as_image_copy(),
                    wgpu::Extent3d {
                        width: self.resolution[0],
                        height: self.resolution[1],
                        depth_or_array_layers: 1,
                    },
                );
                attachments.push(Some(wgpu::RenderPassColorAttachment {
                    view: &self.hdr,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    },
                }));
            }
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("reflective and transmissive surfaces"),
                color_attachments: &attachments,
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.depth,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: timing_slot.map(|index| wgpu::RenderPassTimestampWrites {
                    query_set: &self.timing.as_ref().unwrap().slots[index].query,
                    beginning_of_pass_write_index: Some(6),
                    end_of_pass_write_index: Some(7),
                }),
                occlusion_query_set: None,
            });
            pass.set_pipeline(if self.shading_diagnostics_enabled {
                if self.optical_no_copy_enabled {
                    if self.geometry_instancing_enabled {
                        if self.optical_mask_required {
                            &self.pipelines.optical_overlay_diagnostic
                        } else {
                            &self.pipelines.optical_overlay_alpha_diagnostic
                        }
                    } else if self.optical_mask_required {
                        &self.pipelines.optical_overlay_baked_diagnostic
                    } else {
                        &self.pipelines.optical_overlay_alpha_baked_diagnostic
                    }
                } else if self.geometry_instancing_enabled {
                    &self.pipelines.optical_diagnostic
                } else {
                    &self.pipelines.optical_baked_diagnostic
                }
            } else if self.optical_no_copy_enabled {
                if self.geometry_instancing_enabled {
                    if self.optical_mask_required {
                        &self.pipelines.optical_overlay
                    } else {
                        &self.pipelines.optical_overlay_alpha
                    }
                } else {
                    if self.optical_mask_required {
                        &self.pipelines.optical_overlay_baked
                    } else {
                        &self.pipelines.optical_overlay_alpha_baked
                    }
                }
            } else if self.geometry_instancing_enabled {
                &self.pipelines.optical
            } else {
                &self.pipelines.optical_baked
            });
            pass.set_bind_group(0, &self.globals, &[]);
            pass.set_bind_group(1, &self.textures, &[]);
            pass.set_bind_group(2, &self.optical_group, &[]);
            pass.set_bind_group(3, &self.optical_smoke_groups[self.smoke_index], &[]);
            let vertex_buffer = if self.geometry_instancing_enabled {
                &self.vertex
            } else {
                self.unshared_vertex_buffer
                    .as_ref()
                    .expect("baked reference buffer is allocated when instancing is disabled")
            };
            pass.set_vertex_buffer(0, vertex_buffer.slice(..));
            let instance_buffer = &self.instance_buffers[7];
            for batch in camera_draws.batches.iter().filter(|batch| batch.optical) {
                if self.geometry_instancing_enabled {
                    let offset =
                        u64::from(batch.first_instance) * std::mem::size_of::<InstanceGpu>() as u64;
                    pass.set_vertex_buffer(1, instance_buffer.slice(offset..));
                }
                pass.draw(
                    batch.first_vertex..batch.first_vertex + batch.vertex_count,
                    0..batch.instance_count,
                );
            }
        }
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("pixel treatment"),
                color_attachments: &[clear_attachment(&self.pixels)],
                depth_stencil_attachment: None,
                timestamp_writes: timing_slot.map(|index| wgpu::RenderPassTimestampWrites {
                    query_set: &self.timing.as_ref().unwrap().slots[index].query,
                    beginning_of_pass_write_index: Some(8),
                    end_of_pass_write_index: Some(9),
                }),
                occlusion_query_set: None,
            });
            pass.set_pipeline(
                if self.optical_no_copy_enabled && optical_active && !self.optical_mask_required {
                    &self.pipelines.post_alpha
                } else {
                    &self.pipelines.post
                },
            );
            pass.set_bind_group(0, &self.globals, &[]);
            let post_group = if self.optical_no_copy_enabled && optical_active {
                &self.optical_post_groups.as_ref().unwrap()[self.smoke_index]
            } else {
                &self.post_groups[self.smoke_index]
            };
            pass.set_bind_group(1, post_group, &[]);
            pass.draw(0..3, 0..1);
        }
        if let Some(index) = timing_slot {
            let slot = &self.timing.as_ref().unwrap().slots[index];
            encoder.resolve_query_set(&slot.query, 0..GPU_QUERY_COUNT, &slot.resolve, 0);
            encoder.copy_buffer_to_buffer(&slot.resolve, 0, &slot.read, 0, GPU_QUERY_BYTES);
        }
        let command_buffer = encoder.finish();
        let submit_started = Instant::now();
        self.queue.submit([command_buffer]);
        let submit_ms = submit_started.elapsed().as_secs_f64() * 1000.;
        if absorption_cache_build {
            self.absorption_cache_dirty = false;
        }
        if let Some(index) = tile_stats_slot {
            let slot = &mut self.tile_stats_readbacks[index];
            let (sender, receiver) = mpsc::channel();
            slot.read
                .slice(..)
                .map_async(wgpu::MapMode::Read, move |result| {
                    let _ = sender.send(result);
                });
            slot.pending = Some(receiver);
            slot.frame = self.metrics.frame + 1;
        }
        if let Some(index) = timing_slot {
            let slot = &mut self.timing.as_mut().unwrap().slots[index];
            let (sender, receiver) = mpsc::channel();
            slot.read
                .slice(..)
                .map_async(wgpu::MapMode::Read, move |r| {
                    let _ = sender.send(r);
                });
            slot.frame = self.metrics.frame + 1;
            slot.optical = optical_active;
            slot.shadow_rendered = shadow_redrawn;
            slot.absorption_cache = absorption_cache_build;
            slot.submitted_at = Some(Instant::now());
            slot.pending = Some(receiver);
        }
        self.metrics.cpu_encode_ms = (started.elapsed().as_secs_f64() * 1000. - submit_ms).max(0.);
        self.metrics.cpu_queue_submit_ms += submit_ms;
        self.metrics.frame += 1;
    }

    fn poll_tile_stats(&mut self) {
        for slot in &mut self.tile_stats_readbacks {
            let Some(receiver) = &slot.pending else {
                continue;
            };
            match receiver.try_recv() {
                Ok(Ok(())) => {
                    let view = slot.read.slice(..).get_mapped_range();
                    let values: &[u32] = bytemuck::cast_slice(&view);
                    self.metrics.tile_candidates.copy_from_slice(&values[0..4]);
                    self.metrics
                        .tile_overflow_tiles
                        .copy_from_slice(&values[4..8]);
                    self.metrics
                        .tile_max_occupancy
                        .copy_from_slice(&values[8..12]);
                    self.metrics.tile_stats_frame = Some(slot.frame);
                    drop(view);
                    slot.read.unmap();
                    slot.pending = None;
                }
                Ok(Err(_)) | Err(mpsc::TryRecvError::Disconnected) => {
                    self.metrics.tile_stats_samples_skipped += 1;
                    slot.pending = None;
                }
                Err(mpsc::TryRecvError::Empty) => {}
            }
        }
    }

    pub fn capture(&mut self, path: &Path, scale: u32) -> Result<()> {
        let [w, h] = self.resolution;
        let row = (w * 4).div_ceil(256) * 256;
        let buffer = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("capture"),
            size: (row * h) as u64,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let mut encoder = self.device.create_command_encoder(&Default::default());
        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &self.pixel_texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &buffer,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(row),
                    rows_per_image: Some(h),
                },
            },
            wgpu::Extent3d {
                width: w,
                height: h,
                depth_or_array_layers: 1,
            },
        );
        self.queue.submit([encoder.finish()]);
        let (send, receive) = mpsc::channel();
        buffer
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |result| {
                let _ = send.send(result);
            });
        self.device.poll(wgpu::Maintain::Wait);
        receive.recv()??;
        if self.shading_diagnostics_enabled {
            self.read_shading_counters()?;
        }
        self.poll_tile_stats();
        let mapped = buffer.slice(..).get_mapped_range();
        let mut rgba = Vec::with_capacity((w * h * 4) as usize);
        for line in mapped.chunks_exact(row as usize) {
            rgba.extend_from_slice(&line[..(w * 4) as usize]);
        }
        let img = image::RgbaImage::from_raw(w, h, rgba).context("capture dimensions")?;
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent)?;
        }
        image::imageops::resize(
            &img,
            w * scale,
            h * scale,
            image::imageops::FilterType::Nearest,
        )
        .save(path)?;
        drop(mapped);
        buffer.unmap();
        Ok(())
    }

    pub fn capabilities(&self) -> serde_json::Value {
        let info = self.adapter.get_info();
        serde_json::json!({
            "name": info.name,
            "backend": format!("{:?}", info.backend),
            "device_type": format!("{:?}", info.device_type),
            "gpu_timestamps": self.timing.is_some(),
            "resolution": self.resolution,
            "smoke_grid": VOLUME,
            "vertices": self.vertex_count,
            "object_draw_range_count": self.object_draws.iter().filter(|object| object.vertex_count > 0).count(),
            "shared_mesh_count": self.mesh_draws.len(),
            "geometry_instancing": {
                "enabled": self.geometry_instancing_enabled,
                "instances": self.object_draws.len(),
                "unique_meshes": self.mesh_draws.len(),
                "unshared_vertex_count": self.object_draws.iter().map(|object| object.vertex_count as u64).sum::<u64>(),
                "shared_vertex_count": self.vertex_count
            },
            "geometry_culling": {"enabled": self.geometry_culling_enabled},
            "bounded_object_count": self.object_draws.iter().filter(|object| object.bounds.is_some()).count(),
            "tile_lists": {
                "enabled": self.tile_lists_enabled,
                "force_overflow": self.tile_force_overflow,
                "tile_count": self.tile_count,
                "tile_size": TILE_SIZE,
                "list_bytes": self.resource_inventory["tile_list_bytes"],
                "capacities": {
                    "fire_primitives": FIRE_TILE_CAPACITY,
                    "smoke_lobes": SMOKE_TILE_CAPACITY,
                    "point_lights": POINT_TILE_CAPACITY,
                    "particle_lights": PARTICLE_TILE_CAPACITY
                }
            },
            "max_fire_primitives": MAX_FIRE_PRIMITIVES,
            "max_point_lights": 8,
            "max_particle_lights": MAX_PARTICLE_LIGHTS,
            "smoke_lights_per_sample": 2,
            "max_materials": 256,
            "reflection_ray_steps": 16,
            "reflection_refinement_steps": 4,
            "transmission_layers": 1,
            "shadow_cache": {
                "enabled": !self.force_shadow_redraw,
                "force_redraw": self.force_shadow_redraw,
                "whole_map_count": 7,
                "resident_bytes": self.resource_inventory["shadow_maps_bytes"]
            },
            "resource_inventory": self.resource_inventory
        })
    }

    /// Stable per-object vertex ranges and conservative world-space bounds.
    pub fn object_draw_ranges(&self) -> &[assets::ObjectDrawRange] {
        &self.object_draws
    }
}

pub fn instance() -> wgpu::Instance {
    wgpu::Instance::new(&wgpu::InstanceDescriptor {
        backends: platform::backends(),
        ..Default::default()
    })
}

pub struct Presenter {
    pipeline: wgpu::RenderPipeline,
    group: wgpu::BindGroup,
    dimensions: wgpu::Buffer,
}
impl Presenter {
    pub fn new(renderer: &Renderer, format: wgpu::TextureFormat) -> Self {
        let d = &renderer.device;
        let layout = d.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("presentation"),
            entries: &[
                binding(
                    0,
                    wgpu::ShaderStages::FRAGMENT,
                    sampled(
                        wgpu::TextureViewDimension::D2,
                        wgpu::TextureSampleType::Float { filterable: true },
                    ),
                ),
                binding(
                    1,
                    wgpu::ShaderStages::FRAGMENT,
                    wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                ),
                binding(
                    2,
                    wgpu::ShaderStages::FRAGMENT,
                    wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                ),
            ],
        });
        let sampler = d.create_sampler(&Default::default());
        let dimensions = d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("presentation dimensions"),
            contents: bytemuck::cast_slice(&[1.0f32; 4]),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        let group = group(
            d,
            &layout,
            &[
                wgpu::BindingResource::TextureView(&renderer.pixels),
                wgpu::BindingResource::Sampler(&sampler),
                dimensions.as_entire_binding(),
            ],
        );
        let shader = shader(
            d,
            "presentation",
            include_str!("shaders/present.wgsl").into(),
        );
        let pipeline_layout = d.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[&layout],
            push_constant_ranges: &[],
        });
        let pipeline = d.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("integer presentation"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs"),
                buffers: &[],
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs"),
                targets: &[color_target(format, None)],
                compilation_options: Default::default(),
            }),
            primitive: Default::default(),
            depth_stencil: None,
            multisample: Default::default(),
            multiview: None,
            cache: None,
        });
        Self {
            pipeline,
            group,
            dimensions,
        }
    }
    pub fn draw(
        &self,
        encoder: &mut wgpu::CommandEncoder,
        target: &wgpu::TextureView,
        output: [u32; 2],
        scene: [u32; 2],
        queue: &wgpu::Queue,
        timestamps: Option<&wgpu::QuerySet>,
    ) {
        queue.write_buffer(
            &self.dimensions,
            0,
            bytemuck::cast_slice(&[
                output[0] as f32,
                output[1] as f32,
                scene[0] as f32,
                scene[1] as f32,
            ]),
        );
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("presentation"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: target,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            timestamp_writes: timestamps.map(|query_set| wgpu::RenderPassTimestampWrites {
                query_set,
                beginning_of_pass_write_index: Some(0),
                end_of_pass_write_index: Some(1),
            }),
            occlusion_query_set: None,
        });
        if output.contains(&0) {
            return;
        }
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, &self.group, &[]);
        pass.draw(0..3, 0..1);
    }
}

fn clear_attachment(view: &wgpu::TextureView) -> Option<wgpu::RenderPassColorAttachment<'_>> {
    Some(wgpu::RenderPassColorAttachment {
        view,
        resolve_target: None,
        ops: wgpu::Operations {
            load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
            store: wgpu::StoreOp::Store,
        },
    })
}

#[cfg(test)]
mod shadow_cache_tests {
    use super::*;

    fn rg16_features(
        allowed_usages: wgpu::TextureUsages,
        flags: wgpu::TextureFormatFeatureFlags,
    ) -> wgpu::TextureFormatFeatures {
        wgpu::TextureFormatFeatures {
            allowed_usages,
            flags,
        }
    }

    #[test]
    fn rg16_layout_selection_requires_each_usage_and_feature() {
        let effect_supported = rg16_features(
            wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
            wgpu::TextureFormatFeatureFlags::FILTERABLE,
        );
        assert_eq!(
            super::select_effect_depth_format(effect_supported),
            wgpu::TextureFormat::Rg16Float
        );
        assert_eq!(
            super::select_effect_depth_format(rg16_features(
                wgpu::TextureUsages::TEXTURE_BINDING,
                wgpu::TextureFormatFeatureFlags::FILTERABLE,
            )),
            super::HDR
        );

        let smoke_supported = rg16_features(
            wgpu::TextureUsages::STORAGE_BINDING | wgpu::TextureUsages::TEXTURE_BINDING,
            wgpu::TextureFormatFeatureFlags::FILTERABLE
                | wgpu::TextureFormatFeatureFlags::STORAGE_WRITE_ONLY,
        );
        assert_eq!(
            super::select_smoke_volume_format(smoke_supported, true),
            wgpu::TextureFormat::Rg16Float
        );
        assert_eq!(
            super::select_smoke_volume_format(smoke_supported, false),
            super::HDR
        );
        assert_eq!(
            super::select_smoke_volume_format(
                rg16_features(
                    wgpu::TextureUsages::STORAGE_BINDING | wgpu::TextureUsages::TEXTURE_BINDING,
                    wgpu::TextureFormatFeatureFlags::FILTERABLE,
                ),
                true,
            ),
            super::HDR
        );
    }

    #[test]
    fn perspective_frustum_rejects_behind_and_side_bounds_but_keeps_intersections() {
        let projection = Mat4::perspective_rh(60_f32.to_radians(), 1., 0.1, 100.);
        let frustum = Frustum::from_view_projection(projection).unwrap();
        let bounds = |min, max| assets::Bounds3 { min, max };
        assert!(frustum.intersects(&bounds([-0.5, -0.5, -5.5], [0.5, 0.5, -4.5])));
        assert!(!frustum.intersects(&bounds([-0.5, -0.5, 2.], [0.5, 0.5, 3.])));
        assert!(!frustum.intersects(&bounds([50., -0.5, -5.5], [51., 0.5, -4.5])));
        assert!(frustum.intersects(&bounds([0.4, -0.2, -5.5], [1.2, 0.2, -4.5])));
    }

    #[test]
    fn orthographic_frustum_and_invalid_bounds_are_conservative() {
        let projection = Mat4::orthographic_rh(-2., 2., -1., 1., 0.1, 20.);
        let frustum = Frustum::from_view_projection(projection).unwrap();
        let bounds = |min, max| assets::Bounds3 { min, max };
        assert!(frustum.intersects(&bounds([-0.5, -0.5, -5.5], [0.5, 0.5, -4.5])));
        assert!(!frustum.intersects(&bounds([4., -0.5, -5.5], [5., 0.5, -4.5])));
        assert!(frustum.intersects(&bounds([f32::NAN, 0., 0.], [1., 1., 1.])));
        assert!(frustum.intersects(&bounds([2., 0., 0.], [1., 1., 1.])));
        assert!(Frustum::from_view_projection(Mat4::ZERO).is_none());
    }

    #[test]
    fn shadow_bounds_mark_only_intersecting_cube_face_and_unknown_bounds_fallback() {
        let directions = [
            Vec3::X,
            Vec3::NEG_X,
            Vec3::Y,
            Vec3::NEG_Y,
            Vec3::Z,
            Vec3::NEG_Z,
        ];
        let matrices = std::array::from_fn(|index| {
            if index == 0 {
                Mat4::IDENTITY
            } else {
                let direction = directions[index - 1];
                let up = if direction == Vec3::Y || direction == Vec3::NEG_Y {
                    Vec3::Z
                } else {
                    Vec3::Y
                };
                Mat4::perspective_rh(90_f32.to_radians(), 1., 0.1, 20.)
                    * Mat4::look_at_rh(Vec3::ZERO, direction, up)
            }
        });
        let positive_x = assets::Bounds3 {
            min: [2.8, -0.2, -0.2],
            max: [3.2, 0.2, 0.2],
        };
        let dirty = shadow_face_mask_for_bounds(&[Some(positive_x.clone())], &matrices);
        assert_eq!(dirty, [false, true, false, false, false, false, false]);
        assert_eq!(shadow_face_mask_for_bounds(&[None], &matrices), [true; 7]);
        assert_eq!(
            shadow_face_mask_for_bounds(&[Some(positive_x.clone()), None], &matrices),
            [true; 7]
        );
        assert!(shadow_bounds_require_full_fallback(
            &[Some(positive_x.clone()), None],
            &matrices
        ));
        let invalid_matrices = [Mat4::ZERO; 7];
        assert_eq!(
            shadow_face_mask_for_bounds(&[Some(positive_x.clone())], &invalid_matrices),
            [true; 7]
        );
        assert!(shadow_bounds_require_full_fallback(
            &[Some(positive_x)],
            &invalid_matrices
        ));
    }

    fn scene() -> Scene {
        Scene::load(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../assets/scenes/clearing.json")
                .as_path(),
        )
        .unwrap()
    }

    #[test]
    fn shadow_cache_key_tracks_casters_shadow_materials_and_projection() {
        let baseline = scene();
        let key = shadow_cache_key(&baseline).unwrap();
        assert_eq!(shadow_dirty_reason(None, &key), "resource_initialization");
        assert_eq!(shadow_dirty_reason(Some(&key), &key), "unchanged");

        let mut edited = scene();
        edited.objects[0].position[0] += 1.;
        assert_eq!(
            shadow_dirty_reason(Some(&key), &shadow_cache_key(&edited).unwrap()),
            "casters_changed"
        );

        let mut edited = scene();
        edited.materials[0].transmission = 0.5;
        assert_eq!(
            shadow_dirty_reason(Some(&key), &shadow_cache_key(&edited).unwrap()),
            "shadow_materials_changed"
        );

        let mut edited = scene();
        let sun = edited
            .lights
            .iter_mut()
            .find(|light| light.kind == LightKind::Directional)
            .unwrap();
        sun.position[0] += 1.;
        assert_eq!(
            shadow_dirty_reason(Some(&key), &shadow_cache_key(&edited).unwrap()),
            "directional_light_projection_changed"
        );

        let mut edited = scene();
        let fire = edited
            .lights
            .iter_mut()
            .find(|light| light.kind == LightKind::Point)
            .unwrap();
        fire.range += 1.;
        assert_eq!(
            shadow_dirty_reason(Some(&key), &shadow_cache_key(&edited).unwrap()),
            "point_light_range_changed"
        );

        let mut edited = scene();
        let fire = edited
            .lights
            .iter_mut()
            .find(|light| light.kind == LightKind::Point)
            .unwrap();
        fire.position[0] += 1.;
        edited.emitters[0].position[0] += 1.;
        assert_eq!(
            shadow_dirty_reason(Some(&key), &shadow_cache_key(&edited).unwrap()),
            "point_light_projection_changed"
        );
    }

    #[test]
    fn light_power_and_material_color_do_not_invalidate_shadow_geometry() {
        let key = shadow_cache_key(&scene()).unwrap();
        let mut edited = scene();
        edited.materials[0].color[0] += 0.1;
        for light in &mut edited.lights {
            light.intensity += 0.1;
            light.color[1] += 0.1;
        }
        assert_eq!(
            shadow_dirty_reason(Some(&key), &shadow_cache_key(&edited).unwrap()),
            "unchanged"
        );
    }
}
