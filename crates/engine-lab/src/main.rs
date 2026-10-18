#![recursion_limit = "256"]

mod window;

use anyhow::{bail, Context, Result};
use clap::{Args, Parser, Subcommand};
use pixel_engine::{
    assets, diagnostics, render,
    scene::Scene,
    session::{description, Session},
};
use serde_json::{json, Value};
use std::{
    path::{Path, PathBuf},
    time::Instant,
};

#[derive(Parser)]
#[command(
    about = "Native pixel-art rendering lab. Use describe for the agent contract.",
    version
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    /// Interactive window. Right-drag + WASD to fly; Tab inspector; F11 fullscreen.
    Run {
        #[command(flatten)]
        options: Options,
        #[arg(long)]
        agent_stdio: bool,
        #[arg(long)]
        paused: bool,
    },
    /// Validate scene references and decode assets without a GPU.
    Validate {
        #[arg(default_value = "assets/scenes/clearing.json")]
        scene: PathBuf,
    },
    /// Protocol contract and scene JSON schema; no GPU required.
    Describe,
    /// Exact-tick GPU capture with reproducibility metadata.
    Capture {
        #[command(flatten)]
        options: Options,
        /// Disable GPU queries for a same-frame capture comparison.
        #[arg(long)]
        disable_gpu_timing: bool,
        /// Use exhaustive effect/light candidate evaluation instead of tile lists.
        #[arg(long)]
        disable_tile_lists: bool,
        /// Force exhaustive fallback for every tile to validate overflow behavior.
        #[arg(long)]
        force_tile_overflow: bool,
        /// Precompute conservative fire screen bounds once per frame for O03 lists.
        #[arg(long)]
        precompute_fire_bounds: bool,
        /// Disable conservative per-camera and per-shadow-frustum object culling.
        #[arg(long)]
        disable_object_culling: bool,
        /// Issue one draw per visible object instead of grouping compatible instances.
        #[arg(long)]
        disable_instancing: bool,
        /// Restore the historical Globals + source-local smoke bind-group layout for parity checks.
        #[arg(long)]
        legacy_smoke_bind_layout: bool,
        /// Run an opt-in instrumented volumetric shader and report GPU operation counters.
        #[arg(long)]
        shading_counters: bool,
        #[arg(long, default_value_t = 300)]
        tick: u32,
        #[arg(long, default_value = "artifacts/capture.png")]
        output: PathBuf,
        #[arg(long, default_value_t = 4)]
        scale: u32,
    },
    /// Sample a moving route offscreen, without screenshots/UI/vsync.
    Benchmark {
        #[command(flatten)]
        options: Options,
        /// serial waits per frame for latency; buffered measures queueing throughput.
        #[arg(long, default_value = "serial")]
        mode: String,
        /// Disable GPU queries to measure profiling overhead.
        #[arg(long)]
        disable_gpu_timing: bool,
        /// Redraw all shadow maps every frame to compare against the cache.
        #[arg(long)]
        force_shadow_redraw: bool,
        /// Use exhaustive effect/light candidate evaluation instead of tile lists.
        #[arg(long)]
        disable_tile_lists: bool,
        /// Force exhaustive fallback for every tile to validate overflow behavior.
        #[arg(long)]
        force_tile_overflow: bool,
        /// Precompute conservative fire screen bounds once per frame for O03 lists.
        #[arg(long)]
        precompute_fire_bounds: bool,
        /// Disable conservative per-camera and per-shadow-frustum object culling.
        #[arg(long)]
        disable_object_culling: bool,
        /// Issue one draw per visible object instead of grouping compatible instances.
        #[arg(long)]
        disable_instancing: bool,
        /// Sample shading counters at three fixed checkpoints; timing data is diagnostic only.
        #[arg(long)]
        shading_counter_sampling: bool,
        /// Fixed simulation ticks advanced per rendered route sample (1..60).
        #[arg(long, default_value_t = 1)]
        simulation_steps_per_frame: u32,
        /// Move a scene object around the primary fire light during the route.
        #[arg(long)]
        moving_caster: Option<String>,
        /// Orbit radius in world units for --moving-caster.
        #[arg(long, default_value_t = 5.0)]
        caster_orbit_radius: f32,
        /// Orbit period in seconds for --moving-caster.
        #[arg(long, default_value_t = 20.0)]
        caster_orbit_period: f32,
        #[arg(long, default_value = "clearing-orbit")]
        route: String,
        #[arg(long, default_value_t = 120.)]
        duration: f32,
        #[arg(long, default_value_t = 10.)]
        warmup: f32,
        #[arg(long, default_value = "artifacts/benchmark.json")]
        output: PathBuf,
    },
    /// Measure the moving route in the native window, including acquisition and presentation.
    BenchmarkNative {
        #[command(flatten)]
        options: Options,
        /// Redraw all seven shadow maps every frame as a cache baseline.
        #[arg(long)]
        force_shadow_redraw: bool,
        /// Use exhaustive effect/light candidate evaluation instead of tile lists.
        #[arg(long)]
        disable_tile_lists: bool,
        /// Precompute conservative fire screen bounds once per frame.
        #[arg(long)]
        precompute_fire_bounds: bool,
        /// Disable conservative per-camera and per-shadow-frustum object culling.
        #[arg(long)]
        disable_object_culling: bool,
        /// Issue one draw per visible object instead of grouping compatible instances.
        #[arg(long)]
        disable_instancing: bool,
        /// Restore the redundant render Globals upload during smoke simulation for comparison.
        #[arg(long)]
        legacy_smoke_globals_upload: bool,
        /// Restore the historical Globals + source-local smoke bind-group layout for comparison.
        #[arg(long)]
        legacy_smoke_bind_layout: bool,
        /// Move a scene object around the primary fire light during the route.
        #[arg(long)]
        moving_caster: Option<String>,
        /// Orbit radius in world units for --moving-caster.
        #[arg(long, default_value_t = 5.0)]
        caster_orbit_radius: f32,
        /// Orbit period in seconds for --moving-caster.
        #[arg(long, default_value_t = 20.0)]
        caster_orbit_period: f32,
        #[arg(long, default_value = "clearing-orbit")]
        route: String,
        #[arg(long, default_value_t = 120.)]
        duration: f32,
        #[arg(long, default_value_t = 10.)]
        warmup: f32,
        #[arg(long, default_value = "artifacts/native-benchmark.json")]
        output: PathBuf,
    },
    /// JSON-lines protocol without a window, using the real GPU renderer.
    Serve {
        #[command(flatten)]
        options: Options,
    },
}
#[derive(Clone, Copy)]
struct BenchmarkSettings {
    disable_gpu_timing: bool,
    force_shadow_redraw: bool,
    tile_lists_enabled: bool,
    force_tile_overflow: bool,
    precompute_fire_bounds: bool,
    object_culling_enabled: bool,
    instancing_enabled: bool,
    shading_counter_sampling: bool,
    simulation_steps_per_frame: u32,
    simulation_batching_enabled: bool,
}
#[derive(Clone, Copy)]
pub(crate) struct CasterMotion<'a> {
    pub(crate) object_id: Option<&'a str>,
    pub(crate) radius: f32,
    pub(crate) period: f32,
}
#[derive(Clone, Copy)]
struct BenchmarkRoute<'a> {
    id: &'a str,
    caster_motion: CasterMotion<'a>,
}
#[derive(Args, Clone)]
pub struct Options {
    #[arg(long, default_value = "assets/scenes/clearing.json")]
    pub scene: PathBuf,
    #[arg(long, default_value_t = 42)]
    pub seed: u32,
    #[arg(long, default_value = "hero")]
    pub camera: String,
    /// Explicit scene buffer: 320x180, 480x270 640x360 or 960x540.
    #[arg(long)]
    pub resolution: Option<String>,
    /// Comma separated experiment names, or all.
    #[arg(long)]
    pub experiments: Option<String>,
    /// Select a named scene effect profile independently of rendering style.
    #[arg(long)]
    pub effect_profile: Option<String>,
    /// Smoke absorption cache resolution per axis (8 or 16).
    #[arg(long, value_parser = clap::value_parser!(u32).range(8..=16))]
    pub absorption_cache_resolution: Option<u32>,
    /// Use experimental Rg11b10Ufloat HDR color targets when supported.
    #[arg(long)]
    pub compact_hdr: bool,
    /// Use an experimental optical overlay path to skip the HDR snapshot copy.
    #[arg(long)]
    pub optical_no_copy: bool,
    /// Force the RGBA16F effect-target fallback to validate it on capable adapters.
    #[arg(long)]
    pub force_rg16_fallback: bool,
    /// Use one smoke compute queue submission per fixed tick instead of batching.
    #[arg(long)]
    pub disable_simulation_batching: bool,
    #[arg(long)]
    pub shaders: Option<PathBuf>,
}
fn main() {
    if let Err(error) = start() {
        eprintln!("{}", json!({"error":{"message":format!("{error:#}")}}));
        std::process::exit(1);
    }
}
fn start() -> Result<()> {
    match Cli::parse().command {
        Command::Describe => println!("{}", serde_json::to_string_pretty(&description())?),
        Command::Validate { scene } => {
            let path = resolve_path(&scene);
            let scene = Scene::load(&path)?;
            let mesh = assets::load(&scene, path.parent().unwrap())?;
            println!(
                "{}",
                json!({"valid":true,"name":scene.name,"objects":scene.objects.len(),"vertices":mesh.vertices.len(),"textures":mesh.textures.len()})
            );
        }
        Command::Run {
            options,
            agent_stdio,
            paused,
        } => window::run(options, agent_stdio, paused)?,
        Command::Capture {
            options,
            disable_gpu_timing,
            disable_tile_lists,
            force_tile_overflow,
            precompute_fire_bounds,
            disable_object_culling,
            disable_instancing,
            legacy_smoke_bind_layout,
            shading_counters,
            tick,
            output,
            scale,
        } => {
            if tick > 36000 {
                bail!("tick: maximum 36000");
            }
            let mut session = headless_with_timing(&options, !disable_gpu_timing)?;
            session
                .renderer
                .set_tile_lists(!disable_tile_lists, force_tile_overflow);
            session
                .renderer
                .set_fire_bounds_precompute(precompute_fire_bounds);
            session
                .renderer
                .set_geometry_rendering(!disable_object_culling, !disable_instancing);
            session
                .renderer
                .set_legacy_smoke_bind_layout_for_benchmark(legacy_smoke_bind_layout);
            session.renderer.set_shading_diagnostics(shading_counters);
            session.step(tick);
            let metadata = session.capture(&output, scale)?;
            println!(
                "{}",
                json!({"capture":output,"metadata":output.with_extension("json"),"tick":metadata["tick"],"capabilities":metadata["capabilities"]})
            );
        }
        Command::Benchmark {
            options,
            mode,
            disable_gpu_timing,
            force_shadow_redraw,
            disable_tile_lists,
            force_tile_overflow,
            precompute_fire_bounds,
            disable_object_culling,
            disable_instancing,
            shading_counter_sampling,
            simulation_steps_per_frame,
            moving_caster,
            caster_orbit_radius,
            caster_orbit_period,
            route,
            duration,
            warmup,
            output,
        } => benchmark(
            &options,
            &mode,
            BenchmarkSettings {
                disable_gpu_timing,
                force_shadow_redraw,
                tile_lists_enabled: !disable_tile_lists,
                force_tile_overflow,
                precompute_fire_bounds,
                object_culling_enabled: !disable_object_culling,
                instancing_enabled: !disable_instancing,
                shading_counter_sampling,
                simulation_steps_per_frame,
                simulation_batching_enabled: !options.disable_simulation_batching,
            },
            BenchmarkRoute {
                id: &route,
                caster_motion: CasterMotion {
                    object_id: moving_caster.as_deref(),
                    radius: caster_orbit_radius,
                    period: caster_orbit_period,
                },
            },
            duration,
            warmup,
            &output,
        )?,
        Command::BenchmarkNative {
            options,
            force_shadow_redraw,
            disable_tile_lists,
            precompute_fire_bounds,
            disable_object_culling,
            disable_instancing,
            legacy_smoke_globals_upload,
            legacy_smoke_bind_layout,
            moving_caster,
            caster_orbit_radius,
            caster_orbit_period,
            route,
            duration,
            warmup,
            output,
        } => window::benchmark_native(
            options,
            window::NativeBenchmarkSettings {
                route,
                duration,
                warmup,
                output,
                force_shadow_redraw,
                tile_lists_enabled: !disable_tile_lists,
                precompute_fire_bounds,
                object_culling_enabled: !disable_object_culling,
                instancing_enabled: !disable_instancing,
                legacy_smoke_globals_upload,
                legacy_smoke_bind_layout,
                moving_caster,
                caster_orbit_radius,
                caster_orbit_period,
            },
        )?,
        Command::Serve { options } => {
            use std::io::{BufRead, Write};
            let mut session = headless(&options)?;
            session.paused = true;
            diagnostics::log("ready", session.renderer.capabilities());
            for line in std::io::stdin().lock().lines() {
                let line = line?;
                println!("{}", window::process_line(&mut session, &line));
                std::io::stdout().flush()?;
            }
        }
    }
    Ok(())
}
pub fn resolve_path(path: &Path) -> PathBuf {
    if path.is_absolute() || path.exists() {
        return path.to_path_buf();
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for root in [dir.to_path_buf(), dir.join("../Resources")] {
                let p = root.join(path);
                if p.exists() {
                    return p;
                }
            }
        }
    }
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(path)
}
pub fn prepare(options: &Options) -> Result<(Scene, PathBuf, PathBuf)> {
    let path = resolve_path(&options.scene);
    let mut scene = Scene::load(&path)?;
    if options.compact_hdr {
        scene.render.compact_hdr = true;
    }
    if options.optical_no_copy {
        scene.render.optical_no_copy = true;
    }
    if let Some(profile) = &options.effect_profile {
        scene.emitters[0].effect_profile = profile.clone();
    }
    if let Some(res) = &options.resolution {
        scene.render.resolution = match res.as_str() {
            "320x180" => [320, 180],
            "480x270" => [480, 270],
            "640x360" => [640, 360],
            "960x540" => [960, 540],
            _ => bail!("resolution: choose 320x180, 480x270 640x360 or 960x540"),
        };
    }
    if let Some(resolution) = options.absorption_cache_resolution {
        if !matches!(resolution, 8 | 16) {
            bail!("absorption-cache-resolution: choose 8 or 16");
        }
        scene.render.absorption_cache_resolution = resolution;
    }
    if let Some(experiments) = &options.experiments {
        for e in experiments.split(',') {
            match e {
                "pixel_cluster_lighting" => scene.render.experiments.pixel_cluster_lighting = true,
                "stable_smoke_detail" => scene.render.experiments.stable_smoke_detail = true,
                "connected_motion" => scene.render.experiments.connected_motion = true,
                "projected_detail_lod" => scene.render.experiments.projected_detail_lod = true,
                "smoke_absorption_cache" => scene.render.experiments.smoke_absorption_cache = true,
                "optical_surface_reuse" => scene.render.experiments.optical_surface_reuse = true,
                "all" => {
                    scene.render.experiments.pixel_cluster_lighting = true;
                    scene.render.experiments.stable_smoke_detail = true;
                    scene.render.experiments.connected_motion = true;
                    scene.render.experiments.projected_detail_lod = true;
                    scene.render.experiments.smoke_absorption_cache = true;
                    scene.render.experiments.optical_surface_reuse = true;
                }
                _ => bail!("experiments: unknown '{e}'"),
            }
        }
    }
    scene.validate(path.parent().unwrap_or(Path::new(".")))?;
    let shaders = options.shaders.clone().unwrap_or_else(|| {
        let packaged = resolve_path(Path::new("shaders"));
        if packaged.is_dir() {
            packaged
        } else {
            resolve_path(Path::new("crates/engine/src/render/shaders"))
        }
    });
    Ok((scene, path, shaders))
}
pub fn headless(options: &Options) -> Result<Session> {
    headless_with_timing(options, true)
}
fn headless_with_timing(options: &Options, enable_timestamps: bool) -> Result<Session> {
    let (scene, path, shaders) = prepare(options)?;
    let instance = render::instance();
    let renderer = pollster::block_on(render::Renderer::new_with_timing_and_rg16_fallback(
        &instance,
        None,
        &scene,
        path.parent().unwrap_or(Path::new(".")),
        shaders,
        enable_timestamps,
        options.force_rg16_fallback,
    ))?;
    let mut session = Session::new(scene, path, renderer, options.seed);
    session.set_simulation_batching(!options.disable_simulation_batching);
    session.execute("set_camera", json!({"id":options.camera}))?;
    Ok(session)
}

