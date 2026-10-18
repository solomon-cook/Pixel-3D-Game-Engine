use crate::{prepare, CasterMotion, Options};
use anyhow::{Context, Result};
use glam::Vec3;
use pixel_engine::{
    diagnostics,
    render::{self, Presenter},
    scene::{Camera, Route},
    session::{Request, Session},
};
use serde_json::{json, Value};
use std::{
    collections::{HashSet, VecDeque},
    io::{BufRead, Write},
    sync::{mpsc, Arc},
    time::Instant,
};
use winit::{
    application::ApplicationHandler,
    dpi::LogicalSize,
    event::{DeviceEvent, ElementState, MouseButton, WindowEvent},
    event_loop::{ActiveEventLoop, EventLoop},
    keyboard::{KeyCode, PhysicalKey},
    window::{Fullscreen, Window},
};

pub fn process_line(session: &mut Session, line: &str) -> String {
    let response = match serde_json::from_str::<Value>(line) {
        Ok(value) => {
            let id = value.get("id").cloned().unwrap_or(Value::Null);
            match serde_json::from_value::<Request>(value) {
                Ok(request) => return serde_json::to_string(&session.dispatch(request)).unwrap(),
                Err(error) => {
                    json!({"id":id,"error":{"code":"invalid_request","message":error.to_string()}})
                }
            }
        }
        Err(error) => json!({"id":null,"error":{"code":"parse_error","message":error.to_string()}}),
    };
    response.to_string()
}
struct Native {
    window: Arc<Window>,
    surface: wgpu::Surface<'static>,
    config: wgpu::SurfaceConfiguration,
    session: Session,
    presenter: Presenter,
    egui: egui::Context,
    egui_state: egui_winit::State,
    egui_renderer: egui_wgpu::Renderer,
    last: Instant,
    accumulator: f64,
    keys: HashSet<KeyCode>,
    looking: bool,
    inspector: bool,
    occluded: bool,
    benchmark: Option<NativeBenchmark>,
    native_gpu_timing: Option<NativeGpuTiming>,
}
struct NativeBenchmarkConfig {
    route: String,
    duration: f64,
    warmup: f64,
    output: std::path::PathBuf,
    force_shadow_redraw: bool,
    tile_lists_enabled: bool,
    precompute_fire_bounds: bool,
    object_culling_enabled: bool,
    instancing_enabled: bool,
    moving_caster: Option<String>,
    caster_orbit_radius: f32,
    caster_orbit_period: f32,
    launch_started: Instant,
}
pub struct NativeBenchmarkSettings {
    pub route: String,
    pub duration: f32,
    pub warmup: f32,
    pub output: std::path::PathBuf,
    pub force_shadow_redraw: bool,
    pub tile_lists_enabled: bool,
    pub precompute_fire_bounds: bool,
    pub object_culling_enabled: bool,
    pub instancing_enabled: bool,
    pub moving_caster: Option<String>,
    pub caster_orbit_radius: f32,
    pub caster_orbit_period: f32,
}
struct NativeBenchmark {
    config: NativeBenchmarkConfig,
    route: Route,
    base_camera: Camera,
    moving_caster: Option<(String, f32)>,
    orbit_center_xz: [f32; 2],
    started: Instant,
    setup_seconds: f64,
    samples: Vec<Value>,
    gpu_samples: Vec<render::GpuTimingSample>,
    gpu_compute_samples: Vec<render::GpuComputeTimingSample>,
    gpu_presentation_samples: Vec<NativeGpuTimingSample>,
    finished: bool,
}
#[derive(Clone, serde::Serialize)]
struct NativeGpuTimingSample {
    frame: u64,
    presenter_ms: f64,
    inspector_ms: f64,
    readback_latency_ms: f64,
}
struct NativeGpuTiming {
    slots: Vec<NativeGpuTimingSlot>,
    next: usize,
    completed: VecDeque<NativeGpuTimingSample>,
    skipped: u64,
}
struct NativeGpuTimingSlot {
    query: wgpu::QuerySet,
    resolve: wgpu::Buffer,
    read: wgpu::Buffer,
    pending: Option<mpsc::Receiver<std::result::Result<(), wgpu::BufferAsyncError>>>,
    frame: u64,
    submitted_at: Option<Instant>,
}
impl NativeGpuTiming {
    fn new(device: &wgpu::Device) -> Self {
        let slots = (0..3)
            .map(|_| NativeGpuTimingSlot {
                query: device.create_query_set(&wgpu::QuerySetDescriptor {
                    label: Some("native presentation timestamps"),
                    ty: wgpu::QueryType::Timestamp,
                    count: 4,
                }),
                resolve: device.create_buffer(&wgpu::BufferDescriptor {
                    label: Some("native presentation timestamp resolve"),
                    size: 32,
                    usage: wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
                    mapped_at_creation: false,
                }),
                read: device.create_buffer(&wgpu::BufferDescriptor {
                    label: Some("native presentation timestamp readback"),
                    size: 32,
                    usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
                    mapped_at_creation: false,
                }),
                pending: None,
                frame: 0,
                submitted_at: None,
            })
            .collect();
        Self {
            slots,
            next: 0,
            completed: VecDeque::new(),
            skipped: 0,
        }
    }

    fn acquire(&mut self) -> Option<usize> {
        let count = self.slots.len();
        let index = (0..count)
            .map(|offset| (self.next + offset) % count)
            .find(|&index| self.slots[index].pending.is_none());
        if let Some(index) = index {
            self.next = (index + 1) % count;
        } else {
            self.skipped += 1;
        }
        index
    }

    fn query(&self, index: usize) -> &wgpu::QuerySet {
        &self.slots[index].query
    }

    fn resolve_and_map(&mut self, index: usize, frame: u64, encoder: &mut wgpu::CommandEncoder) {
        let slot = &self.slots[index];
        encoder.resolve_query_set(&slot.query, 0..4, &slot.resolve, 0);
        encoder.copy_buffer_to_buffer(&slot.resolve, 0, &slot.read, 0, 32);
        self.slots[index].frame = frame;
    }

    fn submitted(&mut self, index: usize) {
        let slot = &mut self.slots[index];
        let (sender, receiver) = mpsc::channel();
        slot.read
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |result| {
                let _ = sender.send(result);
            });
        slot.submitted_at = Some(Instant::now());
        slot.pending = Some(receiver);
    }

    fn poll(&mut self, device: &wgpu::Device, queue: &wgpu::Queue) {
        device.poll(wgpu::Maintain::Poll);
        for slot in &mut self.slots {
            let Some(receiver) = &slot.pending else {
                continue;
            };
            match receiver.try_recv() {
                Ok(result) => {
                    if result.is_ok() {
                        let view = slot.read.slice(..).get_mapped_range();
                        let times: &[u64] = bytemuck::cast_slice(&view);
                        let period = queue.get_timestamp_period() as f64 / 1_000_000.;
                        let sample = NativeGpuTimingSample {
                            frame: slot.frame,
                            presenter_ms: times[1].saturating_sub(times[0]) as f64 * period,
                            inspector_ms: times[3].saturating_sub(times[2]) as f64 * period,
                            readback_latency_ms: slot
                                .submitted_at
                                .map(|submitted| submitted.elapsed().as_secs_f64() * 1000.)
                                .unwrap_or(0.),
                        };
                        drop(view);
                        slot.read.unmap();
                        if self.completed.len() == 64 {
                            self.completed.pop_front();
                        }
                        self.completed.push_back(sample);
                    }
                    slot.pending = None;
                }
                Err(mpsc::TryRecvError::Empty) => {}
                Err(mpsc::TryRecvError::Disconnected) => {
                    slot.pending = None;
                    self.skipped += 1;
                }
            }
        }
    }

    fn take_completed(&mut self) -> Vec<NativeGpuTimingSample> {
        self.completed.drain(..).collect()
    }
}
struct App {
    options: Options,
    agent: bool,
    paused: bool,
    native: Option<Native>,
    receiver: mpsc::Receiver<String>,
    error: Option<String>,
    benchmark: Option<NativeBenchmarkConfig>,
}
pub fn run(options: Options, agent: bool, paused: bool) -> Result<()> {
    run_inner(options, agent, paused, None)
}

