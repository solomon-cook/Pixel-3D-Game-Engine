//! Game-authored effect profiles and bounded, deterministic world-space fire.
//! Geometry is sampled once per tick, independently of camera/pixel resolution.
use crate::scene::{Camera, Projection};
use anyhow::{bail, Result};
use bytemuck::{Pod, Zeroable};
use glam::Vec3;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::f32::consts::TAU;

pub const MAX_FIRE_PRIMITIVES: usize = 256;
pub const MAX_PARTICLE_LIGHTS: usize = 12;
pub const MAX_EMITTERS: usize = 2;

/// Mix the user seed with a stable source ID without depending on array order,
/// process hash randomization, source position, or platform endianness.
pub fn stable_emitter_seed(seed: u32, emitter_id: &str) -> u32 {
    let mut hash = 0x811c9dc5u32 ^ seed;
    for byte in b"pixel-engine:emitter:".iter().chain(emitter_id.as_bytes()) {
        hash ^= u32::from(*byte);
        hash = hash.wrapping_mul(0x01000193);
    }
    hash
}

#[derive(Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
pub struct FireSettings {
    /// World-space width and height, independent of pixel resolution.
    pub width: f32,
    pub height: f32,
    pub motion_speed: f32,
    pub curl: f32,
    pub edge_breakup: f32,
    pub tip_breakup: f32,
    pub fragment_size: f32,
    /// 0 retains long tongues, 1 uses broad rounded lobes on shorter curves.
    pub lobe_roundness: f32,
    /// Opaque, discrete-colour coverage on the selected scene pixel grid.
    pub solid: bool,
    pub color_bands: u32,
    /// Maximum shimmer displacement in scene pixels, independent of window size.
    pub heat_distortion: f32,
    pub heat_distortion_height: f32,
    pub branches: u32,
    pub particle_lights: u32,
    pub particle_light_strength: f32,
    pub particle_light_range: f32,
    pub tongues: u32,
    pub segments: u32,
    /// Events per effect second; time is scaled by motion_speed.
    pub fragment_rate: f32,
    pub fragment_lifetime: f32,
    pub ember_rate: f32,
    pub ember_lifetime: f32,
    pub emission: f32,
}
impl Default for FireSettings {
    fn default() -> Self {
        Self {
            width: 0.85,
            height: 1.5,
            motion_speed: 0.55,
            curl: 0.8,
            edge_breakup: 0.5,
            tip_breakup: 0.8,
            fragment_size: 0.06,
            lobe_roundness: 0.,
            solid: false,
            color_bands: 4,
            heat_distortion: 0.,
            heat_distortion_height: 2.8,
            branches: 0,
            particle_lights: 12,
            particle_light_strength: 2.5,
            particle_light_range: 2.,
            tongues: 7,
            segments: 6,
            fragment_rate: 1.5,
            fragment_lifetime: 1.8,
            ember_rate: 4.,
            ember_lifetime: 4.5,
            emission: 1.25,
        }
    }
}
#[derive(Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
pub struct ThermalSettings {
    pub heat_output: f32,
    pub cooling_rate: f32,
    pub lift: f32,
}
impl Default for ThermalSettings {
    fn default() -> Self {
        Self {
            heat_output: 2.5,
            cooling_rate: 0.9,
            lift: 0.6,
        }
    }
}
#[derive(Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
pub struct FirePalette {
    /// Linear HDR radiance before exposure/tone mapping.
    pub outer: [f32; 3],
    pub warm: [f32; 3],
    pub hot: [f32; 3],
}
impl Default for FirePalette {
    fn default() -> Self {
        Self {
            outer: [1.6, 0.085, 0.008],
            warm: [3., 0.78, 0.045],
            hot: [5., 2.8, 0.75],
        }
    }
}
#[derive(Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct EffectProfile {
    pub id: String,
    #[serde(default)]
    pub fire: FireSettings,
    #[serde(default)]
    pub thermal: ThermalSettings,
    #[serde(default)]
    pub palette: FirePalette,
}
impl Default for EffectProfile {
    fn default() -> Self {
        Self {
            id: default_profile_id(),
            fire: FireSettings::default(),
            thermal: ThermalSettings::default(),
            palette: FirePalette::default(),
        }
    }
}
pub fn default_profile_id() -> String {
    "effect-campfire".into()
}
pub fn default_profiles() -> Vec<EffectProfile> {
    vec![EffectProfile::default()]
}
impl EffectProfile {
    pub fn validate(&self) -> Result<()> {
        let f = &self.fire;
        for (name, value, low, high) in [
            ("fire.heat_distortion", f.heat_distortion, 0., 4.),
            (
                "fire.heat_distortion_height",
                f.heat_distortion_height,
                0.1,
                12.,
            ),
            ("fire.lobe_roundness", f.lobe_roundness, 0., 1.),
            (
                "fire.particle_light_strength",
                f.particle_light_strength,
                0.,
                16.,
            ),
            ("fire.particle_light_range", f.particle_light_range, 0.1, 8.),
            ("fire.edge_breakup", f.edge_breakup, 0., 1.),
            ("fire.tip_breakup", f.tip_breakup, 0., 1.),
            ("fire.fragment_size", f.fragment_size, 0.01, 0.2),
            ("fire.width", f.width, 0.05, 4.),
            ("fire.height", f.height, 0.1, 8.),
            ("fire.motion_speed", f.motion_speed, 0.05, 3.),
            ("fire.curl", f.curl, 0., 2.),
            ("fire.fragment_rate", f.fragment_rate, 0., 8.),
            ("fire.fragment_lifetime", f.fragment_lifetime, 0.1, 6.),
            ("fire.ember_rate", f.ember_rate, 0., 32.),
            ("fire.ember_lifetime", f.ember_lifetime, 0.1, 8.),
            ("fire.emission", f.emission, 0., 16.),
            ("thermal.heat_output", self.thermal.heat_output, 0., 16.),
            ("thermal.cooling_rate", self.thermal.cooling_rate, 0., 10.),
            ("thermal.lift", self.thermal.lift, 0., 4.),
        ] {
            if !value.is_finite() || !(low..=high).contains(&value) {
                bail!("effect '{}'.{name}: expected {low}..{high}", self.id);
            }
        }
        if !(2..=8).contains(&f.color_bands) {
            bail!("effect '{}'.fire.color_bands: expected 2..8", self.id);
        }
        if f.branches > 3 || f.particle_lights > MAX_PARTICLE_LIGHTS as u32 {
            bail!(
                "effect '{}'.fire: branches must be 0..3 and particle_lights 0..12",
                self.id
            );
        }
        if !(1..=16).contains(&f.tongues) || !(3..=10).contains(&f.segments) {
            bail!(
                "effect '{}'.fire: tongues must be 1..16 and segments 3..10",
                self.id
            );
        }
        for (name, color) in [
            ("outer", self.palette.outer),
            ("warm", self.palette.warm),
            ("hot", self.palette.hot),
        ] {
            if color
                .iter()
                .any(|x| !x.is_finite() || !(0.0..=64.).contains(x))
            {
                bail!(
                    "effect '{}'.palette.{name}: expected finite linear HDR values 0..64",
                    self.id
                );
            }
        }
        Ok(())
    }
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct FirePrimitive {
    pub center_radius: [f32; 4],
    pub axis_length: [f32; 4],
    /// Normalised heat, extinction, kind (0 tongue, 1 fragment, 2 ember), age.
    pub heat_kind: [f32; 4],
}
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable, Serialize)]
pub struct ParticleLight {
    pub position_range: [f32; 4],
    pub color_power: [f32; 4],
    /// Particle kind, event low/high words, seed: stable through pool reuse.
    pub identity: [u32; 4],
}
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct FireFrame {
    /// Total, tongue segments, fragments, embers.
    pub counts: [u32; 4],
    /// w stores source power and the number of events dropped by pool caps.
    pub bounds_min: [f32; 4],
    pub bounds_max: [f32; 4],
    /// Active lights, candidates omitted by the budget, omitted branch segments, reserved.
    pub lighting: [u32; 4],
    pub lights: [ParticleLight; MAX_PARTICLE_LIGHTS],
    pub primitives: [FirePrimitive; MAX_FIRE_PRIMITIVES],
}

