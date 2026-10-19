#!/usr/bin/env python3
"""Isolate the second emitter's opaque point-shadow contribution in fixed-tick captures."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from absorption_cache_study import image_error


ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets/scenes/two-emitter-review.json"
SHADERS = ROOT / "crates/engine/src/render/shaders"
WORLD_SHADER = SHADERS / "world.wgsl"
CAMERAS = ("dual-wide", "smoke-close", "watchfire-study", "heat-ground-study")
SEED = 42
TICK = 300


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def path_reference(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def make_scene(source: dict) -> dict:
    scene = copy.deepcopy(source)
    if sorted(emitter["id"] for emitter in scene["emitters"]) != ["campfire", "watchfire"]:
        raise ValueError("expected the stable campfire/watchfire source IDs")
    for emitter in scene["emitters"]:
        emitter["enabled"] = emitter["id"] == "watchfire"
    scene["cameras"] = [
        camera for camera in scene["cameras"]
        if camera["id"] not in {"watchfire-study", "heat-ground-study"}
    ]
    scene["cameras"].extend(
        [
            {
                "id": "watchfire-study",
                "position": [-0.6, 1.35, 3.0],
                "target": [-3.0, 1.05, 0.0],
                "projection": {"kind": "perspective", "fov_degrees": 48.0},
            },
            {
                "id": "heat-ground-study",
                "position": [-1.2, 1.8, 2.2],
                "target": [-3.0, 0.0, 0.0],
                "projection": {"kind": "perspective", "fov_degrees": 48.0},
            },
        ]
    )
    return scene


def make_unshadowed_shader(source: str) -> str:
    pattern = re.compile(
        r"fn fire_visibility\(p:vec3<f32>,source_slot:u32\) -> f32 \{.*?\n\}",
        re.DOTALL,
    )
    replacement = """fn fire_visibility(p:vec3<f32>,source_slot:u32) -> f32 {
    if source_slot > 1u {
        let light_index=select(g.light_info.y,g.light_info.z,source_slot>0u);
        let d=p-g.point_lights[light_index].position_range.xyz; let major=max(max(abs(d.x),abs(d.y)),abs(d.z));
        let far=g.point_lights[light_index].position_range.w;
        let depth=far/(far-0.05)-(far*0.05)/((far-0.05)*max(major,0.051));
        return textureSampleCompareLevel(point_shadow,shadow_sampler,d,i32(source_slot),depth-0.004);
    }
    return 1.;
}"""
    updated, count = pattern.subn(replacement, source)
    if count != 1:
        raise RuntimeError(f"expected one world point-shadow function, replaced {count}")
    return updated


def capture(binary: Path, scene_path: Path, camera: str, output: Path, shaders: Path | None) -> dict:
    command = [
        str(binary), "capture", "--scene", str(scene_path), "--seed", str(SEED),
        "--camera", camera, "--tick", str(TICK), "--resolution", "640x360",
        "--scale", "1", "--output", str(output.resolve()),
    ]
    if shaders is not None:
        command.extend(["--shaders", str(shaders)])
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return {"image": path_reference(output), "sha256": sha256(output)}


def make_contact_sheet(output: Path, destination: Path) -> Path:
    from PIL import Image, ImageDraw

    sample = Image.open(output / "point_shadows" / f"{CAMERAS[0]}.png").convert("RGB")
    width, height = sample.size
    label_height = 24
    sheet = Image.new("RGB", (width * len(CAMERAS), (height + label_height) * 2), "#16131d")
    draw = ImageDraw.Draw(sheet)
    for column, camera in enumerate(CAMERAS):
        for row, mode in enumerate(("point_shadows", "point_shadows_disabled")):
            path = output / mode / f"{camera}.png"
            image = Image.open(path).convert("RGB")
            if image.size != (width, height):
                raise ValueError(f"capture size mismatch in {path}: {image.size} vs {(width, height)}")
            x, y = column * width, row * (height + label_height)
            draw.text((x + 6, y + 5), f"{camera} - {mode}", fill="white")
            sheet.paste(image, (x, y + label_height))
    path = destination.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    return path


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/two-emitter-shadow-contribution")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-multi-emitter-shadow-contribution.json")
    parser.add_argument("--contact-sheet", type=Path, default=ROOT / "docs/measurements-multi-emitter-shadow-contribution-contact.png")
    args = parser.parse_args()
    binary, output, report_path = args.binary.resolve(), args.output.resolve(), args.report.resolve()
    if not binary.is_file():
        raise SystemExit(f"engine-lab binary does not exist: {binary}")
    if not SCENE.is_file() or not WORLD_SHADER.is_file():
        raise SystemExit("the two-emitter scene or runtime world shader is missing")
    output.mkdir(parents=True, exist_ok=True)

    scene_path = output / "watchfire-only.json"
    scene_path.write_text(json.dumps(make_scene(json.loads(SCENE.read_text())), indent=2) + "\n")
    subprocess.run([str(binary), "validate", str(scene_path)], cwd=ROOT, check=True, capture_output=True)

    candidate_shaders = output / "shaders-no-point-shadows"
    shutil.copytree(SHADERS, candidate_shaders, dirs_exist_ok=True)
    original_world = WORLD_SHADER.read_text()
    candidate_world = make_unshadowed_shader(original_world)
    (candidate_shaders / "world.wgsl").write_text(candidate_world)

    views = {}
    for camera in CAMERAS:
        view = {}
        for mode, shader_dir in (("point_shadows", None), ("point_shadows_disabled", candidate_shaders)):
            path = output / mode / f"{camera}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            view[mode] = capture(binary, scene_path, camera, path, shader_dir)
        view["difference"] = image_error(
            output / "point_shadows" / f"{camera}.png",
            output / "point_shadows_disabled" / f"{camera}.png",
        )
        if view["difference"] is None:
            raise RuntimeError("Pillow is required to measure the captured image differences")
        view["changed"] = view["point_shadows"]["sha256"] != view["point_shadows_disabled"]["sha256"]
        views[camera] = view

    contact_sheet = make_contact_sheet(output, args.contact_sheet)

    report = {
        "version": 1,
        "date": "2026-10-19",
        "workstream": "O02/O07 two-emitter primary-light shadow contribution",
        "scope": "Source-one-only opaque world-pass point-shadow contribution; direct light, sun shadow, smoke and volume shadow sampling remain unchanged.",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal", "native_window": False},
        "scene": path_reference(SCENE),
        "scene_sha256": sha256(SCENE),
        "variant_scene": path_reference(scene_path),
        "variant_scene_sha256": sha256(scene_path),
        "enabled_emitters": ["watchfire"],
        "disabled_emitters": ["campfire"],
        "seed": SEED,
        "tick": TICK,
        "resolution": [640, 360],
        "shader_change": "world.wgsl fire_visibility returns full visibility for the valid source slots 0 and 1; the original lookup remains in an out-of-range branch for shader-counter hook compatibility",
        "world_shader_sha256": {"reference": sha256(WORLD_SHADER), "point_shadows_disabled": sha256(candidate_shaders / "world.wgsl")},
        "binary_sha256": sha256(binary),
        "script_sha256": sha256(Path(__file__)),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "views": views,
        "contact_sheet": {"path": path_reference(contact_sheet), "sha256": sha256(contact_sheet)},
        "all_views_changed": all(view["changed"] for view in views.values()),
        "limitations": [
            "Diagnostic shader variant only suppresses source primary-light shadow lookup in opaque world shading; it is not a no-shadows renderer mode.",
            "Fixed-tick M1 Max/Metal captures only; no continuous playback, performance conclusion, owner visual acceptance or DX12/other-adapter validation.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": path_reference(report_path), "views_changed": {camera: data["changed"] for camera, data in views.items()}}))
    return 0 if views["heat-ground-study"]["changed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
