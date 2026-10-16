//! Shared operations for CLI, native inspector and JSON-lines clients.
use crate::{
    render::Renderer,
    scene::{self, Camera, Scene},
    simulation,
};
use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub id: Value,
    pub method: String,
    #[serde(default = "empty_object")]
    pub params: Value,
}
fn empty_object() -> Value {
    json!({})
}

#[derive(Serialize)]
pub struct Response {
    pub id: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<Value>,
}

pub struct Session {
    pub scene: Scene,
    pub camera: Camera,
    pub renderer: Renderer,
    pub tick: u64,
    pub seed: u32,
    pub paused: bool,
    pub scene_path: PathBuf,
    pub last_error: Option<String>,
}
impl Session {
    pub fn new(scene: Scene, scene_path: PathBuf, renderer: Renderer, seed: u32) -> Self {
        let camera = scene.cameras[0].clone();
        Self {
            scene,
            camera,
            renderer,
            tick: 0,
            seed,
            paused: false,
            scene_path,
            last_error: None,
        }
    }
    pub fn step(&mut self, count: u32) {
        for _ in 0..count {
            self.tick += 1;
            self.renderer
                .simulate(&self.scene, &self.camera, self.tick, self.seed);
        }
    }
    pub fn render(&mut self) {
        self.renderer
            .render(&self.scene, &self.camera, self.tick, self.seed);
    }
    pub fn reset(&mut self, seed: u32) {
        self.seed = seed;
        self.tick = 0;
        self.renderer.reset_smoke();
    }
    pub fn capture(&mut self, path: &Path, scale: u32) -> Result<Value> {
        if !(1..=8).contains(&scale) {
            bail!("scale: expected integer 1..8");
        }
        self.render();
        self.renderer.capture(path, scale)?;
        self.renderer.poll_timing(true);
        let metadata = json!({"version":1,"scene":self.scene_path,"scene_definition":self.scene,"seed":self.seed,"tick":self.tick,"seconds":self.tick as f32*simulation::FIXED_DT,"camera":self.camera,"scale":scale,"image":path,"capabilities":self.renderer.capabilities(),"metrics":self.renderer.metrics});
        std::fs::write(
            path.with_extension("json"),
            serde_json::to_vec_pretty(&metadata)?,
        )?;
        Ok(
            json!({"image":path,"metadata":path.with_extension("json"),"tick":self.tick,"seed":self.seed,"camera":self.camera.id,"capabilities":self.renderer.capabilities()}),
        )
    }
    pub fn dispatch(&mut self, request: Request) -> Response {
        match self.execute(&request.method, request.params) {
            Ok(result) => Response {
                id: request.id,
                result: Some(result),
                error: None,
            },
            Err(error) => {
                let message = format!("{error:#}");
                self.last_error = Some(message.clone());
                Response {
                    id: request.id,
                    result: None,
                    error: Some(json!({"code":"invalid_operation","message":message})),
                }
            }
        }
    }
    pub fn execute(&mut self, method: &str, params: Value) -> Result<Value> {
        match method {
            "describe" => Ok(description()),
            "inspect_scene" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    section: Option<String>,
                    id: Option<String>,
                }
                let p: P = serde_json::from_value(params)?;
                if let Some(section) = p.section {
                    let data = serde_json::to_value(&self.scene)?;
                    let part = data
                        .get(&section)
                        .with_context(|| format!("section '{section}': unknown"))?;
                    if let Some(id) = p.id {
                        let item = part
                            .as_array()
                            .context("id: section must be an object array")?
                            .iter()
                            .find(|v| v["id"] == id)
                            .with_context(|| format!("section '{section}': unknown ID '{id}'"))?;
                        Ok(item.clone())
                    } else {
                        Ok(part.clone())
                    }
                } else {
                    if p.id.is_some() {
                        bail!("id: supply section when selecting an object");
                    }
                    Ok(
                        json!({"name":self.scene.name,"version":self.scene.version,"counts":{"objects":self.scene.objects.len(),"materials":self.scene.materials.len()},"render":self.scene.render,"environment":self.scene.environment,"lights":self.scene.lights,"emitters":self.scene.emitters,"cameras":self.scene.cameras,"routes":self.scene.routes.iter().map(|r|&r.id).collect::<Vec<_>>(),"camera":self.camera,"tick":self.tick,"seed":self.seed,"paused":self.paused}),
                    )
                }
            }
            "get_metrics" => {
                self.renderer.poll_timing(false);
                Ok(
                    json!({"frame":self.renderer.metrics,"capabilities":self.renderer.capabilities(),"tick":self.tick}),
                )
            }
            "get_errors" => Ok(json!({"last_error":self.last_error})),
            "pause" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    paused: bool,
                }
                let p: P = serde_json::from_value(params)?;
                self.paused = p.paused;
                Ok(json!({"paused":self.paused}))
            }
            "step" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    ticks: u32,
                }
                let p: P = serde_json::from_value(params)?;
                if p.ticks > 36000 {
                    bail!("ticks: maximum 36000 per request");
                }
                self.step(p.ticks);
                Ok(json!({"tick":self.tick}))
            }
            "reset" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    seed: u32,
                }
                let p: P = serde_json::from_value(params)?;
                self.reset(p.seed);
                Ok(json!({"tick":0,"seed":self.seed}))
            }
            "set_camera" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    #[serde(default)]
                    id: Option<String>,
                    #[serde(default)]
                    camera: Option<Camera>,
                }
                let p: P = serde_json::from_value(params)?;
                let camera = match (p.id, p.camera) {
                    (Some(id), None) => self
                        .scene
                        .cameras
                        .iter()
                        .find(|c| c.id == id)
                        .with_context(|| format!("camera '{id}': unknown ID"))?
                        .clone(),
                    (None, Some(camera)) => camera,
                    _ => bail!("set_camera: supply exactly one of id or camera"),
                };
                scene::validate_camera(&camera)?;
                self.camera = camera;
                Ok(json!({"camera":self.camera}))
            }
            "set_parameter" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    path: String,
                    value: Value,
                }
                let p: P = serde_json::from_value(params)?;
                let mut next = self.scene.clone();
                set_parameter(
                    &mut next,
                    &p.path,
                    p.value,
                    self.scene_path.parent().unwrap_or(Path::new(".")),
                )?;
                self.scene = next;
                Ok(json!({"path":p.path,"updated":true}))
            }
            "capture_frame" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    path: PathBuf,
                    #[serde(default = "default_scale")]
                    scale: u32,
                }
                let p: P = serde_json::from_value(params)?;
                self.capture(&p.path, p.scale)
            }
            "reload_shaders" => {
                self.renderer.reload_shaders()?;
                Ok(json!({"reloaded":true}))
            }
            _ => bail!("method '{method}': unknown; use describe"),
        }
    }
}
fn default_scale() -> u32 {
    4
}