/// Fixed-capacity GPU storage for independently sampled emitter frames.
/// Source zero retains the existing single-emitter ABI and shader behavior;
/// source one is reserved for the bounded two-emitter renderer path.
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct FireFrameStorage {
    pub sources: [FireFrame; MAX_EMITTERS],
    pub source_origins: [[f32; 4]; MAX_EMITTERS],
    pub presentations: [FirePresentation; MAX_EMITTERS],
}

/// Per-emitter flame appearance and activity, stored as six WGSL-compatible
/// vec4 values. Source zero mirrors Globals for exact v1 shading parity.
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct FirePresentation {
    pub outer: [f32; 4],
    pub warm: [f32; 4],
    pub hot: [f32; 4],
    pub shape: [f32; 4],
    pub pixels: [f32; 4],
    pub controls: [f32; 4],
    pub smoke: [f32; 4],
}

impl FirePresentation {
    pub fn from_profile(
        profile: &EffectProfile,
        intensity: f32,
        smoke: [f32; 4],
        smoke_shading: [f32; 2],
    ) -> Self {
        Self {
            outer: [
                profile.palette.outer[0],
                profile.palette.outer[1],
                profile.palette.outer[2],
                profile.fire.emission,
            ],
            warm: [
                profile.palette.warm[0],
                profile.palette.warm[1],
                profile.palette.warm[2],
                profile.fire.edge_breakup,
            ],
            hot: [
                profile.palette.hot[0],
                profile.palette.hot[1],
                profile.palette.hot[2],
                profile.fire.tip_breakup,
            ],
            shape: [
                profile.fire.width,
                profile.fire.height,
                profile.fire.motion_speed,
                profile.fire.curl,
            ],
            pixels: [
                u32::from(profile.fire.solid) as f32,
                profile.fire.color_bands as f32,
                profile.fire.heat_distortion,
                profile.fire.heat_distortion_height,
            ],
            controls: [
                intensity.max(0.),
                profile.thermal.heat_output,
                smoke_shading[0],
                smoke_shading[1],
            ],
            smoke,
        }
    }
}

impl FireFrameStorage {
    /// Pack sampled frames in stable emitter-ID order. Preserve the established
    /// v1 sampler for a single source; multi-source sampling derives stable
    /// source-specific seeds through `FireFrame::sample_emitters`.
    pub fn sample_emitters(sources: &[(String, FireKey)]) -> Result<Self> {
        let sampled = if sources.len() == 1 {
            vec![(sources[0].0.clone(), FireFrame::sample(&sources[0].1))]
        } else {
            FireFrame::sample_emitters(sources)?
        };
        let mut storage = Self::zeroed();
        for (slot, (id, frame)) in sampled.iter().cloned().enumerate() {
            storage.sources[slot] = frame;
            let (_, key) = sources
                .iter()
                .find(|(source_id, _)| source_id == &id)
                .expect("sampled emitter has a matching key");
            storage.source_origins[slot] = [key.source[0], key.source[1], key.source[2], 1.];
            storage.presentations[slot] = FirePresentation::from_profile(
                &key.profile,
                key.enabled,
                key.smoke,
                key.smoke_shading,
            );
        }
        if sampled.len() > 1 {
            let selected = select_emitter_particle_lights(&sampled)?;
            let local_drops = sampled
                .iter()
                .map(|(_, frame)| frame.lighting[1])
                .sum::<u32>();
            let candidate_count = sampled
                .iter()
                .map(|(_, frame)| frame.lighting[0])
                .sum::<u32>();
            let branch_drops = sampled
                .iter()
                .map(|(_, frame)| frame.lighting[2])
                .sum::<u32>();
            storage.sources[0].lights = [ParticleLight::zeroed(); MAX_PARTICLE_LIGHTS];
            for (slot, candidate) in selected.iter().enumerate() {
                storage.sources[0].lights[slot] = candidate.light;
            }
            storage.sources[0].lighting = [
                selected.len() as u32,
                local_drops + candidate_count.saturating_sub(selected.len() as u32),
                branch_drops,
                0,
            ];
            for frame in storage.sources.iter_mut().skip(1) {
                frame.lights = [ParticleLight::zeroed(); MAX_PARTICLE_LIGHTS];
                frame.lighting = [0; 4];
            }
        }
        Ok(storage)
    }
}
#[derive(Clone, PartialEq)]
pub struct FireKey {
    pub tick: u64,
    pub seed: u32,
    pub source: [f32; 3],
    pub wind: [f32; 3],
    pub enabled: f32,
    pub profile: EffectProfile,
    pub smoke: [f32; 4],
    pub smoke_shading: [f32; 2],
}

