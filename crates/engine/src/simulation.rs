//! Fixed-step, seeded CPU signals. GPU advection uses the same step count;
//! floating point GPU results are compared with tolerances across backends.
pub const FIXED_DT: f32 = 1. / 60.;

pub fn wind(base: [f32; 3], tick: u64, seed: u32, connected: bool) -> [f32; 3] {
    let t = tick as f32 * FIXED_DT;
    let phase = (seed % 997) as f32 * 0.013;
    let gust = if connected {
        (t * 0.7 + phase).sin() * 0.3 + (t * 1.91).sin() * 0.12
    } else {
        0.
    };
    [base[0] + gust, base[1], base[2] + gust * 0.4]
}
pub fn flicker(tick: u64, seed: u32) -> f32 {
    let t = tick as f32 * FIXED_DT;
    0.75 + 0.12 * (t * 13.1 + seed as f32).sin() + 0.08 * (t * 23.7).sin() + 0.05 * (t * 5.3).cos()
}

#[cfg(test)]
mod tests {
    #[test]
    fn seeded_signals_replay() {
        assert_eq!(
            super::wind([0.1, 0., 0.], 240, 42, true),
            super::wind([0.1, 0., 0.], 240, 42, true)
        );
        assert_ne!(
            super::wind([0.1, 0., 0.], 240, 42, true),
            super::wind([0.1, 0., 0.], 240, 43, true)
        );
    }
}
