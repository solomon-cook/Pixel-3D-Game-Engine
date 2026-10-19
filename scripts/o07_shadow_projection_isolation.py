#!/usr/bin/env python3
"""Isolate sun and fire point-light shadows for a moving O07 caster."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import select
import subprocess

from PIL import Image, ImageChops, ImageDraw

from capture_motion import ROOT


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_diff(first: Path, second: Path) -> dict:
    a = Image.open(first).convert("RGB")
    b = Image.open(second).convert("RGB")
    diff = ImageChops.difference(a, b)
    return {
        "changed_pixels": sum(1 for pixel in diff.getdata() if any(pixel)),
        "changed_bbox": diff.getbbox(),
    }


def serve(binary: Path, scene: Path, output: Path):
    log = (output / f"{scene.stem}.stderr.log").open("w")
    process = subprocess.Popen(
        [str(binary), "serve", "--scene", str(scene), "--seed", "42", "--camera", "hero"],
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

    return process, request, log


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument("--scene", type=Path, default=ROOT / "assets/scenes/clearing.json")
    parser.add_argument("--caster", default="rock-0")
    parser.add_argument("--radius", type=float, default=5.0)
    parser.add_argument("--period", type=float, default=20.0)
    parser.add_argument("--ticks", type=int, nargs="+", default=[0, 300, 600, 900])
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o07/shadow-projection-isolation")
    args = parser.parse_args()
    binary, scene_path, output = args.binary.resolve(), args.scene.resolve(), args.output.resolve()
    source = json.loads(scene_path.read_text())
    camera = next((item for item in source["cameras"] if item["id"] == "hero"), None)
    caster = next((item for item in source["objects"] if item["id"] == args.caster), None)
    emitter = source["emitters"][0] if source.get("emitters") else None
    if not binary.is_file() or camera is None or caster is None or emitter is None:
        parser.error("binary, hero camera, moving caster, and primary emitter must exist")
    lights = {item["id"]: item for item in source["lights"]}
    sun = next((item for item in source["lights"] if item["kind"] == "directional"), None)
    fire = lights.get(emitter.get("light_id"))
    if sun is None or fire is None:
        parser.error("scene must provide the directional sun and linked fire light")
    center = emitter["position"]
    original_position = caster["position"]
    variants = {
        "combined": {sun["id"]: sun["intensity"], fire["id"]: fire["intensity"]},
        "sun-only": {sun["id"]: sun["intensity"], fire["id"]: 0.0},
        "fire-only": {sun["id"]: 0.0, fire["id"]: fire["intensity"]},
    }
    output.mkdir(parents=True, exist_ok=True)
    comparisons = []
    contacts = []
    for name, intensities in variants.items():
        process, request, log = serve(binary, scene_path, output)
        variant_frames = []
        try:
            for light_id, intensity in intensities.items():
                request("set_parameter", path=f"lights.{light_id}.intensity", value=intensity)
            previous_tick = 0
            for tick in args.ticks:
                if tick < previous_tick:
                    raise ValueError("ticks must be increasing")
                request("step", ticks=tick - previous_tick)
                previous_tick = tick
                angle = math.tau * tick / 60.0 / args.period
                position = [center[0] + args.radius * math.cos(angle), original_position[1], center[2] + args.radius * math.sin(angle)]
                request("set_object_transform", id=args.caster, position=position)
                on_path = output / name / f"tick-{tick:04}-with.png"
                on_path.parent.mkdir(parents=True, exist_ok=True)
                request("capture_frame", path=str(on_path), scale=1)
                request("set_object_transform", id=args.caster, position=[1000.0, 1000.0, 1000.0])
                off_path = output / name / f"tick-{tick:04}-without.png"
                request("capture_frame", path=str(off_path), scale=1)
                request("set_object_transform", id=args.caster, position=position)
                diff = image_diff(on_path, off_path)
                comparisons.append({"variant": name, "tick": tick, "caster_position": position, **diff})
                variant_frames.append((tick, on_path, off_path))
        finally:
            try:
                request("shutdown")
            except Exception:
                process.terminate()
            process.wait(timeout=30)
            log.close()
        contacts.append((name, variant_frames))

    tile_w, tile_h = 640, 360
    sheet = Image.new("RGB", (tile_w * 2, tile_h * len(args.ticks) * len(contacts)), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    row = 0
    for name, frames in contacts:
        for tick, on_path, off_path in frames:
            y = row * tile_h
            sheet.paste(Image.open(on_path).convert("RGB"), (0, y))
            sheet.paste(Image.open(off_path).convert("RGB"), (tile_w, y))
            draw.rectangle((0, y, tile_w * 2, y + 22), fill=(0, 0, 0))
            draw.text((4, y + 4), f"{name} · tick {tick} · with caster", fill="white")
            draw.text((tile_w + 4, y + 4), f"{name} · tick {tick} · caster moved away", fill="white")
            row += 1
    contact_path = output / "contact.png"
    sheet.save(contact_path)
    report = {
        "version": 1,
        "date": "2026-10-19",
        "workstream": "O07 moving-caster shadow projection source isolation",
        "source_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "binary_sha256": sha256(binary),
        "scene_sha256": sha256(scene_path),
        "scene": str(scene_path),
        "resolution": source["render"]["resolution"],
        "seed": 42,
        "camera": "hero (fixed)",
        "moving_caster": args.caster,
        "radius": args.radius,
        "period_seconds": args.period,
        "ticks": args.ticks,
        "light_variants": variants,
        "comparison": "same session and tick: caster at orbit pose versus caster moved outside view and all shadow frusta",
        "per_pose": comparisons,
        "summary": {name: {"mean_changed_pixels": sum(item["changed_pixels"] for item in comparisons if item["variant"] == name) / len(args.ticks)} for name in variants},
        "contact_sheet": {"path": str(contact_path), "sha256": sha256(contact_path)},
        "limitations": [
            "The image difference includes the caster itself as well as its shadows; inspect the contact sheet for cast-shadow placement.",
            "Light intensity isolation is offscreen M1 Max/Metal evidence, not native playback or another adapter.",
            "Moving the caster far away removes its visible surface and caster bounds from the sampled shadow maps; it is a diagnostic comparison only.",
        ],
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "contact_sheet": str(contact_path), "poses": len(comparisons)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