/// A derived light selected from a source frame for the shared renderer budget.
#[derive(Clone, Copy)]
pub struct EmitterParticleLight<'a> {
    pub emitter_id: &'a str,
    pub light: ParticleLight,
}

/// Merge per-source light candidates into the renderer-wide budget. Selection
/// is independent of input order: strongest lights win, followed by stable
/// emitter ID and event identity for exact power ties.
pub fn select_emitter_particle_lights<'a>(
    sources: &'a [(String, FireFrame)],
) -> Result<Vec<EmitterParticleLight<'a>>> {
    if sources.len() > MAX_EMITTERS {
        bail!("effects: at most {MAX_EMITTERS} emitters can provide particle lights");
    }
    let mut candidates = Vec::new();
    for (id, frame) in sources {
        for light in frame.lights.iter().take(frame.lighting[0] as usize) {
            candidates.push(EmitterParticleLight {
                emitter_id: id,
                light: *light,
            });
        }
    }
    candidates.sort_by(|a, b| {
        b.light.color_power[3]
            .total_cmp(&a.light.color_power[3])
            .then_with(|| a.emitter_id.cmp(b.emitter_id))
            .then_with(|| a.light.identity.cmp(&b.light.identity))
    });
    candidates.truncate(MAX_PARTICLE_LIGHTS);
    Ok(candidates)
}

fn random(seed: u32, index: u64, lane: u32) -> f32 {
    let mut x = seed
        ^ (index as u32).wrapping_mul(0x9e3779b9)
        ^ ((index >> 32) as u32)
        ^ lane.wrapping_mul(0x85ebca6b);
    x ^= x >> 16;
    x = x.wrapping_mul(0x7feb352d);
    x ^= x >> 15;
    x = x.wrapping_mul(0x846ca68b);
    x ^= x >> 16;
    (x >> 8) as f32 / 16777216.
}
fn path(f: &FireSettings, seed: u32, tongue: u32, u: f32, time: f32, wind: Vec3) -> Vec3 {
    let phase = random(seed, tongue as u64, 0) * TAU;
    let angle = tongue as f32 * 2.399963 + phase * 0.2;
    let rim = if tongue == 0 {
        0.
    } else {
        f.width * (0.29 + f.lobe_roundness * 0.13)
    };
    let root = Vec3::new(angle.cos() * rim, -0.35, angle.sin() * rim);
    let stature = if tongue == 0 {
        1.
    } else {
        0.55 + random(seed, tongue as u64, 1) * 0.35
    };
    let height = f.height
        * stature
        * (1. - f.lobe_roundness * 0.48)
        * (0.88 + 0.12 * (time * 1.1 + phase).sin());
    let wave = u * 4.8 - time * 1.45 + phase;
    let curl = f.curl * height * u.powf(1.6) * 0.22;
    root + Vec3::new(
        wave.sin() * curl,
        height * u,
        (wave * 0.83 + phase).cos() * curl * 0.7,
    ) + wind * u * u * height * 0.17
}
fn branch_path(
    f: &FireSettings,
    seed: u32,
    tongue: u32,
    branch: u32,
    u: f32,
    time: f32,
    wind: Vec3,
) -> Vec3 {
    let id = tongue as u64 * 4 + branch as u64;
    let anchor = 0.3 + random(seed, id, 11) * 0.42;
    let root = path(f, seed, tongue, anchor, time, wind);
    let angle = random(seed, id, 12) * TAU;
    let bend = (u * 3.8 - time * 1.1 + angle).sin() * u * u * f.curl * f.width * 0.11;
    let spread = f.width * (0.12 + random(seed, id, 13) * 0.17) * u;
    root + Vec3::new(
        angle.cos() * spread + bend,
        f.height * (0.22 + random(seed, id, 14) * 0.18) * u,
        angle.sin() * spread + bend * 0.6,
    ) + wind * u * u * 0.1
}
impl FireFrame {
    fn add(&mut self, center: Vec3, radius: f32, axis: Vec3, length: f32, heat_kind: [f32; 4]) {
        let i = self.counts[0] as usize;
        if i >= MAX_FIRE_PRIMITIVES || radius <= 0.0001 {
            return;
        }
        let axis = axis.normalize_or_zero();
        self.primitives[i] = FirePrimitive {
            center_radius: [center.x, center.y, center.z, radius],
            axis_length: [axis.x, axis.y, axis.z, length.max(radius * 0.4)],
            heat_kind,
        };
        self.counts[0] += 1;
        self.counts[heat_kind[2] as usize + 1] += 1;
        let extent = axis.abs() * length + Vec3::splat(radius);
        for j in 0..3 {
            self.bounds_min[j] = self.bounds_min[j].min((center - extent)[j]);
            self.bounds_max[j] = self.bounds_max[j].max((center + extent)[j]);
        }
    }
    fn particle_light(&mut self, key: &FireKey, index: usize, event: u64, seed: u32) {
        let f = &key.profile.fire;
        let p = self.primitives[index];
        let heat = p.heat_kind[0];
        let fade = (1. - p.heat_kind[3]).max(0.);
        let size = p.center_radius[3] / f.width;
        let power = f.particle_light_strength
            * f.emission
            * key.enabled
            * heat
            * fade
            * (0.035 + size * size * 180.);
        if f.particle_lights == 0 || power < 0.0001 {
            return;
        }
        let warm = Vec3::from(key.profile.palette.warm);
        let hot = Vec3::from(key.profile.palette.hot);
        let color = warm.lerp(hot, (heat - 0.35).max(0.) * 0.65);
        let color = color / color.max_element().max(0.001);
        let light = ParticleLight {
            position_range: [
                p.center_radius[0],
                p.center_radius[1],
                p.center_radius[2],
                f.particle_light_range * (0.35 + size * 6.).clamp(0.35, 1.),
            ],
            color_power: [color.x, color.y, color.z, power],
            identity: [
                p.heat_kind[2] as u32,
                event as u32,
                (event >> 32) as u32,
                seed,
            ],
        };
        let count = self.lighting[0] as usize;
        let capacity = f.particle_lights as usize;
        if count < capacity {
            self.lights[count] = light;
            self.lighting[0] += 1;
        } else {
            self.lighting[1] += 1;
            let slot = (0..capacity)
                .min_by(|&a, &b| {
                    self.lights[a].color_power[3].total_cmp(&self.lights[b].color_power[3])
                })
                .unwrap();
            if power > self.lights[slot].color_power[3] {
                self.lights[slot] = light;
            }
        }
    }
    /// Pure seeded reconstruction: arbitrary fixed-tick captures need no particle
    /// history or GPU readback. Event identities survive slot reuse and reset.
    pub fn sample(key: &FireKey) -> Self {
        Self::sample_with_segments(key, key.profile.fire.segments)
    }

