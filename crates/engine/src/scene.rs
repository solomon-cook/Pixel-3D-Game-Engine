use crate::effects::{self, EffectProfile};
use anyhow::{bail, Context, Result};
use glam::{Mat4, Vec3};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::{collections::HashSet, path::Path};

#[derive(Clone, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Scene {
    pub version: u32,
    pub name: String,
    pub render: RenderSettings,
    pub environment: Environment,
    pub materials: Vec<Material>,
    pub objects: Vec<Object>,
    pub lights: Vec<Light>,
    pub emitters: Vec<Emitter>,
    #[serde(default = "effects::default_profiles")]
    pub effects: Vec<EffectProfile>,
    pub cameras: Vec<Camera>,
    pub routes: Vec<Route>,
}

#[derive(Clone, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct RenderSettings {
    pub resolution: [u32; 2],
    /// Experimental 32-bit packed HDR target for comparison; disabled by default.
    #[serde(default)]
    pub compact_hdr: bool,
    /// Experimental optical output plus coverage mask to avoid copying the HDR input; disabled by default.
    #[serde(default)]
    pub optical_no_copy: bool,
    pub exposure: f32,
    pub shading_steps: u32,
    pub dither_strength: f32,
    pub smoke_steps: u32,
    pub experiments: Experiments,
    #[serde(default = "palette_strength")]
    pub palette_strength: f32,
    #[serde(default)]
    pub bloom_strength: f32,
    /// Zero uses only the environment fallback. Never changes the pixel grid.
    #[serde(default = "reflection_steps")]
    pub reflection_steps: u32,
    /// Coarse smoke absorption cache dimension per axis; valid values are 8 or 16.
    #[serde(default = "absorption_cache_resolution")]
    pub absorption_cache_resolution: u32,
}

fn reflection_steps() -> u32 {
    16
}

fn absorption_cache_resolution() -> u32 {
    8
}

fn palette_strength() -> f32 {
    0.55
}

#[derive(Default, Clone, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Experiments {
    pub pixel_cluster_lighting: bool,
    pub stable_smoke_detail: bool,
    pub connected_motion: bool,
    #[serde(default)]
    pub projected_detail_lod: bool,
    #[serde(default)]
    pub smoke_absorption_cache: bool,
    /// Reuse the opaque surface result from the atmosphere-composited snapshot.
    #[serde(default)]
    pub optical_surface_reuse: bool,
}

#[derive(Clone, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Environment {
    pub sky_color: [f32; 3],
    pub horizon_color: [f32; 3],
    pub ambient: [f32; 3],
    pub wind: [f32; 3],
    pub fog_density: f32,
}

#[derive(Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Material {
    pub id: String,
    pub color: [f32; 3],
    #[serde(default)]
    pub emission: f32,
    #[serde(default = "roughness")]
    pub roughness: f32,
    #[serde(default)]
    pub texture: Option<String>,
    /// Conductor blend; base colour becomes the reflection tint.
    #[serde(default)]
    pub metallic: f32,
    /// Environment/screen reflection strength for dielectrics. Zero preserves the legacy look.
    #[serde(default)]
    pub reflectivity: f32,
    #[serde(default)]
    pub transmission: f32,
    #[serde(default = "material_ior")]
    pub ior: f32,
    /// Artist-authored optical thickness in world units, independent of mesh scale.
    #[serde(default = "material_thickness")]
    pub thickness: f32,
    /// Beer-Lambert extinction per world unit, linear RGB.
    #[serde(default)]
    pub absorption: [f32; 3],
    #[serde(default)]
    pub subsurface: f32,
    #[serde(default = "unit_scale")]
    pub scatter_color: [f32; 3],
    /// Visual response to the existing simulated temperature field (0 disables the cue).
    #[serde(default)]
    pub heat_response: f32,
}
fn material_ior() -> f32 {
    1.5
}
fn material_thickness() -> f32 {
    0.25
}
fn roughness() -> f32 {
    0.8
}

#[derive(Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Object {
    pub id: String,
    pub material: String,
    pub geometry: Geometry,
    pub position: [f32; 3],
    #[serde(default)]
    pub rotation: [f32; 3],
    #[serde(default = "unit_scale")]
    pub scale: [f32; 3],
}
fn unit_scale() -> [f32; 3] {
    [1.; 3]
}

#[derive(Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Geometry {
    Cube,
    Sphere,
    SmoothSphere,
    Cylinder,
    Cone,
    Pine { seed: u32 },
    Terrain { size: f32, subdivisions: u32 },
    Glb { path: String },
}

