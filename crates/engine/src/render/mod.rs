use crate::{
    assets::{self, Vertex},
    diagnostics::FrameMetrics,
    effects::{FireFrame, FireKey, MAX_FIRE_PRIMITIVES, MAX_PARTICLE_LIGHTS},
    platform,
    scene::{Camera, LightKind, Material, Scene},
    simulation,
};
use anyhow::{anyhow, Context, Result};
use bytemuck::{Pod, Zeroable};
use glam::{Mat4, Vec3};
use std::{
    path::{Path, PathBuf},
    sync::mpsc,
    time::Instant,
};
use wgpu::util::DeviceExt;

pub const PIXEL_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8UnormSrgb;
const HDR: wgpu::TextureFormat = wgpu::TextureFormat::Rgba16Float;
const DEPTH: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;
const VOLUME: [u32; 3] = [48, 64, 48];

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
            optical: [m.ior, m.thickness, m.subsurface, 0.],
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
    fire_shape: [f32; 4],
    fire_pixels: [f32; 4],
    light_info: [u32; 4],
    point_lights: [PointLightGpu; 8],
}

struct Pipelines {
    mesh: wgpu::RenderPipeline,
    optical: wgpu::RenderPipeline,
    volume: wgpu::RenderPipeline,
    post: wgpu::RenderPipeline,
    shadow: wgpu::RenderPipeline,
    shadow_opaque: wgpu::RenderPipeline,
    smoke: wgpu::ComputePipeline,
}
struct Timing {
    query: wgpu::QuerySet,
    resolve: wgpu::Buffer,
    read: wgpu::Buffer,
    pending: Option<mpsc::Receiver<std::result::Result<(), wgpu::BufferAsyncError>>>,
}

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
    fire_key: Option<FireKey>,
    fire_frame: FireFrame,
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
    hdr_texture: wgpu::Texture,
    normals_texture: wgpu::Texture,
    scene_color: wgpu::Texture,
    scene_normals: wgpu::Texture,
    volume_groups: [wgpu::BindGroup; 2],
    volume_layout: wgpu::BindGroupLayout,
    smoke_groups: [wgpu::BindGroup; 2],
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
    smoke_textures: [wgpu::Texture; 2],
    smoke_index: usize,
    vertex: wgpu::Buffer,
    vertex_count: u32,
    pipelines: Pipelines,
    timing: Option<Timing>,
    pub shader_directory: PathBuf,
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
fn vertex_layout() -> wgpu::VertexBufferLayout<'static> {
    wgpu::VertexBufferLayout {
        array_stride: std::mem::size_of::<Vertex>() as u64,
        step_mode: wgpu::VertexStepMode::Vertex,
        attributes: &ATTRIBUTES,
    }
}