    /// Sample a bounded source set in stable ID order with source-specific event
    /// seeds. Existing single-emitter rendering continues to use `sample` so its
    /// established output remains unchanged.
    pub fn sample_emitters(sources: &[(String, FireKey)]) -> Result<Vec<(String, Self)>> {
        if sources.len() > MAX_EMITTERS {
            bail!("effects: at most {MAX_EMITTERS} emitters can be sampled");
        }
        let mut ordered = sources.iter().collect::<Vec<_>>();
        ordered.sort_by(|left, right| left.0.cmp(&right.0));
        if ordered.windows(2).any(|pair| pair[0].0 == pair[1].0) {
            bail!("effects: emitter IDs must be unique");
        }
        Ok(ordered
            .into_iter()
            .map(|(id, source_key)| {
                let mut key = source_key.clone();
                key.seed = stable_emitter_seed(key.seed, id);
                (id.clone(), Self::sample(&key))
            })
            .collect())
    }

    /// Rebuild render geometry at a requested curve density. Callers preserve
    /// the full-detail frame's emitted lights and simulation bounds.
    pub fn sample_with_segments(key: &FireKey, segments: u32) -> Self {
        let mut frame = Self::zeroed();
        let source = Vec3::from(key.source);
        let wind = Vec3::from(key.wind);
        frame.bounds_min = [source.x, source.y, source.z, 1.];
        frame.bounds_max = [source.x, source.y, source.z, 0.];
        if key.enabled <= 0. {
            return frame;
        }
        let mut profile = key.profile.clone();
        profile.fire.segments = segments.clamp(3, key.profile.fire.segments);
        let f = &profile.fire;
        let time = key.tick as f32 * crate::simulation::FIXED_DT * f.motion_speed;
        frame.bounds_min[3] =
            0.88 + 0.07 * (time * 2.1 + key.seed as f32).sin() + 0.05 * (time * 3.7).cos();
        for tongue in 0..f.tongues {
            let width = f.width
                * if tongue == 0 {
                    0.31 + f.lobe_roundness * 0.06
                } else {
                    0.14 + f.lobe_roundness * 0.12 + random(key.seed, tongue as u64, 2) * 0.06
                };
            for segment in 0..f.segments {
                let u = segment as f32 / f.segments as f32;
                let v = (segment + 1) as f32 / f.segments as f32;
                let a = path(f, key.seed, tongue, u, time, wind);
                let b = path(f, key.seed, tongue, v, time, wind);
                let mid = (u + v) * 0.5;
                let radius = width
                    * (1. - mid).powf(0.8 - f.lobe_roundness * 0.27)
                    * (0.94 + 0.06 * (mid * 9. - time * 1.4).sin());
                let swelling = 1.
                    + f.lobe_roundness
                        * 0.22
                        * (mid * TAU * 1.6 - time * 0.55
                            + random(key.seed, tongue as u64, 9) * TAU)
                            .cos();
                let radius = radius * swelling;
                frame.add(
                    source + (a + b) * 0.5,
                    radius,
                    b - a,
                    ((b - a).length() * 0.5 + radius * (1.2 - f.lobe_roundness * 0.5)).max(radius),
                    [
                        1. - mid * 0.48,
                        1.3 * (1.
                            - f.tip_breakup
                                * ((mid - 0.45) * 2.).clamp(0., 1.)
                                * (0.5
                                    + 0.5
                                        * (time * 2.1 - mid * 12.
                                            + random(key.seed, tongue as u64, 3) * TAU)
                                            .sin())
                                .powi(8)),
                        0.,
                        mid,
                    ],
                );
            }
        }
        let branch_budget = MAX_FIRE_PRIMITIVES - 80;
        for tongue in 0..f.tongues {
            for branch in 0..f.branches {
                let width = f.width
                    * (0.09 + random(key.seed, tongue as u64 * 4 + branch as u64, 15) * 0.055);
                for segment in 0..3 {
                    if frame.counts[0] as usize >= branch_budget {
                        frame.lighting[2] += 1;
                        continue;
                    }
                    let u = segment as f32 / 3.;
                    let v = (segment + 1) as f32 / 3.;
                    let mid = (u + v) * 0.5;
                    let a = branch_path(f, key.seed, tongue, branch, u, time, wind);
                    let b = branch_path(f, key.seed, tongue, branch, v, time, wind);
                    let radius = width * (1. - mid).powf(0.65);
                    frame.add(
                        source + (a + b) * 0.5,
                        radius,
                        b - a,
                        ((b - a).length() * 0.5 + radius * 0.65).max(radius),
                        [
                            0.82 - mid * 0.35,
                            1.1 * (1. - mid * 0.35),
                            0.,
                            0.45 + mid * 0.55,
                        ],
                    );
                }
            }
        }
        for (kind, rate, lifetime, capacity) in [
            (1u32, f.fragment_rate, f.fragment_lifetime, 16u32),
            (2, f.ember_rate, f.ember_lifetime, 64),
        ] {
            if rate <= 0. {
                continue;
            }
            let requested = (rate * lifetime).ceil() as u32;
            frame.bounds_max[3] += requested.saturating_sub(capacity) as f32;
            // Thin births when over budget, preserving full lifetimes instead
            // of abruptly deleting older particles each tick.
            let effective_rate = rate.min(capacity as f32 / lifetime);
            let newest = (time * effective_rate).floor() as u64;
            for offset in 0..requested.min(capacity) {
                let Some(event) = newest.checked_sub(offset as u64) else {
                    break;
                };
                let birth = event as f32 / effective_rate;
                let age = time - birth;
                if age >= lifetime {
                    continue;
                }
                let seed = key.seed.wrapping_add(kind * 7919);
                let h = random(seed, event, 0);
                let angle = h * TAU;
                let phase = age / lifetime;
                let cool = (-key.profile.thermal.cooling_rate * age * 0.65).exp();
                let before = frame.counts[0];
                if kind == 1 {
                    let tongue = (h * f.tongues as f32).floor() as u32;
                    let branch = (random(seed, event, 3) * f.branches.max(1) as f32).floor() as u32;
                    let on_branch = f.branches > 0 && random(seed, event, 4) > 0.45;
                    let start = if on_branch {
                        branch_path(f, key.seed, tongue, branch, 0.82, birth, wind)
                    } else {
                        path(f, key.seed, tongue, 0.82, birth, wind)
                    };
                    let tip = if on_branch {
                        branch_path(f, key.seed, tongue, branch, 0.94, birth, wind)
                    } else {
                        path(f, key.seed, tongue, 0.94, birth, wind)
                    };
                    let velocity =
                        (tip - start).normalize_or_zero() * f.height * 0.42 + wind * 0.25;
                    let roll = Vec3::new(
                        (angle + age * 1.4).sin() - angle.sin(),
                        0.,
                        (angle + age * 1.1).cos() - angle.cos(),
                    ) * f.curl
                        * f.width
                        * 0.1;
                    let center = source + start + velocity * age + roll;
                    let radius =
                        f.width * f.fragment_size * (0.65 + h * 0.7) * (1. - phase).powf(0.65);
                    frame.add(
                        center,
                        radius,
                        velocity + Vec3::Y * 0.2,
                        radius * (1.6 - phase * 0.5),
                        [
                            cool * 0.75,
                            1.2 * (1. - phase) * (0.8 + 0.2 * (age * 7. + angle).sin()),
                            1.,
                            phase,
                        ],
                    );
                } else {
                    let start = Vec3::new(
                        angle.cos() * f.width * 0.25,
                        0.05,
                        angle.sin() * f.width * 0.25,
                    );
                    let initial = Vec3::new(
                        angle.cos() * 0.13,
                        f.height * (0.45 + h * 0.35),
                        angle.sin() * 0.13,
                    );
                    let drift = wind + Vec3::Y * key.profile.thermal.lift * 0.3;
                    let damping = (1. - (-age * 0.65).exp()) / 0.65;
                    let center = source + start + drift * age + (initial - drift) * damping;
                    let velocity = drift + (initial - drift) * (-age * 0.65).exp();
                    let radius =
                        f.width * (0.009 + random(seed, event, 1) * 0.009) * (1. - phase * 0.65);
                    frame.add(
                        center,
                        radius,
                        velocity,
                        radius * (1.8 + h * 1.8),
                        [cool, 2.4 * (1. - phase), 2., phase],
                    );
                }
                if frame.counts[0] > before {
                    frame.particle_light(key, frame.counts[0] as usize - 1, event, seed);
                }
            }
        }
        frame
    }
}