pub fn benchmark_native(options: Options, settings: NativeBenchmarkSettings) -> Result<()> {
    if !settings.duration.is_finite()
        || !(0.1..=600.).contains(&settings.duration)
        || !settings.warmup.is_finite()
        || !(0.0..=120.).contains(&settings.warmup)
        || !settings.caster_orbit_radius.is_finite()
        || settings.caster_orbit_radius <= 0.
        || !settings.caster_orbit_period.is_finite()
        || settings.caster_orbit_period <= 0.
    {
        anyhow::bail!("duration: expected 0.1..600 seconds; warmup: expected 0..120 seconds; caster radius and period must be positive finite values");
    }
    run_inner(
        options,
        false,
        false,
        Some(NativeBenchmarkConfig {
            route: settings.route,
            duration: settings.duration as f64,
            warmup: settings.warmup as f64,
            output: settings.output,
            force_shadow_redraw: settings.force_shadow_redraw,
            tile_lists_enabled: settings.tile_lists_enabled,
            precompute_fire_bounds: settings.precompute_fire_bounds,
            object_culling_enabled: settings.object_culling_enabled,
            instancing_enabled: settings.instancing_enabled,
            moving_caster: settings.moving_caster,
            caster_orbit_radius: settings.caster_orbit_radius,
            caster_orbit_period: settings.caster_orbit_period,
            launch_started: Instant::now(),
        }),
    )
}

fn run_inner(
    options: Options,
    agent: bool,
    paused: bool,
    benchmark: Option<NativeBenchmarkConfig>,
) -> Result<()> {
    let event_loop = EventLoop::<()>::with_user_event().build()?;
    let proxy = event_loop.create_proxy();
    let (send, receiver) = mpsc::channel();
    if agent {
        std::thread::spawn(move || {
            for line in std::io::stdin().lock().lines() {
                match line {
                    Ok(line) => {
                        if send.send(line).is_err() {
                            break;
                        }
                        let _ = proxy.send_event(());
                    }
                    Err(_) => break,
                }
            }
        });
    }
    let mut app = App {
        options,
        agent,
        paused,
        native: None,
        receiver,
        error: None,
        benchmark,
    };
    event_loop.run_app(&mut app)?;
    if let Some(error) = app.error {
        anyhow::bail!(error);
    }
    Ok(())
}
impl App {
    fn service_requests(&mut self, event_loop: &ActiveEventLoop) {
        let Some(n) = &mut self.native else {
            return;
        };
        for line in self.receiver.try_iter() {
            if let Ok(request) = serde_json::from_str::<Request>(&line) {
                if request.method == "shutdown" {
                    println!("{}", json!({"id":request.id,"result":{"shutdown":true}}));
                    let _ = std::io::stdout().flush();
                    event_loop.exit();
                    return;
                }
            }
            println!("{}", n.process_line(&line));
            let _ = std::io::stdout().flush();
        }
    }

