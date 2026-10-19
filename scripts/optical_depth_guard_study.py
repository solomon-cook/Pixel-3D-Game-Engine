#!/usr/bin/env python3
"""Sweep the O06 snapshot depth guard across optical stress cameras."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image, ImageChops, ImageStat

from optical_surface_reuse_study import mixed_scene

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHADER = ROOT / "crates/engine/src/render/shaders/optical.wgsl"
FOREGROUND_ALPHA_LIMITS = (0.001, 0.01, 0.05, 0.1, 0.25)
CAMERAS = ("mixed-from-behind", "mixed-close", "glass-near")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(reference: Path, candidate: Path) -> dict:
    with Image.open(reference) as image:
        a = image.convert("RGB")
    with Image.open(candidate) as image:
        b = image.convert("RGB")
    difference = ImageChops.difference(a, b)
    extrema = difference.getextrema()
    return {
        "changed_pixels": sum(any(pixel) for pixel in difference.getdata()),
        "total_pixels": a.width * a.height,
        "mean_absolute_channel_error": sum(ImageStat.Stat(difference).mean) / 3,
        "max_channel_error": max(high for _, high in extrema),
        "difference_bounds": list(difference.getbbox()) if difference.getbbox() else None,
    }


def render(binary: Path, scene: Path, shaders: Path, camera: str, output: Path) -> dict:
    subprocess.run([
        str(binary), "capture", "--scene", str(scene), "--camera", camera,
        "--seed", "42", "--tick", "300", "--resolution", "640x360", "--scale", "1",
        "--shaders", str(shaders), "--output", str(output),
    ], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return json.loads(output.with_suffix(".json").read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o06/depth-guard")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o06-depth-guard.json")
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_scene = mixed_scene()
    source_scene["render"]["resolution"] = [640, 360]
    saved_scene = output / "mixed-scene.json"
    saved_scene.write_text(json.dumps(source_scene, indent=2) + "\n")
    cases = []
    with tempfile.TemporaryDirectory(prefix="pixel-engine-o06-depth-guard-") as temporary:
        temp = Path(temporary)
        shaders = temp / "shaders"
        shutil.copytree(SOURCE_SHADER.parent, shaders)
        scene_path = temp / "scene.json"
        direct_scene = copy.deepcopy(source_scene)
        direct_scene["render"].setdefault("experiments", {})["optical_surface_reuse"] = False
        scene_path.write_text(json.dumps(direct_scene))
        direct_images = {}
        adapter = None
        for camera in CAMERAS:
            image = output / f"direct-{camera}.png"
            metadata = render(binary, scene_path, shaders, camera, image)
            direct_images[camera] = image
            adapter = metadata["capabilities"]
        # Current production shader requires exact view-depth equality. First
        # capture that unmodified behavior as the current guard case.
        current_shader = SOURCE_SHADER.read_text()
        (shaders / "optical.wgsl").write_text(current_shader)
        guarded_scene = copy.deepcopy(source_scene)
        guarded_scene["render"].setdefault("experiments", {})["optical_surface_reuse"] = True
        scene_path.write_text(json.dumps(guarded_scene))
        camera_results = []
        for camera in CAMERAS:
            image = output / f"current-exact-depth-{camera}.png"
            render(binary, scene_path, shaders, camera, image)
            camera_results.append({
                "camera": camera,
                "reference_capture": str(direct_images[camera].relative_to(ROOT)),
                "capture": str(image.relative_to(ROOT)),
                "shader_sha256": sha256(shaders / "optical.wgsl"),
                "image_comparison": compare(direct_images[camera], image),
            })
        cases.append({"guard": "current-exact-depth", "cameras": camera_results})
        alpha_cases = []
        for alpha_limit in FOREGROUND_ALPHA_LIMITS:
            shader = SOURCE_SHADER.read_text()
            original_condition = "if sampled_normal_depth.w>0. && sampled_normal_depth.w==expected_depth {"
            guarded_condition = f"if sampled_normal_depth.w>0. && sampled_normal_depth.w==expected_depth && foreground.a<={alpha_limit:.3f} {{"
            if original_condition not in shader:
                raise RuntimeError("optical depth-match condition changed; update this study before running")
            shader = shader.replace(original_condition, guarded_condition)
            (shaders / "optical.wgsl").write_text(shader)
            guarded_scene = copy.deepcopy(source_scene)
            guarded_scene["render"].setdefault("experiments", {})["optical_surface_reuse"] = True
            scene_path.write_text(json.dumps(guarded_scene))
            camera_results = []
            for camera in CAMERAS:
                image = output / f"alpha-{alpha_limit:.3f}-{camera}.png"
                render(binary, scene_path, shaders, camera, image)
                camera_results.append({
                    "camera": camera,
                    "reference_capture": str(direct_images[camera].relative_to(ROOT)),
                    "capture": str(image.relative_to(ROOT)),
                    "shader_sha256": sha256(shaders / "optical.wgsl"),
                    "image_comparison": compare(direct_images[camera], image),
                })
            alpha_cases.append({"maximum_foreground_alpha_for_reuse": alpha_limit, "cameras": camera_results})
    report = {
        "version": 1,
        "date": "2026-10-19",
        "workstream": "O06 opaque surface reuse depth guard sweep",
        "adapter": {"name": adapter["name"], "backend": adapter["backend"]},
        "source_scenes": {
            "clearing_sha256": sha256(ROOT / "assets/scenes/clearing.json"),
            "materials_sha256": sha256(ROOT / "assets/scenes/materials.json"),
            "generated_mixed_scene": str(saved_scene.relative_to(ROOT)),
            "generated_mixed_scene_sha256": sha256(saved_scene),
        },
        "optical_shader_sha256": sha256(SOURCE_SHADER),
        "binary_sha256": sha256(binary),
        "runner_sha256": sha256(Path(__file__).resolve()),
        "seed": 42,
        "tick": 300,
        "resolution": [640, 360],
        "comparison": "Direct versus reused opaque lighting at identical fixed ticks. The current exact-depth shader is compared first, then variants add foreground-alpha limits.",
        "cases": cases,
        "foreground_alpha_sweep": alpha_cases,
        "interpretation": "The current release exact-depth guard matches direct shading exactly in all three fixed-tick cameras. Adding foreground-alpha limits from 0.001 to 0.25 does not change the captures. The older reported behind-view discrepancy was not reproduced with the current release binary and current shader. This sweep does not establish continuous visual acceptance or a timing improvement.",
        "limitations": ["Offscreen M1 Max/Metal only.", "Three fixed cameras do not establish continuous visual quality.", "No timing conclusion is drawn from capture metadata."],
    }
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "guards": len(cases), "cameras": len(CAMERAS)}))


if __name__ == "__main__":
    main()