pub fn projected_fire_height_px(
    camera: &Camera,
    resolution: [u32; 2],
    source: [f32; 3],
    profile: &EffectProfile,
) -> f32 {
    if resolution[1] == 0 {
        return f32::INFINITY;
    }
    let position = Vec3::from(camera.position);
    let forward = (Vec3::from(camera.target) - position).normalize_or_zero();
    let depth = (Vec3::from(source) - position).dot(forward);
    if !position.is_finite() || !forward.is_finite() || depth <= 0.1 {
        return f32::INFINITY;
    }
    let world_height = profile.fire.height.max(profile.fire.width * 2.);
    let pixels_per_world = match camera.projection {
        Projection::Perspective { fov_degrees } => {
            resolution[1] as f32 / (2. * (fov_degrees.to_radians() * 0.5).tan() * depth)
        }
        Projection::Orthographic { height } => resolution[1] as f32 / height,
    };
    let projected = world_height * pixels_per_world;
    if projected.is_finite() {
        projected.max(0.)
    } else {
        f32::INFINITY
    }
}

/// Two-threshold hysteresis: tiers change at 40/20 px and return at 48/24 px.
pub fn advance_projected_detail_tier(current: u8, height_px: f32, enabled: bool) -> u8 {
    if !enabled || !height_px.is_finite() {
        return 0;
    }
    let mut tier = current.min(2);
    for _ in 0..2 {
        let next = match tier {
            0 if height_px < 40. => 1,
            1 if height_px > 48. => 0,
            1 if height_px < 20. => 2,
            2 if height_px > 24. => 1,
            _ => tier,
        };
        if next == tier {
            break;
        }
        tier = next;
    }
    tier
}

