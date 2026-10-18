#!/usr/bin/env python3
"""Verify native-window Session control for O01 shading operation counters."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import select
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--scene", type=Path, default=ROOT / "assets/scenes/profiling-heavy.json")
    parser.add_argument("--camera", default="hero")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o01-counter-native")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o01-shading-counter-native.json")
    parser.add_argument("--tick", type=int, default=120)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    binary, scene = args.binary.resolve(), args.scene.resolve()
    if not binary.is_file():
        subprocess.run(["cargo", "build", "-p", "engine-lab"], cwd=ROOT, check=True)
    args.output.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [str(binary), "run", "--agent-stdio", "--paused", "--scene", str(scene),
         "--camera", args.camera, "--seed", str(args.seed)],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True,
    )
    request_id = 0

    def request(method: str, **params):
        nonlocal request_id
        request_id += 1
        if process.poll() is not None or not process.stdin or not process.stdout:
            raise RuntimeError(f"native session exited before {method}")
        process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], 60)
        if not ready:
            raise TimeoutError(f"timed out waiting for {method}")
        response = json.loads(process.stdout.readline())
        if response.get("id") != request_id or response.get("error"):
            raise RuntimeError(f"{method}: {response}")
        return response["result"]

    captures = {}
    toggle_results = {}
    try:
        request("step", ticks=args.tick)
        window = request("get_window")
        for label, enabled in (("disabled_before", False), ("enabled", True), ("disabled_after", False)):
            toggle_results[label] = request("set_shading_diagnostics", enabled=enabled)
            path = (args.output / f"{label}.png").resolve()
            result = request("capture_frame", path=str(path), scale=1)
            metadata = json.loads(path.with_suffix(".json").read_text())
            counters = metadata["metrics"].get("shading_counters")
            captures[label] = {
                "path": str(path),
                "sha256": sha256(path),
                "tick": result["tick"],
                "counters": counters,
                "scratch_bytes": metadata["capabilities"]["resource_inventory"]["shading_diagnostic_targets_bytes"],
            }
        request("shutdown")
        process.wait(timeout=60)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=30)

    before, diagnostic, after = (captures[k] for k in ("disabled_before", "enabled", "disabled_after"))
    report = {
        "version": 1,
        "workstream": "O01 native-window shading-counter Session operation",
        "host": {"device": diagnostic["counters"] and json.loads((Path(diagnostic["path"]).with_suffix(".json")).read_text())["capabilities"]["name"],
                 "backend": json.loads((Path(diagnostic["path"]).with_suffix(".json")).read_text())["capabilities"]["backend"],
                 "native_window": True, "window": window},
        "scene": str(scene.relative_to(ROOT)) if scene.is_relative_to(ROOT) else str(scene),
        "scene_sha256": sha256(scene), "binary_sha256": sha256(binary),
        "session_source_sha256": sha256(ROOT / "crates/engine/src/session.rs"),
        "seed": args.seed, "tick": args.tick, "camera": args.camera,
        "resolution": [640, 360], "toggle_results": toggle_results, "captures": captures,
        "diagnostic_counters_nonzero": bool(diagnostic["counters"]) and any(diagnostic["counters"].values()),
        "counters_absent_when_disabled": before["counters"] is None and after["counters"] is None,
        "scratch_allocation_released": before["scratch_bytes"] == after["scratch_bytes"] == 0 and diagnostic["scratch_bytes"] > 0,
        "normal_diagnostic_normal_pixel_identical": before["sha256"] == diagnostic["sha256"] == after["sha256"],
        "limitations": ["Single fixed-tick native-window M1 Max/Metal capture; it validates access and image preservation, not continuous motion, counter performance or other adapters.", "Atomic diagnostics perturb timing; captured timings are excluded from performance comparisons."],
    }
    report["all_checks_passed"] = all(report[k] for k in (
        "diagnostic_counters_nonzero", "counters_absent_when_disabled", "scratch_allocation_released",
        "normal_diagnostic_normal_pixel_identical")) and all(c["tick"] == args.tick for c in captures.values())
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "all_checks_passed": report["all_checks_passed"],
                      "diagnostic_counter_fields": len(diagnostic["counters"] or {}),
                      "scratch_bytes": [before["scratch_bytes"], diagnostic["scratch_bytes"], after["scratch_bytes"]]}, indent=2))
    return 0 if report["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