#[derive(Clone, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Light {
    pub id: String,
    pub kind: LightKind,
    pub position: [f32; 3],
    pub color: [f32; 3],
    pub intensity: f32,
    #[serde(default)]
    pub flicker: f32,
    #[serde(default = "light_range")]
    pub range: f32,
}
fn light_range() -> f32 {
    20.
}

#[derive(Clone, Serialize, Deserialize, JsonSchema, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum LightKind {
    Directional,
    Point,
}

#[derive(Clone, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Emitter {
    pub id: String,
    pub position: [f32; 3],
    pub intensity: f32,
    pub smoke_density: f32,
    pub buoyancy: f32,
    pub dissipation: f32,
    pub enabled: bool,
    #[serde(default)]
    pub style: EffectStyle,
    #[serde(default = "default_secondary_bubbles")]
    pub secondary_bubbles: u32,
    #[serde(default = "default_bubble_scale")]
    pub bubble_scale: f32,
    #[serde(default = "default_self_shadow_strength")]
    pub self_shadow_strength: f32,
    #[serde(default)]
    pub internal_glow: f32,
    #[serde(default = "effects::default_profile_id")]
    pub effect_profile: String,
}
fn default_secondary_bubbles() -> u32 {
    4
}
fn default_bubble_scale() -> f32 {
    0.25
}
fn default_self_shadow_strength() -> f32 {
    0.9
}

#[derive(Default, Clone, Serialize, Deserialize, JsonSchema, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum EffectStyle {
    #[default]
    Ink,
    Volume,
}

#[derive(Clone, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Camera {
    pub id: String,
    pub position: [f32; 3],
    pub target: [f32; 3],
    pub projection: Projection,
}
#[derive(Clone, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Projection {
    Perspective { fov_degrees: f32 },
    Orthographic { height: f32 },
}

impl Camera {
    pub fn matrix(&self, aspect: f32) -> Mat4 {
        let proj = match self.projection {
            Projection::Perspective { fov_degrees } => {
                Mat4::perspective_rh(fov_degrees.to_radians(), aspect, 0.1, 150.)
            }
            Projection::Orthographic { height } => Mat4::orthographic_rh(
                -height * aspect / 2.,
                height * aspect / 2.,
                -height / 2.,
                height / 2.,
                0.1,
                150.,
            ),
        };
        proj * Mat4::look_at_rh(self.position.into(), self.target.into(), Vec3::Y)
    }
}

#[derive(Clone, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Route {
    pub id: String,
    pub duration_seconds: f32,
    pub keyframes: Vec<RouteKeyframe>,
}
#[derive(Clone, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct RouteKeyframe {
    pub time: f32,
    pub position: [f32; 3],
    pub target: [f32; 3],
}

impl Route {
    pub fn camera_at(&self, seconds: f32, base: &Camera) -> Camera {
        let time = seconds.rem_euclid(self.duration_seconds);
        let i = self
            .keyframes
            .partition_point(|k| k.time <= time)
            .saturating_sub(1)
            .min(self.keyframes.len() - 2);
        let a = &self.keyframes[i];
        let b = &self.keyframes[i + 1];
        let t = ((time - a.time) / (b.time - a.time)).clamp(0., 1.);
        Camera {
            position: Vec3::from(a.position).lerp(b.position.into(), t).into(),
            target: Vec3::from(a.target).lerp(b.target.into(), t).into(),
            ..base.clone()
        }
    }
}

