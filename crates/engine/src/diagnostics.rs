use serde::Serialize;

#[derive(Default, Clone, Serialize)]
pub struct FrameMetrics {
    pub frame: u64,
    pub cpu_encode_ms: f64,
    pub gpu_ms: Option<f64>,
    pub gpu_timestamp_supported: bool,
    pub effect_update_cpu_ms: f64,
    pub fire_primitives: u32,
    pub flame_fragments: u32,
    pub embers: u32,
    pub effect_events_dropped: u32,
}

pub fn percentile(values: &[f64], fraction: f64) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut sorted = values.to_vec();
    sorted.sort_by(f64::total_cmp);
    sorted[((sorted.len() as f64 * fraction).ceil() as usize)
        .saturating_sub(1)
        .min(sorted.len() - 1)]
}

pub fn log(event: &str, detail: impl Serialize) {
    eprintln!("{}", serde_json::json!({"event":event,"detail":detail}));
}

#[cfg(test)]
mod tests {
    #[test]
    fn percentile_handles_small_samples() {
        assert_eq!(super::percentile(&[], 0.95), 0.0);
        assert_eq!(super::percentile(&[3., 1., 2.], 0.5), 2.);
        assert_eq!(super::percentile(&[3., 1., 2.], 0.95), 3.);
    }
}