pub fn projected_detail_segments(full_segments: u32, tier: u8) -> u32 {
    match tier {
        1 => (full_segments * 2).div_ceil(3).max(3),
        2 => (full_segments / 2).max(3),
        _ => full_segments,
    }
}

pub fn render_frame_with_detail(key: &FireKey, full_frame: &FireFrame, segments: u32) -> FireFrame {
    if segments >= key.profile.fire.segments {
        return *full_frame;
    }
    let mut reduced = FireFrame::sample_with_segments(key, segments);
    reduced.bounds_min = full_frame.bounds_min;
    reduced.bounds_max = full_frame.bounds_max;
    reduced.lighting = full_frame.lighting;
    reduced.lights = full_frame.lights;
    reduced
}

#[cfg(test)]
mod tests {
    use super::*;
    fn key() -> FireKey {
        FireKey {
            tick: 300,
            seed: 42,
            source: [0., 0.4, 0.],
            wind: [0.2, 0., 0.1],
            enabled: 1.,
            profile: EffectProfile::default(),
            smoke: [0.6, 0.85, 3., 0.45],
            smoke_shading: [0.9, 0.15],
        }
    }
    #[test]
    fn multi_emitter_sampling_is_stable_ordered_and_source_independent() {
        let first = ("campfire-a".to_string(), key());
        let mut second_key = key();
        second_key.source = [3.0, 0.4, -2.0];
        let second = ("campfire-b".to_string(), second_key);

        let forward = FireFrame::sample_emitters(&[first.clone(), second.clone()]).unwrap();
        let reverse = FireFrame::sample_emitters(&[second.clone(), first.clone()]).unwrap();
        assert_eq!(
            forward
                .iter()
                .map(|entry| entry.0.as_str())
                .collect::<Vec<_>>(),
            ["campfire-a", "campfire-b"]
        );
        for (id, frame) in &forward {
            assert!(frame.lighting[0] > 0);
            let light = frame.lights[0];
            assert_eq!(
                light.identity[3],
                stable_emitter_seed(42, id) + light.identity[0] * 7919
            );
        }
        assert_ne!(
            forward[0].1.lights[0].identity[3],
            forward[1].1.lights[0].identity[3]
        );
        for ((forward_id, forward_frame), (reverse_id, reverse_frame)) in
            forward.iter().zip(&reverse)
        {
            assert_eq!(forward_id, reverse_id);
            assert_eq!(
                bytemuck::bytes_of(forward_frame),
                bytemuck::bytes_of(reverse_frame)
            );
        }

        let mut changed_second = second.clone();
        changed_second.1.tick += 17;
        changed_second.1.profile.fire.curl *= 0.5;
        let changed = FireFrame::sample_emitters(&[first, changed_second]).unwrap();
        assert_eq!(
            bytemuck::bytes_of(&forward[0].1),
            bytemuck::bytes_of(&changed[0].1),
            "changing one emitter must not perturb another source frame"
        );
        assert_ne!(
            bytemuck::bytes_of(&forward[1].1),
            bytemuck::bytes_of(&changed[1].1),
            "changing an emitter must update that source frame"
        );
        assert_ne!(
            stable_emitter_seed(42, "campfire-a"),
            stable_emitter_seed(42, "campfire-b")
        );
    }

    #[test]
    fn multi_emitter_sampling_rejects_duplicate_ids_and_excess_sources() {
        let source = ("same-id".to_string(), key());
        assert!(FireFrame::sample_emitters(&[source.clone(), source.clone()]).is_err());
        let sources = (0..=MAX_EMITTERS)
            .map(|index| (format!("fire-{index}"), key()))
            .collect::<Vec<_>>();
        assert!(FireFrame::sample_emitters(&sources).is_err());
    }

    #[test]
    fn emitter_particle_lights_use_a_stable_global_budget() {
        let mut frames = FireFrame::sample_emitters(&[
            ("fire-b".to_string(), key()),
            ("fire-a".to_string(), key()),
        ])
        .unwrap();
        for (_, frame) in &mut frames {
            frame.lighting[0] = MAX_PARTICLE_LIGHTS as u32;
            for (index, light) in frame.lights.iter_mut().enumerate() {
                light.color_power[3] = 1.;
                light.identity = [0, index as u32, 0, 0];
            }
        }

        let selected = select_emitter_particle_lights(&frames).unwrap();
        assert_eq!(selected.len(), MAX_PARTICLE_LIGHTS);
        assert!(selected
            .iter()
            .all(|candidate| candidate.emitter_id == "fire-a"));
        let reversed = frames.iter().rev().cloned().collect::<Vec<_>>();
        let selected_reversed = select_emitter_particle_lights(&reversed).unwrap();
        assert_eq!(
            selected
                .iter()
                .map(|candidate| (candidate.emitter_id, candidate.light.identity))
                .collect::<Vec<_>>(),
            selected_reversed
                .iter()
                .map(|candidate| (candidate.emitter_id, candidate.light.identity))
                .collect::<Vec<_>>(),
        );

        frames[1].1.lights[0].color_power[3] = 2.;
        let promoted = select_emitter_particle_lights(&frames).unwrap();
        assert_eq!(promoted[0].emitter_id, "fire-b");
        assert_eq!(promoted.len(), MAX_PARTICLE_LIGHTS);
    }

