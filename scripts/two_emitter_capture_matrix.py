#!/usr/bin/env python3
"""Capture source-isolated and combined views for a bounded two-emitter scene."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--binary", type=Path, default=Path("target/debug/engine-lab"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tick", type=int, default=120)
    parser.add_argument("--cameras", default="hero,smoke-close,orthographic,dual-wide")
    args = parser.parse_args()

    scene_path = args.scene.resolve()
    binary = args.binary.resolve()
    output = args.output.resolve()
    scene = json.loads(scene_path.read_text())
    emitters = scene.get("emitters", [])
    if len(emitters) != 2:
        raise SystemExit(f"expected exactly two emitters in {scene_path}, found {len(emitters)}")
    source_ids = sorted(emitter["id"] for emitter in emitters)
    cameras = [camera.strip() for camera in args.cameras.split(",") if camera.strip()]
    output.mkdir(parents=True, exist_ok=True)

    captures = []
    for source_set in [[source_ids[0]], [source_ids[1]], source_ids]:
        variant = copy.deepcopy(scene)
        removed = [emitter for emitter in emitters if emitter["id"] not in source_set]
        variant["emitters"] = [emitter for emitter in variant["emitters"] if emitter["id"] in source_set]
        removed_light_ids = {emitter.get("light_id") for emitter in removed if emitter.get("light_id")}
        variant["lights"] = [light for light in variant["lights"] if light["id"] not in removed_light_ids]
        label = "+".join(source_set)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix=".two-emitter-review-", dir=scene_path.parent, delete=False
        ) as temporary:
            temp_scene = Path(temporary.name)
            json.dump(variant, temporary, indent=2)
            temporary.write("\n")
        try:
            for camera in cameras:
                image_path = output / f"{label}-{camera}-tick-{args.tick}.png"
                command = [
                    str(binary),
                    "capture",
                    "--scene",
                    str(temp_scene),
                    "--seed",
                    str(args.seed),
                    "--camera",
                    camera,
                    "--tick",
                    str(args.tick),
                    "--resolution",
                    "640x360",
                    "--scale",
                    "1",
                    "--output",
                    str(image_path),
                ]
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
                with Image.open(image_path) as image:
                    rgba = image.convert("RGBA")
                    captures.append(
                        {
                            "sources": source_set,
                            "camera": camera,
                            "tick": args.tick,
                            "seed": args.seed,
                            "resolution": list(rgba.size),
                            "image": image_path.name,
                            "rgba_sha256": hashlib.sha256(rgba.tobytes()).hexdigest(),
                        }
                    )
        finally:
            temp_scene.unlink(missing_ok=True)

    reordered = copy.deepcopy(scene)
    reordered["emitters"].reverse()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix=".two-emitter-reordered-", dir=scene_path.parent, delete=False
    ) as temporary:
        temp_scene = Path(temporary.name)
        json.dump(reordered, temporary, indent=2)
        temporary.write("\n")
    try:
        for camera in cameras:
            image_path = output / f"order-reversed-{camera}-tick-{args.tick}.png"
            command = [
                str(binary),
                "capture",
                "--scene",
                str(temp_scene),
                "--seed",
                str(args.seed),
                "--camera",
                camera,
                "--tick",
                str(args.tick),
                "--resolution",
                "640x360",
                "--scale",
                "1",
                "--output",
                str(image_path),
            ]
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
            with Image.open(image_path) as image:
                rgba = image.convert("RGBA")
                captures.append(
                    {
                        "sources": source_ids,
                        "scene_emitter_order": "reversed",
                        "camera": camera,
                        "tick": args.tick,
                        "seed": args.seed,
                        "resolution": list(rgba.size),
                        "image": image_path.name,
                        "rgba_sha256": hashlib.sha256(rgba.tobytes()).hexdigest(),
                    }
                )
    finally:
        temp_scene.unlink(missing_ok=True)

    combined = {
        capture["camera"]: capture["rgba_sha256"]
        for capture in captures
        if len(capture["sources"]) == 2 and capture.get("scene_emitter_order") != "reversed"
    }
    reversed_order = {
        capture["camera"]: capture["rgba_sha256"]
        for capture in captures
        if capture.get("scene_emitter_order") == "reversed"
    }
    if combined != reversed_order:
        raise SystemExit(f"emitter order changed fixed-tick output: {combined!r} != {reversed_order!r}")

    report = {
        "scene": str(scene_path.relative_to(Path.cwd())) if scene_path.is_relative_to(Path.cwd()) else str(scene_path),
        "scene_sha256": hashlib.sha256(scene_path.read_bytes()).hexdigest(),
        "source_ids": source_ids,
        "fixed_tick": args.tick,
        "seed": args.seed,
        "resolution": [640, 360],
        "captures": captures,
        "emitter_order_invariant": True,
        "limit": "Image comparisons characterize fixed-tick source isolation; they do not establish sustained performance or human motion acceptance.",
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(report_path)


if __name__ == "__main__":
    main()
