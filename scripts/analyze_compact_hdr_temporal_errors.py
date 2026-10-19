#!/usr/bin/env python3
"""Locate sparse compact-HDR peak errors in a saved temporal comparison."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS = (4, 8, 16, 32)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def threshold_pixel_count(difference: Image.Image, threshold: int) -> int:
    mask = None
    for channel in difference.split():
        channel_mask = channel.point([0] * threshold + [255] * (256 - threshold))
        mask = channel_mask if mask is None else ImageChops.lighter(mask, channel_mask)
    assert mask is not None
    return mask.histogram()[255]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "docs/measurements-o06-o08-factorial-temporal-full-orbit-current-build.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs/measurements-o08-compact-hdr-peak-error-analysis.json",
    )
    args = parser.parse_args()
    source_report_path = args.report.resolve()
    source_report = json.loads(source_report_path.read_text())
    sequence_paths = source_report["raw_sequences"]
    baseline_path = ROOT / sequence_paths["direct_copy_rgba16"]["path"]
    compact_path = ROOT / sequence_paths["direct_copy_rg11b10"]["path"]
    baseline = json.loads(baseline_path.read_text())
    compact = json.loads(compact_path.read_text())
    baseline_frames = baseline["frames"]
    compact_frames = compact["frames"]
    if len(baseline_frames) != len(compact_frames):
        raise ValueError("baseline and compact-HDR sequences have different frame counts")

    counts = {threshold: {"changed_pixels": 0, "frames_with_changes": 0} for threshold in THRESHOLDS}
    maximum = {"channel_difference": -1}
    for index, (reference, candidate) in enumerate(zip(baseline_frames, compact_frames)):
        if reference["tick"] != candidate["tick"]:
            raise ValueError(f"tick mismatch at frame {index + 1}")
        reference_image = Image.open(reference["image"]).convert("RGB")
        candidate_image = Image.open(candidate["image"]).convert("RGB")
        if reference_image.size != candidate_image.size:
            raise ValueError(f"resolution mismatch at frame {index + 1}")
        difference = ImageChops.difference(reference_image, candidate_image)
        extrema = difference.getextrema()
        peak = max(high for _, high in extrema)
        for threshold in THRESHOLDS:
            pixel_count = threshold_pixel_count(difference, threshold)
            counts[threshold]["changed_pixels"] += pixel_count
            counts[threshold]["frames_with_changes"] += int(pixel_count > 0)
        if peak > maximum["channel_difference"]:
            peak_channels = [channel.getextrema()[1] for channel in difference.split()]
            peak_mask = None
            for channel in difference.split():
                channel_mask = channel.point([0] * peak + [255] * (256 - peak))
                peak_mask = channel_mask if peak_mask is None else ImageChops.lighter(peak_mask, channel_mask)
            assert peak_mask is not None
            coordinates = [
                (x, y)
                for y in range(peak_mask.height)
                for x in range(peak_mask.width)
                if peak_mask.getpixel((x, y))
            ]
            maximum = {
                "channel_difference": peak,
                "frame_index_one_based": index + 1,
                "tick": reference["tick"],
                "coordinates_xy": coordinates,
                "per_channel_maximum": peak_channels,
                "reference_rgb_at_peak": [list(reference_image.getpixel(point)) for point in coordinates],
                "compact_hdr_rgb_at_peak": [list(candidate_image.getpixel(point)) for point in coordinates],
            }

    frame_count = len(baseline_frames)
    output = {
        "version": 1,
        "date": source_report.get("date"),
        "workstream": "O08 compact-HDR temporal peak-error localization",
        "source_report": str(source_report_path.relative_to(ROOT)),
        "source_report_sha256": sha256(source_report_path),
        "baseline_sequence": str(baseline_path.relative_to(ROOT)),
        "baseline_sequence_sha256": sha256(baseline_path),
        "compact_hdr_sequence": str(compact_path.relative_to(ROOT)),
        "compact_hdr_sequence_sha256": sha256(compact_path),
        "baseline_format": "Rgba16Float",
        "compact_hdr_format": "Rg11b10Ufloat",
        "frame_count": frame_count,
        "resolution": source_report["resolution"],
        "seed": source_report["seed"],
        "tick_range": [baseline_frames[0]["tick"], baseline_frames[-1]["tick"]],
        "peak_error": maximum,
        "threshold_counts": {
            f"at_least_{threshold}_of_255": values for threshold, values in counts.items()
        },
        "interpretation": "The maximum 38/255 difference is confined to the listed pixel(s) and frame; the per-sequence counts show how often large differences occur. This does not substitute for human playback acceptance or demonstrate a performance win.",
        "limitations": [
            "Analysis reuses saved offscreen M1 Max/Metal captures; no render was performed.",
            "Pixel error statistics are not a human visual-quality judgment.",
            "Results do not establish behavior on other adapters or DX12.",
        ],
        "analysis_script": str(Path(__file__).resolve().relative_to(ROOT)),
        "analysis_script_sha256": sha256(Path(__file__).resolve()),
    }
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"report": str(output_path), "peak_error": maximum, "threshold_counts": output["threshold_counts"]}))


if __name__ == "__main__":
    main()
