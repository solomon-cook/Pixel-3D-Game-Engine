#!/usr/bin/env python3
"""Measure an O06 snapshot-color guard against direct fixed-tick captures."""

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
CAMERAS = ("mixed-from-behind", "mixed-close", "glass-near")
THRESHOLDS = (0.001, 0.01, 0.05)


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
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o06/snapshot-color-guard")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o06-snapshot-color-guard.json")
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scene = mixed_scene()
    scene["render"]["resolution"] = [640, 360]
    saved_scene = output / "mixed-scene.json"
    saved_scene.write_text(json.dumps(scene, indent=2) + "\n")
    cases = []
    with tempfile.TemporaryDirectory(prefix="pixel-engine-o06-snapshot-color-") as temporary:
        temp = Path(temporary)
        shaders = temp / "shaders"
        shutil.copytree(SOURCE_SHADER.parent, shaders)
        scene_path = temp / "scene.json"
        adapter = None
        direct = {}
        direct_scene = copy.deepcopy(scene)
        direct_scene.setdefault("render", {}).setdefault("experiments", {})["optical_surface_reuse"] = False
        scene_path.write_text(json.dumps(direct_scene))
        for camera in CAMERAS:
            image = output / f"direct-{camera}.png"
            metadata = render(binary, scene_path, shaders, camera, image)
            direct[camera] = image
            adapter = metadata["capabilities"]
        for threshold in THRESHOLDS:
            shader = SOURCE_SHADER.read_text()
            original = "abs(sampled_normal_depth.w-expected_depth)<=depth_tolerance {"
            replacement = (
                f"abs(sampled_normal_depth.w-expected_depth)<=depth_tolerance && "
                f"max(composited.r,max(composited.g,composited.b))>{threshold:.3f} {{"
            )
            if shader.count(original) != 1:
                raise RuntimeError("O06 depth guard changed; update this study before running")
            shader = shader.replace(original, replacement)
            (shaders / "optical.wgsl").write_text(shader)
            reused_scene = copy.deepcopy(scene)
            reused_scene.setdefault("render", {}).setdefault("experiments", {})["optical_surface_reuse"] = True
            scene_path.write_text(json.dumps(reused_scene))
            camera_results = []
            for camera in CAMERAS:
                image = output / f"bright-{threshold:g}-{camera}.png"
                render(binary, scene_path, shaders, camera, image)
                camera_results.append({
                    "camera": camera,
                    "reference_capture": str(direct[camera].relative_to(ROOT)),
                    "capture": str(image.relative_to(ROOT)),
                    "shader_sha256": sha256(shaders / "optical.wgsl"),
                    "image_comparison": compare(direct[camera], image),
                })
            cases.append({"minimum_snapshot_rgb_component": threshold, "cameras": camera_results})
    report = {
        "version": 1,
        "date": "2026-10-18",
        "workstream": "O06 opaque surface reuse snapshot-color guard study",
        "adapter": {"name": adapter["name"], "backend": adapter["backend"]},
        "generated_mixed_scene": str(saved_scene.relative_to(ROOT)),
        "generated_mixed_scene_sha256": sha256(saved_scene),
        "optical_shader_sha256": sha256(SOURCE_SHADER),
        "binary_sha256": sha256(binary),
        "runner_sha256": sha256(Path(__file__).resolve()),
        "seed": 42,
        "tick": 300,
        "resolution": [640, 360],
        "comparison": "Direct versus reused opaque lighting at matching fixed ticks; each variant additionally requires the sampled HDR snapshot RGB maximum to exceed the listed threshold.",
        "cases": cases,
        "interpretation": "The color guard reduces changed pixels in the behind-smoke view from 12 to 8 at threshold 0.05, but maximum channel error remains 52/255. The other two cameras remain exact. This is an image-only experiment and does not establish improved visual acceptability or timing.",
        "limitations": ["Offscreen M1 Max/Metal only.", "Three fixed cameras do not establish continuous visual quality.", "No timing conclusion is drawn from capture metadata."],
    }
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "thresholds": len(cases), "cameras": len(CAMERAS)}))


if __name__ == "__main__":
    main()
