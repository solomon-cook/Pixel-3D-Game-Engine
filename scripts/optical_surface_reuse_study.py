#!/usr/bin/env python3
"""Sustained O06 direct-versus-reuse study in material and mixed scenes."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess

from absorption_cache_study import image_error, sha256

ROOT = Path(__file__).resolve().parents[1]
MATERIALS = ROOT / "assets/scenes/materials.json"
CLEARING = ROOT / "assets/scenes/clearing.json"
MIXED_ROUTE = "mixed-smoke-material-orbit"


def mixed_scene() -> dict:
    scene = json.loads(CLEARING.read_text())
    material_scene = json.loads(MATERIALS.read_text())
    scene["materials"].extend(copy.deepcopy(material_scene["materials"]))
    scene["objects"].extend([
        {"id": "mixed-glass-foreground", "material": "glass", "geometry": {"kind": "smooth_sphere"}, "position": [0.0, 1.25, 2.2], "scale": [1.45, 1.45, 1.45]},
        {"id": "mixed-chrome-background", "material": "chrome", "geometry": {"kind": "smooth_sphere"}, "position": [0.0, 1.25, -2.2], "scale": [1.65, 1.65, 1.65]},
    ])
    scene["render"]["resolution"] = [640, 360]
    scene["cameras"].extend([
        {"id": "mixed-close", "position": [0.0, 3.2, 7.0], "target": [0.0, 1.5, 0.0], "projection": {"kind": "perspective", "fov_degrees": 48.0}},
        {"id": "mixed-from-behind", "position": [0.0, 2.8, -7.5], "target": [0.0, 1.5, 0.0], "projection": {"kind": "perspective", "fov_degrees": 48.0}},
        {"id": "glass-near", "position": [0.5, 1.35, 3.35], "target": [0.2, 1.2, 0.0], "projection": {"kind": "perspective", "fov_degrees": 55.0}},
    ])
    target = [0.0, 1.5, 0.0]
    offsets = ([0.0, 1.7, 7.0], [7.0, 1.2, 0.0], [0.0, 1.7, -7.0], [-7.0, 1.2, 0.0], [0.0, 1.7, 7.0])
    scene["routes"].append({
        "id": MIXED_ROUTE,
        "duration_seconds": 20.0,
        "keyframes": [
            {"time": index * 5.0, "position": [target[i] + offset[i] for i in range(3)], "target": target}
            for index, offset in enumerate(offsets)
        ],
    })
    return scene


def make_variants(output: Path) -> dict[str, dict[str, Path]]:
    bases = {"material_atelier": json.loads(MATERIALS.read_text()), "mixed_smoke_material": mixed_scene()}
    variants: dict[str, dict[str, Path]] = {}
    for workload, source in bases.items():
        variants[workload] = {}
        for mode, enabled in (("direct", False), ("reuse", True)):
            scene = copy.deepcopy(source)
            scene["render"]["resolution"] = [640, 360]
            scene["render"].setdefault("experiments", {})["optical_surface_reuse"] = enabled
            path = output / "scenes" / workload / f"{mode}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(scene, indent=2) + "\n")
            variants[workload][mode] = path
    return variants


def capture_scene(binary: Path, scene_path: Path, camera_ids: list[str], output: Path) -> dict:
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
        for camera in camera_ids:
            request("set_camera", id=camera)
            path = output / f"{camera}-tick-300.png"
            captures[camera] = {"tick": 300, "sha256": None, "image": None}
            response = request("capture_frame", path=str(path.resolve()), scale=1)
            captures[camera]["image"] = response["image"]
            captures[camera]["sha256"] = sha256(Path(response["image"]))
        if scene_path.parent.name == "mixed_smoke_material":
            request("set_parameter", path="materials.chrome.roughness", value=0.42)
            request("set_camera", id="mixed-close")
            path = output / "mixed-close-after-chrome-edit.png"
            response = request("capture_frame", path=str(path.resolve()), scale=1)
            captures["mixed-close-after-chrome-edit"] = {"tick": 300, "sha256": sha256(Path(response["image"])), "image": response["image"], "edit": {"path": "materials.chrome.roughness", "value": 0.42}}
    finally:
        if process.stdin:
            process.stdin.close()
        process.wait(timeout=60)
    if process.returncode:
        raise RuntimeError(f"serve exited {process.returncode}")
    return captures


def benchmark(binary: Path, baseline: Path, candidate: Path, route: str, camera: str, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "python3", str(ROOT / "scripts/profile_compare.py"),
        "--baseline", str(baseline), "--candidate", str(candidate),
        "--route", route, "--camera", camera, "--mode", "serial",
        "--duration", "120", "--warmup", "10", "--pairs", "3",
        "--seed", "42", "--resolution", "640x360", "--output", str(output),
        "--binary", str(binary),
    ], cwd=ROOT, check=True)
    path = output / "comparison.json"
    return {"file": str(path.relative_to(output.parent.parent)), "sha256": sha256(path), "comparison": json.loads(path.read_text())["comparison"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release" / ("engine-lab.exe" if os.name == "nt" else "engine-lab"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o06/sustained-study")
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    variants = make_variants(output)
    report = {
        "workstream": "O06 opaque surface lighting reuse sustained study",
        "date": "2026-10-18",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal", "os": "macOS"},
        "seed": 42,
        "resolution": [640, 360],
        "method": "Direct and reused opaque surface lighting preserve the same scene, simulation, pixel grid and named camera. Captures are at tick 300; benchmarks use three alternating 120-second pairs and 10-second warm-up.",
        "workloads": {},
        "limitations": ["Headless serve/benchmark; native-window behavior is unverified.", "No Windows DX12 or other GPU result is included.", "A fixed tick and discrete camera views do not establish continuous reflection/transmission quality."],
    }
    camera_sets = {"material_atelier": ["hero", "metal-close", "glass-close"], "mixed_smoke_material": ["mixed-close", "mixed-from-behind", "glass-near"]}
    for workload, modes in variants.items():
        baseline = capture_scene(binary, modes["direct"], camera_sets[workload], output / "captures" / workload / "direct")
        candidate = capture_scene(binary, modes["reuse"], camera_sets[workload], output / "captures" / workload / "reuse")
        captures = {}
        for camera in baseline:
            if camera in candidate:
                captures[camera] = {
                    "direct_sha256": baseline[camera]["sha256"],
                    "reuse_sha256": candidate[camera]["sha256"],
                    "absolute_rgb_error": image_error(Path(baseline[camera]["image"]), Path(candidate[camera]["image"])),
                    "live_material_edit": candidate[camera].get("edit"),
                }
        report["workloads"][workload] = {
            "baseline_scene_sha256": sha256(modes["direct"]),
            "candidate_scene_sha256": sha256(modes["reuse"]),
            "captures": captures,
        }
        if args.benchmark:
            route = "material-orbit" if workload == "material_atelier" else MIXED_ROUTE
            camera = "hero" if workload == "material_atelier" else "mixed-close"
            report["workloads"][workload]["benchmark"] = benchmark(
                binary, modes["direct"], modes["reuse"], route, camera,
                output / "benchmarks" / workload,
            )
    report_path = output / "study.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"study": str(report_path), "workloads": list(variants), "benchmark": args.benchmark}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