/// Only live, uniform-backed fields may change here; topology and assets load
/// transactionally at startup. An invalid edit leaves the original scene intact.
pub fn set_parameter(scene: &mut Scene, path: &str, value: Value, base: &Path) -> Result<()> {
    let segments = path.split('.').collect::<Vec<_>>();
    let allowed = match segments.as_slice() {
        ["render", property] => matches!(
            *property,
            "exposure" | "shading_steps" | "dither_strength" | "smoke_steps"
        ),
        ["render", "experiments", property] => matches!(
            *property,
            "pixel_cluster_lighting" | "stable_smoke_detail" | "connected_motion"
        ),
        ["environment", property] => matches!(
            *property,
            "wind" | "ambient" | "fog_density" | "sky_color" | "horizon_color"
        ),
        ["emitters", _, property] => matches!(
            *property,
            "enabled"
                | "intensity"
                | "smoke_density"
                | "buoyancy"
                | "dissipation"
                | "style"
                | "secondary_bubbles"
                | "bubble_scale"
                | "self_shadow_strength"
                | "internal_glow"
        ),
        ["lights", _, property] => matches!(*property, "intensity" | "flicker" | "color"),
        _ => false,
    };
    if !allowed {
        bail!("parameter '{path}': unsupported live field; see describe");
    }
    let mut data = serde_json::to_value(&*scene)?;
    let mut cursor = &mut data;
    for segment in &segments[..segments.len() - 1] {
        if cursor.is_array() {
            cursor = cursor
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|v| v["id"] == *segment)
                .with_context(|| format!("parameter '{path}': unknown object '{segment}'"))?;
        } else {
            cursor = cursor
                .get_mut(*segment)
                .with_context(|| format!("parameter '{path}': unknown property '{segment}'"))?;
        }
    }
    let field = segments.last().unwrap();
    *cursor
        .get_mut(*field)
        .with_context(|| format!("parameter '{path}': unknown property"))? = value;
    let replacement: Scene = serde_json::from_value(data)
        .with_context(|| format!("parameter '{path}': invalid value type"))?;
    replacement.validate(base)?;
    *scene = replacement;
    Ok(())
}

