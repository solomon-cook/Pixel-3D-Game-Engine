mod window;

use anyhow::{bail, Context, Result};
use clap::{Args, Parser, Subcommand};
use pixel_engine::{
    assets, diagnostics, render,
    scene::Scene,
    session::{description, Session},
};
use serde_json::json;
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
        #[arg(long, default_value_t = 300)]
        tick: u32,
        #[arg(long, default_value = "artifacts/capture.png")]
        output: PathBuf,
        #[arg(long, default_value_t = 4)]
        scale: u32,
    },
    /// Sample a moving route at 60 Hz offscreen, without screenshots/UI/vsync.
    Benchmark {
        #[command(flatten)]
        options: Options,
        #[arg(long, default_value = "clearing-orbit")]
        route: String,
        #[arg(long, default_value_t = 120.)]
        duration: f32,
        #[arg(long, default_value_t = 10.)]
        warmup: f32,
        #[arg(long, default_value = "artifacts/benchmark.json")]
        output: PathBuf,
    },
    /// JSON-lines protocol without a window, using the real GPU renderer.
    Serve {
        #[command(flatten)]
        options: Options,
    },
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
            tick,
            output,
            scale,
        } => {
            if tick > 36000 {
                bail!("tick: maximum 36000");
            }
            let mut session = headless(&options)?;
            session.step(tick);
            let metadata = session.capture(&output, scale)?;
            println!(
                "{}",
                json!({"capture":output,"metadata":output.with_extension("json"),"tick":metadata["tick"],"capabilities":metadata["capabilities"]})
            );
        }
        Command::Benchmark {
            options,
            route,
            duration,
            warmup,
            output,
        } => benchmark(&options, &route, duration, warmup, &output)?,
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
    if let Some(experiments) = &options.experiments {
        for e in experiments.split(',') {
            match e {
                "pixel_cluster_lighting" => scene.render.experiments.pixel_cluster_lighting = true,
                "stable_smoke_detail" => scene.render.experiments.stable_smoke_detail = true,
                "connected_motion" => scene.render.experiments.connected_motion = true,
                "all" => {
                    scene.render.experiments.pixel_cluster_lighting = true;
                    scene.render.experiments.stable_smoke_detail = true;
                    scene.render.experiments.connected_motion = true;
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
    let (scene, path, shaders) = prepare(options)?;
    let instance = render::instance();
    let renderer = pollster::block_on(render::Renderer::new(
        &instance,
        None,
        &scene,
        path.parent().unwrap_or(Path::new(".")),
        shaders,
    ))?;
    let mut session = Session::new(scene, path, renderer, options.seed);
    session.execute("set_camera", json!({"id":options.camera}))?;
    Ok(session)
}
fn benchmark(
    options: &Options,
    route_id: &str,
    duration: f32,
    warmup: f32,
    path: &Path,
) -> Result<()> {
    if !duration.is_finite()
        || !(0.1..=600.).contains(&duration)
        || !warmup.is_finite()
        || !(0.0..=120.).contains(&warmup)
    {
        bail!("duration: expected 0.1..600 seconds; warmup: expected 0..120 seconds");
    }
    let mut session = headless(options)?;
    let route = session
        .scene
        .routes
        .iter()
        .find(|r| r.id == route_id)
        .with_context(|| format!("route '{route_id}': unknown ID"))?
        .clone();
    let base = session.camera.clone();
    for tick in 0..(warmup * 60.) as u32 {
        session.camera = route.camera_at(tick as f32 / 60., &base);
        session.step(1);
        session.render();
        session.renderer.device.poll(wgpu::Maintain::Wait);
    }
    session.renderer.poll_timing(true);
    let count = (duration * 60.).ceil() as u32;
    let mut samples = Vec::with_capacity(count as usize);
    let start = Instant::now();
    for frame in 0..count {
        let started = Instant::now();
        session.camera = route.camera_at(frame as f32 / 60., &base);
        let sim = Instant::now();
        session.step(1);
        let simulation_cpu_ms = sim.elapsed().as_secs_f64() * 1000.;
        session.render();
        session.renderer.poll_timing(true);
        samples.push(json!({"frame":frame,"tick":session.tick,"frame_work_ms":started.elapsed().as_secs_f64()*1000.,"simulation_cpu_ms":simulation_cpu_ms,"cpu_encode_ms":session.renderer.metrics.cpu_encode_ms,"gpu_render_ms":session.renderer.metrics.gpu_ms}));
        if frame % 600 == 0 {
            diagnostics::log("benchmark_progress", json!({"frame":frame,"total":count}));
        }
    }
    let summary = |key: &str| {
        let v = samples
            .iter()
            .filter_map(|v| v[key].as_f64())
            .collect::<Vec<_>>();
        json!({"median_ms":diagnostics::percentile(&v,0.5),"p95_ms":diagnostics::percentile(&v,0.95),"samples":v.len()})
    };
    let report = json!({"version":1,"scope":"offscreen renderer; includes simulation submission and synchronous GPU completion; excludes presentation, inspector and vsync","scene":session.scene,"seed":options.seed,"route":route,"route_seconds":duration,"sample_hz":60,"warmup_seconds":warmup,"wall_seconds":start.elapsed().as_secs_f64(),"capabilities":session.renderer.capabilities(),"frame_work":summary("frame_work_ms"),"cpu_encode":summary("cpu_encode_ms"),"simulation_cpu":summary("simulation_cpu_ms"),"gpu_render":summary("gpu_render_ms"),"samples":samples});
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
