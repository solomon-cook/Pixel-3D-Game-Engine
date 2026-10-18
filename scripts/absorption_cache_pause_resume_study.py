#!/usr/bin/env python3
"""Check cache freshness across paused wall time and resumed real-time ticks."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import select
import subprocess
import time

from absorption_cache_study import ROOT, SOURCE, image_error, make_scenes, sha256


class Session:
    def __init__(self, binary: Path, scene: Path, output: Path):
        self.process = subprocess.Popen(
            [str(binary), "run", "--agent-stdio", "--scene", str(scene), "--seed", "42", "--camera", "absorption-study"],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        self.request_id = 0
        self.output = output
        output.mkdir(parents=True, exist_ok=True)

    def request(self, method: str, **params):
        self.request_id += 1
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps({"id": self.request_id, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        ready, _, _ = select.select([self.process.stdout], [], [], 60)
        if not ready:
            raise TimeoutError(f"timed out waiting for {method} response")
        response = json.loads(self.process.stdout.readline())
        if response.get("id") != self.request_id or "error" in response:
            raise RuntimeError(response)
        return response["result"]

    def capture(self, name: str) -> dict:
        state = self.request("inspect_effects")
        image = self.request("capture_frame", path=str((self.output / f"{name}.png").resolve()), scale=1)["image"]
        return {"tick": self.request("inspect_scene")["tick"], "state": state, "image": image, "image_sha256": sha256(Path(image))}

    def close(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=60)


def run_variant(binary: Path, scene: Path, output: Path, pause_seconds: float, resume_seconds: float) -> dict:
    session = Session(binary, scene, output)
    try:
        session.request("step", ticks=300)
        session.request("pause", paused=True)
        before_pause = session.capture("paused-before")
        time.sleep(pause_seconds)
        during_pause = session.capture("paused-after-wall-clock-wait")
        session.request("pause", paused=False)
        time.sleep(resume_seconds)
        session.request("pause", paused=True)
        wallclock_resume = session.capture("after-wall-clock-resume")
        aligned_tick = 300 + math.ceil(resume_seconds * 60) + 120
        if wallclock_resume["tick"] > aligned_tick:
            raise RuntimeError("wall-clock resume exceeded fixed-tick alignment window; increase the alignment margin")
        session.request("step", ticks=aligned_tick - wallclock_resume["tick"])
        after_resume = session.capture("aligned-resume-check")
        return {
            "scene_sha256": sha256(scene),
            "paused_tick_before_wait": before_pause["tick"],
            "paused_tick_after_wait": during_pause["tick"],
            "paused_tick_stable": before_pause["tick"] == during_pause["tick"],
            "paused_image_stable": before_pause["image_sha256"] == during_pause["image_sha256"],
            "wallclock_resume_tick": wallclock_resume["tick"],
            "resume_advanced_ticks": wallclock_resume["tick"] - during_pause["tick"],
            "resume_advanced": wallclock_resume["tick"] > during_pause["tick"],
            "aligned_resume_tick": after_resume["tick"],
            "resume_state": after_resume["state"],
            "resume_image": after_resume["image"],
            "resume_image_sha256": after_resume["image_sha256"],
        }
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release" / ("engine-lab.exe" if os.name == "nt" else "engine-lab"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o05/pause-resume")
    parser.add_argument("--pause-seconds", type=float, default=2.0)
    parser.add_argument("--resume-seconds", type=float, default=2.0)
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o05-pause-resume.json")
    parser.add_argument("--summarize-existing", action="store_true", help="add image-error metrics to existing capture outputs")
    args = parser.parse_args()
    if not 0.1 <= args.pause_seconds <= 60 or not 0.1 <= args.resume_seconds <= 60:
        parser.error("pause and resume durations must be between 0.1 and 60 seconds")
    binary, output, report_path = args.binary.resolve(), args.output.resolve(), args.report.resolve()
    if args.summarize_existing:
        report = json.loads(report_path.read_text())
        direct = output / "direct" / "aligned-resume-check.png"
        cache16 = output / "cache16" / "aligned-resume-check.png"
        report["aligned_resume_image_error"] = image_error(direct, cache16)
        report["aligned_resume_image_error_scope"] = "Direct and 16-cubed cache captures at the shared aligned fixed tick; this measures approximation error, not cache-state divergence."
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"report": str(report_path), "aligned_resume_image_error": report["aligned_resume_image_error"]}))
        return 0
    if not binary.is_file():
        subprocess.run(["cargo", "build", "--release", "-p", "engine-lab"], cwd=ROOT, check=True)
    scenes = make_scenes(output, json.loads(SOURCE.read_text()))["medium"]
    direct = run_variant(binary, scenes["direct"], output / "direct", args.pause_seconds, args.resume_seconds)
    cache16 = run_variant(binary, scenes["cache16"], output / "cache16", args.pause_seconds, args.resume_seconds)
    report = {
        "workstream": "O05 absorption-cache wall-clock pause/resume study",
        "date": "2026-10-18",
        "host": {"device": "Apple M1 Max", "backend": "Metal"},
        "seed": 42,
        "resolution": [640, 360],
        "cache_resolution": [16, 16, 16],
        "binary_sha256": sha256(binary),
        "study_script_sha256": sha256(Path(__file__).resolve()),
        "pause_wait_seconds": args.pause_seconds,
        "resume_wait_seconds": args.resume_seconds,
        "direct": direct,
        "cache16": cache16,
        "resume_fire_state_equal_at_matching_tick": direct["resume_state"] == cache16["resume_state"] and direct["aligned_resume_tick"] == cache16["aligned_resume_tick"],
        "aligned_resume_image_error": image_error(Path(direct["resume_image"]), Path(cache16["resume_image"])),
        "aligned_resume_image_error_scope": "Direct and 16-cubed cache captures at the shared aligned fixed tick; this measures approximation error, not cache-state divergence.",
        "limitations": [
            "Native run --agent-stdio window on Apple M1 Max/Metal; Windows/DX12 behavior remains unverified.",
            "Wall-clock resume tick totals depend on host scheduling and are not cross-run performance measurements.",
            "The check validates pause stability and post-resume cache refresh at sampled captures, not continuous visual playback.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "direct_pause_stable": direct["paused_tick_stable"] and direct["paused_image_stable"], "cache_pause_stable": cache16["paused_tick_stable"] and cache16["paused_image_stable"], "direct_resumed": direct["resume_advanced"], "cache_resumed": cache16["resume_advanced"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