    #[test]
    fn pixel_treatment_does_not_change_particle_geometry_or_lights() {
        let mut k = key();
        let before = FireFrame::sample(&k);
        k.profile.fire.solid = true;
        k.profile.fire.color_bands = 3;
        k.profile.fire.heat_distortion = 2.;
        k.profile.fire.heat_distortion_height = 4.;
        assert_eq!(
            bytemuck::bytes_of(&before),
            bytemuck::bytes_of(&FireFrame::sample(&k))
        );
        k.profile.fire.color_bands = 9;
        assert!(k.profile.validate().is_err());
        k.profile.fire.color_bands = 4;
        k.profile.fire.heat_distortion = f32::NAN;
        assert!(k.profile.validate().is_err());
    }
    #[test]
    fn rounded_branches_and_particle_emission_remain_bounded() {
        let mut k = key();
        k.profile.fire.lobe_roundness = 1.;
        k.profile.fire.branches = 3;
        let with = FireFrame::sample(&k);
        assert!(with.counts[1] > k.profile.fire.tongues * k.profile.fire.segments);
        assert!(with.lighting[0] > 0 && with.lighting[0] <= MAX_PARTICLE_LIGHTS as u32);
        for l in &with.lights[..with.lighting[0] as usize] {
            assert!(l.position_range.iter().all(|v| v.is_finite()));
            assert!(l.position_range[3] > 0. && l.color_power[3] > 0.);
            assert!(l.identity[0] == 1 || l.identity[0] == 2);
            assert!(with.primitives[..with.counts[0] as usize]
                .iter()
                .any(|p| p.heat_kind[2] as u32 == l.identity[0]
                    && p.center_radius[..3] == l.position_range[..3]));
        }
        k.profile.fire.particle_lights = 0;
        let dark = FireFrame::sample(&k);
        assert_eq!(dark.lighting[0], 0);
        assert_eq!(
            bytemuck::cast_slice::<_, u8>(&with.primitives),
            bytemuck::cast_slice::<_, u8>(&dark.primitives)
        );
        k.profile.fire.particle_lights = 12;
        k.profile.fire.tongues = 16;
        k.profile.fire.segments = 10;
        k.profile.fire.fragment_rate = 8.;
        k.profile.fire.fragment_lifetime = 6.;
        k.profile.fire.ember_rate = 32.;
        k.profile.fire.ember_lifetime = 8.;
        k.tick = 36000;
        let max = FireFrame::sample(&k);
        assert!(max.counts[0] as usize <= MAX_FIRE_PRIMITIVES);
        assert!(max.lighting[2] > 0 && max.counts[2] > 0 && max.counts[3] > 0);
        assert!(max.lighting[0] <= 12);
    }
    #[test]
    fn detached_lights_move_in_three_dimensions_with_stable_identities() {
        let mut k = key();
        let before = FireFrame::sample(&k);
        k.tick += 12;
        let after = FireFrame::sample(&k);
        let (a, b) = before.lights[..before.lighting[0] as usize]
            .iter()
            .find_map(|a| {
                after.lights[..after.lighting[0] as usize]
                    .iter()
                    .find(|b| b.identity == a.identity)
                    .map(|b| (a, b))
            })
            .unwrap();
        for axis in 0..3 {
            assert!((a.position_range[axis] - b.position_range[axis]).abs() > 0.00001);
        }
    }
    #[test]
    fn storage_layout_matches_wgsl_contract() {
        assert_eq!(std::mem::size_of::<FirePrimitive>(), 48);
        assert_eq!(std::mem::size_of::<ParticleLight>(), 48);
        assert_eq!(std::mem::size_of::<FirePresentation>(), 112);
        assert_eq!(std::mem::size_of::<FireFrame>(), 64 + 12 * 48 + 256 * 48);
        assert_eq!(
            std::mem::size_of::<FireFrameStorage>(),
            MAX_EMITTERS * (std::mem::size_of::<FireFrame>() + 16 + 112)
        );
    }
    #[test]
    fn fire_frame_storage_packs_sources_stably_and_preserves_v1_sampling() {
        let single_key = key();
        let single =
            FireFrameStorage::sample_emitters(&[("only".into(), single_key.clone())]).unwrap();
        assert_eq!(
            bytemuck::bytes_of(&single.sources[0]),
            bytemuck::bytes_of(&FireFrame::sample(&single_key))
        );
        assert_eq!(single.sources[1].counts, [0; 4]);
        assert_eq!(single.source_origins[0], [0., 0.4, 0., 1.]);
        assert_eq!(single.source_origins[1], [0.; 4]);

        let mut first = key();
        first.source = [-1.0, 0.0, 0.5];
        let mut second = key();
        second.source = [2.0, 0.0, -0.5];
        second.profile.fire.width *= 0.6;
        second.profile.palette.outer = [2.8, 0.12, 0.01];
        let sources = vec![("fire-b".into(), second), ("fire-a".into(), first)];
        let forward = FireFrameStorage::sample_emitters(&sources).unwrap();
        let reverse =
            FireFrameStorage::sample_emitters(&sources.iter().cloned().rev().collect::<Vec<_>>())
                .unwrap();
        assert_eq!(bytemuck::bytes_of(&forward), bytemuck::bytes_of(&reverse));
        assert!(forward.sources[0].counts[0] > 0);
        assert!(forward.sources[1].counts[0] > 0);
        assert_eq!(forward.source_origins[0], [-1., 0., 0.5, 1.]);
        assert_eq!(forward.source_origins[1], [2., 0., -0.5, 1.]);
        assert_eq!(forward.presentations[0].shape[0], key().profile.fire.width);
        assert_eq!(
            forward.presentations[1].shape[0],
            key().profile.fire.width * 0.6
        );
        assert_eq!(forward.presentations[1].outer[..3], [2.8, 0.12, 0.01]);
        let sampled = FireFrame::sample_emitters(&sources).unwrap();
        let selected = select_emitter_particle_lights(&sampled).unwrap();
        assert_eq!(forward.sources[0].lighting[0], selected.len() as u32);
        assert_eq!(forward.sources[1].lighting, [0; 4]);
        for (slot, candidate) in selected.iter().enumerate() {
            assert_eq!(
                forward.sources[0].lights[slot].identity,
                candidate.light.identity
            );
        }
        let generated = sampled
            .iter()
            .map(|(_, frame)| frame.lighting[0])
            .sum::<u32>();
        let locally_dropped = sampled
            .iter()
            .map(|(_, frame)| frame.lighting[1])
            .sum::<u32>();
        assert_eq!(
            forward.sources[0].lighting[1],
            locally_dropped + generated - selected.len() as u32
        );
    }
    #[test]
    fn seeded_fire_replays_and_is_camera_independent() {
        let a = FireFrame::sample(&key());
        let b = FireFrame::sample(&key());
        assert_eq!(bytemuck::bytes_of(&a), bytemuck::bytes_of(&b));
        let mut next = key();
        next.tick += 1;
        assert_ne!(
            bytemuck::bytes_of(&a),
            bytemuck::bytes_of(&FireFrame::sample(&next))
        );
        let mut other = key();
        other.seed += 1;
        assert_ne!(
            bytemuck::bytes_of(&a),
            bytemuck::bytes_of(&FireFrame::sample(&other))
        );
    }
    #[test]
    fn pools_are_bounded_and_bounds_contain_geometry() {
        let mut k = key();
        k.tick = 36000;
        k.profile.fire.tongues = 16;
        k.profile.fire.segments = 10;
        k.profile.fire.ember_rate = 32.;
        k.profile.fire.ember_lifetime = 8.;
        k.profile.fire.fragment_rate = 8.;
        k.profile.fire.fragment_lifetime = 6.;
        let f = FireFrame::sample(&k);
        assert!(f.counts[0] as usize <= MAX_FIRE_PRIMITIVES);
        assert!(f.bounds_max[3] > 0.);
        for kind in [1., 2.] {
            assert!(
                f.primitives[..f.counts[0] as usize]
                    .iter()
                    .any(|p| p.heat_kind[2] == kind && p.heat_kind[3] > 0.8),
                "capping must preserve older particles, not truncate their lifetime"
            );
        }
        for p in &f.primitives[..f.counts[0] as usize] {
            for i in 0..3 {
                let r = p.center_radius[3];
                let length = p.axis_length[3];
                let axis = p.axis_length[i];
                let extent = (r * r + (length * length - r * r) * axis * axis)
                    .max(0.)
                    .sqrt();
                assert!(p.center_radius[i] - extent >= f.bounds_min[i] - 0.0001);
                assert!(p.center_radius[i] + extent <= f.bounds_max[i] + 0.0001);
                assert!(p.center_radius[i].is_finite());
                assert!(p.center_radius[i] >= f.bounds_min[i]);
                assert!(p.center_radius[i] <= f.bounds_max[i]);
            }
        }
        k.enabled = 0.;
        assert_eq!(FireFrame::sample(&k).counts[0], 0);
    }
    #[test]
    fn effect_time_scale_and_emission_controls_are_independent() {
        let a = FireFrame::sample(&key());
        let mut k = key();
        k.profile.fire.motion_speed *= 2.;
        k.tick /= 2;
        assert_eq!(
            bytemuck::bytes_of(&a),
            bytemuck::bytes_of(&FireFrame::sample(&k))
        );
        k.profile.fire.emission = 0.;
        assert_eq!(
            bytemuck::cast_slice::<_, u8>(&a.primitives),
            bytemuck::cast_slice::<_, u8>(&FireFrame::sample(&k).primitives)
        );
        assert_eq!(FireFrame::sample(&k).lighting[0], 0);
        k.profile.fire.motion_speed = f32::NAN;
        assert!(k.profile.validate().is_err());
    }

