//! Game-authored effect profiles and bounded, deterministic world-space fire.
//! Geometry is sampled once per tick, independently of camera/pixel resolution.
use anyhow::{bail, Result};
use bytemuck::{Pod, Zeroable};
use glam::Vec3;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::f32::consts::TAU;

pub const MAX_FIRE_PRIMITIVES: usize = 256;

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
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct FireFrame {
    /// Total, tongue segments, fragments, embers.
    pub counts: [u32; 4],
    /// w stores source power and the number of events dropped by pool caps.
    pub bounds_min: [f32; 4],
    pub bounds_max: [f32; 4],
    pub primitives: [FirePrimitive; MAX_FIRE_PRIMITIVES],
}
#[derive(Clone, PartialEq)]
pub struct FireKey {
    pub tick: u64,
    pub seed: u32,
    pub source: [f32; 3],
    pub wind: [f32; 3],
    pub enabled: f32,
    pub profile: EffectProfile,
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
    let rim = if tongue == 0 { 0. } else { f.width * 0.29 };
    let root = Vec3::new(angle.cos() * rim, -0.35, angle.sin() * rim);
    let stature = if tongue == 0 {
        1.
    } else {
        0.55 + random(seed, tongue as u64, 1) * 0.35
    };
    let height = f.height * stature * (0.88 + 0.12 * (time * 1.1 + phase).sin());
    let wave = u * 4.8 - time * 1.45 + phase;
    let curl = f.curl * height * u.powf(1.6) * 0.22;
    root + Vec3::new(
        wave.sin() * curl,
        height * u,
        (wave * 0.83 + phase).cos() * curl * 0.7,
    ) + wind * u * u * height * 0.17
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
    /// Pure seeded reconstruction: arbitrary fixed-tick captures need no particle
    /// history or GPU readback. Event identities survive slot reuse and reset.
    pub fn sample(key: &FireKey) -> Self {
        let mut frame = Self::zeroed();
        let source = Vec3::from(key.source);
        let wind = Vec3::from(key.wind);
        frame.bounds_min = [source.x, source.y, source.z, 1.];
        frame.bounds_max = [source.x, source.y, source.z, 0.];
        if key.enabled <= 0. {
            return frame;
        }
        let f = &key.profile.fire;
        let time = key.tick as f32 * crate::simulation::FIXED_DT * f.motion_speed;
        frame.bounds_min[3] =
            0.88 + 0.07 * (time * 2.1 + key.seed as f32).sin() + 0.05 * (time * 3.7).cos();
        for tongue in 0..f.tongues {
            let width = f.width
                * if tongue == 0 {
                    0.31
                } else {
                    0.14 + random(key.seed, tongue as u64, 2) * 0.06
                };
            for segment in 0..f.segments {
                let u = segment as f32 / f.segments as f32;
                let v = (segment + 1) as f32 / f.segments as f32;
                let a = path(f, key.seed, tongue, u, time, wind);
                let b = path(f, key.seed, tongue, v, time, wind);
                let mid = (u + v) * 0.5;
                let radius =
                    width * (1. - mid).powf(0.8) * (0.94 + 0.06 * (mid * 9. - time * 1.4).sin());
                frame.add(
                    source + (a + b) * 0.5,
                    radius,
                    b - a,
                    (b - a).length() * 0.5 + radius * 1.2,
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
                if kind == 1 {
                    let tongue = (h * f.tongues as f32).floor() as u32;
                    let start = path(f, key.seed, tongue, 0.82, birth, wind);
                    let tip = path(f, key.seed, tongue, 0.94, birth, wind);
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
            }
        }
        frame
    }
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
        }
    }
    #[test]
    fn storage_layout_matches_wgsl_contract() {
        assert_eq!(std::mem::size_of::<FirePrimitive>(), 48);
        assert_eq!(std::mem::size_of::<FireFrame>(), 48 + 256 * 48);
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
            bytemuck::bytes_of(&a),
            bytemuck::bytes_of(&FireFrame::sample(&k))
        );
        k.profile.fire.motion_speed = f32::NAN;
        assert!(k.profile.validate().is_err());
    }
}
