#!/usr/bin/env python3
"""Extend compact-HDR temporal evidence to clearing, heavy-fire and material routes."""
import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from compact_hdr_temporal_study import frame_error, load_frames, percentile, run_motion, sha256  # noqa: E402

WORKLOADS = {
    "clearing": ("assets/scenes/clearing.json", "fire-study", "clearing-orbit"),
    "profiling-heavy": ("assets/scenes/profiling-heavy.json", "smoke-close", "clearing-orbit"),
    "materials": ("assets/scenes/materials.json", "glass-close", "material-orbit"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/o08/compact-hdr-workloads")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/measurements-o08-compact-hdr-workloads.json")
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--route-start", type=float, default=8.0)
    parser.add_argument("--reuse-captures", action="store_true", help="analyze existing paired frame sequences")
    args = parser.parse_args()
    if not 2 <= args.frames <= 600 or not 1 <= args.stride <= 60:
        parser.error("frames must be 2..600 and stride 1..60")
    args.binary = args.binary.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    workloads = {}
    for name, (source_name, camera, route) in WORKLOADS.items():
        source_path = ROOT / source_name
        source = json.loads(source_path.read_text())
        baseline = copy.deepcopy(source)
        candidate = copy.deepcopy(source)
        baseline["render"]["compact_hdr"] = False
        candidate["render"]["compact_hdr"] = True
        verify = copy.deepcopy(candidate)
        verify["render"]["compact_hdr"] = False
        if verify != baseline:
            raise RuntimeError(f"{name}: scene variants differ beyond render.compact_hdr")
        scene_dir = args.output / name / "scenes"
        scene_dir.mkdir(parents=True, exist_ok=True)
        baseline_scene = scene_dir / "rgba16.json"
        candidate_scene = scene_dir / "rg11b10.json"
        baseline_scene.write_text(json.dumps(baseline, indent=2) + "\n")
        candidate_scene.write_text(json.dumps(candidate, indent=2) + "\n")
        baseline_dir = args.output / name / "rgba16"
        candidate_dir = args.output / name / "rg11b10"
        reuse_pair = args.reuse_captures and (baseline_dir / "sequence.json").is_file() and (candidate_dir / "sequence.json").is_file()
        if not reuse_pair:
            run_motion(args.binary, baseline_scene, baseline_dir, args.frames, args.stride,
                       args.route_start, camera, route)
            run_motion(args.binary, candidate_scene, candidate_dir, args.frames, args.stride,
                       args.route_start, camera, route)
        baseline_sequence = json.loads((baseline_dir / "sequence.json").read_text())
        candidate_sequence = json.loads((candidate_dir / "sequence.json").read_text())
        for key in ("seed", "start_tick", "frame_stride_ticks", "route", "route_start_seconds", "binary_sha256"):
            if baseline_sequence[key] != candidate_sequence[key]:
                raise RuntimeError(f"{name}: paired sequences differ in {key}")
        for a, b in zip(baseline_sequence["frames"], candidate_sequence["frames"]):
            if a["tick"] != b["tick"] or a["camera"] != b["camera"]:
                raise RuntimeError(f"{name}: paired frame tick or camera differs")
        baseline_frames = load_frames(baseline_dir, args.frames)
        candidate_frames = load_frames(candidate_dir, args.frames)
        frame_pairs = [frame_error(a, b) for a, b in zip(baseline_frames, candidate_frames)]
        temporal_pairs = []
        from PIL import ImageChops, ImageStat
        for i in range(1, args.frames):
            base_delta = ImageChops.difference(baseline_frames[i], baseline_frames[i - 1])
            candidate_delta = ImageChops.difference(candidate_frames[i], candidate_frames[i - 1])
            delta_error = ImageChops.difference(base_delta, candidate_delta)
            temporal_pairs.append((sum(ImageStat.Stat(delta_error).mean) / 3,
                                   max(high for _, high in delta_error.getextrema())))
        frame_means = [entry[0] for entry in frame_pairs]
        temporal_means = [entry[0] for entry in temporal_pairs]
        base_cap = baseline_sequence["frames"][0]["capabilities"]
        candidate_cap = candidate_sequence["frames"][0]["capabilities"]
        workloads[name] = {
            "source_scene": source_name,
            "camera": camera,
            "route": route,
            "seed": 42,
            "start_tick": 300,
            "route_start_seconds": args.route_start,
            "frame_count": args.frames,
            "frame_stride_ticks": args.stride,
            "capture_rate_hz": 60 / args.stride,
            "resolution": base_cap["resolution"],
            "baseline_format": base_cap["resource_inventory"]["hdr_color_format"],
            "candidate_format": candidate_cap["resource_inventory"]["hdr_color_format"],
            "compact_hdr_supported": candidate_cap["resource_inventory"]["rg11b10_renderable_feature_available"],
            "scene_variant_only_difference": "render.compact_hdr",
            "scene_sha256": {"baseline": baseline_sequence["scene_sha256"],
                             "candidate": candidate_sequence["scene_sha256"]},
            "binary_sha256": baseline_sequence["binary_sha256"],
            "capture_script_sha256": baseline_sequence["capture_script_sha256"],
            "frame_error_rgb_255": {
                "mean_of_frame_means": sum(frame_means) / len(frame_means),
                "p95_frame_mean": percentile(frame_means, 0.95),
                "max_frame_mean": max(frame_means),
                "max_channel_error": max(entry[1] for entry in frame_pairs),
            },
            "temporal_change_magnitude_error_rgb_255": {
                "mean_of_frame_means": sum(temporal_means) / len(temporal_means),
                "p95_frame_mean": percentile(temporal_means, 0.95),
                "max_frame_mean": max(temporal_means),
                "max_channel_error": max(entry[1] for entry in temporal_pairs),
            },
        }
    report = {
        "version": 1,
        "purpose": "Additional compact-HDR temporal coverage on three O01-O08 workloads; no promotion decision is inferred.",
        "host": {"gpu": "Apple M1 Max", "backend": "Metal"},
        "workloads": workloads,
        "limitations": [
            "Offscreen M1 Max/Metal only; no native-window, DX12, other-adapter, physical fallback or human playback acceptance.",
            "Temporal metric compares per-pixel absolute frame-to-frame change magnitudes and is not a perceptual threshold.",
            "Capture timing is not performance evidence; no timing comparison was run.",
        ],
        "runner_sha256": sha256(Path(__file__).resolve()),
        "shared_analysis_helper_sha256": sha256(ROOT / "scripts/compact_hdr_temporal_study.py"),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(args.report), "workloads": list(workloads)}))


if __name__ == "__main__":
    main()