    #[test]
    fn projected_detail_tiers_have_hysteresis_and_preserve_emitted_lights() {
        assert_eq!(advance_projected_detail_tier(0, 39., true), 1);
        assert_eq!(advance_projected_detail_tier(1, 44., true), 1);
        assert_eq!(advance_projected_detail_tier(1, 19., true), 2);
        assert_eq!(advance_projected_detail_tier(2, 22., true), 2);
        assert_eq!(advance_projected_detail_tier(2, 25., true), 1);
        assert_eq!(advance_projected_detail_tier(1, 49., true), 0);
        assert_eq!(advance_projected_detail_tier(2, f32::INFINITY, true), 0);
        assert_eq!(projected_detail_segments(6, 0), 6);
        assert_eq!(projected_detail_segments(6, 1), 4);
        assert_eq!(projected_detail_segments(6, 2), 3);

        let key = key();
        let full = FireFrame::sample(&key);
        let reduced = render_frame_with_detail(&key, &full, 3);
        assert!(reduced.counts[1] < full.counts[1]);
        assert_eq!(reduced.counts[2..], full.counts[2..]);
        assert_eq!(reduced.lighting, full.lighting);
        assert_eq!(
            bytemuck::bytes_of(&reduced.lights),
            bytemuck::bytes_of(&full.lights)
        );
        assert_eq!(reduced.bounds_min, full.bounds_min);
        assert_eq!(reduced.bounds_max, full.bounds_max);
    }

    #[test]
    fn projected_fire_size_supports_perspective_and_orthographic_cameras() {
        let profile = EffectProfile::default();
        let camera = Camera {
            id: "test".into(),
            position: [0., 0., 10.],
            target: [0., 0., 0.],
            projection: Projection::Perspective { fov_degrees: 60. },
        };
        let perspective = projected_fire_height_px(&camera, [640, 360], [0., 0., 0.], &profile);
        let mut orthographic = camera.clone();
        orthographic.projection = Projection::Orthographic { height: 10. };
        let ortho = projected_fire_height_px(&orthographic, [640, 360], [0., 0., 0.], &profile);
        assert!(perspective.is_finite() && perspective > 0.);
        assert!(ortho.is_finite() && ortho > perspective);
        assert!(
            projected_fire_height_px(&camera, [640, 360], [0., 0., 12.], &profile).is_infinite()
        );
    }
}
