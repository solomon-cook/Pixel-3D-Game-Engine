#!/usr/bin/env python3
"""Compare frame-to-frame image changes around projected-fire LOD transitions."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPORT = ROOT / "docs/measurements-o04-motion-review.json"
PROFILES = {
    "campfire": ("base-20fps", "lod-20fps"),
    "quiet": ("quiet-base", "quiet-lod"),
    "bonfire": ("bonfire-base", "bonfire-lod"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_sequence(name: str) -> tuple[dict, list[dict], list[Image.Image], list[dict]]:
    sequence_path = ROOT / "artifacts/o04/continuous-motion" / name / "sequence.json"
    sequence = json.loads(sequence_path.read_text())
    frames = sequence["frames"]
    metadata = [json.loads(Path(frame["metadata"]).read_text()) for frame in frames]
    images = [Image.open(frame["image"]).convert("RGB") for frame in frames]
    return sequence, frames, images, metadata


def rgb_mae(image: Image.Image) -> float:
    return sum(ImageStat.Stat(image).mean[:3]) / 3.0


def summarize(values: list[float]) -> dict:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "mean": None, "median": None, "p95": None, "max": None}
    return {
        "count": len(ordered),
        "mean": statistics.fmean(ordered),
        "median": statistics.median(ordered),
        "p95_nearest_rank": ordered[math.ceil(0.95 * len(ordered)) - 1],
        "max": ordered[-1],
    }


def transition_metrics(base: list[Image.Image], lod: list[Image.Image],
                       bbox: tuple[int, int, int, int], indexes: set[int]) -> dict:
    base_changes: list[float] = []
    lod_changes: list[float] = []
    temporal_errors: list[float] = []
    local_temporal_errors: list[float] = []
    frame_errors: list[float] = []
    local_frame_errors: list[float] = []
    for index in range(1, len(base)):
        base_delta = ImageChops.difference(base[index], base[index - 1])
        lod_delta = ImageChops.difference(lod[index], lod[index - 1])
        temporal_error = ImageChops.difference(base_delta, lod_delta)
        frame_error = ImageChops.difference(base[index], lod[index])
        base_changes.append(rgb_mae(base_delta))
        lod_changes.append(rgb_mae(lod_delta))
        temporal_errors.append(rgb_mae(temporal_error))
        local_temporal_errors.append(rgb_mae(temporal_error.crop(bbox)))
        frame_errors.append(rgb_mae(frame_error))
        local_frame_errors.append(rgb_mae(frame_error.crop(bbox)))

    transition_steps = [i - 1 for i in range(1, len(base)) if i in indexes]
    other_steps = [i - 1 for i in range(1, len(base)) if i not in indexes]
    return {
        "whole_route": {
            "baseline_frame_to_frame_rgb_mae": summarize(base_changes),
            "lod_frame_to_frame_rgb_mae": summarize(lod_changes),
            "baseline_vs_lod_temporal_change_rgb_mae": summarize(temporal_errors),
            "baseline_vs_lod_frame_rgb_mae": summarize(frame_errors),
        },
        "transition_window": {
            "baseline_vs_lod_temporal_change_rgb_mae": summarize([temporal_errors[i] for i in transition_steps]),
            "local_flame_baseline_vs_lod_temporal_change_rgb_mae": summarize([local_temporal_errors[i] for i in transition_steps]),
            "baseline_vs_lod_frame_rgb_mae": summarize([frame_errors[i + 1] for i in transition_steps]),
            "local_flame_baseline_vs_lod_frame_rgb_mae": summarize([local_frame_errors[i + 1] for i in transition_steps]),
        },
        "outside_transition_window": {
            "baseline_vs_lod_temporal_change_rgb_mae": summarize([temporal_errors[i] for i in other_steps]),
            "local_flame_baseline_vs_lod_temporal_change_rgb_mae": summarize([local_temporal_errors[i] for i in other_steps]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path,
                        default=ROOT / "docs/measurements-o04-transition-temporal.json")
    args = parser.parse_args()
    source = json.loads(SOURCE_REPORT.read_text())
    result = {
        "title": "O04 projected fire detail temporal changes around LOD transitions",
        "source_report": str(SOURCE_REPORT.relative_to(ROOT)),
        "source_report_sha256": sha256(SOURCE_REPORT),
        "profiles": {},
        "method": "Frame-to-frame absolute RGB changes are compared for baseline and LOD sequences. Transition windows include the transition sample and two samples on either side. The flame crop uses the baseline report's per-profile union difference bounds.",
        "limitations": [
            "This is a deterministic image-difference analysis, not human continuous-playback or silhouette/flicker acceptance.",
            "Samples are 20 fps for campfire and 12 fps for quiet and bonfire; faster artifacts may be missed.",
            "One Apple M1 Max/Metal adapter; native-window and other-adapter validation remain open.",
        ],
    }
    checks = []
    for profile, (base_name, lod_name) in PROFILES.items():
        base_sequence, base_frames, base_images, base_meta = read_sequence(base_name)
        lod_sequence, lod_frames, lod_images, lod_meta = read_sequence(lod_name)
        assert len(base_frames) == len(lod_frames)
        assert base_sequence["scene_sha256"] == lod_sequence["scene_sha256"]
        assert base_sequence["seed"] == lod_sequence["seed"]
        assert base_sequence["fps"] == lod_sequence["fps"]
        assert [f["tick"] for f in base_frames] == [f["tick"] for f in lod_frames]
        assert [f["camera"] for f in base_frames] == [f["camera"] for f in lod_frames]

        state_keys = ("fire_primitives_full", "embers", "particle_lights")
        state_parity = all(
            tuple(frame["metrics"][key] for key in state_keys) ==
            tuple(candidate["metrics"][key] for key in state_keys)
            for frame, candidate in zip(base_meta, lod_meta)
        )
        assert state_parity, f"{profile}: LOD changed full simulation state or emitted-light counts"

        events = source["profiles"][profile]["transitions"]
        transition_indexes = {event["frame"] for event in events}
        for event in events:
            index = event["frame"]
            assert lod_meta[index]["metrics"]["fire_lod_level"] == event["to"], (profile, event)
            assert lod_meta[index - 1]["metrics"]["fire_lod_level"] == event["from"], (profile, event)
        observed_transitions = [
            {"frame": index, "from": lod_meta[index - 1]["metrics"]["fire_lod_level"],
             "to": lod_meta[index]["metrics"]["fire_lod_level"]}
            for index in range(1, len(lod_meta))
            if lod_meta[index - 1]["metrics"]["fire_lod_level"] != lod_meta[index]["metrics"]["fire_lod_level"]
        ]
        expected_transitions = [
            {"frame": event["frame"], "from": event["from"], "to": event["to"]}
            for event in events
        ]
        assert observed_transitions == expected_transitions, (profile, observed_transitions, expected_transitions)
        # Exclude two neighboring steps on either side from the comparison set.
        transition_window_indexes = {
            index + offset for index in transition_indexes for offset in (-2, -1, 0, 1, 2)
            if 1 <= index + offset < len(base_frames)
        }
        bbox = tuple(source["profiles"][profile]["pixel_diff_union_bbox"])
        result["profiles"][profile] = {
            "baseline_sequence": f"artifacts/o04/continuous-motion/{base_name}/sequence.json",
            "baseline_sequence_sha256": sha256(ROOT / f"artifacts/o04/continuous-motion/{base_name}/sequence.json"),
            "lod_sequence": f"artifacts/o04/continuous-motion/{lod_name}/sequence.json",
            "lod_sequence_sha256": sha256(ROOT / f"artifacts/o04/continuous-motion/{lod_name}/sequence.json"),
            "frame_count": len(base_frames),
            "fps": base_sequence["fps"],
            "full_fire_geometry_embers_and_particle_lights_match_every_sample": state_parity,
            "observed_transitions_match_source_report": observed_transitions == expected_transitions,
            "observed_transitions": observed_transitions,
            "transitions_zero_based_frame_index": events,
            "transition_window_indexes_zero_based": sorted(transition_window_indexes),
            "flame_difference_bbox": bbox,
            "metrics": transition_metrics(base_images, lod_images, bbox, transition_window_indexes),
        }
        checks.append(len(base_frames) == len(lod_frames) and len(transition_indexes) > 0)
        for image in base_images + lod_images:
            image.close()
    result["all_checks_passed"] = all(checks)
    result["runner"] = str(Path(__file__).resolve().relative_to(ROOT))
    result["runner_sha256"] = sha256(Path(__file__).resolve())
    result["report_path"] = str(args.report.resolve().relative_to(ROOT))
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "report": str(report_path),
        "all_checks_passed": result["all_checks_passed"],
        "transition_temporal_error": {
            profile: values["metrics"]["transition_window"]["baseline_vs_lod_temporal_change_rgb_mae"]
            for profile, values in result["profiles"].items()
        },
    }, indent=2))
    return 0 if result["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