impl Renderer {
    pub async fn new(
        instance: &wgpu::Instance,
        surface: Option<&wgpu::Surface<'_>>,
        scene: &Scene,
        base: &Path,
        shader_directory: PathBuf,
    ) -> Result<Self> {
        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                compatible_surface: surface,
                force_fallback_adapter: false,
            })
            .await
            .context("no compatible desktop GPU adapter")?;
        let timestamp = adapter.features().contains(wgpu::Features::TIMESTAMP_QUERY);
        let (device, queue) = adapter
            .request_device(
                &wgpu::DeviceDescriptor {
                    label: Some("Pixel Engine"),
                    required_features: if timestamp {
                        wgpu::Features::TIMESTAMP_QUERY
                    } else {
                        wgpu::Features::empty()
                    },
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
                    wgpu::ShaderStages::FRAGMENT,
                    wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                ),
            ],
        });
        let fire_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("bounded fire primitives"),
            contents: bytemuck::bytes_of(&FireFrame::zeroed()),
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
            &[uniform.as_entire_binding(), fire_buffer.as_entire_binding()],
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
        let use_color =
            wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING;
        let hdr_texture = texture(
            &device,
            "HDR",
            [w, h, 1],
            HDR,
            use_color | wgpu::TextureUsages::COPY_SRC,
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
        let smoke_textures = std::array::from_fn(|_| {
            texture(
                &device,
                "smoke density/temperature",
                VOLUME,
                HDR,
                wgpu::TextureUsages::TEXTURE_BINDING
                    | wgpu::TextureUsages::STORAGE_BINDING
                    | wgpu::TextureUsages::COPY_DST,
                wgpu::TextureDimension::D3,
            )
        });
        let smoke_views = smoke_textures
            .each_ref()
            .map(|t| t.create_view(&Default::default()));
        let linear = device.create_sampler(&wgpu::SamplerDescriptor {
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        let snapshot_usage = wgpu::TextureUsages::COPY_DST | wgpu::TextureUsages::TEXTURE_BINDING;
        let scene_color = texture(
            &device,
            "opaque + atmosphere snapshot",
            [w, h, 1],
            HDR,
            snapshot_usage,
            wgpu::TextureDimension::D2,
        );
        let scene_normals = texture(
            &device,
            "opaque normal/depth snapshot",
            [w, h, 1],
            HDR,
            snapshot_usage,
            wgpu::TextureDimension::D2,
        );
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
                wgpu::BindingResource::TextureView(&scene_color.create_view(&Default::default())),
                wgpu::BindingResource::TextureView(&scene_normals.create_view(&Default::default())),
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
            ],
        });
        let volume_groups = std::array::from_fn(|i| {
            group(
                &device,
                &volume_layout,
                &[
                    wgpu::BindingResource::TextureView(&depth),
                    wgpu::BindingResource::TextureView(&smoke_views[i]),
                    wgpu::BindingResource::Sampler(&linear),
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
                ],
            });
        let optical_smoke_groups = std::array::from_fn(|i| {
            device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("optical foreground atmosphere"),
                layout: &optical_smoke_layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::TextureView(&smoke_views[i]),
                    },
                    wgpu::BindGroupEntry {
                        binding: 2,
                        resource: wgpu::BindingResource::Sampler(&linear),
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
                        format: HDR,
                        view_dimension: wgpu::TextureViewDimension::D3,
                    },
                ),
                binding(
                    2,
                    wgpu::ShaderStages::COMPUTE,
                    wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                ),
            ],
        });
        let smoke_groups = std::array::from_fn(|i| {
            group(
                &device,
                &smoke_layout,
                &[
                    wgpu::BindingResource::TextureView(&smoke_views[i]),
                    wgpu::BindingResource::TextureView(&smoke_views[1 - i]),
                    wgpu::BindingResource::Sampler(&linear),
                ],
            )
        });
        let effect_depth = texture(
            &device,
            "visible atmosphere depth and flame mask",
            [w, h, 1],
            HDR,
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
                    wgpu::BindingResource::TextureView(&smoke_views[i]),
                    wgpu::BindingResource::Sampler(&linear),
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
        let pipelines = Self::pipelines(
            &device,
            &global_layout,
            &texture_layout,
            &optical_layout,
            &optical_smoke_layout,
            &volume_layout,
            &smoke_layout,
            &post_layout,
            &shadow_layout,
            &shadow_material_layout,
            &shader_directory,
        )?;
        let timing = timestamp.then(|| Timing {
            query: device.create_query_set(&wgpu::QuerySetDescriptor {
                label: Some("frame timestamps"),
                ty: wgpu::QueryType::Timestamp,
                count: 2,
            }),
            resolve: device.create_buffer(&wgpu::BufferDescriptor {
                label: None,
                size: 16,
                usage: wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
                mapped_at_creation: false,
            }),
            read: device.create_buffer(&wgpu::BufferDescriptor {
                label: None,
                size: 16,
                usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            }),
            pending: None,
        });
        let mut renderer = Self {
            device,
            queue,
            adapter,
            pixels,
            pixel_texture,
            resolution: scene.render.resolution,
            metrics: FrameMetrics {
                gpu_timestamp_supported: timestamp,
                ..Default::default()
            },
            uniform,
            fire_buffer,
            fire_key: None,
            fire_frame: FireFrame::zeroed(),
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
            hdr_texture,
            normals_texture,
            scene_color,
            scene_normals,
            volume_groups,
            volume_layout,
            smoke_groups,
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
            vertex_count: mesh.vertices.len() as u32,
            pipelines,
            timing,
            shader_directory,
        };
        renderer.reset_smoke();
        renderer.update_globals(scene, &scene.cameras[0], 0, 42);
        Ok(renderer)
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
        post: &wgpu::BindGroupLayout,
        shadow: &wgpu::BindGroupLayout,
        shadow_materials: &wgpu::BindGroupLayout,
        dir: &Path,
    ) -> Result<Pipelines> {
        let read = |name: &str| {
            std::fs::read_to_string(dir.join(name))
                .with_context(|| format!("shader {}", dir.join(name).display()))
        };
        let common = read("common.wgsl")?;
        let world = format!("{}\n{}", read("materials.wgsl")?, read("world.wgsl")?);
        let optical_source = read("optical.wgsl")?;
        let volume_source = read("volume.wgsl")?;
        let fire_source = read("fire.wgsl")?;
        let post_source = read("post.wgsl")?;
        let smoke_source = read("smoke.wgsl")?;
        let shadow_source = format!("{}\n{}", read("materials.wgsl")?, read("shadow.wgsl")?);
        device.push_error_scope(wgpu::ErrorFilter::Validation);
        let mesh_module = shader(device, "world", format!("{common}\n{world}"));
        let optical_module = shader(
            device,
            "optical surfaces",
            format!(
                "{common}\n{world}\n{fire_source}\n{}\n{optical_source}",
                volume_source.replace("@group(2)", "@group(3)")
            ),
        );
        let volume_module = shader(
            device,
            "volumetrics",
            format!("{common}\n{world}\n{fire_source}\n{}", volume_source),
        );
        let post_module = shader(
            device,
            "pixel treatment",
            format!("{common}\n{}", post_source),
        );
        let smoke_module = shader(
            device,
            "smoke advection",
            format!("{common}\n{}", smoke_source),
        );
        let shadow_module = shader(device, "shadow", shadow_source);
        let layout = |groups: &[&wgpu::BindGroupLayout]| {
            device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                label: None,
                bind_group_layouts: groups,
                push_constant_ranges: &[],
            })
        };
        let mesh_layout = layout(&[global, textures]);
        let volume_layout = layout(&[global, textures, volumes]);
        let optical_layout = layout(&[global, textures, optical, optical_smoke]);
        let post_layout = layout(&[global, post]);
        let smoke_layout = layout(&[global, smoke]);
        let shadow_layout = layout(&[shadow, shadow_materials]);
        let vertex_buffers = [vertex_layout()];
        let render = |label: &str,
                      module: &wgpu::ShaderModule,
                      layout: &wgpu::PipelineLayout,
                      vs: &str,
                      fs: Option<&str>,
                      targets: &[Option<wgpu::ColorTargetState>],
                      depth: bool,
                      vertices: bool| {
            device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: Some(label),
                layout: Some(layout),
                vertex: wgpu::VertexState {
                    module,
                    entry_point: Some(vs),
                    compilation_options: Default::default(),
                    buffers: if vertices { &vertex_buffers } else { &[] },
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
                        constant: if label == "shadow" { 2 } else { 0 },
                        slope_scale: if label == "shadow" { 2. } else { 0. },
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
            &[color_target(HDR, None), color_target(HDR, None)],
            true,
            true,
        );
        let optical = render(
            "optical surfaces",
            &optical_module,
            &optical_layout,
            "optical_vs",
            Some("optical_fs"),
            &[color_target(HDR, None), color_target(HDR, None)],
            true,
            true,
        );
        let volume = render(
            "volumetrics",
            &volume_module,
            &volume_layout,
            "fullscreen",
            Some("volume_fs"),
            &[
                color_target(HDR, Some(wgpu::BlendState::PREMULTIPLIED_ALPHA_BLENDING)),
                color_target(HDR, None),
            ],
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
        );
        let smoke = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("advection"),
            layout: Some(&smoke_layout),
            module: &smoke_module,
            entry_point: Some("advect"),
            compilation_options: Default::default(),
            cache: None,
        });
        if let Some(error) = pollster::block_on(device.pop_error_scope()) {
            return Err(anyhow!(error.to_string()));
        }
        Ok(Pipelines {
            mesh,
            optical,
            volume,
            post,
            shadow,
            shadow_opaque,
            smoke,
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
            &self.post_layout,
            &self.shadow_layout,
            &self.shadow_material_layout,
            &self.shader_directory,
        )?;
        self.pipelines = replacement;
        Ok(())
    }

    pub fn update_globals(&mut self, scene: &Scene, camera: &Camera, tick: u64, seed: u32) {
        let sun = scene
            .lights
            .iter()
            .find(|l| l.kind == LightKind::Directional)
            .unwrap();
        let fire = scene
            .lights
            .iter()
            .find(|l| l.kind == LightKind::Point && l.position == scene.emitters[0].position)
            .unwrap();
        let emitter = &scene.emitters[0];
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
        self.queue.write_buffer(
            &self.shadow_buffers[0],
            0,
            bytemuck::cast_slice(&sun_matrix.to_cols_array()),
        );
        let fire_position = Vec3::from(fire.position);
        for (i, (direction, up)) in [
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
            let m = Mat4::perspective_rh(std::f32::consts::FRAC_PI_2, 1., 0.05, fire.range)
                * Mat4::look_at_rh(fire_position, fire_position + direction, up);
            self.queue.write_buffer(
                &self.shadow_buffers[i + 1],
                0,
                bytemuck::cast_slice(&m.to_cols_array()),
            );
        }
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
        if self.fire_key.as_ref() != Some(&key) {
            let started = Instant::now();
            self.fire_frame = FireFrame::sample(&key);
            self.queue
                .write_buffer(&self.fire_buffer, 0, bytemuck::bytes_of(&self.fire_frame));
            self.fire_key = Some(key);
            self.metrics.effect_update_cpu_ms = started.elapsed().as_secs_f64() * 1000.;
            self.metrics.fire_primitives = self.fire_frame.counts[0];
            self.metrics.flame_fragments = self.fire_frame.counts[2];
            self.metrics.embers = self.fire_frame.counts[3];
            self.metrics.effect_events_dropped = self.fire_frame.bounds_max[3] as u32;
            self.metrics.particle_lights = self.fire_frame.lighting[0];
            self.metrics.particle_lights_dropped = self.fire_frame.lighting[1];
            self.metrics.branch_segments_dropped = self.fire_frame.lighting[2];
        }
        let power = self.fire_frame.bounds_min[3];
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
                0.,
            ],
        };
        self.queue
            .write_buffer(&self.uniform, 0, bytemuck::bytes_of(&g));
    }

    pub fn effect_state(&self) -> serde_json::Value {
        serde_json::json!({"counts":self.fire_frame.counts,"bounds_min":self.fire_frame.bounds_min,
            "bounds_max":self.fire_frame.bounds_max,"lighting":self.fire_frame.lighting,
            "particle_lights":&self.fire_frame.lights[..self.fire_frame.lighting[0] as usize]})
    }
    pub fn reset_smoke(&mut self) {
        let bytes = vec![0u8; (VOLUME[0] * VOLUME[1] * VOLUME[2] * 8) as usize];
        for t in &self.smoke_textures {
            self.queue.write_texture(
                wgpu::TexelCopyTextureInfo {
                    texture: t,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                &bytes,
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(VOLUME[0] * 8),
                    rows_per_image: Some(VOLUME[1]),
                },
                wgpu::Extent3d {
                    width: VOLUME[0],
                    height: VOLUME[1],
                    depth_or_array_layers: VOLUME[2],
                },
            );
        }
        self.smoke_index = 0;
    }
    pub fn simulate(&mut self, scene: &Scene, camera: &Camera, tick: u64, seed: u32) {
        self.update_globals(scene, camera, tick, seed);
        let mut encoder = self.device.create_command_encoder(&Default::default());
        {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("smoke simulation"),
                timestamp_writes: None,
            });
            pass.set_pipeline(&self.pipelines.smoke);
            pass.set_bind_group(0, &self.globals, &[]);
            pass.set_bind_group(1, &self.smoke_groups[self.smoke_index], &[]);
            pass.dispatch_workgroups(VOLUME[0] / 4, VOLUME[1] / 4, VOLUME[2] / 4);
        }
        self.queue.submit([encoder.finish()]);
        self.smoke_index = 1 - self.smoke_index;
    }

    pub fn poll_timing(&mut self, wait: bool) {
        self.device.poll(if wait {
            wgpu::Maintain::Wait
        } else {
            wgpu::Maintain::Poll
        });
        if let Some(t) = &mut self.timing {
            if let Some(receiver) = &t.pending {
                if let Ok(result) = receiver.try_recv() {
                    if result.is_ok() {
                        let view = t.read.slice(..).get_mapped_range();
                        let numbers: &[u64] = bytemuck::cast_slice(&view);
                        self.metrics.gpu_ms = Some(
                            numbers[1].saturating_sub(numbers[0]) as f64
                                * self.queue.get_timestamp_period() as f64
                                / 1_000_000.,
                        );
                        drop(view);
                        t.read.unmap();
                    }
                    t.pending = None;
                }
            }
        }
    }

    pub fn render(&mut self, scene: &Scene, camera: &Camera, tick: u64, seed: u32) {
        self.poll_timing(false);
        let started = Instant::now();
        if self.material_cache != scene.materials {
            self.queue.write_buffer(
                &self.material_buffer,
                0,
                bytemuck::cast_slice(&material_table(scene)),
            );
            self.material_cache.clone_from(&scene.materials);
        }
        self.update_globals(scene, camera, tick, seed);
        let timed = self.timing.as_ref().is_some_and(|t| t.pending.is_none());
        let mut encoder = self.device.create_command_encoder(&Default::default());
        for i in 0..7 {
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
                timestamp_writes: if i == 0 && timed {
                    Some(wgpu::RenderPassTimestampWrites {
                        query_set: &self.timing.as_ref().unwrap().query,
                        beginning_of_pass_write_index: Some(0),
                        end_of_pass_write_index: None,
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
            pass.set_pipeline(if transparent_shadows {
                &self.pipelines.shadow
            } else {
                &self.pipelines.shadow_opaque
            });
            pass.set_bind_group(0, &self.shadow_groups[i], &[]);
            pass.set_bind_group(1, &self.shadow_materials, &[]);
            pass.set_vertex_buffer(0, self.vertex.slice(..));
            pass.draw(0..self.vertex_count, 0..1);
        }

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
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            pass.set_pipeline(&self.pipelines.mesh);
            pass.set_bind_group(0, &self.globals, &[]);
            pass.set_bind_group(1, &self.textures, &[]);
            pass.set_vertex_buffer(0, self.vertex.slice(..));
            pass.draw(0..self.vertex_count, 0..1);
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
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            pass.set_pipeline(&self.pipelines.volume);
            pass.set_bind_group(0, &self.globals, &[]);
            pass.set_bind_group(1, &self.textures, &[]);
            pass.set_bind_group(2, &self.volume_groups[self.smoke_index], &[]);
            pass.draw(0..3, 0..1);
        }
        // Skip the copies and extra draw entirely for existing diffuse scenes.
        let optical_active = scene
            .materials
            .iter()
            .any(|m| m.metallic > 0. || m.reflectivity > 0. || m.transmission > 0.);
        if optical_active {
            for (source, target) in [
                (&self.hdr_texture, &self.scene_color),
                (&self.normals_texture, &self.scene_normals),
            ] {
                encoder.copy_texture_to_texture(
                    source.as_image_copy(),
                    target.as_image_copy(),
                    wgpu::Extent3d {
                        width: self.resolution[0],
                        height: self.resolution[1],
                        depth_or_array_layers: 1,
                    },
                );
            }
            let attachment = |view| {
                Some(wgpu::RenderPassColorAttachment {
                    view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    },
                })
            };
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("reflective and transmissive surfaces"),
                color_attachments: &[attachment(&self.hdr), attachment(&self.normals)],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.depth,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            pass.set_pipeline(&self.pipelines.optical);
            pass.set_bind_group(0, &self.globals, &[]);
            pass.set_bind_group(1, &self.textures, &[]);
            pass.set_bind_group(2, &self.optical_group, &[]);
            pass.set_bind_group(3, &self.optical_smoke_groups[self.smoke_index], &[]);
            pass.set_vertex_buffer(0, self.vertex.slice(..));
            pass.draw(0..self.vertex_count, 0..1);
        }
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("pixel treatment"),
                color_attachments: &[clear_attachment(&self.pixels)],
                depth_stencil_attachment: None,
                timestamp_writes: if timed {
                    Some(wgpu::RenderPassTimestampWrites {
                        query_set: &self.timing.as_ref().unwrap().query,
                        beginning_of_pass_write_index: None,
                        end_of_pass_write_index: Some(1),
                    })
                } else {
                    None
                },
                occlusion_query_set: None,
            });
            pass.set_pipeline(&self.pipelines.post);
            pass.set_bind_group(0, &self.globals, &[]);
            pass.set_bind_group(1, &self.post_groups[self.smoke_index], &[]);
            pass.draw(0..3, 0..1);
        }
        if timed {
            let t = self.timing.as_ref().unwrap();
            encoder.resolve_query_set(&t.query, 0..2, &t.resolve, 0);
            encoder.copy_buffer_to_buffer(&t.resolve, 0, &t.read, 0, 16);
        }
        self.queue.submit([encoder.finish()]);
        if timed {
            let t = self.timing.as_mut().unwrap();
            let (sender, receiver) = mpsc::channel();
            t.read.slice(..).map_async(wgpu::MapMode::Read, move |r| {
                let _ = sender.send(r);
            });
            t.pending = Some(receiver);
        }
        self.metrics.cpu_encode_ms = started.elapsed().as_secs_f64() * 1000.;
        self.metrics.frame += 1;
    }

    pub fn capture(&self, path: &Path, scale: u32) -> Result<()> {
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
        serde_json::json!({"name":info.name,"backend":format!("{:?}",info.backend),"device_type":format!("{:?}",info.device_type),"gpu_timestamps":self.timing.is_some(),"resolution":self.resolution,"smoke_grid":VOLUME,"vertices":self.vertex_count,"max_fire_primitives":MAX_FIRE_PRIMITIVES,"max_point_lights":8,"max_particle_lights":MAX_PARTICLE_LIGHTS,"smoke_lights_per_sample":2,"max_materials":256,"reflection_ray_steps":16,"reflection_refinement_steps":4,"transmission_layers":1})
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
            timestamp_writes: None,
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
