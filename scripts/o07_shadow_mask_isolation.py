#!/usr/bin/env python3
"""Visualize O07 sun and fire-light shadow visibility for a moving caster."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import select
import shutil
import subprocess

from PIL import Image, ImageDraw

from capture_motion import ROOT


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def masked_shadow_deltas(with_path: Path, without_path: Path, threshold: int = 3) -> dict:
    with_image = Image.open(with_path).convert("RGB")
    without_image = Image.open(without_path).convert("RGB")
    results = {}
    for channel, name in ((0, "sun"), (1, "fire_point_light")):
        points = []
        drops = []
        for y in range(with_image.height):
            for x in range(with_image.width):
                current = with_image.getpixel((x, y))
                reference = without_image.getpixel((x, y))
                # The temporary shader marks stone-material pixels blue. Exclude all stone
                # surfaces so the moving rock itself cannot be counted as its ground shadow.
                if current[2] > 127 or reference[2] > 127:
                    continue
                drop = reference[channel] - current[channel]
                if drop > threshold:
                    points.append((x, y))
                    drops.append(drop)
        if not points:
            results[name] = {"changed_ground_pixels": 0, "threshold_0_255": threshold}
            continue
        results[name] = {
            "changed_ground_pixels": len(points),
            "bbox_xyxy": [min(x for x, _ in points), min(y for _, y in points),
                          max(x for x, _ in points) + 1, max(y for _, y in points) + 1],
            "centroid_xy": [sum(x for x, _ in points) / len(points),
                            sum(y for _, y in points) / len(points)],
            "mean_visibility_drop_0_255": sum(drops) / len(drops),
            "threshold_0_255": threshold,
        }
    return results


def moving_stone_mask(with_path: Path, without_path: Path, threshold: int = 127) -> dict:
    """Locate the moving caster by subtracting the stone-material debug mask."""
    with_image = Image.open(with_path).convert("RGB")
    without_image = Image.open(without_path).convert("RGB")
    points = []
    for y in range(with_image.height):
        for x in range(with_image.width):
            if with_image.getpixel((x, y))[2] - without_image.getpixel((x, y))[2] > threshold:
                points.append((x, y))
    if not points:
        return {"visible_pixels": 0, "threshold_0_255": threshold}
    return {
        "visible_pixels": len(points),
        "bbox_xyxy": [min(x for x, _ in points), min(y for _, y in points),
                      max(x for x, _ in points) + 1, max(y for _, y in points) + 1],
        "centroid_xy": [sum(x for x, _ in points) / len(points),
                        sum(y for _, y in points) / len(points)],
        "threshold_0_255": threshold,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--scene", type=Path, default=ROOT / "assets/scenes/clearing.json")
    parser.add_argument("--caster", default="rock-0")
    parser.add_argument("--radius", type=float, default=5.0)
    parser.add_argument("--period", type=float, default=20.0)
    parser.add_argument("--ticks", type=int, nargs="+", default=[0, 300, 600, 900])
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o07/shadow-mask-isolation")
    args = parser.parse_args()
    binary, scene_path, output = args.binary.resolve(), args.scene.resolve(), args.output.resolve()
    if not binary.is_file() or not scene_path.is_file():
        parser.error("binary and scene must exist")
    scene = json.loads(scene_path.read_text())
    caster = next((item for item in scene["objects"] if item["id"] == args.caster), None)
    emitter = scene["emitters"][0] if scene.get("emitters") else None
    stone_index = next((i for i, item in enumerate(scene["materials"]) if item["id"] == "stone"), None)
    if caster is None or emitter is None or stone_index is None:
        parser.error("moving caster, primary emitter and stone material must exist")
    output.mkdir(parents=True, exist_ok=True)
    shader_dir = output / "debug-shaders"
    if shader_dir.exists():
        shutil.rmtree(shader_dir)
    shutil.copytree(ROOT / "crates/engine/src/render/shaders", shader_dir)
    world_path = shader_dir / "world.wgsl"
    world = world_path.read_text()
    normal_output = "    if transmission(materials[v.material])>0. {discard;}\n    return result;\n}"
    debug_output = (
        "    if transmission(materials[v.material])>0. {discard;}\n"
        "    let shadow_normal=normalize(v.normal);\n"
        f"    result.color=vec4(sun_visibility(v.position,shadow_normal),"
        f"fire_visibility(v.position+shadow_normal*0.025,0u),"
        f"select(0.0,1.0,v.material=={stone_index}u),1.0);\n"
        "    return result;\n}"
    )
    if world.count(normal_output) != 1:
        raise RuntimeError("expected one final world-fragment output site")
    world_path.write_text(world.replace(normal_output, debug_output))
    source = scene
    center = emitter["position"]
    original_y = caster["position"][1]
    log = (output / "engine.stderr.log").open("w")
    process = subprocess.Popen(
        [str(binary), "serve", "--scene", str(scene_path), "--seed", "42", "--camera", "hero", "--shaders", str(shader_dir)],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True,
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

    poses = []
    previous_tick = 0
    try:
        request("set_geometry_rendering", culling=True, instancing=True)
        for tick in args.ticks:
            if tick < previous_tick:
                raise ValueError("ticks must be increasing")
            request("step", ticks=tick - previous_tick)
            previous_tick = tick
            angle = math.tau * tick / 60.0 / args.period
            position = [center[0] + args.radius * math.cos(angle), original_y,
                        center[2] + args.radius * math.sin(angle)]
            request("set_object_transform", id=args.caster, position=position)
            with_path = output / f"tick-{tick:04}-with.png"
            request("capture_frame", path=str(with_path), scale=1)
            request("set_object_transform", id=args.caster, position=[1000.0, 1000.0, 1000.0])
            without_path = output / f"tick-{tick:04}-without.png"
            request("capture_frame", path=str(without_path), scale=1)
            request("set_object_transform", id=args.caster, position=position)
            caster_mask = moving_stone_mask(with_path, without_path)
            shadow_deltas = masked_shadow_deltas(with_path, without_path)
            caster_centroid = caster_mask.get("centroid_xy")
            fire_centroid = shadow_deltas["fire_point_light"].get("centroid_xy")
            if caster_centroid and fire_centroid:
                shadow_deltas["fire_point_light"]["offset_from_caster_centroid_xy"] = [
                    fire_centroid[0] - caster_centroid[0],
                    fire_centroid[1] - caster_centroid[1],
                ]
            poses.append({
                "tick": tick,
                "caster_position": position,
                "with_caster": str(with_path),
                "caster_moved_away": str(without_path),
                "moving_caster_screen_mask": caster_mask,
                "shadow_visibility_deltas": shadow_deltas,
            })
    finally:
        try:
            request("shutdown")
        except Exception:
            process.terminate()
        process.wait(timeout=30)
        log.close()

    width, height = scene["render"]["resolution"]
    contact = Image.new("RGB", (width * 2, (height + 20) * len(poses)), (0, 0, 0))
    draw = ImageDraw.Draw(contact)
    for row, pose in enumerate(poses):
        y = row * (height + 20)
        contact.paste(Image.open(pose["with_caster"]).convert("RGB"), (0, y + 20))
        contact.paste(Image.open(pose["caster_moved_away"]).convert("RGB"), (width, y + 20))
        draw.text((4, y + 4), f"tick {pose['tick']}: red=sun visibility, green=fire visibility, blue=stone mask; with caster", fill="white")
        draw.text((width + 4, y + 4), f"tick {pose['tick']}: caster moved away", fill="white")
    contact_path = output / "contact.png"
    contact.save(contact_path)
    report = {
        "version": 1,
        "date": "2026-10-19",
        "workstream": "O07 source-separated moving-caster shadow projection probe",
        "source_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "binary_sha256": sha256(binary),
        "scene_sha256": sha256(scene_path),
        "debug_world_shader_sha256": sha256(world_path),
        "scene": str(scene_path),
        "host": {"device": "Apple M1 Max", "backend": "Metal", "native_window": False},
        "resolution": scene["render"]["resolution"],
        "seed": 42,
        "camera": "hero (fixed)",
        "moving_caster": args.caster,
        "radius": args.radius,
        "period_seconds": args.period,
        "ticks": args.ticks,
        "visualization": {"red": "sun shadow visibility", "green": "primary fire point-light shadow visibility", "blue": "stone material surface mask"},
        "method": "The moving rock screen mask is isolated by subtracting the no-caster stone mask. The point-light ground-shadow centroid offset is reported where both regions are visible.",
        "per_pose": poses,
        "contact_sheet": {"path": str(contact_path), "sha256": sha256(contact_path)},
        "limitations": [
            "The debug shader replaces final opaque world color with shadow visibility; it does not represent normal scene color or owner visual acceptance.",
            "Visibility changes are counted only on non-stone pixels, with a 3/255 threshold; this excludes the caster surface but also all other stone surfaces.",
            "The moving-caster screen mask is a difference of material-ID masks, so edge pixels can vary with raster coverage; its centroid is a screen-space locator, not a world-space contact or shadow measurement.",
            "The fixed hero camera shows only the portion of each shadow inside its view; zero sampled ground pixels does not mean the light failed to cast a shadow outside frame.",
            "This is offscreen M1 Max/Metal evidence, not native playback or another adapter.",
        ],
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "contact_sheet": str(contact_path), "poses": len(poses)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
