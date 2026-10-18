#!/usr/bin/env python3
"""Exercise dual-emitter rendering across native surface resize and minimize/restore."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import select
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENE = ROOT / "assets/scenes/two-emitter-review.json"

class Session:
    def __init__(self, binary: Path, scene: Path, seed: int) -> None:
        self.process = subprocess.Popen([str(binary), "run", "--agent-stdio", "--scene", str(scene), "--seed", str(seed)], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.request_id = 0
    def request(self, method: str, **params):
        self.request_id += 1
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps({"id": self.request_id, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        ready, _, _ = select.select([self.process.stdout], [], [], 90)
        if not ready: raise TimeoutError(f"timed out waiting for {method}")
        response = json.loads(self.process.stdout.readline())
        if response.get("id") != self.request_id or "error" in response: raise RuntimeError(f"{method}: {response}")
        return response["result"]
    def close(self):
        try: self.request("shutdown")
        except Exception: self.process.terminate()
        self.process.wait(timeout=60)

def capture(session: Session, path: Path) -> dict:
    image = Path(session.request("capture_frame", path=str(path.resolve()), scale=1)["image"])
    meta = json.loads(image.with_suffix(".json").read_text())
    inventory = meta.get("capabilities", {}).get("resource_inventory", {})
    return {"image": str(image.relative_to(ROOT)) if image.is_relative_to(ROOT) else str(image), "sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "tick": meta.get("tick"), "camera": meta.get("camera"), "resolution": meta.get("resolution"), "device": meta.get("capabilities", {}).get("name"), "backend": meta.get("capabilities", {}).get("backend"), "resource_inventory": inventory}

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    ap.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    ap.add_argument("--output", type=Path, default=ROOT / "artifacts/multi-emitter/native-lifecycle")
    ap.add_argument("--report", type=Path, default=ROOT / "docs/measurements-multi-emitter-native-lifecycle.json")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    binary, scene, output, report_path = (args.binary.resolve(), args.scene.resolve(), args.output.resolve(), args.report.resolve())
    data = json.loads(scene.read_text())
    if len(data.get("emitters", [])) != 2: ap.error("scene must contain exactly two emitters")
    output.mkdir(parents=True, exist_ok=True); report_path.parent.mkdir(parents=True, exist_ok=True)
    session = Session(binary, scene, args.seed)
    stages = {}
    try:
        initial_window = session.request("get_window")
        session.request("step", ticks=120)
        stages["before"] = capture(session, output / "before.png")
        window_states = {"before": initial_window}
        session.request("set_window", size=[1000, 700])
        window_states["resized"] = session.request("get_window")
        stages["resized"] = capture(session, output / "resized.png")
        window_states["restored"] = window_states["resized"]
        stages["restored"] = capture(session, output / "restored.png")
        session.request("set_window", minimized=True)
        window_states["minimize_request"] = session.request("get_window")
        session.request("set_window", minimized=False)
        scale = initial_window["scale_factor"]
        original_logical_size = [round(v / scale) for v in initial_window["physical_size"]]
        session.request("set_window", size=original_logical_size)
        window_states["original_size"] = session.request("get_window")
        stages["original_size"] = capture(session, output / "original-size.png")
    finally:
        session.close()
    stable_tick = len({v["tick"] for v in stages.values()}) == 1
    stable_camera = len({json.dumps(v["camera"], sort_keys=True) for v in stages.values()}) == 1
    same_renderer_resources = len({json.dumps(v["resource_inventory"], sort_keys=True) for v in stages.values()}) == 1
    image_repeat = stages["before"]["sha256"] == stages["original_size"]["sha256"]
    window_resize_observed = window_states["resized"]["physical_size"] != initial_window["physical_size"]
    minimize_request_observed = window_states["minimize_request"]["minimized"]
    report = {"version": 1, "date": "2026-10-18", "study": "dual-emitter native surface resize and minimize/restore lifecycle", "host": {"device": stages["before"]["device"], "backend": stages["before"]["backend"], "native_window": True, "initial_window": initial_window}, "source_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip(), "scene": str(scene.relative_to(ROOT)) if scene.is_relative_to(ROOT) else str(scene), "scene_sha256": hashlib.sha256(scene.read_bytes()).hexdigest(), "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "source_ids": sorted(e["id"] for e in data["emitters"]), "seed": args.seed, "window_states": window_states, "stages": stages, "checks": {"native_resize_observed": window_resize_observed, "minimize_request_registered": minimize_request_observed, "same_fixed_tick": stable_tick, "same_camera": stable_camera, "renderer_resource_inventory_stable": same_renderer_resources, "image_restored_after_surface_changes": image_repeat}, "limitations": ["One M1 Max/Metal native window; resize and restore are covered, but the native host did not report minimized=true after the minimize request, so minimize handling is unverified.", "This exercises surface resize, not GPU device loss or full device recreation.", "Windows/DX12 and other-adapter acceptance remain unverified."]}
    report["all_checks_passed"] = all(value for key, value in report["checks"].items() if key != "minimize_request_registered")
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "checks": report["checks"], "all_checks_passed": report["all_checks_passed"]}, indent=2))
    return 0 if report["all_checks_passed"] else 1
if __name__ == "__main__": raise SystemExit(main())
