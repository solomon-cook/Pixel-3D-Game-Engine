use crate::scene::{Geometry, Scene};
use anyhow::{bail, Context, Result};
use bytemuck::{Pod, Zeroable};
use glam::{EulerRot, Mat3, Mat4, Quat, Vec2, Vec3};
use image::RgbaImage;
use std::{collections::HashMap, path::Path};

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct Vertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub color: [f32; 3],
    pub uv: [f32; 2],
    pub texture: f32,
    pub emission: f32,
    pub roughness: f32,
    pub material: u32,
}

pub struct MeshData {
    pub vertices: Vec<Vertex>,
    /// World-baked reference stream used for exact culling/instancing comparisons.
    pub baked_vertices: Vec<Vertex>,
    pub textures: Vec<RgbaImage>,
    pub object_draws: Vec<ObjectDrawRange>,
    pub mesh_draws: Vec<MeshDrawRange>,
}

/// Conservative bounds over the emitted world-space vertices for one scene object.
#[derive(Clone, Debug, PartialEq)]
pub struct Bounds3 {
    pub min: [f32; 3],
    pub max: [f32; 3],
}

/// Stable, shared non-indexed vertex range for one geometry/material key.
#[derive(Clone, Debug, PartialEq)]
pub struct MeshDrawRange {
    pub key: String,
    pub material_id: String,
    pub first_vertex: u32,
    pub vertex_count: u32,
}

/// One scene instance referring to a shared mesh range.
#[derive(Clone, Debug, PartialEq)]
pub struct ObjectDrawRange {
    pub object_id: String,
    pub material_id: String,
    pub mesh_index: usize,
    pub first_vertex: u32,
    pub vertex_count: u32,
    pub baked_first_vertex: u32,
    /// Local-to-world transform in column-major order.
    pub transform: [[f32; 4]; 4],
    /// `None` means the range is empty or contains non-finite positions and must not be culled.
    pub bounds: Option<Bounds3>,
}

impl Bounds3 {
    fn from_vertices(vertices: &[Vertex], transform: Mat4) -> Option<Self> {
        let first = vertices.first()?;
        let first = transform.transform_point3(Vec3::from(first.position));
        if !first.is_finite() {
            return None;
        }
        let (min, max) = vertices
            .iter()
            .skip(1)
            .try_fold((first, first), |(min, max), v| {
                let p = transform.transform_point3(Vec3::from(v.position));
                p.is_finite().then(|| (min.min(p), max.max(p)))
            })?;
        Some(Self {
            min: min.to_array(),
            max: max.to_array(),
        })
    }

    pub fn contains(&self, point: [f32; 3]) -> bool {
        (0..3).all(|axis| point[axis] >= self.min[axis] && point[axis] <= self.max[axis])
    }
}

