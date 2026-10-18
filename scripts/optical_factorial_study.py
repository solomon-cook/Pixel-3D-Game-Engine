#!/usr/bin/env python3
"""Factorial O06 opaque lighting reuse and O08 optical no-copy/HDR study."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess

from absorption_cache_study import image_error, sha256
from optical_surface_reuse_study import mixed_scene

ROOT = Path(__file__).resolve().parents[1]
ROUTE = "mixed-smoke-material-orbit"
CAMERAS = ["mixed-close", "mixed-from-behind", "glass-near"]
BASELINE = "direct_copy_rgba16"


def variants() -> dict[str, dict]:
    source = mixed_scene()
    # Push fire output above the tone-map knee to expose packed-HDR error in the
    # same smoke/reflector/transmissive scene used for the factorial timing.
    for light in source["lights"]:
        if light["id"] == "fire-light":
            light["intensity"] = 18.0
    for profile in source["effects"]:
        if profile["id"] == "effect-campfire":
            profile["fire"]["emission"] = 2.4
            profile["palette"]["hot"] = [9.0, 5.0, 1.2]
            profile["palette"]["warm"] = [5.0, 1.25, 0.08]
    choices = {}
    for compact_hdr in (False, True):
        for optical_no_copy in (False, True):
            for optical_surface_reuse in (False, True):
                name = f"{'reuse' if optical_surface_reuse else 'direct'}_{'no_copy' if optical_no_copy else 'copy'}_{'rg11b10' if compact_hdr else 'rgba16'}"
                scene = copy.deepcopy(source)
                scene["render"]["resolution"] = [640, 360]
                scene["render"]["compact_hdr"] = compact_hdr
                scene["render"]["optical_no_copy"] = optical_no_copy
                scene["render"].setdefault("experiments", {})["optical_surface_reuse"] = optical_surface_reuse
                choices[name] = scene
    return choices


def serve_capture(binary: Path, scene_path: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen([str(binary), "serve", "--scene", str(scene_path)], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    request_id = 0

    def request(method: str, **params):
        nonlocal request_id
        request_id += 1
        assert process.stdin and process.stdout
        process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        if response.get("id") != request_id or "error" in response:
            raise RuntimeError(response)
        return response["result"]

    captures = {}
    try:
        request("step", ticks=300)
        for camera in CAMERAS:
            request("set_camera", id=camera)
            image = request("capture_frame", path=str((output / f"{camera}.png").resolve()), scale=1)["image"]
            captures[camera] = {"image": image, "sha256": sha256(Path(image))}
        capabilities = request("get_metrics")["capabilities"]
    finally:
        if process.stdin:
            process.stdin.close()
        process.wait(timeout=60)
    if process.returncode:
        raise RuntimeError(f"serve exited {process.returncode}")
    inventory = capabilities["resource_inventory"]
    return {
        "captures": captures,
        "capabilities": {"backend": capabilities.get("backend"), "device": capabilities.get("name"), "compact_hdr_renderable": inventory.get("rg11b10_renderable_feature_available")},
        "resources": {key: inventory.get(key) for key in ("known_gpu_allocation_bytes", "optical_snapshot_bytes", "optical_output_bytes", "optical_mask_bytes", "render_targets_bytes", "hdr_color_format")},
    }


def run_benchmark(binary: Path, base: Path, candidate: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "python3", str(ROOT / "scripts/profile_compare.py"),
        "--baseline", str(base), "--candidate", str(candidate),
        "--route", ROUTE, "--camera", "mixed-close", "--mode", "serial",
        "--duration", "120", "--warmup", "10", "--pairs", "3", "--seed", "42",
        "--resolution", "640x360", "--output", str(output), "--binary", str(binary),
    ], cwd=ROOT, check=True)
    return read_benchmark(output)


def read_benchmark(output: Path) -> dict:
    comparison = output / "comparison.json"
    return {"comparison_file": str(comparison.relative_to(output.parent.parent)), "sha256": sha256(comparison), "paired_deltas": json.loads(comparison.read_text())["comparison"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release" / ("engine-lab.exe" if os.name == "nt" else "engine-lab"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o06-o08/factorial")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--summarize-existing", action="store_true", help="reuse the saved paired comparisons while refreshing captures")
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    scenes = {}
    for name, scene in variants().items():
        path = output / "scenes" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(scene, indent=2) + "\n")
        scenes[name] = path

    report = {
        "workstream": "O06 x O08 optical reuse/no-copy/compact-HDR factorial",
        "date": "2026-10-18",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal", "os": "macOS"},
        "scene": "mixed high-dynamic fire/smoke/opaque reflector/transmissive glass",
        "seed": 42,
        "tick": 300,
        "resolution": [640, 360],
        "route": ROUTE,
        "factors": {"lighting": ["direct", "reuse"], "optical_io": ["copy", "no_copy"], "hdr": ["rgba16", "rg11b10"]},
        "high_dynamic_overrides": {"lights.fire-light.intensity": 18.0, "effects.effect-campfire.fire.emission": 2.4, "effects.effect-campfire.palette.hot": [9.0, 5.0, 1.2], "effects.effect-campfire.palette.warm": [5.0, 1.25, 0.08]},
        "method": "The full 2x2x2 matrix changes only render.experiments.optical_surface_reuse, render.optical_no_copy and render.compact_hdr. The eight variants share scene, route, fire HDR values, seed and pixel grid.",
        "variants": {},
        "timing": {"enabled": args.benchmark or args.summarize_existing, "duration_seconds_per_run": 120, "warmup_seconds": 10, "pairs": 3, "baseline": BASELINE, "comparisons": {}},
        "limitations": ["Metal offscreen only; native window, DX12 and other adapters remain unverified.", "The smoke/material HDR stress route does not establish camera-inside-glass behavior.", "Fixed-tick captures and aggregate route timing do not replace continuous motion review."],
    }
    for name, path in scenes.items():
        captured = serve_capture(binary, path, output / "captures" / name)
        report["variants"][name] = {"scene_sha256": sha256(path), **captured}
    direct_capture = report["variants"][BASELINE]["captures"]
    for name, item in report["variants"].items():
        item["image_error_vs_direct_copy_rgba16"] = {
            camera: image_error(Path(direct_capture[camera]["image"]), Path(item["captures"][camera]["image"]))
            for camera in CAMERAS
        }
    if args.benchmark or args.summarize_existing:
        for name, path in scenes.items():
            if name == BASELINE:
                continue
            comparison_dir = output / "benchmarks" / name
            if args.benchmark:
                report["timing"]["comparisons"][name] = run_benchmark(binary, scenes[BASELINE], path, comparison_dir)
            else:
                report["timing"]["comparisons"][name] = read_benchmark(comparison_dir)
    report_path = output / "study.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"study": str(report_path), "variant_count": len(scenes), "benchmark": args.benchmark, "summarized_existing": args.summarize_existing}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