    fn init(&mut self, event_loop: &ActiveEventLoop) -> Result<()> {
        let window = Arc::new(
            event_loop.create_window(
                Window::default_attributes()
                    .with_title("Emberwood · Pixel Engine Lab")
                    .with_inner_size(LogicalSize::new(1280., 800.))
                    .with_min_inner_size(LogicalSize::new(640., 400.)),
            )?,
        );
        let instance = render::instance();
        let surface = instance.create_surface(window.clone())?;
        let (scene, path, shaders) = prepare(&self.options)?;
        let renderer = pollster::block_on(render::Renderer::new_with_timing_and_rg16_fallback(
            &instance,
            Some(&surface),
            &scene,
            path.parent().unwrap(),
            shaders,
            true,
            self.options.force_rg16_fallback,
        ))?;
        let size = window.inner_size();
        let mut config = surface
            .get_default_config(&renderer.adapter, size.width.max(1), size.height.max(1))
            .context("surface has no compatible format")?;
        config.format = surface
            .get_capabilities(&renderer.adapter)
            .formats
            .into_iter()
            .find(|f| f.is_srgb())
            .unwrap_or(config.format);
        config.present_mode = wgpu::PresentMode::AutoVsync;
        surface.configure(&renderer.device, &config);
        let presenter = Presenter::new(&renderer, config.format);
        let egui = egui::Context::default();
        egui.set_visuals(egui::Visuals::dark());
        let egui_state = egui_winit::State::new(
            egui.clone(),
            egui::ViewportId::ROOT,
            window.as_ref(),
            Some(window.scale_factor() as f32),
            window.theme(),
            None,
        );
        let egui_renderer =
            egui_wgpu::Renderer::new(&renderer.device, config.format, None, 1, false);
        let mut session = Session::new(scene, path, renderer, self.options.seed);
        session.set_simulation_batching(!self.options.disable_simulation_batching);
        session.paused = self.agent || self.paused;
        session.execute("set_camera", json!({"id":self.options.camera}))?;
        diagnostics::log("ready", session.renderer.capabilities());
        let benchmark = if let Some(config) = self.benchmark.take() {
            session
                .renderer
                .set_force_shadow_redraw(config.force_shadow_redraw);
            session
                .renderer
                .set_tile_lists(config.tile_lists_enabled, false);
            session
                .renderer
                .set_fire_bounds_precompute(config.precompute_fire_bounds);
            session
                .renderer
                .set_geometry_rendering(config.object_culling_enabled, config.instancing_enabled);
            let route = session
                .scene
                .routes
                .iter()
                .find(|route| route.id == config.route)
                .cloned()
                .ok_or_else(|| anyhow::anyhow!("route '{}' is unknown", config.route))?;
            let moving_caster = config
                .moving_caster
                .as_ref()
                .map(|id| {
                    session
                        .scene
                        .objects
                        .iter()
                        .find(|object| object.id == *id)
                        .map(|object| (id.clone(), object.position[1]))
                        .with_context(|| format!("moving caster '{id}': unknown object ID"))
                })
                .transpose()?;
            let orbit_center_xz = session
                .scene
                .emitters
                .first()
                .map(|emitter| [emitter.position[0], emitter.position[2]])
                .unwrap_or([0., 0.]);
            crate::update_benchmark_caster(
                &mut session,
                moving_caster.as_ref(),
                0,
                CasterMotion {
                    object_id: config.moving_caster.as_deref(),
                    radius: config.caster_orbit_radius,
                    period: config.caster_orbit_period,
                },
                orbit_center_xz,
            )?;
            let setup_seconds = config.launch_started.elapsed().as_secs_f64();
            Some(NativeBenchmark {
                config,
                route,
                base_camera: session.camera.clone(),
                moving_caster,
                orbit_center_xz,
                started: Instant::now(),
                setup_seconds,
                samples: Vec::new(),
                gpu_samples: Vec::new(),
                gpu_compute_samples: Vec::new(),
                gpu_presentation_samples: Vec::new(),
                finished: false,
            })
        } else {
            None
        };
        let native_gpu_timing =
            if benchmark.is_some() && session.renderer.metrics.gpu_timestamp_supported {
                Some(NativeGpuTiming::new(&session.renderer.device))
            } else {
                None
            };
        self.native = Some(Native {
            window,
            surface,
            config,
            session,
            presenter,
            egui,
            egui_state,
            egui_renderer,
            last: Instant::now(),
            accumulator: 0.,
            keys: HashSet::new(),
            looking: false,
            inspector: true,
            occluded: false,
            benchmark,
            native_gpu_timing,
        });
        Ok(())
    }
}
impl ApplicationHandler for App {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.native.is_none() {
            if let Err(error) = self.init(event_loop) {
                self.error = Some(format!("{error:#}"));
                event_loop.exit();
            }
        }
    }
    fn user_event(&mut self, event_loop: &ActiveEventLoop, _: ()) {
        self.service_requests(event_loop);
        if let Some(n) = &self.native {
            n.window.request_redraw();
        }
    }
    fn device_event(&mut self, _: &ActiveEventLoop, _: winit::event::DeviceId, event: DeviceEvent) {
        if let Some(n) = &mut self.native {
            if n.looking {
                if let DeviceEvent::MouseMotion { delta } = event {
                    let c = &mut n.session.camera;
                    let forward = (Vec3::from(c.target) - Vec3::from(c.position)).normalize();
                    let yaw = forward.z.atan2(forward.x) - delta.0 as f32 * 0.003;
                    let pitch = (forward.y.asin() - delta.1 as f32 * 0.003).clamp(-1.5, 1.5);
                    c.target = (Vec3::from(c.position)
                        + Vec3::new(
                            yaw.cos() * pitch.cos(),
                            pitch.sin(),
                            yaw.sin() * pitch.cos(),
                        ))
                    .into();
                }
            }
        }
    }
    fn window_event(
        &mut self,
        event_loop: &ActiveEventLoop,
        _: winit::window::WindowId,
        event: WindowEvent,
    ) {
        if matches!(event, WindowEvent::RedrawRequested) {
            self.service_requests(event_loop);
        }
        let Some(n) = &mut self.native else {
            return;
        };
        let consumed = n.egui_state.on_window_event(&n.window, &event).consumed;
        match event {
            WindowEvent::CloseRequested => event_loop.exit(),
            WindowEvent::Focused(false) => {
                n.keys.clear();
                n.looking = false;
            }
            WindowEvent::Occluded(occluded) => {
                n.occluded = occluded;
                n.last = Instant::now();
                if !occluded {
                    n.window.request_redraw();
                }
            }
            WindowEvent::Resized(size) => {
                if size.width > 0 && size.height > 0 {
                    n.config.width = size.width;
                    n.config.height = size.height;
                    n.surface.configure(&n.session.renderer.device, &n.config);
                }
                n.window.request_redraw();
            }
            WindowEvent::MouseInput {
                state,
                button: MouseButton::Right,
                ..
            } => {
                if !consumed || state == ElementState::Released {
                    n.looking = state == ElementState::Pressed;
                }
            }
            WindowEvent::KeyboardInput { event, .. } => {
                if let PhysicalKey::Code(code) = event.physical_key {
                    if event.state == ElementState::Released {
                        n.keys.remove(&code);
                    } else if !consumed && !event.repeat {
                        n.keys.insert(code);
                        match code {
                            KeyCode::Escape => n.looking = false,
                            KeyCode::Tab => n.inspector = !n.inspector,
                            KeyCode::F11 => {
                                let mode = if n.window.fullscreen().is_some() {
                                    None
                                } else {
                                    Some(Fullscreen::Borderless(None))
                                };
                                n.window.set_fullscreen(mode);
                            }
                            KeyCode::Space => {
                                let _ = n
                                    .session
                                    .execute("pause", json!({"paused":!n.session.paused}));
                            }
                            KeyCode::F5 => {
                                if let Err(error) = n.session.execute("reload_shaders", json!({})) {
                                    n.session.last_error = Some(format!("{error:#}"));
                                }
                            }
                            _ => {}
                        }
                    }
                }
            }
            WindowEvent::RedrawRequested => {
                if let Err(error) = n.draw() {
                    n.session.last_error = Some(format!("{error:#}"));
                    diagnostics::log("frame_error", format!("{error:#}"));
                    self.error = Some(format!("{error:#}"));
                    event_loop.exit();
                }
                if n.benchmark
                    .as_ref()
                    .is_some_and(|benchmark| benchmark.finished)
                {
                    event_loop.exit();
                }
            }
            _ => {}
        }
    }
    fn about_to_wait(&mut self, _: &ActiveEventLoop) {
        if let Some(n) = &self.native {
            if !n.occluded && !n.window.is_minimized().unwrap_or(false) {
                n.window.request_redraw();
            }
        }
    }
}
impl Native {
    fn process_line(&mut self, line: &str) -> String {
        if let Ok(request) = serde_json::from_str::<Request>(line) {
            let result: Result<Value> = match request.method.as_str() {
                "get_window" => Ok(
                    json!({"physical_size":[self.window.inner_size().width,self.window.inner_size().height],"scale_factor":self.window.scale_factor(),"minimized":self.window.is_minimized(),"fullscreen":self.window.fullscreen().is_some()}),
                ),
                "set_window" => {
                    #[derive(serde::Deserialize)]
                    #[serde(deny_unknown_fields)]
                    struct P {
                        size: Option<[u32; 2]>,
                        minimized: Option<bool>,
                        fullscreen: Option<bool>,
                    }
                    (|| {
                        let p: P = serde_json::from_value(request.params.clone())?;
                        if let Some([w, h]) = p.size {
                            if !(320..=8192).contains(&w) || !(240..=8192).contains(&h) {
                                anyhow::bail!(
                                    "size: logical dimensions must be 320..8192 by 240..8192"
                                );
                            }
                        }
                        if let Some([w, h]) = p.size {
                            let _ = self.window.request_inner_size(LogicalSize::new(w, h));
                        }
                        if let Some(minimized) = p.minimized {
                            self.window.set_minimized(minimized);
                        }
                        if let Some(fullscreen) = p.fullscreen {
                            self.window
                                .set_fullscreen(fullscreen.then_some(Fullscreen::Borderless(None)));
                        }
                        Ok(json!({"requested":true}))
                    })()
                }
                _ => return process_line(&mut self.session, line),
            };
            return match result {Ok(value)=>json!({"id":request.id,"result":value}),Err(error)=>json!({"id":request.id,"error":{"code":"invalid_window_operation","message":format!("{error:#}")}})}.to_string();
        }
        process_line(&mut self.session, line)
    }
    fn draw(&mut self) -> Result<()> {
        if self.occluded
            || self.window.is_minimized().unwrap_or(false)
            || self.window.inner_size().width == 0
            || self.window.inner_size().height == 0
        {
            self.last = Instant::now();
            return Ok(());
        }
        let native_frame_started = Instant::now();
        if let Some(timer) = &mut self.native_gpu_timing {
            timer.poll(&self.session.renderer.device, &self.session.renderer.queue);
            let completed = timer.take_completed();
            if let Some(benchmark) = &mut self.benchmark {
                benchmark.gpu_presentation_samples.extend(completed);
            }
        }
        let benchmark_elapsed_at_start = self
            .benchmark
            .as_ref()
            .map(|benchmark| benchmark.started.elapsed().as_secs_f64());
        self.session.begin_measurement_frame();
        let dt = self.last.elapsed().as_secs_f64().min(0.1);
        self.last = Instant::now();
        if self.looking {
            let c = &mut self.session.camera;
            let forward = (Vec3::from(c.target) - Vec3::from(c.position)).normalize();
            let right = forward.cross(Vec3::Y).normalize();
            let mut movement = Vec3::ZERO;
            for (key, direction) in [
                (KeyCode::KeyW, forward),
                (KeyCode::KeyS, -forward),
                (KeyCode::KeyD, right),
                (KeyCode::KeyA, -right),
                (KeyCode::KeyE, Vec3::Y),
                (KeyCode::KeyQ, -Vec3::Y),
            ] {
                if self.keys.contains(&key) {
                    movement += direction;
                }
            }
            let movement = movement.normalize_or_zero()
                * dt as f32
                * if self.keys.contains(&KeyCode::ShiftLeft) {
                    10.
                } else {
                    3.
                };
            c.position = (Vec3::from(c.position) + movement).into();
            c.target = (Vec3::from(c.target) + movement).into();
        }
        if let Some(benchmark) = &self.benchmark {
            let route_time = benchmark_elapsed_at_start
                .unwrap_or(0.)
                .min(benchmark.config.warmup + benchmark.config.duration)
                as f32;
            self.session.camera = benchmark
                .route
                .camera_at(route_time, &benchmark.base_camera);
        }
        let mut fixed_steps = 0u32;
        if !self.session.paused {
            self.accumulator += dt;
            while self.accumulator >= 1. / 60. {
                if let Some(benchmark) = &self.benchmark {
                    let route_frame = (self.session.tick as u32).wrapping_add(fixed_steps);
                    let motion = CasterMotion {
                        object_id: benchmark.config.moving_caster.as_deref(),
                        radius: benchmark.config.caster_orbit_radius,
                        period: benchmark.config.caster_orbit_period,
                    };
                    crate::update_benchmark_caster(
                        &mut self.session,
                        benchmark.moving_caster.as_ref(),
                        route_frame,
                        motion,
                        benchmark.orbit_center_xz,
                    )?;
                }
                fixed_steps += 1;
                self.accumulator -= 1. / 60.;
            }
            if fixed_steps > 0 {
                self.session.step(fixed_steps);
            }
        } else {
            self.accumulator = 0.;
        }
        let input = self.egui_state.take_egui_input(&self.window);
        let mut commands = Vec::<(&str, Value)>::new();
        let ui_started = Instant::now();
        let output = self.egui.run(input, |ctx| {
            if self.inspector {
                draw_inspector(ctx, &self.session, &mut commands);
            }
        });
        for (method, params) in commands {
            if let Err(error) = self.session.execute(method, params) {
                self.session.last_error = Some(format!("{error:#}"));
            }
        }
        self.egui_state
            .handle_platform_output(&self.window, output.platform_output);
        self.session.renderer.metrics.cpu_native_ui_ms =
            Some(ui_started.elapsed().as_secs_f64() * 1000.);
        self.session.render();
        let surface_started = Instant::now();
        let acquired = self.surface.get_current_texture();
        self.session.renderer.metrics.cpu_surface_acquire_ms =
            Some(surface_started.elapsed().as_secs_f64() * 1000.);
        let frame = match acquired {
            Ok(frame) => frame,
            Err(wgpu::SurfaceError::Lost | wgpu::SurfaceError::Outdated) => {
                self.surface
                    .configure(&self.session.renderer.device, &self.config);
                return Ok(());
            }
            Err(wgpu::SurfaceError::Timeout) => return Ok(()),
            Err(error) => return Err(error.into()),
        };
        let view = frame.texture.create_view(&Default::default());
        let renderer = &self.session.renderer;
        let presentation_slot = self
            .native_gpu_timing
            .as_mut()
            .and_then(NativeGpuTiming::acquire);
        let presentation_query =
            presentation_slot.map(|index| self.native_gpu_timing.as_ref().unwrap().query(index));
        let present_encode_started = Instant::now();
        let mut encoder = renderer.device.create_command_encoder(&Default::default());
        self.presenter.draw(
            &mut encoder,
            &view,
            [self.config.width, self.config.height],
            self.session.scene.render.resolution,
            &renderer.queue,
            presentation_query,
        );
        let jobs = self.egui.tessellate(output.shapes, output.pixels_per_point);
        let descriptor = egui_wgpu::ScreenDescriptor {
            size_in_pixels: [self.config.width, self.config.height],
            pixels_per_point: output.pixels_per_point,
        };
        for (id, delta) in &output.textures_delta.set {
            self.egui_renderer
                .update_texture(&renderer.device, &renderer.queue, *id, delta);
        }
        let buffers = self.egui_renderer.update_buffers(
            &renderer.device,
            &renderer.queue,
            &mut encoder,
            &jobs,
            &descriptor,
        );
        {
            let pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("inspector"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: presentation_query.map(|query_set| {
                    wgpu::RenderPassTimestampWrites {
                        query_set,
                        beginning_of_pass_write_index: Some(2),
                        end_of_pass_write_index: Some(3),
                    }
                }),
                occlusion_query_set: None,
            });
            self.egui_renderer
                .render(&mut pass.forget_lifetime(), &jobs, &descriptor);
        }
        if let Some(index) = presentation_slot {
            self.native_gpu_timing.as_mut().unwrap().resolve_and_map(
                index,
                self.session.renderer.metrics.frame,
                &mut encoder,
            );
        }
        let present_encode_ms = present_encode_started.elapsed().as_secs_f64() * 1000.;
        let present_submit_started = Instant::now();
        let queue_submit_started = Instant::now();
        renderer
            .queue
            .submit(buffers.into_iter().chain([encoder.finish()]));
        let queue_submit_ms = queue_submit_started.elapsed().as_secs_f64() * 1000.;
        if let Some(index) = presentation_slot {
            self.native_gpu_timing.as_mut().unwrap().submitted(index);
        }
        frame.present();
        let present_submit_ms = present_submit_started.elapsed().as_secs_f64() * 1000.;
        self.session.renderer.metrics.cpu_present_encode_ms = Some(present_encode_ms);
        self.session.renderer.metrics.cpu_present_submit_ms = Some(present_submit_ms);
        self.session.renderer.metrics.cpu_queue_submit_ms += queue_submit_ms;
        self.session.renderer.metrics.cpu_native_frame_ms =
            Some(native_frame_started.elapsed().as_secs_f64() * 1000.);
        self.session.renderer.poll_timing(false);
        let gpu_timings = self.session.renderer.take_gpu_timing_samples();
        let compute_timings = self.session.renderer.take_gpu_compute_timing_samples();
        let presentation_timings = if let Some(timer) = &mut self.native_gpu_timing {
            timer.poll(&self.session.renderer.device, &self.session.renderer.queue);
            timer.take_completed()
        } else {
            Vec::new()
        };
        if let Some(benchmark) = &mut self.benchmark {
            benchmark.gpu_samples.extend(gpu_timings);
            benchmark.gpu_compute_samples.extend(compute_timings);
            benchmark
                .gpu_presentation_samples
                .extend(presentation_timings);
            let elapsed = benchmark.started.elapsed().as_secs_f64();
            let warmup_end = benchmark.config.warmup;
            let benchmark_end = warmup_end + benchmark.config.duration;
            let sample_elapsed = benchmark_elapsed_at_start.unwrap_or(elapsed);
            if sample_elapsed >= warmup_end && sample_elapsed < benchmark_end {
                let metrics = &self.session.renderer.metrics;
                benchmark.samples.push(json!({
                    "frame":metrics.frame,
                    "elapsed_seconds":sample_elapsed - warmup_end,
                    "tick":self.session.tick,
                    "cpu_native_frame_ms":metrics.cpu_native_frame_ms,
                    "cpu_simulation_submit_ms":metrics.cpu_simulation_submit_ms,
                    "cpu_simulation_encode_ms":metrics.cpu_simulation_encode_ms,
                    "simulation_submissions":metrics.cpu_simulation_submissions_this_frame,
                    "cpu_queue_submit_ms":metrics.cpu_queue_submit_ms,
                    "cpu_steps":metrics.cpu_steps_this_frame,
                    "cpu_renderer_encode_ms":metrics.cpu_encode_ms,
                    "cpu_upload_calls_ms":metrics.cpu_upload_ms,
                    "smoke_config_uploads":metrics.smoke_config_uploads_this_frame,
                    "smoke_config_upload_bytes":metrics.smoke_config_upload_bytes_this_frame,
                    "globals_uploads":metrics.globals_uploads_this_frame,
                    "globals_upload_bytes":metrics.globals_upload_bytes_this_frame,
                    "cpu_ui_ms":metrics.cpu_native_ui_ms,
                    "cpu_surface_acquire_ms":metrics.cpu_surface_acquire_ms,
                    "cpu_present_encode_ms":metrics.cpu_present_encode_ms,
                    "cpu_present_submit_ms":metrics.cpu_present_submit_ms,
                    "gpu_timing_frame":metrics.gpu_timing_frame,
                    "gpu_smoke_tick":metrics.gpu_smoke_tick,
                    "moving_caster_position":benchmark.moving_caster.as_ref().and_then(|(id, _)| self.session.scene.objects.iter().find(|object| object.id == *id).map(|object| object.position)),
                    "shadow_cache_hit":metrics.shadow_cache_hit,
                    "shadow_redrawn":metrics.shadow_redrawn,
                    "shadow_maps_redrawn":metrics.shadow_maps_redrawn,
                    "shadow_dirty_faces":metrics.shadow_dirty_faces,
                    "shadow_dirty_reason":metrics.shadow_dirty_reason,
                    "fire_primitives":metrics.fire_primitives,
                    "particle_lights":metrics.particle_lights
                }));
            }
            if elapsed >= benchmark_end {
                self.session.renderer.device.poll(wgpu::Maintain::Wait);
                self.session.renderer.poll_timing(true);
                if let Some(timer) = &mut self.native_gpu_timing {
                    timer.poll(&self.session.renderer.device, &self.session.renderer.queue);
                    benchmark
                        .gpu_presentation_samples
                        .extend(timer.take_completed());
                }
                benchmark
                    .gpu_samples
                    .extend(self.session.renderer.take_gpu_timing_samples());
                benchmark
                    .gpu_compute_samples
                    .extend(self.session.renderer.take_gpu_compute_timing_samples());
                let report = native_benchmark_report(
                    benchmark,
                    &self.session,
                    self.config.present_mode,
                    self.native_gpu_timing.as_ref().map(|timer| timer.skipped),
                );
                if let Some(parent) = benchmark
                    .config
                    .output
                    .parent()
                    .filter(|parent| !parent.as_os_str().is_empty())
                {
                    std::fs::create_dir_all(parent)?;
                }
                std::fs::write(
                    &benchmark.config.output,
                    serde_json::to_vec_pretty(&report)?,
                )?;
                eprintln!(
                    "{}",
                    json!({"event":"native_benchmark_complete","report":benchmark.config.output,"samples":benchmark.samples.len()})
                );
                benchmark.finished = true;
            }
        }
        for id in &output.textures_delta.free {
            self.egui_renderer.free_texture(id);
        }
        Ok(())
    }
}

