use serde::Serialize;
use std::collections::BTreeMap;

#[derive(Default, Clone, Serialize)]
pub struct FrameMetrics {
    /// Counts are populated only by an explicitly requested diagnostic capture.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub shading_counters: Option<ShadingCounters>,
    pub frame: u64,
    pub cpu_encode_ms: f64,
    pub cpu_shadow_encode_ms: f64,
    pub cpu_tile_list_encode_ms: f64,
    pub cpu_object_culling_ms: f64,
    pub object_culling_enabled: bool,
    pub object_instancing_enabled: bool,
    pub camera_objects_considered: u32,
    pub camera_objects_visible: u32,
    pub camera_draw_batches: u32,
    pub camera_vertices_submitted: u64,
    pub optical_draw_batches: u32,
    pub optical_surface_reuse_enabled: bool,
    pub shadow_objects_visible: [u32; 7],
    pub shadow_draw_batches: [u32; 7],
    pub shadow_vertices_submitted: [u64; 7],
    pub tile_count: u32,
    pub tile_list_bytes: u64,
    pub tile_lists_enabled: bool,
    pub tile_overflow_forced: bool,
    pub tile_candidates: [u32; 4],
    pub tile_overflow_tiles: [u32; 4],
    pub tile_max_occupancy: [u32; 4],
    pub tile_stats_frame: Option<u64>,
    pub tile_stats_samples_skipped: u64,
    pub gpu_tile_list_ms: Option<f64>,
    pub gpu_absorption_cache_ms: Option<f64>,
    pub cpu_absorption_cache_ms: f64,
    pub smoke_absorption_cache_enabled: bool,
    pub cpu_upload_ms: f64,
    pub cpu_queue_submit_ms: f64,
    pub cpu_simulation_encode_ms: f64,
    pub cpu_simulation_submit_ms: f64,
    pub cpu_steps_this_frame: u32,
    pub cpu_native_ui_ms: Option<f64>,
    pub cpu_surface_acquire_ms: Option<f64>,
    pub cpu_present_encode_ms: Option<f64>,
    pub cpu_present_submit_ms: Option<f64>,
    pub cpu_native_frame_ms: Option<f64>,
    pub gpu_ms: Option<f64>,
    pub gpu_passes_ms: BTreeMap<String, f64>,
    pub gpu_timing_frame: Option<u64>,
    pub gpu_smoke_compute_ms: Option<f64>,
    pub gpu_smoke_tick: Option<u64>,
    pub gpu_samples_skipped: u64,
    pub gpu_compute_samples_skipped: u64,
    pub gpu_samples_late: u64,
    pub gpu_timestamp_supported: bool,
    pub shadow_cache_hit: bool,
    pub shadow_redrawn: bool,
    pub shadow_cache_resident: bool,
    pub shadow_maps_redrawn: u32,
    /// Redrawn maps by index: sun, +X, -X, +Y, -Y, +Z, -Z.
    pub shadow_dirty_faces: [bool; 7],
    pub shadow_dirty_reason: Option<String>,
    pub effect_update_cpu_ms: f64,
    pub projected_detail_cpu_ms: f64,
    pub projected_detail_lod_enabled: bool,
    pub projected_fire_height_px: f32,
    pub fire_lod_level: u32,
    pub fire_segments_full: u32,
    pub fire_segments_rendered: u32,
    pub fire_primitives_full: u32,
    pub fire_primitives_rendered: u32,
    pub fire_primitives: u32,
    pub flame_fragments: u32,
    pub embers: u32,
    pub effect_events_dropped: u32,
    pub particle_lights: u32,
    pub particle_lights_dropped: u32,
    pub branch_segments_dropped: u32,
}

#[derive(Default, Clone, Serialize)]
pub struct ShadingCounters {
    pub fire_primitive_candidates: u32,
    pub fire_bounds_tests: u32,
    pub fire_ellipsoid_tests: u32,
    pub smoke_lobe_candidates: u32,
    pub smoke_parent_bounds_tests: u32,
    pub smoke_bubble_intersection_tests: u32,
    pub smoke_density_samples: u32,
    pub direct_absorption_samples: u32,
    pub cached_absorption_samples: u32,
    pub sun_shadow_lookups: u32,
    pub fire_shadow_lookups: u32,
    pub point_light_candidates: u32,
    pub particle_light_candidates: u32,
    pub camera_to_flame_absorption_samples: u32,
}

impl FrameMetrics {
    pub fn begin_frame(&mut self) {
        self.cpu_simulation_submit_ms = 0.;
        self.cpu_tile_list_encode_ms = 0.;
        self.cpu_absorption_cache_ms = 0.;
        self.gpu_absorption_cache_ms = None;
        self.cpu_object_culling_ms = 0.;
        self.camera_objects_considered = 0;
        self.camera_objects_visible = 0;
        self.camera_draw_batches = 0;
        self.camera_vertices_submitted = 0;
        self.optical_draw_batches = 0;
        self.optical_surface_reuse_enabled = false;
        self.shadow_objects_visible = [0; 7];
        self.shadow_draw_batches = [0; 7];
        self.shadow_vertices_submitted = [0; 7];
        self.cpu_steps_this_frame = 0;
        self.cpu_upload_ms = 0.;
        self.cpu_queue_submit_ms = 0.;
        self.cpu_simulation_encode_ms = 0.;
        self.cpu_native_ui_ms = None;
        self.cpu_surface_acquire_ms = None;
        self.cpu_present_encode_ms = None;
        self.cpu_present_submit_ms = None;
        self.cpu_native_frame_ms = None;
    }
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
    use super::FrameMetrics;

    #[test]
    fn percentile_handles_small_samples() {
        assert_eq!(super::percentile(&[], 0.95), 0.0);
        assert_eq!(super::percentile(&[3., 1., 2.], 0.5), 2.);
        assert_eq!(super::percentile(&[3., 1., 2.], 0.95), 3.);
    }

    #[test]
    fn begin_frame_resets_frame_spans_but_keeps_cumulative_query_counts() {
        let mut metrics = FrameMetrics {
            cpu_steps_this_frame: 3,
            cpu_simulation_submit_ms: 1.5,
            gpu_samples_skipped: 2,
            ..Default::default()
        };
        metrics.begin_frame();
        assert_eq!(metrics.cpu_steps_this_frame, 0);
        assert_eq!(metrics.cpu_simulation_submit_ms, 0.);
        assert_eq!(metrics.gpu_samples_skipped, 2);
        let value = serde_json::to_value(metrics).unwrap();
        assert!(value.get("gpu_passes_ms").unwrap().is_object());
        assert!(value.get("cpu_surface_acquire_ms").unwrap().is_null());
    }
}