impl Scene {
    pub fn load(path: &Path) -> Result<Self> {
        let text =
            std::fs::read_to_string(path).with_context(|| format!("scene {}", path.display()))?;
        let scene: Self =
            serde_json::from_str(&text).context("scene JSON: invalid property or value")?;
        scene.validate(path.parent().unwrap_or(Path::new(".")))?;
        Ok(scene)
    }
    pub fn schema() -> serde_json::Value {
        serde_json::to_value(schemars::schema_for!(Scene)).expect("schema serialization")
    }
    pub fn validate(&self, base: &Path) -> Result<()> {
        let bounded =
            |values: &[f32], limit: f32| values.iter().all(|v| v.is_finite() && v.abs() <= limit);
        let color = |values: &[f32; 3]| bounded(values, 64.) && values.iter().all(|v| *v >= 0.);
        if !bounded(&self.environment.wind, 8.)
            || !color(&self.environment.ambient)
            || !color(&self.environment.sky_color)
            || !color(&self.environment.horizon_color)
        {
            bail!("environment: colors must be finite 0..64, wind components must be -8..8");
        }
        if self.version != 1 {
            bail!("version: expected 1, got {}", self.version);
        }
        let [w, h] = self.render.resolution;
        if !(64..=1920).contains(&w) || !(64..=1080).contains(&h) {
            bail!("render.resolution: expected 64..1920 by 64..1080");
        }
        if !(2..=32).contains(&self.render.shading_steps) {
            bail!("render.shading_steps: expected 2..32");
        }
        if !(8..=128).contains(&self.render.smoke_steps) {
            bail!("render.smoke_steps: expected 8..128");
        }
        if !(0.05..=8.).contains(&self.render.exposure) {
            bail!("render.exposure: expected 0.05..8");
        }
        if !(0.0..=1.).contains(&self.render.palette_strength)
            || !(0.0..=1.).contains(&self.render.bloom_strength)
        {
            bail!("render.palette_strength/bloom_strength: expected 0..1");
        }
        if !(0.0..=1.).contains(&self.render.dither_strength) {
            bail!("render.dither_strength: expected 0..1");
        }
        if !matches!(self.render.absorption_cache_resolution, 8 | 16) {
            bail!("render.absorption_cache_resolution: expected 8 or 16");
        }
        if !(0.0..=1.).contains(&self.environment.fog_density) {
            bail!("environment.fog_density: expected 0..1");
        }
        let mut ids = HashSet::new();
        for (kind, id) in self
            .materials
            .iter()
            .map(|x| ("material", &x.id))
            .chain(self.objects.iter().map(|x| ("object", &x.id)))
            .chain(self.lights.iter().map(|x| ("light", &x.id)))
            .chain(self.emitters.iter().map(|x| ("emitter", &x.id)))
            .chain(self.effects.iter().map(|x| ("effect", &x.id)))
            .chain(self.cameras.iter().map(|x| ("camera", &x.id)))
            .chain(self.routes.iter().map(|x| ("route", &x.id)))
        {
            if id.is_empty() || !ids.insert(id) {
                bail!("{kind} '{id}'.id: empty or duplicate stable ID");
            }
        }
        if self.render.reflection_steps > 16 {
            bail!("render.reflection_steps: expected 0..16");
        }
        if self.materials.is_empty() || self.materials.len() > 256 {
            bail!("materials: expected 1..256 entries");
        }
        for m in &self.materials {
            for (property, value, low, high) in [
                ("metallic", m.metallic, 0., 1.),
                ("reflectivity", m.reflectivity, 0., 1.),
                ("transmission", m.transmission, 0., 1.),
                ("ior", m.ior, 1., 2.5),
                ("thickness", m.thickness, 0., 10.),
                ("subsurface", m.subsurface, 0., 1.),
                ("heat_response", m.heat_response, 0., 1.),
            ] {
                if !value.is_finite() || !(low..=high).contains(&value) {
                    bail!("material '{}'.{property}: expected {low}..{high}", m.id);
                }
            }
            for (property, values) in [
                ("absorption", m.absorption),
                ("scatter_color", m.scatter_color),
            ] {
                if !color(&values) {
                    bail!(
                        "material '{}'.{property}: expected finite RGB in 0..64",
                        m.id
                    );
                }
            }
            if !(0.0..=1.).contains(&m.roughness)
                || !(0.0..=64.).contains(&m.emission)
                || !color(&m.color)
            {
                bail!("material '{}': invalid roughness/emission", m.id);
            }
            if let Some(p) = &m.texture {
                if !base.join(p).is_file() {
                    bail!("material '{}'.texture: missing {p}", m.id);
                }
            }
        }
        for o in &self.objects {
            if !bounded(&o.position, 1000.)
                || !bounded(&o.rotation, 1000.)
                || !bounded(&o.scale, 1000.)
            {
                bail!(
                    "object '{}': position/rotation/scale must be finite and bounded by 1000",
                    o.id
                );
            }
            if !self.materials.iter().any(|m| m.id == o.material) {
                bail!("object '{}'.material: unknown '{}'", o.id, o.material);
            }
            if o.scale.iter().any(|s| *s <= 0.) {
                bail!("object '{}'.scale: expected positive values", o.id);
            }
            if let Geometry::Glb { path } = &o.geometry {
                if !base.join(path).is_file() {
                    bail!("object '{}'.geometry.path: missing {path}", o.id);
                }
            }
            if let Geometry::Terrain { size, subdivisions } = o.geometry {
                if !(0.1..=1000.).contains(&size) || !(1..=256).contains(&subdivisions) {
                    bail!(
                        "object '{}'.geometry: invalid terrain size/subdivisions",
                        o.id
                    );
                }
            }
        }
        if self.cameras.is_empty() {
            bail!("cameras: at least one camera is required");
        }
        for c in &self.cameras {
            validate_camera(c)?;
        }
        if self
            .lights
            .iter()
            .filter(|l| l.kind == LightKind::Directional)
            .count()
            != 1
            || !(1..=8).contains(
                &self
                    .lights
                    .iter()
                    .filter(|l| l.kind == LightKind::Point)
                    .count(),
            )
        {
            bail!("lights: requires one directional light and 1..8 point lights");
        }
        if self.emitters.len() != 1 {
            bail!("emitters: v1 requires exactly one bounded fire/smoke emitter");
        }
        for effect in &self.effects {
            effect.validate()?;
        }
        for e in &self.emitters {
            if !self.effects.iter().any(|p| p.id == e.effect_profile) {
                bail!(
                    "emitter '{}'.effect_profile: unknown effect '{}'",
                    e.id,
                    e.effect_profile
                );
            }
            if !(0.0..=4.).contains(&e.self_shadow_strength)
                || !(0.0..=4.).contains(&e.internal_glow)
            {
                bail!(
                    "emitter '{}': self_shadow_strength/internal_glow must be 0..4",
                    e.id
                );
            }
            if e.secondary_bubbles > 8 || !(0.1..=0.5).contains(&e.bubble_scale) {
                bail!(
                    "emitter '{}': secondary_bubbles must be 0..8 and bubble_scale 0.1..0.5",
                    e.id
                );
            }
            if !(0.0..=16.).contains(&e.intensity)
                || !(0.0..=64.).contains(&e.smoke_density)
                || !bounded(&e.position, 1000.)
                || !(0.0..=10.).contains(&e.buoyancy)
                || !(0.0..=10.).contains(&e.dissipation)
            {
                bail!(
                    "emitter '{}': invalid intensity/density/buoyancy/dissipation",
                    e.id
                );
            }
        }
        for l in &self.lights {
            if !(0.0..=1000.).contains(&l.intensity)
                || !(0.0..=1.).contains(&l.flicker)
                || !color(&l.color)
                || !bounded(&l.position, 1000.)
            {
                bail!("light '{}': invalid intensity/flicker", l.id);
            }
            if !(0.1..=128.).contains(&l.range) {
                bail!("light '{}'.range: expected finite 0.1..128", l.id);
            }
            if l.kind == LightKind::Directional && Vec3::from(l.position).length() < 0.001 {
                bail!(
                    "light '{}'.position: directional vector cannot be zero",
                    l.id
                );
            }
        }
        if !self
            .lights
            .iter()
            .any(|l| l.kind == LightKind::Point && l.position == self.emitters[0].position)
        {
            bail!(
                "emitter '{}'.position: one point light must coincide with the fire source",
                self.emitters[0].id
            );
        }
        for r in &self.routes {
            if !r.duration_seconds.is_finite() || r.duration_seconds <= 0. || r.keyframes.len() < 2
            {
                bail!(
                    "route '{}': positive duration and at least two keyframes required",
                    r.id
                );
            }
            if r.keyframes[0].time != 0.
                || (r.keyframes.last().unwrap().time - r.duration_seconds).abs() > 0.001
                || r.keyframes.windows(2).any(|w| w[0].time >= w[1].time)
            {
                bail!(
                    "route '{}'.keyframes: times must increase from 0 to duration_seconds",
                    r.id
                );
            }
            for k in &r.keyframes {
                if !k.time.is_finite() {
                    bail!("route '{}'.keyframes.time: expected finite time", r.id);
                }
                validate_camera(&Camera {
                    id: r.id.clone(),
                    position: k.position,
                    target: k.target,
                    projection: Projection::Perspective { fov_degrees: 60. },
                })?;
            }
        }
        Ok(())
    }
}

pub fn validate_camera(c: &Camera) -> Result<()> {
    if c.position
        .iter()
        .chain(c.target.iter())
        .any(|v| !v.is_finite() || v.abs() > 1000.)
    {
        bail!(
            "camera '{}': position and target must be finite and bounded by 1000",
            c.id
        );
    }
    let v = Vec3::from(c.target) - Vec3::from(c.position);
    if v.length() < 0.001 || v.normalize().dot(Vec3::Y).abs() > 0.9999 {
        bail!(
            "camera '{}'.target: view direction is degenerate or parallel to up",
            c.id
        );
    }
    match c.projection {
        Projection::Perspective { fov_degrees } if !(10.0..=140.).contains(&fov_degrees) => {
            bail!("camera '{}'.projection.fov_degrees: expected 10..140", c.id)
        }
        Projection::Orthographic { height } if !(0.1..=150.).contains(&height) => {
            bail!("camera '{}'.projection.height: expected 0.1..150", c.id)
        }
        _ => Ok(()),
    }
}
