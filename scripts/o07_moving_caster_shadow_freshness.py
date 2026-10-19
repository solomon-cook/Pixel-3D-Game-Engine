#!/usr/bin/env python3
"""Compare cached moving-caster shadows with a forced redraw at matched poses."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import select
import subprocess

from PIL import Image, ImageChops

from capture_motion import route_camera_at

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_error(first: Path, second: Path) -> dict:
    a = Image.open(first).convert("RGB")
    b = Image.open(second).convert("RGB")
    diff = ImageChops.difference(a, b)
    histogram = diff.histogram()
    pixels = a.width * a.height
    channel_means = [
        sum(value * count for value, count in enumerate(histogram[start : start + 256])) / pixels
        for start in (0, 256, 512)
    ]
    return {
        "changed_pixels": sum(1 for pixel in diff.getdata() if any(pixel)),
        "pixel_count": pixels,
        "mean_absolute_rgb_error_0_255": channel_means,
        "maximum_absolute_rgb_error_0_255": [
            max(value for value, count in enumerate(histogram[start : start + 256]) if count)
            for start in (0, 256, 512)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--scene", type=Path, default=ROOT / "assets/scenes/clearing.json")
    parser.add_argument("--camera", default="hero")
    parser.add_argument("--route", default="clearing-orbit")
    parser.add_argument("--route-start", type=float, default=30.0)
    parser.add_argument("--moving-caster", default="rock-0")
    parser.add_argument("--caster-orbit-radius", type=float, default=5.0)
    parser.add_argument("--caster-orbit-period", type=float, default=20.0)
    parser.add_argument("--start-tick", type=int, default=300)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--frames", type=int, default=400)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/o07/shadow-freshness-current-release",
    )
    args = parser.parse_args()
    if not 1 <= args.frames <= 600 or not 1 <= args.stride <= 60:
        parser.error("--frames must be 1..600 and --stride must be 1..60")

    binary = args.binary.resolve()
    scene_path = args.scene.resolve()
    if not binary.is_file() or not scene_path.is_file():
        parser.error("binary and scene must exist")
    scene = json.loads(scene_path.read_text())
    route = next((item for item in scene.get("routes", []) if item.get("id") == args.route), None)
    if route is None:
        parser.error(f"route '{args.route}' not found")
    base_camera = next((item for item in scene.get("cameras", []) if item.get("id") == args.camera), None)
    caster = next((item for item in scene.get("objects", []) if item.get("id") == args.moving_caster), None)
    emitter = scene.get("emitters", [{}])[0] if scene.get("emitters") else None
    if base_camera is None or caster is None or emitter is None:
        parser.error("camera, moving caster, and primary emitter must exist")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [str(binary), "serve", "--scene", str(scene_path), "--seed", "42", "--camera", args.camera],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=(output / "engine.stderr.log").open("w"),
        text=True,
    )
    counter = 0

    def request(method: str, **params):
        nonlocal counter
        counter += 1
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({"id": counter, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], 90)
        if not ready:
            raise TimeoutError(f"timed out waiting for {method}")
        response = json.loads(process.stdout.readline())
        if response.get("id") != counter or "error" in response:
            raise RuntimeError(response)
        return response["result"]

    comparisons = []
    cache_events = []
    effect_counts_match = True
    try:
        request("set_geometry_rendering", culling=True, instancing=True)
        request("step", ticks=args.start_tick)
        for index in range(args.frames):
            if index:
                request("step", ticks=args.stride)
            tick = args.start_tick + index * args.stride
            angle = math.tau * tick / 60.0 / args.caster_orbit_period
            center = emitter["position"]
            position = [
                center[0] + args.caster_orbit_radius * math.cos(angle),
                caster["position"][1],
                center[2] + args.caster_orbit_radius * math.sin(angle),
            ]
            request("set_object_transform", id=args.moving_caster, position=position)
            camera = route_camera_at(route, base_camera, args.route_start + index * args.stride / 60.0)
            request("set_camera", camera=camera)

            cached_path = output / "cached" / f"{index:04}.png"
            cached_path.parent.mkdir(parents=True, exist_ok=True)
            request("set_shadow_cache", force_redraw=False)
            request("capture_frame", path=str(cached_path), scale=1)

            forced_path = output / "forced" / f"{index:04}.png"
            forced_path.parent.mkdir(parents=True, exist_ok=True)
            request("set_shadow_cache", force_redraw=True)
            request("capture_frame", path=str(forced_path), scale=1)
            request("set_shadow_cache", force_redraw=False)

            cached_meta = json.loads(cached_path.with_suffix(".json").read_text())
            forced_meta = json.loads(forced_path.with_suffix(".json").read_text())
            metrics = cached_meta["metrics"]
            forced_metrics = forced_meta["metrics"]
            effect_counts = ("embers", "fire_primitives", "flame_fragments", "particle_lights")
            frame_counts_match = all(metrics[key] == forced_metrics[key] for key in effect_counts)
            effect_counts_match &= frame_counts_match
            cache_events.append(
                {
                    "frame": index,
                    "tick": tick,
                    "caster_position": position,
                    "shadow_dirty_reason": metrics["shadow_dirty_reason"],
                    "shadow_maps_redrawn": metrics["shadow_maps_redrawn"],
                    "shadow_dirty_faces": metrics["shadow_dirty_faces"],
                    "forced_shadow_maps_redrawn": forced_meta["metrics"]["shadow_maps_redrawn"],
                }
            )
            comparisons.append(
                {
                    "frame": index,
                    "tick": tick,
                    "effect_counts_match": frame_counts_match,
                    **image_error(cached_path, forced_path),
                    "cached_sha256": sha256(cached_path),
                    "forced_sha256": sha256(forced_path),
                }
            )
    finally:
        try:
            request("shutdown")
        except Exception:
            process.terminate()
        process.wait(timeout=30)

    report = {
        "version": 1,
        "date": "2026-10-19",
        "workstream": "O07 current-release moving-caster shadow freshness against forced redraw",
        "source_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip(),
        "binary": str(binary),
        "binary_sha256": sha256(binary),
        "scene": str(scene_path),
        "scene_sha256": sha256(scene_path),
        "resolution": scene["render"]["resolution"],
        "seed": 42,
        "camera": args.camera,
        "route": args.route,
        "route_start_seconds": args.route_start,
        "moving_caster": args.moving_caster,
        "caster_orbit_radius": args.caster_orbit_radius,
        "caster_orbit_period_seconds": args.caster_orbit_period,
        "start_tick": args.start_tick,
        "stride_ticks": args.stride,
        "frames": args.frames,
        "comparison": "same Session pose: cached shadow maps versus force_redraw=true; compare final RGBA capture",
        "effect_counts_match_every_frame": effect_counts_match,
        "summary": {
            "exact_image_pairs": sum(item["changed_pixels"] == 0 for item in comparisons),
            "frames_with_image_difference": sum(item["changed_pixels"] != 0 for item in comparisons),
            "max_changed_pixels": max(item["changed_pixels"] for item in comparisons),
            "max_channel_difference": max(max(item["maximum_absolute_rgb_error_0_255"]) for item in comparisons),
            "cache_redrew_at_every_pose": all(event["shadow_maps_redrawn"] > 0 for event in cache_events),
        },
        "per_frame": comparisons,
        "shadow_cache_events": cache_events,
        "limitations": [
            "Headless real Metal renderer; this verifies current shadow-cache output against full redraw, not human visual quality or native presentation.",
            "One scene, moving caster, camera route, adapter, and fixed 640x360 grid.",
        ],
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), **report["summary"]}))
    return 0 if report["summary"]["frames_with_image_difference"] == 0 and effect_counts_match else 2


if __name__ == "__main__":
    raise SystemExit(main())