pub fn description() -> Value {
    json!({"protocol_version":1,"transport":"JSON lines on stdin/stdout; diagnostics on stderr; one response per request at a frame boundary","scene_schema":Scene::schema(),"commands":{
        "describe":{},"inspect_scene":{"section":"optional top-level scene field; omitted returns compact overview","id":"optional stable ID within selected array"},"get_metrics":{},"get_errors":{},
        "pause":{"paused":"boolean"},"step":{"ticks":"integer 0..36000"},"reset":{"seed":"u32"},
        "set_camera":{"id":"named camera, OR supply camera object matching scene schema"},
        "set_parameter":{"path":"render.{exposure,shading_steps,dither_strength,smoke_steps}; render.experiments.{pixel_cluster_lighting,stable_smoke_detail,connected_motion}; environment.{wind,ambient,fog_density,sky_color,horizon_color}; emitters.<id>.{enabled,intensity,smoke_density,buoyancy,dissipation,style,secondary_bubbles,bubble_scale,self_shadow_strength,internal_glow}; lights.<id>.{intensity,flicker,color}","value":"typed JSON value"},
        "get_window":{"availability":"native run only"},"set_window":{"availability":"native run only","size":"optional logical [width,height]","minimized":"optional boolean","fullscreen":"optional boolean"},"shutdown":{"availability":"native run only"},
        "capture_frame":{"path":"PNG output path","scale":"integer 1..8, default 4"},"reload_shaders":{}},
        "notes":["Start --agent-stdio paused for deterministic control. step advances even when paused.","Shader and effect mutations preserve smoke history; reset before A/B captures.","Topology, assets and resolution are startup settings. Restart to change them.","No floating point GPU bit-identity is promised between vendors."]})
}

#[cfg(test)]
mod tests {
    use super::*;
    fn scene() -> Scene {
        Scene::load(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../assets/scenes/clearing.json")
                .as_path(),
        )
        .unwrap()
    }
    #[test]
    fn invalid_edit_is_transactional() {
        let mut s = scene();
        let original = s.render.exposure;
        assert!(set_parameter(&mut s, "render.exposure", json!(-1), Path::new(".")).is_err());
        assert_eq!(s.render.exposure, original);
    }
    #[test]
    fn duplicate_id_is_rejected() {
        let mut s = scene();
        s.objects[1].id = s.objects[0].id.clone();
        assert!(s
            .validate(Path::new("."))
            .unwrap_err()
            .to_string()
            .contains("duplicate"));
    }
    #[test]
    fn route_wraps_and_interpolates() {
        let s = scene();
        let r = &s.routes[0];
        let a = r.camera_at(0., &s.cameras[0]);
        let b = r.camera_at(r.duration_seconds, &s.cameras[0]);
        assert_eq!(a.position, b.position);
        let middle = r.camera_at(1., &s.cameras[0]);
        assert_ne!(a.position, middle.position);
    }
    #[test]
    fn request_rejects_unknown_fields() {
        assert!(
            serde_json::from_value::<Request>(json!({"id":1,"method":"step","bad":true})).is_err()
        );
    }
}
