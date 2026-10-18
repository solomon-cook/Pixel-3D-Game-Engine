#!/usr/bin/env python3
"""Compare O01 counter captures across named optical-material cameras."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
CAMERAS = ("hero", "metal-close", "glass-close", "subsurface-close", "orthographic")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixel_hash(path: Path) -> str:
    with Image.open(path) as image:
        return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def compare(reference: Path, candidate: Path) -> dict:
    with Image.open(reference) as image:
        baseline = image.convert("RGB")
    with Image.open(candidate) as image:
        diagnostic = image.convert("RGB")
    diff = ImageChops.difference(baseline, diagnostic)
    extrema = diff.getextrema()
    return {
        "changed_pixels": sum(any(pixel) for pixel in diff.getdata()),
        "total_pixels": baseline.width * baseline.height,
        "mean_absolute_channel_error": sum(ImageStat.Stat(diff).mean) / 3,
        "max_channel_error": max(high for _, high in extrema),
        "difference_bounds": list(diff.getbbox()) if diff.getbbox() else None,
    }


def capture(
    binary: Path,
    scene: Path,
    camera: str,
    seed: int,
    tick: int,
    output: Path,
    counters: bool,
    options: tuple[str, ...] = (),
) -> dict:
    command = [
        str(binary), "capture", "--scene", str(scene), "--camera", camera,
        "--seed", str(seed), "--tick", str(tick), "--resolution", "640x360",
        "--scale", "1", "--output", str(output),
    ]
    command.extend(options)
    if counters:
        command.append("--shading-counters")
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return json.loads(output.with_suffix(".json").read_text())


def study_case(
    binary: Path,
    scene: Path,
    camera: str,
    name: str,
    seed: int,
    tick: int,
    output: Path,
    options: tuple[str, ...] = (),
) -> dict:
    variants = {}
    for label, counters in (("normal", False), ("diagnostic", True)):
        image = output / f"{name}-{label}.png"
        metadata = capture(binary, scene, camera, seed, tick, image, counters, options)
        variants[label] = {
            "image": str(image.relative_to(ROOT)),
            "pixel_sha256": pixel_hash(image),
            "backend": metadata["capabilities"]["backend"],
            "adapter": metadata["capabilities"]["name"],
            "resolution": metadata["capabilities"]["resolution"],
        }
        if counters:
            variants["counters"] = metadata["metrics"].get("shading_counters")
            variants["scratch_bytes"] = metadata["capabilities"]["resource_inventory"]["shading_diagnostic_targets_bytes"]
            if not variants["counters"]:
                raise RuntimeError(f"missing shading counters in {name}")
    return {
        "camera": camera,
        "variant": name,
        "options": list(options),
        "normal": variants["normal"],
        "diagnostic": variants["diagnostic"],
        "pixel_identical": variants["normal"]["pixel_sha256"] == variants["diagnostic"]["pixel_sha256"],
        "pixel_difference": compare(
            ROOT / variants["normal"]["image"], ROOT / variants["diagnostic"]["image"]
        ),
        "counters": variants["counters"],
        "diagnostic_scratch_bytes": variants["scratch_bytes"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--scene", type=Path, default=ROOT / "assets/scenes/materials.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o01/optical-counter-coverage")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o01-optical-counter-coverage.json")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tick", type=int, default=300)
    args = parser.parse_args()
    binary, scene, output = args.binary.resolve(), args.scene.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    for camera in CAMERAS:
        cases.append(study_case(binary, scene, camera, camera, args.seed, args.tick, output))
    cases.append(study_case(
        binary, scene, "glass-close", "glass-close-compact-hdr-no-copy", args.seed, args.tick,
        output, ("--compact-hdr", "--optical-no-copy"),
    ))
    if not any(case["counters"]["optical_surface_interactions"] for case in cases):
        raise RuntimeError("optical camera set did not exercise instrumented surfaces")
    report = {
        "version": 1,
        "purpose": "Fixed-tick output parity and operation counts across named optical material views; atomic diagnostic draws are not timing evidence.",
        "scene": str(scene.relative_to(ROOT)),
        "scene_sha256": sha256(scene),
        "seed": args.seed,
        "tick": args.tick,
        "resolution": [640, 360],
        "cameras": list(CAMERAS),
        "binary_sha256": sha256(binary),
        "runner_sha256": sha256(Path(__file__).resolve()),
        "renderer_source_sha256": sha256(ROOT / "crates/engine/src/render/mod.rs"),
        "cases": cases,
        "all_pixel_identical": all(case["pixel_identical"] for case in cases),
        "limitations": [
            "Fixed-tick M1 Max/Metal captures do not establish continuous visual quality.",
            "Diagnostic mode allocates scratch render targets and adds rendering work; its timings are not comparable.",
            "Native-window and non-Metal optical-counter coverage remain open.",
        ],
    }
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "cases": len(cases), "all_pixel_identical": report["all_pixel_identical"]}))


if __name__ == "__main__":
    main()