pub(crate) fn update_benchmark_caster(
    session: &mut Session,
    caster: Option<&(String, f32)>,
    frame: u32,
    motion: CasterMotion<'_>,
    center_xz: [f32; 2],
) -> Result<Option<[f32; 3]>> {
    let Some((id, height)) = caster else {
        return Ok(None);
    };
    let angle = std::f32::consts::TAU * (frame as f32 / 60.) / motion.period;
    let position = [
        center_xz[0] + motion.radius * angle.cos(),
        *height,
        center_xz[1] + motion.radius * angle.sin(),
    ];
    session.execute("set_object_transform", json!({"id":id,"position":position}))?;
    Ok(Some(position))
}

fn benchmark(
    options: &Options,
    mode: &str,
    settings: BenchmarkSettings,
    benchmark_route: BenchmarkRoute<'_>,
    duration: f32,
    warmup: f32,
    path: &Path,
) -> Result<()> {
    if !matches!(mode, "serial" | "buffered") {
        bail!("mode: expected serial or buffered");
    }
    let gpu_timing_enabled = !settings.disable_gpu_timing && !settings.shading_counter_sampling;
    if !duration.is_finite()
        || !(0.1..=600.).contains(&duration)
        || !warmup.is_finite()
        || !(0.0..=120.).contains(&warmup)
    {
        bail!("duration: expected 0.1..600 seconds; warmup: expected 0..120 seconds");
    }
    if !(1..=60).contains(&settings.simulation_steps_per_frame) {
        bail!("simulation-steps-per-frame: expected 1..60");
    }
    let caster_motion = benchmark_route.caster_motion;
    if !caster_motion.radius.is_finite()
        || !(0.1..=100.).contains(&caster_motion.radius)
        || !caster_motion.period.is_finite()
        || !(0.1..=600.).contains(&caster_motion.period)
    {
        bail!("caster orbit: radius must be 0.1..100 and period 0.1..600 seconds");
    }
    let setup_started = Instant::now();
    let mut session = headless_with_timing(options, gpu_timing_enabled)?;
    session
        .renderer
        .set_force_shadow_redraw(settings.force_shadow_redraw);
    session
        .renderer
        .set_tile_lists(settings.tile_lists_enabled, settings.force_tile_overflow);
    session
        .renderer
        .set_fire_bounds_precompute(settings.precompute_fire_bounds);
    session
        .renderer
        .set_geometry_rendering(settings.object_culling_enabled, settings.instancing_enabled);
    let setup_seconds = setup_started.elapsed().as_secs_f64();
    let route = session
        .scene
        .routes
        .iter()
        .find(|r| r.id == benchmark_route.id)
        .with_context(|| format!("route '{}': unknown ID", benchmark_route.id))?
        .clone();
    let base = session.camera.clone();
    let moving_caster = caster_motion
        .object_id
        .map(|id| {
            session
                .scene
                .objects
                .iter()
                .find(|object| object.id == id)
                .map(|object| (id.to_string(), object.position[1]))
                .with_context(|| format!("moving caster '{id}': unknown object ID"))
        })
        .transpose()?;
    let orbit_center = session
        .scene
        .emitters
        .first()
        .map(|emitter| [emitter.position[0], emitter.position[2]])
        .unwrap_or([0., 0.]);
    let steps_per_frame = settings.simulation_steps_per_frame;
    let warmup_ticks = (warmup * 60.).ceil() as u32;
    let warmup_frames = warmup_ticks.div_ceil(steps_per_frame);
    for _ in 0..warmup_frames {
        let route_tick = session.tick as u32;
        update_benchmark_caster(
            &mut session,
            moving_caster.as_ref(),
            route_tick,
            caster_motion,
            orbit_center,
        )?;
        session.camera = route.camera_at(route_tick as f32 / 60., &base);
        session.begin_measurement_frame();
        if settings.simulation_batching_enabled {
            session.step(steps_per_frame);
        } else {
            session.step_unbatched(steps_per_frame);
        }
        session.render();
        session.renderer.poll_timing(true);
        session.renderer.take_gpu_timing_samples();
        session.renderer.take_gpu_compute_timing_samples();
    }
    let duration_ticks = (duration * 60.).ceil() as u32;
    let count = duration_ticks.div_ceil(steps_per_frame);
    let counter_sample_frames = if settings.shading_counter_sampling && count > 0 {
        [0, count / 2, count - 1]
            .into_iter()
            .collect::<std::collections::BTreeSet<_>>()
    } else {
        std::collections::BTreeSet::new()
    };
    let mut samples = Vec::with_capacity(count as usize);
    let mut shading_counter_samples = Vec::with_capacity(counter_sample_frames.len());
    let mut gpu_samples = Vec::with_capacity(count as usize);
    let mut gpu_compute_samples = Vec::with_capacity(count as usize);
    let start = Instant::now();
    for frame in 0..count {
        let started = Instant::now();
        let route_frame = if moving_caster.is_some() {
            warmup_ticks + frame * steps_per_frame
        } else {
            frame * steps_per_frame
        };
        let caster_position = update_benchmark_caster(
            &mut session,
            moving_caster.as_ref(),
            route_frame,
            caster_motion,
            orbit_center,
        )?;
        session.camera = route.camera_at(route_frame as f32 / 60., &base);
        session.begin_measurement_frame();
        let capture_counters = counter_sample_frames.contains(&frame);
        session.renderer.set_shading_diagnostics(capture_counters);
        let sim = Instant::now();
        if settings.simulation_batching_enabled {
            session.step(steps_per_frame);
        } else {
            session.step_unbatched(steps_per_frame);
        }
        let simulation_cpu_ms = sim.elapsed().as_secs_f64() * 1000.;
        session.render();
        if capture_counters {
            let counters = session.renderer.read_shading_counters()?;
            shading_counter_samples.push(json!({
                "frame":frame,
                "route_frame":route_frame,
                "tick":session.tick,
                "camera":{"position":session.camera.position,"target":session.camera.target},
                "moving_caster_position":caster_position,
                "counters":counters
            }));
            session.renderer.set_shading_diagnostics(false);
        }
        session.renderer.poll_timing(mode == "serial");
        gpu_samples.extend(session.renderer.take_gpu_timing_samples());
        gpu_compute_samples.extend(session.renderer.take_gpu_compute_timing_samples());
        let metrics = &session.renderer.metrics;
        samples.push(json!({
            "frame":frame,
            "route_tick":route_frame,
            "camera_position":session.camera.position,
            "camera_target":session.camera.target,
            "simulation_steps_requested":steps_per_frame,
            "moving_caster_position":caster_position,
            "render_frame":metrics.frame,
            "tick":session.tick,
            "frame_work_ms":started.elapsed().as_secs_f64()*1000.,
            "simulation_cpu_ms":simulation_cpu_ms,
            "cpu_simulation_submit_ms":metrics.cpu_simulation_submit_ms,
            "cpu_simulation_encode_ms":metrics.cpu_simulation_encode_ms,
            "cpu_queue_submit_ms":metrics.cpu_queue_submit_ms,
            "cpu_steps":metrics.cpu_steps_this_frame,
            "cpu_simulation_submissions":metrics.cpu_simulation_submissions_this_frame,
            "cpu_encode_ms":metrics.cpu_encode_ms,
            "cpu_tile_list_encode_ms":metrics.cpu_tile_list_encode_ms,
            "geometry_rendering":{
                "cpu_culling_ms":metrics.cpu_object_culling_ms,
                "culling_enabled":metrics.object_culling_enabled,
                "instancing_enabled":metrics.object_instancing_enabled,
                "camera_objects_considered":metrics.camera_objects_considered,
                "camera_objects_visible":metrics.camera_objects_visible,
                "camera_draw_batches":metrics.camera_draw_batches,
                "camera_vertices_submitted":metrics.camera_vertices_submitted,
                "optical_draw_batches":metrics.optical_draw_batches,
                "surface_lighting_reuse_enabled":metrics.optical_surface_reuse_enabled,
                "shadow_objects_visible":metrics.shadow_objects_visible,
                "shadow_draw_batches":metrics.shadow_draw_batches,
                "shadow_vertices_submitted":metrics.shadow_vertices_submitted
            },
            "cpu_shadow_encode_ms":metrics.cpu_shadow_encode_ms,
            "cpu_upload_ms":metrics.cpu_upload_ms,
            "smoke_config_uploads":metrics.smoke_config_uploads_this_frame,
            "smoke_config_upload_bytes":metrics.smoke_config_upload_bytes_this_frame,
            "globals_uploads":metrics.globals_uploads_this_frame,
            "globals_upload_bytes":metrics.globals_upload_bytes_this_frame,
            "gpu_render_ms":metrics.gpu_ms,
            "gpu_passes_ms":metrics.gpu_passes_ms,
            "gpu_timing_frame":metrics.gpu_timing_frame,
            "gpu_samples_skipped":metrics.gpu_samples_skipped,
            "gpu_samples_late":metrics.gpu_samples_late,
            "shadow_cache_hit":metrics.shadow_cache_hit,
            "shadow_redrawn":metrics.shadow_redrawn,
            "shadow_cache_resident":metrics.shadow_cache_resident,
            "shadow_maps_redrawn":metrics.shadow_maps_redrawn,
            "shadow_dirty_faces":metrics.shadow_dirty_faces,
            "shadow_dirty_reason":metrics.shadow_dirty_reason,
            "tile_count":metrics.tile_count,
            "tile_list_bytes":metrics.tile_list_bytes,
            "tile_lists_enabled":metrics.tile_lists_enabled,
            "tile_overflow_forced":metrics.tile_overflow_forced,
            "tile_candidates":metrics.tile_candidates,
            "tile_overflow_tiles":metrics.tile_overflow_tiles,
            "tile_max_occupancy":metrics.tile_max_occupancy,
            "tile_stats_frame":metrics.tile_stats_frame,
            "gpu_tile_list_ms":metrics.gpu_tile_list_ms,
            "smoke_absorption_cache":{
                "enabled":metrics.smoke_absorption_cache_enabled,
                "cpu_build_ms":metrics.cpu_absorption_cache_ms,
                "gpu_build_ms":metrics.gpu_absorption_cache_ms
            },
            "fire_primitives":metrics.fire_primitives,
            "projected_detail":{
                "cpu_ms":metrics.projected_detail_cpu_ms,
                "enabled":metrics.projected_detail_lod_enabled,
                "height_px":metrics.projected_fire_height_px,
                "tier":metrics.fire_lod_level,
                "segments_full":metrics.fire_segments_full,
                "segments_rendered":metrics.fire_segments_rendered,
                "primitives_full":metrics.fire_primitives_full,
                "primitives_rendered":metrics.fire_primitives_rendered
            },
            "flame_fragments":metrics.flame_fragments,
            "embers":metrics.embers,
            "particle_lights":metrics.particle_lights
        }));
        if frame % 600 == 0 {
            diagnostics::log("benchmark_progress", json!({"frame":frame,"total":count}));
        }
    }
    let submission_wall_seconds = start.elapsed().as_secs_f64();
    if mode == "buffered" {
        session.renderer.device.poll(wgpu::Maintain::Wait);
        session.renderer.poll_timing(true);
        gpu_samples.extend(session.renderer.take_gpu_timing_samples());
        gpu_compute_samples.extend(session.renderer.take_gpu_compute_timing_samples());
    }
    let wall_seconds = start.elapsed().as_secs_f64();
    let summary = |key: &str| {
        let v = samples
            .iter()
            .filter_map(|v| {
                key.split('.')
                    .try_fold(v, |value, part| value.get(part))
                    .and_then(Value::as_f64)
            })
            .collect::<Vec<_>>();
        json!({"median_ms":diagnostics::percentile(&v,0.5),"p95_ms":diagnostics::percentile(&v,0.95),"samples":v.len()})
    };
    let stage_names = [
        "shadow_maps",
        "opaque_geometry",
        "atmosphere_fire",
        "optical_resolve",
        "post",
        "tile_list_build",
        "smoke_absorption_cache",
    ];
    let gpu_stages = stage_names
        .iter()
        .map(|name| {
            let values = gpu_samples
                .iter()
                .filter_map(|sample| sample.passes_ms.get(*name).copied())
                .collect::<Vec<_>>();
            ((*name).to_string(), timing_summary(&values))
        })
        .collect::<serde_json::Map<_, _>>();
    let smoke_values = gpu_compute_samples
        .iter()
        .map(|sample| sample.elapsed_ms)
        .collect::<Vec<_>>();
    let mut gpu_stages = gpu_stages;
    gpu_stages.insert("smoke_compute".into(), timing_summary(&smoke_values));
    let total_frames = samples.len();
    let timing_frames = gpu_samples.len();
    let gpu_total_values = gpu_samples
        .iter()
        .map(|sample| sample.total_ms)
        .collect::<Vec<_>>();
    let optical_active = session.scene.materials.iter().any(|material| {
        material.metallic > 0. || material.reflectivity > 0. || material.transmission > 0.
    });
    let capabilities = session.renderer.capabilities();
    let cache_hits = samples
        .iter()
        .filter(|sample| sample["shadow_cache_hit"] == true)
        .count();
    let shadow_redraws = samples
        .iter()
        .filter(|sample| sample["shadow_redrawn"] == true)
        .count();
    let shadow_maps_redrawn = samples
        .iter()
        .filter_map(|sample| sample["shadow_maps_redrawn"].as_u64())
        .sum::<u64>();
    let shadow_faces_redrawn = (0..7)
        .map(|face| {
            samples
                .iter()
                .filter(|sample| sample["shadow_dirty_faces"][face] == true)
                .count()
        })
        .collect::<Vec<_>>();
    let shadow_draw_calls_per_frame = if total_frames == 0 {
        0.
    } else {
        samples
            .iter()
            .map(|sample| {
                if sample["shadow_redrawn"] == true {
                    sample["geometry_rendering"]["shadow_draw_batches"]
                        .as_array()
                        .map_or(0, |values| {
                            values.iter().filter_map(Value::as_u64).sum::<u64>()
                        })
                } else {
                    0
                }
            })
            .sum::<u64>() as f64
            / total_frames as f64
    };
    let unshared_vertices = session
        .renderer
        .object_draw_ranges()
        .iter()
        .map(|object| object.vertex_count as u64)
        .sum::<u64>();
    let camera_draw_batches_median = samples
        .iter()
        .filter_map(|sample| sample["geometry_rendering"]["camera_draw_batches"].as_f64())
        .collect::<Vec<_>>();
    let workload_counts = json!({
        "objects":session.scene.objects.len(),
        "materials":session.scene.materials.len(),
        "authored_lights":session.scene.lights.len(),
        "emitters":session.scene.emitters.len(),
        "vertices":capabilities["vertices"],
        "unshared_vertex_count":unshared_vertices,
        "shared_mesh_count":capabilities["shared_mesh_count"],
        "shadow_draw_calls_per_frame":shadow_draw_calls_per_frame,
        "shadow_draw_calls_when_redrawn": if shadow_redraws == 0 { 0. } else { shadow_draw_calls_per_frame * total_frames as f64 / shadow_redraws as f64 },
        "opaque_geometry_draw_calls_per_frame":diagnostics::percentile(&camera_draw_batches_median, 0.5),
        "effect_draw_calls_per_frame":1,
        "optical_draw_calls_per_frame":u32::from(optical_active),
        "post_draw_calls_per_frame":1,
        "draw_calls_per_frame":shadow_draw_calls_per_frame + diagnostics::percentile(&camera_draw_batches_median, 0.5) + 2. + f64::from(optical_active),
        "fire_primitives_last_frame":session.renderer.metrics.fire_primitives,
        "particle_lights_last_frame":session.renderer.metrics.particle_lights
    });
    let mut shadow_dirty_reasons = std::collections::BTreeMap::<String, usize>::new();
    for sample in &samples {
        if let Some(reason) = sample["shadow_dirty_reason"].as_str() {
            *shadow_dirty_reasons.entry(reason.to_string()).or_default() += 1;
        }
    }
    let mut tile_candidates = [0u64; 4];
    let mut tile_overflow_tiles = [0u64; 4];
    let mut tile_max_occupancy = [0u64; 4];
    let mut tile_stat_frames = 0u64;
    let mut seen_tile_stat_frames = std::collections::BTreeSet::new();
    for sample in &samples {
        let Some(frame) = sample["tile_stats_frame"].as_u64() else {
            continue;
        };
        if !seen_tile_stat_frames.insert(frame) {
            continue;
        }
        tile_stat_frames += 1;
        for index in 0..4 {
            tile_candidates[index] += sample["tile_candidates"][index].as_u64().unwrap_or(0);
            tile_overflow_tiles[index] +=
                sample["tile_overflow_tiles"][index].as_u64().unwrap_or(0);
            tile_max_occupancy[index] = tile_max_occupancy[index]
                .max(sample["tile_max_occupancy"][index].as_u64().unwrap_or(0));
        }
    }
    let measured_tile_count = tile_stat_frames * u64::from(session.renderer.metrics.tile_count);
    let tile_categories = diagnostics::TILE_CATEGORY_ORDER;
    let tile_overflow_by_category = tile_categories
        .iter()
        .enumerate()
        .map(|(index, category)| {
            (
                (*category).to_string(),
                json!({
                    "candidate_memberships": tile_candidates[index],
                    "overflow_tiles": tile_overflow_tiles[index],
                    "fallback_rate": if measured_tile_count==0 {0.} else {tile_overflow_tiles[index] as f64/measured_tile_count as f64},
                    "max_candidates_per_tile": tile_max_occupancy[index]
                }),
            )
        })
        .collect::<serde_json::Map<_, _>>();
    let shadow_cache = json!({
        "force_redraw":settings.force_shadow_redraw,
        "hits":cache_hits,
        "misses":shadow_redraws,
        "redraws":shadow_redraws,
        "shadow_map_count":7,
        "shadow_map_bytes_resident":capabilities["resource_inventory"]["shadow_maps_bytes"],
        "redrawn_shadow_passes":shadow_maps_redrawn,
        "frames_with_redraw":shadow_redraws,
        "face_redraws_by_index":shadow_faces_redrawn,
        "face_order":["sun","+X","-X","+Y","-Y","+Z","-Z"],
        "dirty_reasons":shadow_dirty_reasons
    });
    let report = json!({
        "version":2,
        "scope":if mode == "serial" {"serial offscreen latency benchmark; includes CPU simulation/submission and waits for GPU completion each rendered sample; excludes native presentation, inspector and vsync"} else {"buffered offscreen throughput benchmark; queues rendered samples without a per-sample GPU wait, then waits once to drain; excludes native presentation, inspector and vsync"},
        "aggregation_policy":"GPU pass intervals can overlap on the backend; do not sum stage distributions. gpu_render is the end-to-end shadow-to-post interval.",
        "mode":mode,
        "gpu_timing_enabled":gpu_timing_enabled,
        "performance_data_usable":!settings.shading_counter_sampling,
        "performance_data_note":if settings.shading_counter_sampling {json!("Counter route sampling uses atomic instrumentation at selected frames and omits GPU timestamps; do not use this report for timing conclusions.")} else {Value::Null},
        "shading_counter_sampling":{
            "enabled":settings.shading_counter_sampling,
            "sample_frames":counter_sample_frames,
            "samples":shading_counter_samples
        },
        "scene":session.scene,
        "seed":options.seed,
        "route":route,
        "route_seconds":duration,
        "moving_caster":moving_caster.as_ref().map(|(id, height)| json!({
            "object":id,
            "orbit_center_xz":orbit_center,
            "height":height,
            "radius":caster_motion.radius,
            "period_seconds":caster_motion.period,
            "sample_hz":60,
            "note":"Deterministic circular transform updates use the shared Session operation before each route frame."
        })),
        "sample_hz":60. / steps_per_frame as f64,
        "warmup_seconds":warmup,
        "warmup_simulation_ticks":warmup_frames * steps_per_frame,
        "duration_simulation_ticks":count * steps_per_frame,
        "simulation_steps_per_frame":steps_per_frame,
        "simulation_batching_enabled":settings.simulation_batching_enabled,
        "simulation_submissions_per_sample":if settings.simulation_batching_enabled {steps_per_frame.div_ceil(render::SIMULATION_BATCH_CAPACITY as u32)} else {steps_per_frame},
        "rendered_samples":count,
        "simulation_ticks_per_second_submitted":(count * steps_per_frame) as f64 / submission_wall_seconds,
        "simulation_ticks_per_second_drained":(count * steps_per_frame) as f64 / wall_seconds,
        "renderer_setup_seconds":setup_seconds,
        "submission_wall_seconds":submission_wall_seconds,
        "wall_seconds":wall_seconds,
        "submitted_frames_per_second":count as f64 / submission_wall_seconds,
        "drained_frames_per_second":count as f64 / wall_seconds,
        "capabilities":capabilities,
        "workload_counts":workload_counts,
        "projected_detail":{
            "enabled":session.scene.render.experiments.projected_detail_lod,
            "cpu_ms":summary("projected_detail.cpu_ms"),
            "projected_height_px":{
                "median":diagnostics::percentile(&samples.iter().filter_map(|s|s["projected_detail"]["height_px"].as_f64()).collect::<Vec<_>>(),0.5),
                "p95":diagnostics::percentile(&samples.iter().filter_map(|s|s["projected_detail"]["height_px"].as_f64()).collect::<Vec<_>>(),0.95)
            },
            "tier_frames":([0u64,1,2].map(|tier| samples.iter().filter(|s|s["projected_detail"]["tier"].as_u64()==Some(tier)).count())),
            "segments_full_median":diagnostics::percentile(&samples.iter().filter_map(|s|s["projected_detail"]["segments_full"].as_f64()).collect::<Vec<_>>(),0.5),
            "segments_rendered_median":diagnostics::percentile(&samples.iter().filter_map(|s|s["projected_detail"]["segments_rendered"].as_f64()).collect::<Vec<_>>(),0.5),
            "primitives_full_median":diagnostics::percentile(&samples.iter().filter_map(|s|s["projected_detail"]["primitives_full"].as_f64()).collect::<Vec<_>>(),0.5),
            "primitives_rendered_median":diagnostics::percentile(&samples.iter().filter_map(|s|s["projected_detail"]["primitives_rendered"].as_f64()).collect::<Vec<_>>(),0.5),
            "note":"Only flame curve segments are reduced. Full deterministic simulation state, bounds and emitted lights are retained; this does not change pixel resolution."
        },
        "smoke_absorption_cache":{
            "enabled":session.scene.render.experiments.smoke_absorption_cache,
            "cpu_build_ms":summary("smoke_absorption_cache.cpu_build_ms"),
            "gpu_build":timing_summary(&samples.iter().filter_map(|s|s["smoke_absorption_cache"]["gpu_build_ms"].as_f64()).collect::<Vec<_>>()),
            "texture_dimensions":[session.scene.render.absorption_cache_resolution,session.scene.render.absorption_cache_resolution,session.scene.render.absorption_cache_resolution],
            "note":"Caches only primary authored fire-light smoke optical depth. Other authored/particle lights and out-of-volume points use direct sampling. Cache rebuilds every rendered frame so paused density/light edits are current."
        },
        "optical_surface_reuse":{
            "enabled":session.scene.render.experiments.optical_surface_reuse,
            "opaque_surface_only":true,
            "optical_resolve_gpu":timing_summary(&samples.iter().filter_map(|s|s["gpu_passes_ms"]["optical_resolve"].as_f64()).collect::<Vec<_>>()),
            "note":"Opaque reflectors recover the same-pixel shaded base from the atmosphere-composited snapshot. Transmissive surfaces retain direct lighting because the opaque pass discards them."
        },
        "shadow_cache":shadow_cache,
        "geometry_rendering":{
            "culling_enabled":settings.object_culling_enabled,
            "instancing_enabled":settings.instancing_enabled,
            "cpu_culling_ms":summary("geometry_rendering.cpu_culling_ms"),
            "camera_objects_considered":session.scene.objects.len(),
            "camera_objects_visible_median":diagnostics::percentile(&samples.iter().filter_map(|sample| sample["geometry_rendering"]["camera_objects_visible"].as_f64()).collect::<Vec<_>>(),0.5),
            "camera_draw_batches_median":diagnostics::percentile(&camera_draw_batches_median,0.5),
            "camera_vertices_submitted_median":diagnostics::percentile(&samples.iter().filter_map(|sample| sample["geometry_rendering"]["camera_vertices_submitted"].as_f64()).collect::<Vec<_>>(),0.5),
            "optical_draw_batches_median":diagnostics::percentile(&samples.iter().filter_map(|sample| sample["geometry_rendering"]["optical_draw_batches"].as_f64()).collect::<Vec<_>>(),0.5),
            "shadow_visible_objects_median_by_map":(0..7).map(|i| diagnostics::percentile(&samples.iter().filter_map(|sample| sample["geometry_rendering"]["shadow_objects_visible"][i].as_f64()).collect::<Vec<_>>(),0.5)).collect::<Vec<_>>(),
            "shadow_draw_batches_median_by_map":(0..7).map(|i| diagnostics::percentile(&samples.iter().filter_map(|sample| sample["geometry_rendering"]["shadow_draw_batches"][i].as_f64()).collect::<Vec<_>>(),0.5)).collect::<Vec<_>>(),
            "shadow_vertices_submitted_median_by_map":(0..7).map(|i| diagnostics::percentile(&samples.iter().filter_map(|sample| sample["geometry_rendering"]["shadow_vertices_submitted"][i].as_f64()).collect::<Vec<_>>(),0.5)).collect::<Vec<_>>(),
            "unique_mesh_count":capabilities["shared_mesh_count"],
            "shared_vertex_count":capabilities["vertices"],
            "unshared_vertex_count":unshared_vertices
        },
        "tile_lists":{
            "enabled":settings.tile_lists_enabled,
            "force_overflow":settings.force_tile_overflow,
            "fire_bounds_precompute":settings.precompute_fire_bounds,
            "tile_size":capabilities["tile_lists"]["tile_size"],
            "capacity_bytes":capabilities["tile_lists"]["list_bytes"],
            "cpu_encode_ms":summary("cpu_tile_list_encode_ms"),
            "gpu_build":timing_summary(&samples.iter().filter_map(|sample| sample["gpu_tile_list_ms"].as_f64()).collect::<Vec<_>>()),
            "stats_frames":tile_stat_frames,
            "overflow_by_category":tile_overflow_by_category,
            "note":"Stats are asynchronous and frame-tagged. Oversized categories and forced overflow use exhaustive shader evaluation."
        },
        "cpu_tile_list_encode":summary("cpu_tile_list_encode_ms"),
        "smoke_config_uploads":summary("smoke_config_uploads"),
        "smoke_config_upload_bytes":summary("smoke_config_upload_bytes"),
        "globals_uploads":summary("globals_uploads"),
        "globals_upload_bytes":summary("globals_upload_bytes"),
        "timing_coverage":{"gpu_timing_requested":gpu_timing_enabled,"gpu_timestamps_supported":session.renderer.metrics.gpu_timestamp_supported,"unavailable_reason":if settings.shading_counter_sampling {json!("disabled for diagnostic counter sampling")} else if settings.disable_gpu_timing {json!("disabled by request")} else if session.renderer.metrics.gpu_timestamp_supported {Value::Null} else {json!("adapter does not support TIMESTAMP_QUERY")},"timed_frames":timing_frames,"rendered_frames":total_frames,"smoke_compute_samples":gpu_compute_samples.len(),"skipped_samples":session.renderer.metrics.gpu_samples_skipped,"skipped_compute_samples":session.renderer.metrics.gpu_compute_samples_skipped,"late_samples":session.renderer.metrics.gpu_samples_late},
        "queue_latency":{"value_ms":null,"reason":"wgpu timestamp queries have no calibrated CPU clock mapping; readback latency is reported separately"},
        "frame_work":summary("frame_work_ms"),
        "cpu_encode":summary("cpu_encode_ms"),
        "cpu_shadow_encode":summary("cpu_shadow_encode_ms"),
        "cpu_upload":summary("cpu_upload_ms"),
        "simulation_cpu":summary("cpu_simulation_submit_ms"),
        "simulation_encode_cpu":summary("cpu_simulation_encode_ms"),
        "queue_submit_cpu":summary("cpu_queue_submit_ms"),
        "gpu_render":timing_summary(&gpu_total_values),
        "gpu_stages":gpu_stages,
        "gpu_timing_samples":gpu_samples,
        "gpu_smoke_compute_samples":gpu_compute_samples,
        "samples":samples
    });
    if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(path, serde_json::to_vec_pretty(&report)?)?;
    println!(
        "{}",
        json!({"report":path,"frame_work":report["frame_work"],"gpu_render":report["gpu_render"],"capabilities":report["capabilities"]})
    );
    Ok(())
}

fn timing_summary(values: &[f64]) -> Value {
    if values.is_empty() {
        return json!({"median_ms":null,"p95_ms":null,"samples":0});
    }
    json!({"median_ms":diagnostics::percentile(values,0.5),"p95_ms":diagnostics::percentile(values,0.95),"samples":values.len()})
}
