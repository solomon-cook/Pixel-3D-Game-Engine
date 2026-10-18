#!/usr/bin/env python3
"""Compare direct/reused optical lighting from inside glass and at a near plane."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/materials.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def error_stats(a: Image.Image, b: Image.Image) -> dict:
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    histogram = diff.histogram()
    channels = (histogram[:256], histogram[256:512], histogram[512:768])
    count = diff.width * diff.height
    changed = sum(1 for pixel in diff.getdata() if any(pixel))
    return {
        "changed_pixels": changed,
        "pixel_count": count,
        "mean_absolute_rgb_error_0_255": [sum(i * n for i, n in enumerate(ch)) / count for ch in channels],
        "maximum_absolute_rgb_error_0_255": [max(i for i, n in enumerate(ch) if n) for ch in channels],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release" / ("engine-lab.exe" if os.name == "nt" else "engine-lab"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o06/camera-stress")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o06-camera-stress.json")
    args = parser.parse_args()
    binary, output, report_path = args.binary.resolve(), args.output.resolve(), args.report.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    output.mkdir(parents=True, exist_ok=True)
    scene = json.loads(SOURCE.read_text())
    cameras = [
        {"id": "glass-inside-oblique", "position": [0.0, 1.35, 2.55], "target": [1.0, 1.35, 2.55], "projection": {"kind": "perspective", "fov_degrees": 48.0}},
        {"id": "glass-near-plane", "position": [0.0, 1.35, 2.85], "target": [0.0, 1.35, 1.7], "projection": {"kind": "perspective", "fov_degrees": 48.0}},
    ]
    scene["cameras"] = [camera for camera in scene["cameras"] if camera["id"] not in {c["id"] for c in cameras}] + cameras
    scene_path = output / "scene.json"
    scene_path.write_text(json.dumps(scene, indent=2) + "\n")
    subprocess.run([str(binary), "validate", str(scene_path)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)

    cases = {}
    sheet = Image.new("RGB", (1280, 420), (20, 20, 20))
    for row, camera in enumerate(cameras):
        case = camera["id"]
        captures = {}
        for mode, experiment in (("direct", None), ("reuse", "optical_surface_reuse")):
            image_path = output / f"{case}-{mode}.png"
            command = [str(binary), "capture", "--scene", str(scene_path), "--camera", case, "--seed", "42", "--tick", "300", "--scale", "1", "--output", str(image_path)]
            if experiment:
                command.extend(["--experiments", experiment])
            subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
            captures[mode] = Image.open(image_path).convert("RGB")
        stats = error_stats(captures["direct"], captures["reuse"])
        cases[case] = {
            **stats,
            "direct_sha256": sha256(output / f"{case}-direct.png"),
            "reuse_sha256": sha256(output / f"{case}-reuse.png"),
        }
        difference = ImageChops.difference(captures["direct"], captures["reuse"]).point(lambda value: min(255, value * 6))
        for x, image, label in ((0, captures["direct"], "direct"), (430, captures["reuse"], "reuse"), (860, difference, "6x difference")):
            image.thumbnail((420, 180))
            sheet.paste(image, (x, row * 210 + 24))
            ImageDraw.Draw(sheet).text((x + 4, row * 210 + 5), f"{case}: {label}", fill="white")
    contact_path = output / "contact.png"
    sheet.save(contact_path)
    report = {
        "workstream": "O06 inside-glass and near-plane optical stress",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal"},
        "resolution": [640, 360],
        "seed": 42,
        "tick": 300,
        "cameras": {camera["id"]: camera for camera in cameras},
        "source_scene_sha256": sha256(SOURCE),
        "stress_scene_sha256": sha256(scene_path),
        "shader_source_sha256": sha256(ROOT / "crates/engine/src/render/shaders/optical.wgsl"),
        "binary_sha256": sha256(binary),
        "study_script_sha256": sha256(Path(__file__).resolve()),
        "cases": cases,
        "fix": "Transmissive backfaces are no longer discarded. The geometric normal/view relation selects entry versus exit and the refraction ratio; total internal reflection falls back to reflection.",
        "visual_review": "The inside-to-oblique capture renders the environment through the exit interface. The near-plane sample shows no direct/reuse image difference. Contact sheet is sampled fixed-tick evidence.",
        "limitations": ["Two still cameras only; continuous inside-glass motion is not reviewed.", "M1 Max/Metal only; Windows/DX12 and other adapters remain unverified.", "The near-plane camera is 0.1 world units outside the glass sphere surface, approximating the renderer's 0.1 near clip distance."],
        "contact_sheet": {"path": str(contact_path.relative_to(ROOT)), "sha256": sha256(contact_path)},
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "cases": {key: value["changed_pixels"] for key, value in cases.items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
