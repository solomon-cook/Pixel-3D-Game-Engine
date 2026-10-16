use crate::{prepare, Options};
use anyhow::{Context, Result};
use glam::Vec3;
use pixel_engine::{
    diagnostics,
    render::{self, Presenter},
    session::{Request, Session},
};
use serde_json::{json, Value};
use std::{
    collections::HashSet,
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
}
struct App {
    options: Options,
    agent: bool,
    paused: bool,
    native: Option<Native>,
    receiver: mpsc::Receiver<String>,
    error: Option<String>,
}
pub fn run(options: Options, agent: bool, paused: bool) -> Result<()> {
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
        let renderer = pollster::block_on(render::Renderer::new(
            &instance,
            Some(&surface),
            &scene,
            path.parent().unwrap(),
            shaders,
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
        session.paused = self.agent || self.paused;
        session.execute("set_camera", json!({"id":self.options.camera}))?;
        diagnostics::log("ready", session.renderer.capabilities());
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
        if !self.session.paused {
            self.accumulator += dt;
            while self.accumulator >= 1. / 60. {
                self.session.step(1);
                self.accumulator -= 1. / 60.;
            }
        } else {
            self.accumulator = 0.;
        }
        let input = self.egui_state.take_egui_input(&self.window);
        let mut commands = Vec::<(&str, Value)>::new();
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
        self.session.render();
        let frame = match self.surface.get_current_texture() {
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
        let mut encoder = renderer.device.create_command_encoder(&Default::default());
        self.presenter.draw(
            &mut encoder,
            &view,
            [self.config.width, self.config.height],
            self.session.scene.render.resolution,
            &renderer.queue,
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
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            self.egui_renderer
                .render(&mut pass.forget_lifetime(), &jobs, &descriptor);
        }
        renderer
            .queue
            .submit(buffers.into_iter().chain([encoder.finish()]));
        frame.present();
        for id in &output.textures_delta.free {
            self.egui_renderer.free_texture(id);
        }
        Ok(())
    }
}

fn draw_inspector(ctx: &egui::Context, session: &Session, commands: &mut Vec<(&str, Value)>) {
    egui::Window::new("PIXEL ENGINE / EMBERWOOD").default_width(278.).show(ctx, |ui| {
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
        ui.separator();
        ui.label("EXPERIMENTS / independent toggles");
        let e=&session.scene.render.experiments;
        for (key,label,initial) in [("pixel_cluster_lighting","Pixel-cluster lighting",e.pixel_cluster_lighting),("stable_smoke_detail","Smoke-field detail",e.stable_smoke_detail),("connected_motion","Connected wind",e.connected_motion)] {
            let mut value=initial;
            if ui.checkbox(&mut value,label).changed() {commands.push(("set_parameter",json!({"path":format!("render.experiments.{key}"),"value":value})));}
        }
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
