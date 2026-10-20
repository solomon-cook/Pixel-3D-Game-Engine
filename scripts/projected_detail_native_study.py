#!/usr/bin/env python3
"""Compare direct and projected-fire-detail LOD in native-window playback."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "crates/engine-lab/src/window.rs",
    "crates/engine/src/render/mod.rs",
    "crates/engine/src/effects.rs",
    "scripts/projected_detail_native_study.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nested(run: dict, *keys: str):
    value = run
    for key in keys:
        value = value.get(key, {}) if isinstance(value, dict) else {}
    return value


def metric(run: dict, *keys: str) -> dict:
    value = nested(run, *keys)
    if isinstance(value, dict):
        return {key: value.get(key) for key in ("median_ms", "p95_ms", "samples")}
    return {}


def difference(candidate: dict, baseline: dict, *keys: str) -> float | None:
    after, before = nested(candidate, *keys), nested(baseline, *keys)
    after = after.get("median_ms") if isinstance(after, dict) else after
    before = before.get("median_ms") if isinstance(before, dict) else before
    if isinstance(after, (int, float)) and isinstance(before, (int, float)):
        return after - before
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/engine-lab")
    parser.add_argument(
        "--foreground-app",
        type=Path,
        help="launch the benchmark through a macOS .app bundle with LaunchServices",
    )
    parser.add_argument("--scene", type=Path, default=ROOT / "assets/scenes/projected-detail-motion-review.json")
    parser.add_argument("--camera", default="hero")
    parser.add_argument("--route", default="projected-detail-review-orbit")
    parser.add_argument("--profile", choices=("campfire", "quiet", "bonfire"), default="campfire")
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o04/projected-detail-native")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o04-native.json")
    parser.add_argument("--resume", action="store_true", help="reuse completed native reports in the output directory")
    args = parser.parse_args()
    binary, source = args.binary.resolve(), args.scene.resolve()
    foreground_app = args.foreground_app.resolve() if args.foreground_app else None
    output, report_path = args.output.resolve(), args.report.resolve()
    if not binary.is_file() or not source.is_file():
        parser.error("binary and scene must exist")
    app_executable = None
    if foreground_app:
        if platform.system() != "Darwin" or not foreground_app.is_dir():
            parser.error("--foreground-app requires an existing macOS .app bundle")
        info_path = foreground_app / "Contents" / "Info.plist"
        if not info_path.is_file():
            parser.error("--foreground-app is missing Contents/Info.plist")
        import plistlib

        with info_path.open("rb") as info_file:
            app_info = plistlib.load(info_file)
        executable_name = app_info.get("CFBundleExecutable")
        app_executable = foreground_app / "Contents" / "MacOS" / str(executable_name)
        if not executable_name or not app_executable.is_file():
            parser.error("--foreground-app executable is missing")
        if sha256(app_executable) != sha256(binary):
            parser.error("--foreground-app executable does not match --binary")
    if args.pairs < 1 or args.duration <= 0 or args.warmup < 0:
        parser.error("pairs and duration must be positive; warmup cannot be negative")

    original = json.loads(source.read_text())
    profile_id = f"effect-{args.profile}"
    if not any(effect.get("id") == profile_id for effect in original.get("effects", [])):
        parser.error(f"scene does not define profile {profile_id!r}")
    if len(original.get("emitters", [])) != 1:
        parser.error("the projected-detail native study expects a single-emitter profile scene")
    original["emitters"][0]["effect_profile"] = profile_id
    scene_dir = output / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)
    scenes = {}
    for variant, enabled in (("direct", False), ("lod", True)):
        scene = json.loads(json.dumps(original))
        scene.setdefault("render", {}).setdefault("experiments", {})["projected_detail_lod"] = enabled
        scenes[variant] = scene_dir / f"{args.profile}-{variant}.json"
        scenes[variant].write_text(json.dumps(scene, indent=2) + "\n")
        subprocess.run([str(binary), "validate", str(scenes[variant])], cwd=ROOT, check=True, stdout=subprocess.PIPE)

    output.mkdir(parents=True, exist_ok=True)
    pairs = []
    for pair_number in range(1, args.pairs + 1):
        order = ("direct", "lod") if pair_number % 2 else ("lod", "direct")
        runs = {}
        for variant in order:
            path = output / f"pair-{pair_number:02d}-{variant}.engine.json"
            if not (args.resume and path.is_file()):
                command = [
                    str(binary), "benchmark-native", "--scene", str(scenes[variant]),
                    "--camera", args.camera, "--seed", "42", "--route", args.route,
                    "--duration", str(args.duration), "--warmup", str(args.warmup),
                    "--output", str(path),
                ]
                if foreground_app:
                    command.append("--wait-for-foreground")
                launch_command = command
                if foreground_app:
                    launch_command = [
                        "/usr/bin/open", "-n", "-W", "-a", str(foreground_app),
                        "--args", *command[1:],
                    ]
                with (output / f"pair-{pair_number:02d}-{variant}.log").open("w") as log:
                    subprocess.run(launch_command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            run = json.loads(path.read_text())
            expected = variant == "lod"
            if run.get("scene", {}).get("render", {}).get("experiments", {}).get("projected_detail_lod") is not expected:
                raise RuntimeError(f"{variant} report has the wrong projected-detail setting")
            coverage = run.get("timing_coverage", {})
            rendered, timed = coverage.get("rendered_frames", 0), coverage.get("timed_render_frames", 0)
            if not coverage.get("gpu_timestamps_supported") or not rendered or timed / rendered < 0.99:
                raise RuntimeError(f"native GPU timing coverage below 99% for {variant}: {timed}/{rendered}")
            runs[variant] = run

        baseline, candidate = runs["direct"], runs["lod"]
        deltas = {
            "frames_per_second": candidate["frames_per_second"] - baseline["frames_per_second"],
            "cpu_native_frame_ms": difference(candidate, baseline, "cpu_native_frame"),
            "cpu_renderer_encode_ms": difference(candidate, baseline, "cpu_renderer_encode"),
            "cpu_projected_detail_ms": difference(candidate, baseline, "projected_detail", "cpu_ms"),
            "gpu_atmosphere_fire_ms": difference(candidate, baseline, "gpu_stages", "atmosphere_fire"),
        }
        pair = {"pair": pair_number, "order": list(order), "deltas_lod_minus_direct": deltas}
        for variant, run in (("direct", baseline), ("lod", candidate)):
            pair[variant] = {
                "frames_per_second": run["frames_per_second"],
                "cpu_native_frame": metric(run, "cpu_native_frame"),
                "cpu_renderer_encode": metric(run, "cpu_renderer_encode"),
                "projected_detail": run["projected_detail"],
                "gpu_atmosphere_fire": metric(run, "gpu_stages", "atmosphere_fire"),
                "timing_coverage": run["timing_coverage"],
                "report": f"pair-{pair_number:02d}-{variant}.engine.json",
                "report_sha256": sha256(output / f"pair-{pair_number:02d}-{variant}.engine.json"),
            }
        pairs.append(pair)
        print(json.dumps({"pair": pair_number, "order": order, "deltas": deltas}), flush=True)

    fields = ("frames_per_second", "cpu_native_frame_ms", "cpu_renderer_encode_ms", "cpu_projected_detail_ms", "gpu_atmosphere_fire_ms")
    paired = {}
    for field in fields:
        values = [pair["deltas_lod_minus_direct"][field] for pair in pairs if pair["deltas_lod_minus_direct"][field] is not None]
        paired[field] = statistics.median(values) if values else None

    first_variant = pairs[0]["order"][0]
    first_run = json.loads((output / f"pair-01-{first_variant}.engine.json").read_text())
    report = {
        "workstream": "O04 native-window projected fire-detail LOD",
        "host": {"adapter": first_run["capabilities"].get("name"), "backend": first_run["capabilities"].get("backend"), "os": platform.platform()},
        "source_scene": str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source),
        "scene_sha256": sha256(source),
        "profile": profile_id,
        "camera": args.camera,
        "route": args.route,
        "seed": 42,
        "resolution": first_run["capabilities"].get("resolution"),
        "duration_seconds_per_run": args.duration,
        "warmup_seconds": args.warmup,
        "git_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, text=True, stdout=subprocess.PIPE).stdout.strip(),
        "binary_sha256": sha256(binary),
        "foreground_app": {
            "bundle_path": str(foreground_app),
            "executable_sha256": sha256(app_executable),
            "launch_command": "/usr/bin/open -n -W -a <app> --args ... --wait-for-foreground",
        } if foreground_app else None,
        "source_sha256": {item: sha256(ROOT / item) for item in SOURCES},
        "pairs": pairs,
        "paired_medians_lod_minus_direct": paired,
        "limitations": [
            "Native-window results include surface acquisition, UI, submission and present; CPU spans overlap.",
            "The native study reports bounded fire-segment reduction, not human visual acceptance during continuous playback.",
            "This Mac/Metal route does not qualify Windows/DX12 or other adapters.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(report_path), "pairs": len(pairs), "paired_medians": paired}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
