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
    pub simulation_batching_enabled: bool,
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
            simulation_batching_enabled: true,
            scene_path,
            last_error: None,
        }
    }
    pub fn step(&mut self, count: u32) {
        self.step_batched(count, self.simulation_batching_enabled);
    }
    pub fn step_unbatched(&mut self, count: u32) {
        self.step_batched(count, false);
    }
    pub fn set_simulation_batching(&mut self, enabled: bool) {
        self.simulation_batching_enabled = enabled;
    }
    fn step_batched(&mut self, count: u32, batching: bool) {
        let mut remaining = count;
        while remaining > 0 {
            if batching {
                let batch_count = remaining.min(crate::render::SIMULATION_BATCH_CAPACITY as u32);
                let ticks = (1..=batch_count)
                    .map(|offset| self.tick + offset as u64)
                    .collect::<Vec<_>>();
                self.renderer
                    .simulate_batch(&self.scene, &self.camera, &ticks, self.seed);
                self.tick += batch_count as u64;
                remaining -= batch_count;
            } else {
                self.tick += 1;
                self.renderer
                    .simulate(&self.scene, &self.camera, self.tick, self.seed);
                remaining -= 1;
            }
        }
    }
    pub fn render(&mut self) {
        self.renderer
            .render(&self.scene, &self.camera, self.tick, self.seed);
    }
    pub fn begin_measurement_frame(&mut self) {
        self.renderer.begin_measurement_frame();
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
                        json!({"name":self.scene.name,"version":self.scene.version,"counts":{"objects":self.scene.objects.len(),"materials":self.scene.materials.len()},"render":self.scene.render,"environment":self.scene.environment,"lights":self.scene.lights,"emitters":self.scene.emitters,"effects":self.scene.effects,"cameras":self.scene.cameras,"routes":self.scene.routes.iter().map(|r|&r.id).collect::<Vec<_>>(),"camera":self.camera,"tick":self.tick,"seed":self.seed,"paused":self.paused}),
                    )
                }
            }
            "inspect_effects" => {
                self.render();
                Ok(self.renderer.effect_state())
            }
            "get_metrics" => {
                self.renderer.poll_timing(false);
                Ok(
                    json!({"frame":self.renderer.metrics,"capabilities":self.renderer.capabilities(),"tick":self.tick,"simulation_batching_enabled":self.simulation_batching_enabled}),
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
            "set_object_transform" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    id: String,
                    position: Option<[f32; 3]>,
                    rotation: Option<[f32; 3]>,
                    scale: Option<[f32; 3]>,
                }
                let p: P = serde_json::from_value(params)?;
                if p.position.is_none() && p.rotation.is_none() && p.scale.is_none() {
                    bail!("set_object_transform: provide position, rotation, or scale");
                }
                let mut next = self.scene.clone();
                let object = next
                    .objects
                    .iter_mut()
                    .find(|object| object.id == p.id)
                    .with_context(|| format!("set_object_transform: unknown object '{}'", p.id))?;
                if let Some(position) = p.position {
                    object.position = position;
                }
                if let Some(rotation) = p.rotation {
                    object.rotation = rotation;
                }
                if let Some(scale) = p.scale {
                    object.scale = scale;
                }
                next.validate(self.scene_path.parent().unwrap_or(Path::new(".")))?;
                let updated = next
                    .objects
                    .iter()
                    .find(|object| object.id == p.id)
                    .expect("validated scene retains its object");
                let revision = self.renderer.set_object_transform(updated)?;
                let transform = json!({
                    "position":updated.position,
                    "rotation":updated.rotation,
                    "scale":updated.scale
                });
                self.scene = next;
                Ok(json!({"id":p.id,"revision":revision,"transform":transform}))
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
                self.renderer.invalidate_absorption_cache();
                self.renderer.invalidate_smoke_candidates();
                Ok(json!({"path":p.path,"updated":true}))
            }
            "set_shadow_cache" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    force_redraw: bool,
                }
                let p: P = serde_json::from_value(params)?;
                self.renderer.set_force_shadow_redraw(p.force_redraw);
                Ok(json!({"force_redraw":self.renderer.force_shadow_redraw()}))
            }
            "set_tile_lists" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    enabled: bool,
                    #[serde(default)]
                    force_overflow: bool,
                    #[serde(default)]
                    precompute_fire_bounds: bool,
                }
                let p: P = serde_json::from_value(params)?;
                self.renderer.set_tile_lists(p.enabled, p.force_overflow);
                self.renderer
                    .set_fire_bounds_precompute(p.precompute_fire_bounds);
                Ok(
                    json!({"enabled":p.enabled,"force_overflow":p.force_overflow,"precompute_fire_bounds":p.precompute_fire_bounds}),
                )
            }
            "set_shading_diagnostics" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    enabled: bool,
                }
                let p: P = serde_json::from_value(params)?;
                self.renderer.set_shading_diagnostics(p.enabled);
                Ok(json!({
                    "enabled": p.enabled,
                    "scratch_bytes": self.renderer.capabilities()["resource_inventory"]["shading_diagnostic_targets_bytes"],
                }))
            }
            "set_geometry_rendering" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    culling: bool,
                    instancing: bool,
                }
                let p: P = serde_json::from_value(params)?;
                self.renderer
                    .set_geometry_rendering(p.culling, p.instancing);
                Ok(json!({"culling":p.culling,"instancing":p.instancing}))
            }
            "set_simulation_batching" => {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct P {
                    enabled: bool,
                }
                let p: P = serde_json::from_value(params)?;
                self.set_simulation_batching(p.enabled);
                Ok(json!({"enabled":self.simulation_batching_enabled}))
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
                self.renderer.invalidate_absorption_cache();
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
    let linked_emitter_ids = match segments.as_slice() {
        ["lights", light_id, "position"] => scene
            .emitters
            .iter()
            .filter(|emitter| {
                scene
                    .light_for_emitter(emitter)
                    .is_some_and(|light| light.id == *light_id)
            })
            .map(|emitter| emitter.id.clone())
            .collect::<Vec<_>>(),
        _ => Vec::new(),
    };
    let allowed = match segments.as_slice() {
        ["render", property] => matches!(
            *property,
            "exposure"
                | "shading_steps"
                | "dither_strength"
                | "smoke_steps"
                | "palette_strength"
                | "bloom_strength"
                | "reflection_steps"
        ),
        ["render", "experiments", property] => matches!(
            *property,
            "pixel_cluster_lighting"
                | "stable_smoke_detail"
                | "connected_motion"
                | "projected_detail_lod"
                | "smoke_absorption_cache"
                | "optical_surface_reuse"
                | "smoke_candidate_cache"
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
                | "effect_profile"
        ),
        ["effects", _, "fire", property] => matches!(
            *property,
            "width"
                | "height"
                | "motion_speed"
                | "curl"
                | "edge_breakup"
                | "tip_breakup"
                | "fragment_size"
                | "lobe_roundness"
                | "solid"
                | "color_bands"
                | "heat_distortion"
                | "heat_distortion_height"
                | "branches"
                | "particle_lights"
                | "particle_light_strength"
                | "particle_light_range"
                | "tongues"
                | "segments"
                | "fragment_rate"
                | "fragment_lifetime"
                | "ember_rate"
                | "ember_lifetime"
                | "emission"
        ),
        ["effects", _, "thermal", property] => {
            matches!(*property, "heat_output" | "cooling_rate" | "lift")
        }
        ["effects", _, "palette", property] => matches!(*property, "outer" | "warm" | "hot"),
        ["materials", _, property] => matches!(
            *property,
            "color"
                | "roughness"
                | "emission"
                | "metallic"
                | "reflectivity"
                | "transmission"
                | "ior"
                | "thickness"
                | "absorption"
                | "subsurface"
                | "scatter_color"
                | "heat_response"
        ),
        ["lights", _, property] => matches!(
            *property,
            "intensity" | "flicker" | "color" | "range" | "position"
        ),
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
    if !linked_emitter_ids.is_empty() {
        let ["lights", light_id, "position"] = segments.as_slice() else {
            unreachable!("linked emitters only exist for light position edits");
        };
        let light_position = data["lights"]
            .as_array()
            .and_then(|lights| lights.iter().find(|light| light["id"] == *light_id))
            .and_then(|light| light.get("position"))
            .cloned()
            .context("linked point light position disappeared during edit")?;
        for emitter in data["emitters"]
            .as_array_mut()
            .context("scene emitters must be an array")?
        {
            if linked_emitter_ids.iter().any(|id| emitter["id"] == *id) {
                emitter["position"] = light_position.clone();
            }
        }
    }
    let replacement: Scene = serde_json::from_value(data)
        .with_context(|| format!("parameter '{path}': invalid value type"))?;
    replacement.validate(base)?;
    *scene = replacement;
    Ok(())
}

pub fn description() -> Value {
    json!({"protocol_version":1,"transport":"JSON lines on stdin/stdout; diagnostics on stderr; one response per request at a frame boundary","scene_schema":Scene::schema(),"commands":{
        "describe":{},"inspect_scene":{"section":"optional top-level scene field; omitted returns compact overview","id":"optional stable ID within selected array"},"get_metrics":{},"inspect_effects":{"result":"bounded runtime flame counts, bounds and particle light positions/powers with stable event identities"},"get_errors":{},
        "pause":{"paused":"boolean"},"step":{"ticks":"integer 0..36000"},"reset":{"seed":"u32"},
        "set_camera":{"id":"named camera, OR supply camera object matching scene schema"},
        "set_object_transform":{"id":"stable scene object ID","position":"optional [x,y,z]","rotation":"optional [x,y,z] radians, XYZ order","scale":"optional positive [x,y,z]","result":"updated transform and per-object transform revision"},
        "set_parameter":{"path":"render.{exposure,shading_steps,dither_strength,smoke_steps,palette_strength,bloom_strength,reflection_steps}; render.experiments.{pixel_cluster_lighting,stable_smoke_detail,connected_motion,projected_detail_lod,smoke_absorption_cache,optical_surface_reuse,smoke_candidate_cache}; environment.{wind,ambient,fog_density,sky_color,horizon_color}; emitters.<id>.{enabled,intensity,smoke_density,buoyancy,dissipation,style,secondary_bubbles,bubble_scale,self_shadow_strength,internal_glow,effect_profile}; effects.<id>.fire.{width,height,motion_speed,curl,edge_breakup,tip_breakup,fragment_size,lobe_roundness,solid,color_bands,heat_distortion,heat_distortion_height,branches,particle_lights,particle_light_strength,particle_light_range,tongues,segments,fragment_rate,fragment_lifetime,ember_rate,ember_lifetime,emission}; effects.<id>.thermal.{heat_output,cooling_rate,lift}; effects.<id>.palette.{outer,warm,hot}; lights.<id>.{intensity,flicker,color,position,range}; materials.<id>.{color,roughness,emission,metallic,reflectivity,transmission,ior,thickness,absorption,subsurface,scatter_color,heat_response}","value":"typed JSON value; moving a linked fire-light position also moves its emitter atomically"},
        "get_window":{"availability":"native run only"},"set_window":{"availability":"native run only","size":"optional logical [width,height]","minimized":"optional boolean","fullscreen":"optional boolean"},"shutdown":{"availability":"native run only"},
        "set_shadow_cache":{"force_redraw":"boolean; true redraws every shadow map on every frame for comparison"},
        "set_tile_lists":{"enabled":"boolean; false uses exhaustive candidate evaluation for the correctness baseline","force_overflow":"optional boolean; forces exhaustive fallback for every tile to validate overflow behavior","precompute_fire_bounds":"optional boolean; precompute conservative fire screen bounds once per frame instead of projecting each primitive for every tile"},
        "set_shading_diagnostics":{"enabled":"boolean; enables companion instrumented draws and exposes counters in capture_frame/get_metrics; adds diagnostic scratch targets and perturbs timing"},
        "set_simulation_batching":{"enabled":"boolean; true batches up to six fixed smoke ticks per queue submission; false uses one submission per tick"},
        "set_geometry_rendering":{"culling":"boolean; false draws every object in every applicable pass","instancing":"boolean; false issues one object draw for comparison"},
        "capture_frame":{"path":"PNG output path","scale":"integer 1..8, default 4"},"reload_shaders":{}},
        "notes":["Start --agent-stdio paused for deterministic control. step advances even when paused.","get_metrics includes CPU simulation submission, renderer encoding/uploads, fixed-step counts, object-culling/instancing counts and CPU time, tile-list encoding/capacity and per-pass GPU timestamps when supported; timestamps are asynchronous and identify their source frame. Per-frame smoke-configuration and render-Globals upload counts and payload bytes are reported; smoke compute reads tick inputs from the source-local configuration buffer; absorption-cache build/skip counters are cumulative for the session.","Use set_shading_diagnostics on a paused native session to enable companion instrumented draws; capture_frame then records shading_counters in get_metrics and capture metadata. Counters include fire/smoke/light/optical operations and soft-volume, inked-smoke and total volume-fragment invocations. Atomic instrumentation perturbs timing and is diagnostic only; disable it after sampling to release scratch targets.","Object culling tests bounds independently against the active camera and each shadow frustum; unknown bounds remain visible. Shadow casters outside the camera can still render into visible light maps.","Tile lists preserve original candidate order. Per-category overflow and forced-overflow mode use exhaustive evaluation for that category.","Shadow cache hits, redraws, dirty reasons and shadow_dirty_faces are reported per frame. The mask starts with the sun face, then has six cube faces for each source ID in shadow_source_ids order. Tracked transform and shadow-participation changes redraw affected faces by conservative bounds; uncertain changes redraw all maps. Camera and light color/power do not invalidate shadow maps.","Native get_metrics also reports UI, surface acquisition, presentation encoding/submission and full-frame CPU spans; these overlap and must not be summed.","render.compact_hdr or --compact-hdr selects the experimental Rg11b10Ufloat HDR color target at startup when adapter features allow it; the default is Rgba16Float and unsupported adapters retain the default.","render.optical_no_copy or --optical-no-copy selects the experimental optical overlay path and skips the HDR snapshot copy; RGBA16F uses alpha coverage while compact HDR uses an R8 mask, and the option remains disabled by default.","Shader and effect mutations preserve smoke history; reset before A/B captures.","Topology, assets, resolution and HDR target format are startup settings. Restart to change them.","No floating point GPU bit-identity is promised between vendors."]})
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
    fn metrics_description_explains_timing_coverage() {
        let notes = description()["notes"].as_array().unwrap().clone();
        assert!(notes
            .iter()
            .any(|note| note.as_str().unwrap().contains("per-pass GPU timestamps")));
        assert!(notes
            .iter()
            .any(|note| note.as_str().unwrap().contains("must not be summed")));
    }
    #[test]
    fn material_edits_validate_transactionally() {
        let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/scenes/clearing.json");
        let mut scene = Scene::load(&path).unwrap();
        let base = path.parent().unwrap();
        assert_eq!(scene.materials[0].metallic, 0.);
        assert_eq!(scene.materials[0].transmission, 0.);
        assert_eq!(scene.materials[0].heat_response, 0.);
        for (property, value) in [
            ("metallic", json!(1.)),
            ("reflectivity", json!(0.7)),
            ("transmission", json!(0.8)),
            ("ior", json!(1.33)),
            ("thickness", json!(0.6)),
            ("absorption", json!([0.1, 0.2, 0.3])),
            ("subsurface", json!(0.75)),
            ("scatter_color", json!([0.8, 0.4, 0.1])),
            ("heat_response", json!(0.75)),
        ] {
            set_parameter(
                &mut scene,
                &format!("materials.earth.{property}"),
                value,
                base,
            )
            .unwrap();
        }
        let before = serde_json::to_value(&scene).unwrap();
        for (property, value) in [
            ("ior", json!(0.)),
            ("metallic", json!(2.)),
            ("thickness", json!(-1.)),
            ("transmission", json!("glass")),
            ("absorption", json!([-1., 0., 0.])),
            ("subsurface", json!(1.1)),
            ("heat_response", json!(1.1)),
        ] {
            let error = set_parameter(
                &mut scene,
                &format!("materials.earth.{property}"),
                value,
                base,
            )
            .unwrap_err();
            assert!(format!("{error:#}").contains(property));
            assert_eq!(serde_json::to_value(&scene).unwrap(), before);
        }
        assert!(
            set_parameter(&mut scene, "materials.missing.roughness", json!(0.2), base).is_err()
        );
    }

    #[test]
    fn moving_linked_fire_light_moves_emitter_atomically() {
        let mut s = scene();
        let base = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets/scenes");
        let position = json!([1.0, 0.5, -2.0]);
        set_parameter(
            &mut s,
            "lights.fire-light.position",
            position.clone(),
            &base,
        )
        .unwrap();
        assert_eq!(s.emitters[0].position, [1.0, 0.5, -2.0]);
        assert_eq!(
            s.lights
                .iter()
                .find(|light| light.id == "fire-light")
                .unwrap()
                .position,
            [1.0, 0.5, -2.0]
        );
        let before_invalid_edit = serde_json::to_value(&s).unwrap();
        assert!(set_parameter(
            &mut s,
            "lights.fire-light.position",
            json!("invalid"),
            &base,
        )
        .is_err());
        assert_eq!(serde_json::to_value(&s).unwrap(), before_invalid_edit);

        let mut legacy_data = serde_json::to_value(scene()).unwrap();
        legacy_data["emitters"][0]
            .as_object_mut()
            .unwrap()
            .remove("light_id");
        let mut legacy_scene: Scene = serde_json::from_value(legacy_data).unwrap();
        set_parameter(
            &mut legacy_scene,
            "lights.fire-light.position",
            position,
            &base,
        )
        .unwrap();
        assert_eq!(legacy_scene.emitters[0].position, [1.0, 0.5, -2.0]);
    }

    #[test]
    fn invalid_edit_is_transactional() {
        let mut s = scene();
        let original = s.render.exposure;
        assert!(set_parameter(&mut s, "render.exposure", json!(-1), Path::new(".")).is_err());
        assert_eq!(s.render.exposure, original);
    }
    #[test]
    fn effect_profiles_validate_and_live_edits_are_transactional() {
        let mut s = scene();
        set_parameter(
            &mut s,
            "effects.effect-campfire.fire.motion_speed",
            json!(0.3),
            Path::new("."),
        )
        .unwrap();
        assert_eq!(s.effects[0].fire.motion_speed, 0.3);
        assert!(set_parameter(
            &mut s,
            "effects.effect-campfire.fire.segments",
            json!(1000),
            Path::new(".")
        )
        .is_err());
        assert_eq!(s.effects[0].fire.segments, 6);
        assert!(set_parameter(
            &mut s,
            "emitters.campfire.effect_profile",
            json!("missing"),
            Path::new(".")
        )
        .is_err());
        set_parameter(
            &mut s,
            "emitters.campfire.effect_profile",
            json!("effect-quiet"),
            Path::new("."),
        )
        .unwrap();
        assert_eq!(s.emitters[0].effect_profile, "effect-quiet");
        assert!(set_parameter(
            &mut s,
            "effects.effect-quiet.thermal.cooling_rate",
            json!(-1),
            Path::new(".")
        )
        .is_err());
    }
    #[test]
    fn original_v1_scenes_receive_default_effects() {
        let mut data = serde_json::to_value(scene()).unwrap();
        data.as_object_mut().unwrap().remove("effects");
        data["emitters"][0]
            .as_object_mut()
            .unwrap()
            .remove("effect_profile");
        data["render"]
            .as_object_mut()
            .unwrap()
            .remove("bloom_strength");
        data["render"]
            .as_object_mut()
            .unwrap()
            .remove("palette_strength");
        let s: Scene = serde_json::from_value(data).unwrap();
        s.validate(Path::new(".")).unwrap();
        assert_eq!(s.effects.len(), 1);
        assert_eq!(s.effects[0].id, s.emitters[0].effect_profile);
        assert_eq!(s.render.bloom_strength, 0.);
        assert!(!s.render.compact_hdr);
    }
    #[test]
    fn point_light_budget_and_source_binding_are_validated() {
        let mut s = scene();
        let base = s
            .lights
            .iter()
            .find(|l| l.kind == crate::scene::LightKind::Point)
            .unwrap()
            .clone();
        for i in 0..7 {
            let mut light = base.clone();
            light.id = format!("test-light-{i}");
            light.position[0] += i as f32 + 1.;
            s.lights.push(light);
        }
        s.validate(Path::new(".")).unwrap();
        let mut extra = base.clone();
        extra.id = "too-many".into();
        s.lights.push(extra);
        assert!(s
            .validate(Path::new("."))
            .unwrap_err()
            .to_string()
            .contains("1..8"));
        s.lights.pop();
        s.lights.last_mut().unwrap().range = 0.;
        assert!(s
            .validate(Path::new("."))
            .unwrap_err()
            .to_string()
            .contains(".range"));
        let mut s = scene();
        s.lights
            .iter_mut()
            .find(|l| l.kind == crate::scene::LightKind::Point)
            .unwrap()
            .position[0] += 1.;
        assert!(s
            .validate(Path::new("."))
            .unwrap_err()
            .to_string()
            .contains("coincide"));
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