struct Builder {
    vertices: Vec<Vertex>,
    transform: Mat4,
    normal: Mat3,
    color: [f32; 3],
    texture: f32,
    emission: f32,
    roughness: f32,
    material: u32,
    trunk_material: u32,
}
impl Builder {
    fn vertex(&mut self, p: Vec3, n: Vec3, uv: Vec2) {
        self.vertices.push(Vertex {
            position: self.transform.transform_point3(p).into(),
            normal: (self.normal * n).normalize_or_zero().into(),
            color: self.color,
            uv: uv.into(),
            texture: self.texture,
            emission: self.emission,
            roughness: self.roughness,
            material: self.material,
        });
    }
    fn tri(&mut self, a: Vec3, b: Vec3, c: Vec3) {
        let n = (b - a).cross(c - a).normalize();
        self.vertex(a, n, Vec2::new(a.x, a.z));
        self.vertex(b, n, Vec2::new(b.x, b.z));
        self.vertex(c, n, Vec2::new(c.x, c.z));
    }
    fn cube(&mut self) {
        for (n, u, v) in [
            (Vec3::X, Vec3::NEG_Z, Vec3::Y),
            (Vec3::NEG_X, Vec3::Z, Vec3::Y),
            (Vec3::Y, Vec3::X, Vec3::NEG_Z),
            (Vec3::NEG_Y, Vec3::X, Vec3::Z),
            (Vec3::Z, Vec3::X, Vec3::Y),
            (Vec3::NEG_Z, Vec3::NEG_X, Vec3::Y),
        ] {
            let a = (n - u - v) * 0.5;
            let b = (n + u - v) * 0.5;
            let c = (n + u + v) * 0.5;
            let d = (n - u + v) * 0.5;
            for (p, uv) in [
                (a, [0., 0.]),
                (b, [1., 0.]),
                (c, [1., 1.]),
                (a, [0., 0.]),
                (c, [1., 1.]),
                (d, [0., 1.]),
            ] {
                self.vertex(p, n, uv.into());
            }
        }
    }
    fn pine(&mut self, seed: u32) {
        let transform = self.transform;
        let normal = self.normal;
        let original_color = self.color;
        self.transform = transform * Mat4::from_scale(Vec3::new(0.055, 0.98, 0.055));
        self.normal = Mat3::from_mat4(self.transform).inverse().transpose();
        let material = self.material;
        self.material = self.trunk_material;
        self.color = [0.16, 0.075, 0.045];
        self.round(false, false);
        self.material = material;
        self.transform = transform;
        self.normal = normal;
        for tier in 0..7 {
            let height = 0.19 + tier as f32 * 0.105;
            for branch in 0..7 {
                let phase =
                    branch as f32 / 7. * std::f32::consts::TAU + tier as f32 * 0.71 + seed as f32;
                let direction = Vec3::new(phase.cos(), 0., phase.sin());
                let side = Vec3::new(-phase.sin(), 0., phase.cos());
                let radius = (1. - height) * 0.64 * (0.86 + 0.14 * (phase * 13.).sin());
                let root = Vec3::new(0., height, 0.);
                let tip = root + direction * radius - Vec3::Y * 0.035;
                self.color = original_color.map(|c| c * (0.72 + tier as f32 * 0.065));
                // Branch strip plus offset, tapered needle fans. All are real
                // world-space triangles, so the silhouette works from any view.
                self.tri(
                    root - side * 0.012,
                    tip + Vec3::Y * 0.012,
                    root + side * 0.012,
                );
                for twig in 0..5 {
                    let t = 0.12 + twig as f32 * 0.17;
                    let center = root.lerp(tip, t);
                    let width = radius * (1. - t) * 0.36;
                    let end = center + direction * radius * 0.3 + Vec3::Y * 0.015;
                    self.tri(
                        center - side * width - Vec3::Y * 0.025,
                        end,
                        center + Vec3::Y * 0.025,
                    );
                    self.tri(
                        center + Vec3::Y * 0.025,
                        end,
                        center + side * width - Vec3::Y * 0.025,
                    );
                }
            }
        }
        self.transform = transform
            * Mat4::from_scale_rotation_translation(
                Vec3::new(0.17, 0.28, 0.17),
                Quat::IDENTITY,
                Vec3::new(0., 0.78, 0.),
            );
        self.normal = Mat3::from_mat4(self.transform).inverse().transpose();
        self.color = original_color.map(|c| c * 1.1);
        self.round(true, false);
        self.transform = transform;
        self.normal = normal;
        self.color = original_color;
    }
    fn smooth_sphere(&mut self) {
        for j in 0..16 {
            for i in 0..32 {
                let point = |x: u32, y: u32| {
                    let a = x as f32 / 32. * std::f32::consts::TAU;
                    let b = y as f32 / 16. * std::f32::consts::PI;
                    Vec3::new(a.cos() * b.sin(), b.cos(), a.sin() * b.sin()) * 0.5
                };
                let a = point(i, j);
                let b = point(i + 1, j);
                let c = point(i + 1, j + 1);
                let d = point(i, j + 1);
                for [a, b, c] in [[a, b, c], [a, c, d]] {
                    if (b - a).cross(c - a).length_squared() > 1e-10 {
                        for p in [a, b, c] {
                            self.vertex(p, p.normalize(), Vec2::new(p.x, p.z));
                        }
                    }
                }
            }
        }
    }
    fn round(&mut self, cone: bool, sphere: bool) {
        let segments = if sphere { 12 } else { 10 };
        let rings = if sphere { 6 } else { 1 };
        for j in 0..rings {
            for i in 0..segments {
                let point = |s: u32, r: u32| {
                    let angle = s as f32 / segments as f32 * std::f32::consts::TAU;
                    if sphere {
                        let lat = r as f32 / rings as f32 * std::f32::consts::PI;
                        Vec3::new(angle.cos() * lat.sin(), lat.cos(), angle.sin() * lat.sin()) * 0.5
                    } else {
                        let radius = if cone && r == 1 { 0. } else { 0.5 };
                        Vec3::new(angle.cos() * radius, r as f32, angle.sin() * radius)
                    }
                };
                let a = point(i, j);
                let b = point(i + 1, j);
                let c = point(i + 1, j + 1);
                let d = point(i, j + 1);
                if (c - a).cross(b - a).length_squared() > 1e-10 {
                    if sphere {
                        self.tri(a, b, c);
                    } else {
                        self.tri(a, c, b);
                    }
                }
                if (d - a).cross(c - a).length_squared() > 1e-10 {
                    if sphere {
                        self.tri(a, c, d);
                    } else {
                        self.tri(a, d, c);
                    }
                }
                if !sphere {
                    self.tri(Vec3::ZERO, b, a);
                    if !cone {
                        self.tri(Vec3::Y, d, c);
                    }
                }
            }
        }
    }
}