fn native_benchmark_report(
    benchmark: &NativeBenchmark,
    session: &Session,
    present_mode: wgpu::PresentMode,
    skipped_presentation_samples: Option<u64>,
) -> Value {
    let measured_frame_start = benchmark
        .samples
        .first()
        .and_then(|sample| sample["frame"].as_u64());
    let measured_frame_end = benchmark
        .samples
        .last()
        .and_then(|sample| sample["frame"].as_u64());
    let measured_tick_start = benchmark
        .samples
        .first()
        .and_then(|sample| sample["tick"].as_u64());
    let measured_tick_end = benchmark
        .samples
        .last()
        .and_then(|sample| sample["tick"].as_u64());
    let measured_gpu_samples = benchmark
        .gpu_samples
        .iter()
        .filter(|sample| {
            measured_frame_start.is_some_and(|start| sample.frame >= start)
                && measured_frame_end.is_some_and(|end| sample.frame <= end)
        })
        .collect::<Vec<_>>();
    let measured_gpu_compute_samples = benchmark
        .gpu_compute_samples
        .iter()
        .filter(|sample| {
            measured_tick_start.is_some_and(|start| sample.tick >= start)
                && measured_tick_end.is_some_and(|end| sample.tick <= end)
        })
        .collect::<Vec<_>>();
    let measured_gpu_presentation_samples = benchmark
        .gpu_presentation_samples
        .iter()
        .filter(|sample| {
            measured_frame_start.is_some_and(|start| sample.frame >= start)
                && measured_frame_end.is_some_and(|end| sample.frame <= end)
        })
        .collect::<Vec<_>>();
    let summarize_frames = |key: &str| {
        let values = benchmark
            .samples
            .iter()
            .filter_map(|sample| sample[key].as_f64())
            .collect::<Vec<_>>();
        if values.is_empty() {
            json!({"median_ms":null,"p95_ms":null,"samples":0})
        } else {
            json!({"median_ms":diagnostics::percentile(&values,0.5),"p95_ms":diagnostics::percentile(&values,0.95),"samples":values.len()})
        }
    };
    let stage_names = [
        "shadow_maps",
        "opaque_geometry",
        "atmosphere_fire",
        "optical_resolve",
        "post",
    ];
    let mut gpu_stages = serde_json::Map::new();
    for stage in stage_names {
        let values = measured_gpu_samples
            .iter()
            .filter_map(|sample| sample.passes_ms.get(stage).copied())
            .collect::<Vec<_>>();
        let summary = if values.is_empty() {
            json!({"median_ms":null,"p95_ms":null,"samples":0})
        } else {
            json!({"median_ms":diagnostics::percentile(&values,0.5),"p95_ms":diagnostics::percentile(&values,0.95),"samples":values.len()})
        };
        gpu_stages.insert(stage.into(), summary);
    }
    let smoke = measured_gpu_compute_samples
        .iter()
        .map(|sample| sample.elapsed_ms)
        .collect::<Vec<_>>();
    gpu_stages.insert(
        "smoke_compute".into(),
        if smoke.is_empty() {
            json!({"median_ms":null,"p95_ms":null,"samples":0})
        } else {
            json!({"median_ms":diagnostics::percentile(&smoke,0.5),"p95_ms":diagnostics::percentile(&smoke,0.95),"samples":smoke.len()})
        },
    );
    let presenter_values = measured_gpu_presentation_samples
        .iter()
        .map(|sample| sample.presenter_ms)
        .collect::<Vec<_>>();
    let inspector_values = measured_gpu_presentation_samples
        .iter()
        .map(|sample| sample.inspector_ms)
        .collect::<Vec<_>>();
    for (name, values) in [
        ("native_presenter", presenter_values),
        ("native_inspector", inspector_values),
    ] {
        gpu_stages.insert(
            name.into(),
            if values.is_empty() {
                json!({"median_ms":null,"p95_ms":null,"samples":0})
            } else {
                json!({"median_ms":diagnostics::percentile(&values,0.5),"p95_ms":diagnostics::percentile(&values,0.95),"samples":values.len()})
            },
        );
    }
    let actual_seconds = benchmark
        .samples
        .last()
        .and_then(|sample| sample["elapsed_seconds"].as_f64())
        .unwrap_or(0.);
    let render_readback = measured_gpu_samples
        .iter()
        .map(|sample| sample.readback_latency_ms)
        .collect::<Vec<_>>();
    let presentation_readback = measured_gpu_presentation_samples
        .iter()
        .map(|sample| sample.readback_latency_ms)
        .collect::<Vec<_>>();
    let capabilities = session.renderer.capabilities();
    let mut shadow_dirty_reasons = std::collections::BTreeMap::<String, u64>::new();
    for reason in benchmark
        .samples
        .iter()
        .filter_map(|sample| sample["shadow_dirty_reason"].as_str())
    {
        *shadow_dirty_reasons.entry(reason.to_owned()).or_default() += 1;
    }
    let shadow_redrawn_frames = benchmark
        .samples
        .iter()
        .filter(|sample| sample["shadow_redrawn"].as_bool() == Some(true))
        .count();
    let shadow_redrawn_passes = benchmark
        .samples
        .iter()
        .filter_map(|sample| sample["shadow_maps_redrawn"].as_u64())
        .sum::<u64>();
    let measured_simulation_ticks = benchmark
        .samples
        .iter()
        .filter_map(|sample| sample["cpu_steps"].as_u64())
        .sum::<u64>();
    let measured_simulation_submissions = benchmark
        .samples
        .iter()
        .filter_map(|sample| sample["simulation_submissions"].as_u64())
        .sum::<u64>();
    json!({
        "version":1,
        "mode":"native_vsync_route",
        "scope":"native surface route; frame wall includes surface acquisition, UI encoding, queue submission and present call; CPU spans overlap and are not additive",
        "route":benchmark.route,
        "route_seconds":benchmark.config.duration,
        "warmup_seconds":benchmark.config.warmup,
        "simulation_batching_enabled":session.simulation_batching_enabled,
        "simulation_accounting":{
            "fixed_ticks":measured_simulation_ticks,
            "queue_submissions":measured_simulation_submissions,
            "batching_enabled":session.simulation_batching_enabled
        },
        "setup_seconds":benchmark.setup_seconds,
        "actual_measured_seconds":actual_seconds,
        "frames_per_second":if actual_seconds > 0. {benchmark.samples.len() as f64 / actual_seconds} else {0.},
        "present_mode":format!("{:?}", present_mode),
        "vsync":present_mode == wgpu::PresentMode::AutoVsync || present_mode == wgpu::PresentMode::Fifo,
        "tile_lists_enabled":benchmark.config.tile_lists_enabled,
        "fire_bounds_precompute":benchmark.config.precompute_fire_bounds,
        "force_shadow_redraw":benchmark.config.force_shadow_redraw,
        "geometry_rendering":{"culling":benchmark.config.object_culling_enabled,"instancing":benchmark.config.instancing_enabled},
        "moving_caster":benchmark.moving_caster.as_ref().map(|(id, _)| json!({"object":id,"radius":benchmark.config.caster_orbit_radius,"period_seconds":benchmark.config.caster_orbit_period,"orbit_center_xz":benchmark.orbit_center_xz,"sample_hz":60})),
        "shadow_cache":{"frames_with_redraw":shadow_redrawn_frames,"redrawn_shadow_passes":shadow_redrawn_passes,"dirty_reasons":shadow_dirty_reasons},
        "scene":session.scene,
        "seed":session.seed,
        "capabilities":capabilities,
        "workload_counts":{"objects":session.scene.objects.len(),"materials":session.scene.materials.len(),"authored_lights":session.scene.lights.len(),"emitters":session.scene.emitters.len(),"draw_calls_per_frame":10 + u32::from(session.scene.materials.iter().any(|m|m.metallic > 0. || m.reflectivity > 0. || m.transmission > 0.)),"vertices":session.renderer.capabilities()["vertices"]},
        "timing_coverage":{"gpu_timestamps_supported":session.renderer.metrics.gpu_timestamp_supported,"timed_render_frames":measured_gpu_samples.len(),"smoke_compute_samples":measured_gpu_compute_samples.len(),"native_presentation_ui_samples":measured_gpu_presentation_samples.len(),"rendered_frames":benchmark.samples.len(),"counter_scope":"skipped and late counters are cumulative for the native session, including warm-up","skipped_render_samples":session.renderer.metrics.gpu_samples_skipped,"skipped_compute_samples":session.renderer.metrics.gpu_compute_samples_skipped,"skipped_native_presentation_ui_samples":skipped_presentation_samples,"late_render_samples":session.renderer.metrics.gpu_samples_late,"gpu_presentation_ui_reason":if session.renderer.metrics.gpu_timestamp_supported {Value::Null} else {json!("adapter does not support TIMESTAMP_QUERY")}},
        "queue_latency":{"value_ms":null,"reason":"GPU timestamps are not calibrated to the host clock; queue/readback completion delay is reported separately"},
        "gpu_readback_latency":{"render_stages":timing_summary(&render_readback),"presentation_ui":timing_summary(&presentation_readback),"meaning":"host submit-to-map-completion delay including queueing, GPU work, and polling; not pure queue latency"},
        "cpu_native_frame":summarize_frames("cpu_native_frame_ms"),
        "cpu_renderer_encode":summarize_frames("cpu_renderer_encode_ms"),
        "cpu_simulation_submit":summarize_frames("cpu_simulation_submit_ms"),
        "cpu_simulation_encode":summarize_frames("cpu_simulation_encode_ms"),
        "cpu_queue_submit":summarize_frames("cpu_queue_submit_ms"),
        "cpu_ui":summarize_frames("cpu_ui_ms"),
        "cpu_surface_acquire":summarize_frames("cpu_surface_acquire_ms"),
        "cpu_present_encode":summarize_frames("cpu_present_encode_ms"),
        "cpu_present_submit":summarize_frames("cpu_present_submit_ms"),
        "gpu_stages":gpu_stages,
        "gpu_timing_samples":measured_gpu_samples,
        "gpu_smoke_compute_samples":measured_gpu_compute_samples,
        "gpu_native_presentation_samples":measured_gpu_presentation_samples,
        "samples":benchmark.samples
    })
}

