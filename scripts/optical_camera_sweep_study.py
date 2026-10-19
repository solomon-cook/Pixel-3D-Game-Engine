#!/usr/bin/env python3
"""Compare direct and reused optical lighting along a deterministic glass-camera sweep."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/scenes/materials.json"
OPTICAL_SHADER = ROOT / "crates/engine/src/render/shaders/optical.wgsl"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stats(a: Image.Image, b: Image.Image) -> dict:
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    histogram = diff.histogram()
    channels = (histogram[:256], histogram[256:512], histogram[512:768])
    count = diff.width * diff.height
    changed = sum(1 for pixel in diff.getdata() if any(pixel))
    return {
        "changed_pixels": changed,
        "pixel_count": count,
        "mean_absolute_rgb_error_0_255": [
            sum(value * occurrences for value, occurrences in enumerate(channel)) / count
            for channel in channels
        ],
        "maximum_absolute_rgb_error_0_255": [
            max(value for value, occurrences in enumerate(channel) if occurrences)
            for channel in channels
        ] if changed else [0, 0, 0],
    }


def camera_pose(index: int, frames: int, center: tuple[float, float, float],
                radius_start: float, radius_end: float) -> dict:
    t = index / (frames - 1)
    angle = 2.0 * math.pi * t
    radius = radius_start + (radius_end - radius_start) * t
    x, y, z = center
    return {
        "id": "glass-orbit-sweep",
        "position": [x + math.sin(angle) * radius, y, z + math.cos(angle) * radius],
        "target": [x, y, z],
        "projection": {"kind": "perspective", "fov_degrees": 48.0},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--frames", type=int, default=40)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o06/camera-sweep-current-release")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o06-camera-sweep-current-release.json")
    args = parser.parse_args()
    binary, output, report_path = args.binary.resolve(), args.output.resolve(), args.report.resolve()
    if not binary.is_file() or not SOURCE.is_file():
        parser.error("binary and source scene must exist")
    if args.frames < 8 or args.frames > 240:
        parser.error("frames must be between 8 and 240")

    base = json.loads(SOURCE.read_text())
    glass = next((obj for obj in base.get("objects", []) if obj.get("id") == "glass-sample"), None)
    if glass is None or glass.get("material") != "glass":
        parser.error("source scene must contain the glass-sample object with the glass material")
    center = tuple(float(value) for value in glass["position"])
    # The source scene uses a unit-diameter sphere mesh scaled by 2.1, so its
    # world-space radius is 1.05. This sweep starts inside and exits the surface.
    radius_start, radius_end = 0.75, 1.25
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    direct_images, reuse_images = [], []
    for frame in range(args.frames):
        scene = json.loads(json.dumps(base))
        camera = camera_pose(frame, args.frames, center, radius_start, radius_end)
        scene["cameras"] = [item for item in scene.get("cameras", []) if item.get("id") != camera["id"]]
        scene["cameras"].append(camera)
        scene_path = output / f"scene-{frame:04d}.json"
        scene_path.write_text(json.dumps(scene, indent=2) + "\n")
        captures = {}
        for variant, experiment in (("direct", None), ("reuse", "optical_surface_reuse")):
            image_path = output / f"frame-{frame:04d}-{variant}.png"
            command = [
                str(binary), "capture", "--scene", str(scene_path),
                "--camera", camera["id"], "--seed", "42", "--tick", "300",
                "--resolution", "640x360", "--scale", "1", "--output", str(image_path),
            ]
            if experiment:
                command.extend(["--experiments", experiment])
            subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
            captures[variant] = Image.open(image_path).convert("RGB")
        image_stats = stats(captures["direct"], captures["reuse"])
        rows.append({"frame": frame, "t": frame / (args.frames - 1), "camera": camera, **image_stats})
        direct_images.append(captures["direct"])
        reuse_images.append(captures["reuse"])
        print(json.dumps({"frame": frame, "changed_pixels": image_stats["changed_pixels"]}), flush=True)

    temporal_rows = []
    for frame in range(1, args.frames):
        direct_delta = ImageChops.difference(direct_images[frame], direct_images[frame - 1])
        reuse_delta = ImageChops.difference(reuse_images[frame], reuse_images[frame - 1])
        temporal_rows.append({"frame": frame, **stats(direct_delta, reuse_delta)})

    playback = []
    for direct, reuse in zip(direct_images, reuse_images):
        pair = Image.new("RGB", (1280, 360), (16, 16, 16))
        pair.paste(direct, (0, 0))
        pair.paste(reuse, (640, 0))
        draw = ImageDraw.Draw(pair)
        draw.text((8, 8), "direct", fill="white")
        draw.text((648, 8), "optical reuse", fill="white")
        playback.append(pair)
    playback_path = output / "direct-vs-reuse.gif"
    playback[0].save(playback_path, save_all=True, append_images=playback[1:], duration=100, loop=0, optimize=False)

    contact = Image.new("RGB", (1280, 900), (16, 16, 16))
    sample_indices = sorted(set(round(i * (args.frames - 1) / 7) for i in range(8)))
    for row, frame in enumerate(sample_indices):
        direct = direct_images[frame].copy()
        reuse = reuse_images[frame].copy()
        diff = ImageChops.difference(direct, reuse).point(lambda value: min(255, value * 6))
        for x, image, label in ((0, direct, "direct"), (430, reuse, "reuse"), (860, diff, "6x difference")):
            image.thumbnail((420, 180))
            contact.paste(image, (x, row * 112 + 20))
            ImageDraw.Draw(contact).text((x + 4, row * 112 + 3), f"frame {frame}: {label}", fill="white")
    contact_path = output / "contact.png"
    contact.save(contact_path)

    report = {
        "workstream": "O06 current-release deterministic inside-to-outside glass camera sweep",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal", "os": platform.platform()},
        "source_scene": str(SOURCE.relative_to(ROOT)),
        "source_scene_sha256": sha256(SOURCE),
        "binary_path": str(binary.relative_to(ROOT)) if binary.is_relative_to(ROOT) else str(binary),
        "binary_sha256": sha256(binary),
        "source_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, text=True, stdout=subprocess.PIPE).stdout.strip(),
        "study_script": str(Path(__file__).resolve().relative_to(ROOT)),
        "study_script_sha256": sha256(Path(__file__).resolve()),
        "optical_shader_sha256": sha256(OPTICAL_SHADER),
        "resolution": [640, 360],
        "seed": 42,
        "tick": 300,
        "camera_path": {
            "frames": args.frames,
            "center": list(center),
            "radius_start": radius_start,
            "radius_end": radius_end,
            "sphere_world_radius": 1.05,
            "motion": "one horizontal orbit while camera radius moves linearly from inside to outside the transmissive sphere; camera always targets sphere center",
        },
        "direct_vs_reuse": {
            "frames": rows,
            "changed_pixel_frames": sum(row["changed_pixels"] > 0 for row in rows),
            "mean_changed_pixels": statistics.mean(row["changed_pixels"] for row in rows),
            "max_changed_pixels": max(row["changed_pixels"] for row in rows),
            "mean_rgb_mae_0_255": statistics.mean(sum(row["mean_absolute_rgb_error_0_255"]) / 3 for row in rows),
        },
        "temporal_delta_comparison": {
            "frame_pairs": temporal_rows,
            "pairs_with_changed_pixels": sum(row["changed_pixels"] > 0 for row in temporal_rows),
            "mean_changed_pixels": statistics.mean(row["changed_pixels"] for row in temporal_rows),
            "max_channel_error_0_255": max(max(row["maximum_absolute_rgb_error_0_255"]) for row in temporal_rows),
        },
        "artifacts": {
            "playback": {"path": str(playback_path.relative_to(ROOT)), "sha256": sha256(playback_path)},
            "contact_sheet": {"path": str(contact_path.relative_to(ROOT)), "sha256": sha256(contact_path)},
        },
        "limitations": [
            "Fixed-tick camera-pose sweep compares captures, not native playback performance.",
            "Single scene, material and M1 Max/Metal adapter; Windows/DX12 and other adapters remain unverified.",
            "The comparison checks direct/reuse parity, not owner approval of the art direction.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "frames": args.frames,
                      "changed_pixel_frames": report["direct_vs_reuse"]["changed_pixel_frames"],
                      "temporal_changed_pairs": report["temporal_delta_comparison"]["pairs_with_changed_pixels"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