pub fn terrain_height(x: f32, z: f32) -> f32 {
    let r = (x * x + z * z).sqrt();
    ((x * 0.43).sin() * (z * 0.31).cos() * 0.7 + (x * 0.13 + z * 0.19).sin() * 0.5)
        * (r / 6.).clamp(0., 1.)
        - 0.2
}

pub fn load(scene: &Scene, base: &Path) -> Result<MeshData> {
    let mut textures = vec![RgbaImage::from_pixel(1, 1, image::Rgba([255; 4]))];
    let mut slots = HashMap::new();
    for m in &scene.materials {
        if let Some(p) = &m.texture {
            let img = image::open(base.join(p))
                .with_context(|| format!("material '{}'.texture: {p}", m.id))?
                .into_rgba8();
            slots.insert(m.id.clone(), textures.len() as f32);
            textures.push(img);
        }
    }
    let mut builder = Builder {
        vertices: vec![],
        transform: Mat4::IDENTITY,
        normal: Mat3::IDENTITY,
        color: [1.; 3],
        texture: 0.,
        emission: 0.,
        roughness: 1.,
        material: 0,
        trunk_material: scene.materials.len() as u32,
    };
    let mut object_draws = Vec::with_capacity(scene.objects.len());
    let mut mesh_draws = Vec::new();
    let mut mesh_by_key = HashMap::<String, usize>::new();
    let mut baked_vertices = Vec::new();
    for o in &scene.objects {
        let m = scene
            .materials
            .iter()
            .find(|m| m.id == o.material)
            .context("validated material missing")?;
        let object_transform = Mat4::from_scale_rotation_translation(
            o.scale.into(),
            Quat::from_euler(EulerRot::XYZ, o.rotation[0], o.rotation[1], o.rotation[2]),
            o.position.into(),
        );
        let key = format!("{}|{}", serde_json::to_string(&o.geometry)?, o.material);
        let mesh_index = if let Some(&mesh_index) = mesh_by_key.get(&key) {
            mesh_index
        } else {
            builder.transform = Mat4::IDENTITY;
            builder.normal = Mat3::IDENTITY;
            builder.color = [1.; 3];
            builder.emission = 1.;
            builder.roughness = 1.;
            builder.material = scene.materials.iter().position(|x| x.id == m.id).unwrap() as u32;
            builder.texture = *slots.get(&m.id).unwrap_or(&0.);
            let first_vertex = builder.vertices.len();
            match &o.geometry {
                Geometry::Cube => builder.cube(),
                Geometry::Sphere => builder.round(false, true),
                Geometry::SmoothSphere => builder.smooth_sphere(),
                Geometry::Cylinder => builder.round(false, false),
                Geometry::Cone => builder.round(true, false),
                Geometry::Pine { seed } => builder.pine(*seed),
                Geometry::Terrain { size, subdivisions } => {
                    for z in 0..*subdivisions {
                        for x in 0..*subdivisions {
                            let p = |x: u32, z: u32| {
                                let x = x as f32 / *subdivisions as f32 * size - size / 2.;
                                let z = z as f32 / *subdivisions as f32 * size - size / 2.;
                                Vec3::new(x, terrain_height(x, z), z)
                            };
                            let a = p(x, z);
                            let b = p(x + 1, z);
                            let c = p(x + 1, z + 1);
                            let d = p(x, z + 1);
                            let variation = 0.91 + 0.09 * ((x * 73 + z * 137) % 17) as f32 / 16.;
                            builder.color = [variation; 3];
                            builder.tri(a, c, b);
                            builder.tri(a, d, c);
                        }
                    }
                }
                Geometry::Glb { path } => {
                    let (doc, buffers, images) = gltf::import(base.join(path))
                        .with_context(|| format!("object '{}'.geometry.path: {path}", o.id))?;
                    let first_texture = textures.len();
                    for img in &images {
                        let mut rgba = Vec::with_capacity((img.width * img.height * 4) as usize);
                        use gltf::image::Format;
                        let channels = match img.format {
                            Format::R8 => 1,
                            Format::R8G8 => 2,
                            Format::R8G8B8 => 3,
                            Format::R8G8B8A8 => 4,
                            _ => bail!("object '{}': GLB texture must use 8-bit channels", o.id),
                        };
                        for px in img.pixels.chunks_exact(channels) {
                            match channels {
                                1 => rgba.extend([px[0], px[0], px[0], 255]),
                                2 => rgba.extend([px[0], px[0], px[0], px[1]]),
                                3 => rgba.extend([px[0], px[1], px[2], 255]),
                                _ => rgba.extend_from_slice(px),
                            }
                        }
                        textures.push(
                            RgbaImage::from_raw(img.width, img.height, rgba)
                                .context("GLB image dimensions")?,
                        );
                    }
                    fn visit(
                        node: gltf::Node<'_>,
                        parent: Mat4,
                        b: &mut Builder,
                        buffers: &[gltf::buffer::Data],
                        first: usize,
                    ) -> Result<()> {
                        let world = parent * Mat4::from_cols_array_2d(&node.transform().matrix());
                        if node.skin().is_some() {
                            bail!("GLB: skinned meshes are outside the static geometry contract");
                        }
                        if let Some(mesh) = node.mesh() {
                            for primitive in mesh.primitives() {
                                if primitive.material().alpha_mode()
                                    != gltf::material::AlphaMode::Opaque
                                {
                                    bail!("GLB: only opaque materials are supported");
                                }
                                if primitive.mode() != gltf::mesh::Mode::Triangles {
                                    bail!("GLB: only triangle primitives are supported");
                                }
                                let reader = primitive.reader(|buf| Some(&buffers[buf.index()]));
                                let positions: Vec<[f32; 3]> = reader
                                    .read_positions()
                                    .context("GLB mesh missing positions")?
                                    .collect();
                                let normals: Option<Vec<[f32; 3]>> =
                                    reader.read_normals().map(Iterator::collect);
                                let uvs: Option<Vec<[f32; 2]>> =
                                    reader.read_tex_coords(0).map(|x| x.into_f32().collect());
                                let indices: Vec<u32> = reader
                                    .read_indices()
                                    .map(|x| x.into_u32().collect())
                                    .unwrap_or_else(|| (0..positions.len() as u32).collect());
                                let original = (
                                    b.transform,
                                    b.normal,
                                    b.color,
                                    b.texture,
                                    b.roughness,
                                    b.emission,
                                );
                                b.transform = world;
                                b.normal = Mat3::from_mat4(world).inverse().transpose();
                                let pbr = primitive.material().pbr_metallic_roughness();
                                let factor = pbr.base_color_factor();
                                b.color = [
                                    original.2[0] * factor[0],
                                    original.2[1] * factor[1],
                                    original.2[2] * factor[2],
                                ];
                                b.roughness = pbr.roughness_factor();
                                if let Some(tex) = pbr.base_color_texture() {
                                    b.texture = (first + tex.texture().source().index()) as f32;
                                }
                                for tri in indices.as_chunks::<3>().0 {
                                    let a = Vec3::from(positions[tri[0] as usize]);
                                    let c = Vec3::from(positions[tri[1] as usize]);
                                    let d = Vec3::from(positions[tri[2] as usize]);
                                    let n = (c - a).cross(d - a).normalize_or_zero();
                                    for &index in tri {
                                        let i = index as usize;
                                        b.vertex(
                                            positions[i].into(),
                                            normals.as_ref().map(|v| Vec3::from(v[i])).unwrap_or(n),
                                            uvs.as_ref()
                                                .map(|v| Vec2::from(v[i]))
                                                .unwrap_or(Vec2::ZERO),
                                        );
                                    }
                                }
                                (
                                    b.transform,
                                    b.normal,
                                    b.color,
                                    b.texture,
                                    b.roughness,
                                    b.emission,
                                ) = original;
                            }
                        }
                        for child in node.children() {
                            visit(child, world, b, buffers, first)?;
                        }
                        Ok(())
                    }
                    let root = doc
                        .default_scene()
                        .or_else(|| doc.scenes().next())
                        .context("GLB missing scene")?;
                    let parent = Mat4::IDENTITY;
                    for node in root.nodes() {
                        visit(node, parent, &mut builder, &buffers, first_texture)?;
                    }
                }
            }
            let vertex_count = builder.vertices.len() - first_vertex;
            let first_vertex =
                u32::try_from(first_vertex).context("objects: vertex range overflow")?;
            let vertex_count =
                u32::try_from(vertex_count).context("objects: vertex range overflow")?;
            let mesh_index = mesh_draws.len();
            mesh_draws.push(MeshDrawRange {
                key: key.clone(),
                material_id: o.material.clone(),
                first_vertex,
                vertex_count,
            });
            mesh_by_key.insert(key, mesh_index);
            mesh_index
        };
        let mesh = &mesh_draws[mesh_index];
        let first_vertex = mesh.first_vertex;
        let vertex_count = mesh.vertex_count;
        let end = first_vertex as usize + vertex_count as usize;
        let baked_first_vertex =
            u32::try_from(baked_vertices.len()).context("objects: baked vertex range overflow")?;
        let object_normal = Mat3::from_mat4(object_transform).inverse().transpose();
        for vertex in &builder.vertices[first_vertex as usize..end] {
            let mut baked = *vertex;
            baked.position = object_transform
                .transform_point3(Vec3::from(vertex.position))
                .to_array();
            baked.normal = (object_normal * Vec3::from(vertex.normal))
                .normalize_or_zero()
                .to_array();
            baked_vertices.push(baked);
        }
        object_draws.push(ObjectDrawRange {
            object_id: o.id.clone(),
            material_id: o.material.clone(),
            mesh_index,
            first_vertex,
            vertex_count,
            baked_first_vertex,
            transform: object_transform.to_cols_array_2d(),
            bounds: Bounds3::from_vertices(
                &builder.vertices[first_vertex as usize..end],
                object_transform,
            ),
        });
    }
    if builder.vertices.is_empty() {
        bail!("objects: scene must contain renderable geometry");
    }
    Ok(MeshData {
        vertices: builder.vertices,
        baked_vertices,
        textures,
        object_draws,
        mesh_draws,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn round_mesh_normals_face_outward() {
        let mut b = Builder {
            vertices: vec![],
            transform: Mat4::IDENTITY,
            normal: Mat3::IDENTITY,
            color: [1.; 3],
            texture: 0.,
            emission: 0.,
            roughness: 1.,
            material: 0,
            trunk_material: 0,
        };
        b.smooth_sphere();
        for v in &b.vertices {
            let p = Vec3::from(v.position);
            let n = Vec3::from(v.normal);
            assert!(p.dot(n) > 0.49 && (n.length() - 1.).abs() < 0.0001);
        }
        b.vertices.clear();
        b.round(false, true);
        for v in &b.vertices {
            assert!(
                Vec3::from(v.position).dot(v.normal.into()) > 0.1,
                "sphere normal faces inward"
            );
        }
        b.vertices.clear();
        b.round(false, false);
        for v in &b.vertices {
            let radial = Vec3::new(v.position[0], 0., v.position[2]);
            let n = Vec3::from(v.normal);
            if n.y.abs() < 0.9 {
                assert!(radial.dot(n) > 0.1, "cylinder side normal faces inward");
            }
        }
    }
    #[test]
    fn imports_static_glb_and_png_texture() {
        let root = std::env::temp_dir().join(format!(
            "pixel-assets-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let positions: [f32; 9] = [-1., 0., 0., 1., 0., 0., 0., 1., 0.];
        let mut doc=serde_json::to_vec(&serde_json::json!({"asset":{"version":"2.0"},"buffers":[{"byteLength":36}],"bufferViews":[{"buffer":0,"byteLength":36}],"accessors":[{"bufferView":0,"componentType":5126,"count":3,"type":"VEC3","min":[-1,0,0],"max":[1,1,0]}],"meshes":[{"primitives":[{"attributes":{"POSITION":0}}]}],"nodes":[{"mesh":0}],"scenes":[{"nodes":[0]}],"scene":0})).unwrap();
        while !doc.len().is_multiple_of(4) {
            doc.push(b' ');
        }
        let mut glb = vec![];
        for n in [
            0x46546c67u32,
            2,
            (12 + 8 + doc.len() + 8 + 36) as u32,
            doc.len() as u32,
            0x4e4f534a,
        ] {
            glb.extend_from_slice(&n.to_le_bytes());
        }
        glb.extend(doc);
        for n in [36u32, 0x004e4942] {
            glb.extend_from_slice(&n.to_le_bytes());
        }
        for v in positions {
            glb.extend_from_slice(&v.to_le_bytes());
        }
        std::fs::write(root.join("triangle.glb"), glb).unwrap();
        RgbaImage::from_pixel(2, 2, image::Rgba([180, 220, 110, 255]))
            .save(root.join("moss.png"))
            .unwrap();
        let mut scene = Scene::load(
            &Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/scenes/clearing.json"),
        )
        .unwrap();
        scene.objects.truncate(1);
        scene.objects[0].geometry = Geometry::Glb {
            path: "triangle.glb".into(),
        };
        scene.objects[0].position = [0.; 3];
        scene.materials[0].texture = Some("moss.png".into());
        scene.validate(&root).unwrap();
        let mesh = load(&scene, &root).unwrap();
        assert_eq!(mesh.vertices.len(), 3);
        assert_eq!(mesh.textures.len(), 2);
        assert_eq!(mesh.object_draws.len(), 1);
        let draw = &mesh.object_draws[0];
        assert_eq!(draw.object_id, scene.objects[0].id);
        assert_eq!(draw.material_id, scene.objects[0].material);
        assert_eq!(draw.mesh_index, 0);
        assert_eq!((draw.first_vertex, draw.vertex_count), (0, 3));
        assert_eq!(draw.baked_first_vertex, 0);
        let bounds = draw.bounds.as_ref().unwrap();
        assert_eq!(bounds.min, [-1., 0., 0.]);
        assert_eq!(bounds.max, [1., 1., 0.]);
        assert!(mesh
            .vertices
            .iter()
            .all(|v| v.normal.iter().all(|n| n.is_finite())));
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn shared_mesh_instances_have_stable_ranges_and_transformed_bounds() {
        let scene_path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/scenes/clearing.json");
        let mut scene = Scene::load(&scene_path).unwrap();
        scene.objects[0].scale = [1.7, 0.55, 1.2];
        scene.objects[0].rotation = [0.17, 0.31, -0.09];
        scene.validate(scene_path.parent().unwrap()).unwrap();
        let mesh = load(&scene, scene_path.parent().unwrap()).unwrap();
        assert_eq!(mesh.object_draws.len(), scene.objects.len());
        assert!(mesh.mesh_draws.len() < mesh.object_draws.len());
        let mut next_vertex = 0usize;
        for draw in &mesh.mesh_draws {
            assert_eq!(draw.first_vertex as usize, next_vertex);
            next_vertex += draw.vertex_count as usize;
        }
        assert_eq!(next_vertex, mesh.vertices.len());
        assert_eq!(
            mesh.baked_vertices.len(),
            mesh.object_draws
                .iter()
                .map(|object| object.vertex_count as usize)
                .sum::<usize>()
        );
        for (object, draw) in scene.objects.iter().zip(&mesh.object_draws) {
            assert_eq!(draw.object_id, object.id);
            assert_eq!(draw.material_id, object.material);
            let shared = &mesh.mesh_draws[draw.mesh_index];
            assert_eq!(
                (draw.first_vertex, draw.vertex_count),
                (shared.first_vertex, shared.vertex_count)
            );
            let start = shared.first_vertex as usize;
            let end = start + shared.vertex_count as usize;
            assert!(end <= mesh.vertices.len());
            let bounds = draw.bounds.as_ref().expect("finite scene object bounds");
            let transform = Mat4::from_cols_array_2d(&draw.transform);
            assert!(mesh.vertices[start..end].iter().all(|vertex| {
                bounds.contains(
                    transform
                        .transform_point3(Vec3::from(vertex.position))
                        .to_array(),
                )
            }));
        }
    }
}
