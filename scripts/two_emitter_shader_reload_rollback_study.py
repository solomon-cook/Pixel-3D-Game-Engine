#!/usr/bin/env python3
"""Verify failed shader reload rollback across runtime WGSL modules."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets/scenes/two-emitter-review.json"
SHADERS = ROOT / "crates/engine/src/render/shaders"
# Every shader-directory source read by Renderer::pipelines. `present.wgsl` is
# compiled into the native host with include_str! and is not part of hot reload.
INVALID_SHADERS = (
    "common.wgsl",
    "tile_common.wgsl",
    "tile_bindings.wgsl",
    "tile_build.wgsl",
    "materials.wgsl",
    "world.wgsl",
    "optical.wgsl",
    "volume.wgsl",
    "fire.wgsl",
    "post.wgsl",
    "smoke.wgsl",
    "absorption.wgsl",
    "shadow.wgsl",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--scene", type=Path, default=SCENE)
    parser.add_argument("--camera", default="dual-wide")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tick", type=int, default=120)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/multi-emitter/shader-rollback")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-multi-emitter-shader-rollback.json")
    parser.add_argument("--native", action="store_true", help="run the same fixed-tick sequence through the native window Session")
    args = parser.parse_args()
    binary, scene = args.binary.resolve(), args.scene.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "-p", "engine-lab"], cwd=ROOT, check=True)
    output, report_path = args.output.resolve(), args.report.resolve()
    output.mkdir(parents=True, exist_ok=True)
    isolated_shaders = Path(tempfile.mkdtemp(prefix="pixel-engine-shader-rollback-"))
    shutil.rmtree(isolated_shaders)
    shutil.copytree(SHADERS, isolated_shaders)
    command = ([str(binary), "run", "--agent-stdio", "--paused"] if args.native
               else [str(binary), "serve"])
    command += ["--scene", str(scene), "--camera", args.camera,
                "--seed", str(args.seed), "--shaders", str(isolated_shaders)]
    process = subprocess.Popen(
        command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    request_id = 0

    def request(method: str, **params):
        nonlocal request_id
        request_id += 1
        if process.poll() is not None or process.stdin is None or process.stdout is None:
            raise RuntimeError(f"headless renderer exited before {method}")
        process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(f"headless renderer closed stdout during {method}")
        response = json.loads(line)
        if response.get("id") != request_id:
            raise RuntimeError(f"unexpected response for {method}: {response}")
        return response

    def capture(label: str) -> dict:
        path = (output / f"{label}.png").resolve()
        response = request("capture_frame", path=str(path), scale=1)
        if "error" in response:
            raise RuntimeError(f"capture failed: {response}")
        metadata = json.loads(path.with_suffix(".json").read_text())
        return {"path": str(path), "png_sha256": sha256(path), "tick": metadata["tick"],
                "device": metadata["capabilities"]["name"], "backend": metadata["capabilities"]["backend"],
                "shadow_maps_redrawn": metadata["metrics"].get("shadow_maps_redrawn"),
                "shadow_dirty_reason": metadata["metrics"].get("shadow_dirty_reason")}

    failures = []
    try:
        if process.stderr is None:
            raise RuntimeError("headless renderer stderr is unavailable")
        ready_line = process.stderr.readline()
        ready = json.loads(ready_line)
        if ready.get("event") != "ready":
            raise RuntimeError(f"renderer not ready: {ready}")
        request("step", ticks=args.tick)
        baseline = capture("baseline")
        for index, filename in enumerate(INVALID_SHADERS):
            path = isolated_shaders / filename
            original = path.read_text()
            path.write_text(original + "\nthis is deliberately invalid WGSL\n")
            result = request("reload_shaders")
            if "error" not in result:
                raise RuntimeError(f"invalid {filename} reload unexpectedly succeeded")
            error_message = result["error"]["message"]
            if ("hook no longer matches" in error_message or
                    "parsing error" not in error_message or
                    "deliberately invalid WGSL" not in error_message):
                raise RuntimeError(f"{filename} reload failed before shader validation: {result['error']}")
            rollback = capture(f"rollback-{index}-{path.stem}")
            failures.append({"shader": filename, "source_sha256": hashlib.sha256(original.encode()).hexdigest(),
                             "reload_error": result["error"], "capture": rollback,
                             "failure_reached_shader_validation": True,
                             "image_matches_baseline": rollback["png_sha256"] == baseline["png_sha256"]})
            path.write_text(original)
        success = request("reload_shaders")
        if "error" in success:
            raise RuntimeError(f"restored shader set failed to reload: {success}")
        after_success = capture("after-successful-reload")
        if args.native:
            closed = request("shutdown")
            if "error" in closed:
                raise RuntimeError(f"native shutdown failed: {closed}")
        elif process.stdin is not None:
            process.stdin.close()
        process.wait(timeout=60)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=30)
        shutil.rmtree(isolated_shaders, ignore_errors=True)

    report = {
        "version": 1,
        "study": "O02 transactional shader reload rollback across runtime WGSL modules",
        "host": {"device": baseline["device"], "backend": baseline["backend"], "native_window": args.native},
        "session_mode": "native run --agent-stdio" if args.native else "headless serve",
        "scene": str(scene.relative_to(ROOT)) if scene.is_relative_to(ROOT) else str(scene),
        "scene_sha256": sha256(scene), "binary_sha256": sha256(binary),
        "renderer_source_sha256": sha256(ROOT / "crates/engine/src/render/mod.rs"),
        "runner_sha256": sha256(Path(__file__).resolve()),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "seed": args.seed, "tick": args.tick, "camera": args.camera,
        "emitters": [emitter["id"] for emitter in sorted(json.loads(scene.read_text())["emitters"], key=lambda x: x["id"])],
        "resolution": [640, 360], "baseline": baseline, "failed_reloads": failures,
        "restored_shader_reload_succeeded": "result" in success,
        "capture_after_successful_reload": after_success,
        "successful_reload_image_matches_baseline": after_success["png_sha256"] == baseline["png_sha256"],
        "all_failed_reload_captures_match_baseline": all(item["image_matches_baseline"] for item in failures),
        "all_failures_reached_shader_validation": all(item["failure_reached_shader_validation"] for item in failures),
        "failed_reloads_preserve_shadow_cache": (None if args.native else all(item["capture"]["shadow_maps_redrawn"] == 0 and item["capture"]["shadow_dirty_reason"] == "unchanged" for item in failures)),
        "successful_reload_invalidates_all_shadow_maps": (None if args.native else after_success["shadow_maps_redrawn"] == 13 and after_success["shadow_dirty_reason"] == "shader_reload"),
        "tested_runtime_shader_modules": list(INVALID_SHADERS),
        "excluded_embedded_shader_modules": ["present.wgsl (compiled into the host with include_str!; not hot-reloadable)"],
        "limitations": (["Fixed-tick native-window captures do not establish continuous playback or native performance.",
                         "M1 Max/Metal only; other-adapter behavior remains unverified.",
                         "Window frames may render between requests, so per-frame shadow invalidation metrics cannot be attributed to the reload command in this native run.",
                         "All reloadable shader-directory modules are covered; the embedded presentation module is not hot-reloadable."] if args.native else ["Headless M1 Max/Metal fixed-tick evidence; no native-window timing or other-adapter validation.",
                         "All reloadable shader-directory modules are covered; the embedded presentation module is not hot-reloadable."]),
    }
    report["all_checks_passed"] = (baseline["tick"] == args.tick and
                                   all(item["capture"]["tick"] == args.tick for item in failures) and
                                   report["restored_shader_reload_succeeded"] and
                                   report["successful_reload_image_matches_baseline"] and
                                   report["all_failed_reload_captures_match_baseline"] and
                                   report["all_failures_reached_shader_validation"] and
                                   (args.native or (report["failed_reloads_preserve_shadow_cache"] and
                                                    report["successful_reload_invalidates_all_shadow_maps"])))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "all_checks_passed": report["all_checks_passed"],
                      "failed_reload_images_match": [item["image_matches_baseline"] for item in failures],
                      "successful_reload_image_matches": report["successful_reload_image_matches_baseline"]}, indent=2))
    return 0 if report["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