fn timing_summary(values: &[f64]) -> Value {
    if values.is_empty() {
        json!({"median_ms":null,"p95_ms":null,"samples":0})
    } else {
        json!({"median_ms":diagnostics::percentile(values,0.5),"p95_ms":diagnostics::percentile(values,0.95),"samples":values.len()})
    }
}

fn draw_inspector(ctx: &egui::Context, session: &Session, commands: &mut Vec<(&str, Value)>) {
    egui::Window::new("PIXEL ENGINE / INSPECTOR").default_width(278.).vscroll(true).show(ctx, |ui| {
        ui.label("Native rendering research lab");
        ui.separator();
        ui.label(format!("Tick {} · {}", session.tick, if session.paused {"paused"} else {"running"}));
        ui.label(format!("Pixel grid {} × {}",session.scene.render.resolution[0],session.scene.render.resolution[1]));
        ui.label(format!("CPU {:.2} ms · GPU {}",session.renderer.metrics.cpu_encode_ms,session.renderer.metrics.gpu_ms.map(|x|format!("{x:.2} ms")).unwrap_or_else(||"unavailable".into())));
        ui.horizontal(|ui| {
            if ui.button(if session.paused {"Play"} else {"Pause"}).clicked() { commands.push(("pause",json!({"paused":!session.paused}))); }
            if ui.button("Step").clicked() { commands.push(("step",json!({"ticks":1}))); }
            if ui.button("Reset").clicked() { commands.push(("reset",json!({"seed":session.seed}))); }
        });
        egui::ComboBox::from_label("Camera").selected_text(&session.camera.id).show_ui(ui, |ui| {
            for camera in &session.scene.cameras {
                if ui.selectable_label(session.camera.id==camera.id,&camera.id).clicked() { commands.push(("set_camera",json!({"id":camera.id}))); }
            }
        });
        let emitter=&session.scene.emitters[0];
        egui::ComboBox::from_label("Effect treatment").selected_text(if emitter.style==pixel_engine::scene::EffectStyle::Ink {"Inked / stylised"} else {"Soft volume"}).show_ui(ui, |ui| {
            for (label,value) in [("Inked / stylised","ink"),("Soft volume","volume")] {
                if ui.button(label).clicked() {commands.push(("set_parameter",json!({"path":format!("emitters.{}.style",emitter.id),"value":value})));}
            }
        });
        ui.separator();
        let mut exposure=session.scene.render.exposure;
        if ui.add(egui::Slider::new(&mut exposure,0.1..=3.).text("Exposure")).changed() {commands.push(("set_parameter",json!({"path":"render.exposure","value":exposure})));}
        let mut levels=session.scene.render.shading_steps;
        if ui.add(egui::Slider::new(&mut levels,2..=32).text("Shade levels")).changed() {commands.push(("set_parameter",json!({"path":"render.shading_steps","value":levels})));}
        let mut enabled=emitter.enabled;
        if ui.checkbox(&mut enabled,"Fire and smoke enabled").changed() {commands.push(("set_parameter",json!({"path":format!("emitters.{}.enabled",emitter.id),"value":enabled})));}
        let mut density=emitter.smoke_density;
        if ui.add(egui::Slider::new(&mut density,0.0..=8.).text("Smoke source")).changed() {commands.push(("set_parameter",json!({"path":format!("emitters.{}.smoke_density",emitter.id),"value":density})));}
        let mut bubbles=emitter.secondary_bubbles;
        if ui.add(egui::Slider::new(&mut bubbles,0..=8).text("Small bubbles")).changed() {commands.push(("set_parameter",json!({"path":format!("emitters.{}.secondary_bubbles",emitter.id),"value":bubbles})));}
        let mut scale=emitter.bubble_scale;
        if ui.add(egui::Slider::new(&mut scale,0.1..=0.5).text("Bubble size")).changed() {commands.push(("set_parameter",json!({"path":format!("emitters.{}.bubble_scale",emitter.id),"value":scale})));}
        let mut shadow=emitter.self_shadow_strength;
        if ui.add(egui::Slider::new(&mut shadow,0.0..=4.).text("Smoke self-shadow")).changed() {commands.push(("set_parameter",json!({"path":format!("emitters.{}.self_shadow_strength",emitter.id),"value":shadow})));}
        let mut glow=emitter.internal_glow;
        if ui.add(egui::Slider::new(&mut glow,0.0..=4.).text("Internal glow")).changed() {commands.push(("set_parameter",json!({"path":format!("emitters.{}.internal_glow",emitter.id),"value":glow})));}
        ui.collapsing("Fire / reusable effect profile", |ui| {
            let profile=session.scene.effects.iter().find(|p|p.id==emitter.effect_profile).unwrap();
            egui::ComboBox::from_label("Profile").selected_text(&profile.id).show_ui(ui, |ui| {
                for p in &session.scene.effects {
                    if ui.selectable_label(p.id==profile.id,&p.id).clicked() {commands.push(("set_parameter",json!({"path":format!("emitters.{}.effect_profile",emitter.id),"value":p.id})));}
                }
            });
            for (property,label,initial,low,high) in [
                ("motion_speed","Motion pace",profile.fire.motion_speed,0.05,3.),
                ("curl","Curl",profile.fire.curl,0.,2.),
                ("lobe_roundness","Rounded lobes",profile.fire.lobe_roundness,0.,1.),
                ("heat_distortion","Heat shimmer (pixels)",profile.fire.heat_distortion,0.,4.),
                ("heat_distortion_height","Shimmer height",profile.fire.heat_distortion_height,0.1,12.),
                ("particle_light_strength","Particle light",profile.fire.particle_light_strength,0.,16.),
                ("particle_light_range","Particle light range",profile.fire.particle_light_range,0.1,8.),
                ("edge_breakup","Edge breakup",profile.fire.edge_breakup,0.,1.),
                ("tip_breakup","Tip breakup",profile.fire.tip_breakup,0.,1.),
                ("fragment_size","Fragment size",profile.fire.fragment_size,0.01,0.2),
                ("width","Flame width",profile.fire.width,0.05,4.),
                ("height","Flame height",profile.fire.height,0.1,8.),
                ("fragment_rate","Breakaway rate",profile.fire.fragment_rate,0.,8.),
                ("ember_rate","Ember rate",profile.fire.ember_rate,0.,32.),
                ("emission","HDR emission",profile.fire.emission,0.,16.),
            ] {
                let mut value=initial;
                if ui.add(egui::Slider::new(&mut value,low..=high).text(label)).changed() {commands.push(("set_parameter",json!({"path":format!("effects.{}.fire.{property}",profile.id),"value":value})));}
            }
            for (property,label,mut value,high) in [("branches","Upward branches",profile.fire.branches,3),("particle_lights","Particle light budget",profile.fire.particle_lights,12)] {
                if ui.add(egui::Slider::new(&mut value,0..=high).text(label)).changed() {commands.push(("set_parameter",json!({"path":format!("effects.{}.fire.{property}",profile.id),"value":value})));}
            }
            ui.small(format!("{} moving lights · {} omitted",session.renderer.metrics.particle_lights,session.renderer.metrics.particle_lights_dropped));
            let mut solid=profile.fire.solid;
            if ui.checkbox(&mut solid,"Solid pixel flames").changed() {commands.push(("set_parameter",json!({"path":format!("effects.{}.fire.solid",profile.id),"value":solid})));}
            let mut bands=profile.fire.color_bands;
            if ui.add(egui::Slider::new(&mut bands,2..=8).text("Flame colour bands")).changed() {commands.push(("set_parameter",json!({"path":format!("effects.{}.fire.color_bands",profile.id),"value":bands})));}
            let mut segments=profile.fire.segments;
            if ui.add(egui::Slider::new(&mut segments,3..=10).text("Curve segments")).changed() {commands.push(("set_parameter",json!({"path":format!("effects.{}.fire.segments",profile.id),"value":segments})));}
            for (property,label,initial) in [("heat_output","Source heat",profile.thermal.heat_output),("cooling_rate","Cooling",profile.thermal.cooling_rate),("lift","Thermal lift",profile.thermal.lift)] {
                let mut value=initial;
                let high=match property {"heat_output"=>16.,"lift"=>4.,_=>10.};
                if ui.add(egui::Slider::new(&mut value,0.0..=high).text(label)).changed() {commands.push(("set_parameter",json!({"path":format!("effects.{}.thermal.{property}",profile.id),"value":value})));}
            }
            ui.small(format!("{} primitives · {} fragments · {} embers\nEffect CPU {:.3} ms · dropped events {}",session.renderer.metrics.fire_primitives,session.renderer.metrics.flame_fragments,session.renderer.metrics.embers,session.renderer.metrics.effect_update_cpu_ms,session.renderer.metrics.effect_events_dropped));
        });
        ui.collapsing("Point lights / smoke gradients", |ui| {
            for light in session.scene.lights.iter().filter(|l|l.kind==pixel_engine::scene::LightKind::Point) {
                ui.label(&light.id);
                let mut intensity=light.intensity;
                if ui.add(egui::Slider::new(&mut intensity,0.0..=40.).text("Intensity")).changed() {commands.push(("set_parameter",json!({"path":format!("lights.{}.intensity",light.id),"value":intensity})));}
                let mut range=light.range;
                if ui.add(egui::Slider::new(&mut range,0.1..=40.).text("Range")).changed() {commands.push(("set_parameter",json!({"path":format!("lights.{}.range",light.id),"value":range})));}
            }
        });
        ui.collapsing("Materials", |ui| {
            let mut steps=session.scene.render.reflection_steps;
            if ui.add(egui::Slider::new(&mut steps,0..=16).text("Reflection ray steps")).changed() {commands.push(("set_parameter",json!({"path":"render.reflection_steps","value":steps})));}

            for material in &session.scene.materials {
                ui.collapsing(&material.id, |ui| {
                    let mut color=material.color;
                    ui.horizontal(|ui| {ui.label("Base colour");
                        if ui.color_edit_button_rgb(&mut color).changed() {commands.push(("set_parameter",json!({"path":format!("materials.{}.color",material.id),"value":color})));}
                    });
                    for (property,label,mut value,low,high) in [
                        ("roughness","Roughness",material.roughness,0.,1.),
                        ("metallic","Metallic",material.metallic,0.,1.),
                        ("reflectivity","Reflections",material.reflectivity,0.,1.),
                        ("transmission","Transmission",material.transmission,0.,1.),
                        ("ior","Index of refraction",material.ior,1.,2.5),
                        ("thickness","Optical thickness",material.thickness,0.,10.),
                        ("subsurface","Subsurface wrap",material.subsurface,0.,1.),
                        ("heat_response","Gameplay heat response",material.heat_response,0.,1.),
                        ("emission","Emission",material.emission,0.,8.),
                    ] {
                        if ui.add(egui::Slider::new(&mut value,low..=high).text(label)).changed() {commands.push(("set_parameter",json!({"path":format!("materials.{}.{property}",material.id),"value":value})));}
                    }
                    let mut scatter=material.scatter_color;
                    ui.horizontal(|ui| {ui.label("Scatter colour");
                        if ui.color_edit_button_rgb(&mut scatter).changed() {commands.push(("set_parameter",json!({"path":format!("materials.{}.scatter_color",material.id),"value":scatter})));}
                    });
                    let mut absorption=material.absorption;
                    let mut changed=false;
                    ui.horizontal(|ui| {ui.label("Absorption RGB"); for channel in &mut absorption {changed |= ui.add(egui::DragValue::new(channel).speed(0.02).range(0.0..=64.)).changed();}});
                    if changed {commands.push(("set_parameter",json!({"path":format!("materials.{}.absorption",material.id),"value":absorption})));}
                });
            }
        });
        ui.collapsing("Pixel / HDR presentation",|ui| {
            for (property,label,initial) in [("palette_strength","Colour band strength",session.scene.render.palette_strength),("bloom_strength","HDR glow",session.scene.render.bloom_strength)] {
                let mut value=initial;
                if ui.add(egui::Slider::new(&mut value,0.0..=1.).text(label)).changed() {commands.push(("set_parameter",json!({"path":format!("render.{property}"),"value":value})));}
            }
        });
        ui.separator();
        ui.label("EXPERIMENTS / independent toggles");
        let e=&session.scene.render.experiments;
        for (key,label,initial) in [("pixel_cluster_lighting","Pixel-cluster lighting",e.pixel_cluster_lighting),("stable_smoke_detail","Smoke-field detail",e.stable_smoke_detail),("connected_motion","Connected wind",e.connected_motion),("projected_detail_lod","Projected fire detail LOD",e.projected_detail_lod),("smoke_absorption_cache","Smoke absorption cache",e.smoke_absorption_cache),("optical_surface_reuse","Reuse optical surface lighting",e.optical_surface_reuse)] {
            let mut value=initial;
            if ui.checkbox(&mut value,label).changed() {commands.push(("set_parameter",json!({"path":format!("render.experiments.{key}"),"value":value})));}
        }
        ui.collapsing("Shading operation counters", |ui| {
            let mut enabled = session.renderer.shading_diagnostics_enabled();
            if ui.checkbox(&mut enabled, "Run diagnostic counter draws").changed() {
                commands.push(("set_shading_diagnostics", json!({"enabled":enabled})));
            }
            ui.small("Diagnostic draws add scratch targets and perturb timing.");
            if let Some(counters) = &session.renderer.metrics.shading_counters {
                ui.monospace(format!("Fire candidates: {} · tests: {}", counters.fire_primitive_candidates, counters.fire_ellipsoid_tests));
                ui.monospace(format!("Smoke candidates: {} · density samples: {}", counters.smoke_lobe_candidates, counters.smoke_density_samples));
                ui.monospace(format!("Volume pixels: {} · soft/inked: {}/{}", counters.volume_pixel_invocations, counters.soft_volume_pixel_invocations, counters.inked_smoke_pixel_invocations));
                ui.monospace(format!("Absorption direct/cache: {}/{}", counters.direct_absorption_samples, counters.cached_absorption_samples));
                ui.monospace(format!("Shadow sun/fire: {}/{}", counters.sun_shadow_lookups, counters.fire_shadow_lookups));
                ui.monospace(format!("World lights point/particle: {}/{}", counters.world_point_light_candidates, counters.world_particle_light_candidates));
                ui.monospace(format!("Optical surfaces: {} · reflection steps: {} · transmission: {}", counters.optical_surface_interactions, counters.optical_reflection_steps, counters.optical_transmission_interactions));
            } else if enabled {
                ui.small("Counters appear after the next rendered frame.");
            }
        });
        ui.separator();
        ui.horizontal(|ui| {
            if ui.button("Capture").clicked() {commands.push(("capture_frame",json!({"path":format!("artifacts/native-{}.png",session.tick),"scale":3})));}
            if ui.button("Reload shaders").clicked() {commands.push(("reload_shaders",json!({})));}
        });
        if let Some(error)=&session.last_error {ui.colored_label(egui::Color32::LIGHT_RED,error);}
        ui.separator();
        ui.small("Right-drag + WASD: fly · Q/E: down/up\nShift: fast · Tab: inspector\nSpace: pause · F5: shaders · F11: fullscreen");
    });
}
