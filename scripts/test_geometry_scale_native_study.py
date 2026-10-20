#!/usr/bin/env python3
"""Safety checks for resumable O07 native study evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from geometry_scale_native_study import (
    append_rejected_attempt,
    compact_report,
    rejected_attempt_record,
    ROOT,
    validate_saved_run,
)


class SavedRunValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.path = root / "pair-01-baseline.json"
        self.raw_path = root / "pair-01-baseline.engine.json"
        self.provenance = {"binary_sha256": "a" * 64, "scene_sha256": "b" * 64, "tier": 276}

    def make_report(self, duration: float = 120.0) -> dict:
        raw = {
            "mode": "native_vsync_route",
            "actual_measured_seconds": duration,
            "frames_per_second": 60.0,
            "timing_coverage": {
                "gpu_timestamps_supported": True,
                "rendered_frames": 7200,
                "timed_render_frames": 7200,
            },
        }
        self.raw_path.write_text(json.dumps(raw))
        report = compact_report(raw)
        report.update(
            raw_report_sha256=hashlib.sha256(self.raw_path.read_bytes()).hexdigest(),
            raw_report_path=str(self.raw_path),
            provenance=self.provenance,
        )
        self.path.write_text(json.dumps(report))
        return report

    def test_valid_run_checks_raw_hash_and_summary(self) -> None:
        report = self.make_report()
        validate_saved_run(report, self.path, self.raw_path, self.provenance, 120.0)
        self.assertTrue(report["raw_report_retained"])

    def test_mismatched_provenance_is_rejected(self) -> None:
        report = self.make_report()
        with self.assertRaisesRegex(RuntimeError, "provenance does not match"):
            validate_saved_run(report, self.path, self.raw_path, {**self.provenance, "tier": 552}, 120.0)

    def test_undercovered_run_is_rejected(self) -> None:
        report = self.make_report(duration=88.0)
        with self.assertRaisesRegex(RuntimeError, "incomplete native run"):
            validate_saved_run(report, self.path, self.raw_path, self.provenance, 120.0)

    def test_compact_run_without_raw_file_is_marked_unretained(self) -> None:
        report = self.make_report()
        self.raw_path.unlink()
        validate_saved_run(report, self.path, self.raw_path, self.provenance, 120.0)
        self.assertFalse(report["raw_report_retained"])

    def test_retained_raw_hash_mismatch_is_rejected(self) -> None:
        report = self.make_report()
        self.raw_path.write_text('{"tampered": true}')
        with self.assertRaisesRegex(RuntimeError, "raw native report hash does not match"):
            validate_saved_run(report, self.path, self.raw_path, self.provenance, 120.0)

    def test_compact_summary_mismatch_is_rejected(self) -> None:
        report = self.make_report()
        report["frames_per_second"] = 1.0
        with self.assertRaisesRegex(RuntimeError, "compact report differs from retained raw report"):
            validate_saved_run(report, self.path, self.raw_path, self.provenance, 120.0)

    def test_timed_frame_coverage_below_99_percent_is_rejected(self) -> None:
        report = self.make_report()
        raw = json.loads(self.raw_path.read_text())
        raw["timing_coverage"]["timed_render_frames"] = 7127
        self.raw_path.write_text(json.dumps(raw))
        report["timing_coverage"] = raw["timing_coverage"]
        report["raw_report_sha256"] = hashlib.sha256(self.raw_path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(RuntimeError, "incomplete native run"):
            validate_saved_run(report, self.path, self.raw_path, self.provenance, 120.0)

    def test_run_at_99_percent_duration_threshold_is_accepted(self) -> None:
        report = self.make_report(duration=118.8)
        validate_saved_run(report, self.path, self.raw_path, self.provenance, 120.0)

    def test_rejected_zero_frame_run_keeps_abort_and_coverage_provenance(self) -> None:
        raw = {
            "abort_reason": "foreground_wait_timeout",
            "actual_measured_seconds": 0.0,
            "timing_coverage": {
                "gpu_timestamps_supported": True,
                "rendered_frames": 0,
                "timed_render_frames": 0,
            },
        }
        self.raw_path.write_text(json.dumps(raw))
        attempt = rejected_attempt_record(
            self.raw_path,
            self.provenance,
            120.0,
            "incomplete native run",
            1,
        )
        self.assertEqual(attempt["abort_reason"], "foreground_wait_timeout")
        self.assertEqual(attempt["rendered_frames"], 0)
        self.assertEqual(attempt["timed_render_frames"], 0)
        self.assertEqual(attempt["provenance"], self.provenance)
        self.assertEqual(attempt["raw_report_sha256"], hashlib.sha256(self.raw_path.read_bytes()).hexdigest())

    def test_rejected_attempt_without_raw_report_is_still_journaled(self) -> None:
        attempt = rejected_attempt_record(
            self.raw_path,
            self.provenance,
            120.0,
            "process could not launch",
            None,
        )
        self.assertFalse(attempt["raw_report_retained"])
        journal = Path(self.temporary.name) / "rejected-attempts.json"
        append_rejected_attempt(journal, attempt)
        append_rejected_attempt(journal, {"runner_error": "second failure"})
        self.assertEqual(len(json.loads(journal.read_text())), 2)

    def test_cli_journals_a_failed_native_process_with_raw_abort_report(self) -> None:
        fake_binary = Path(self.temporary.name) / "fake-engine-lab"
        fake_binary.write_text(
            f"#!{sys.executable}\n"
            "import json, pathlib, sys\n"
            "output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])\n"
            "output.write_text(json.dumps({"
            "'abort_reason': 'foreground_wait_timeout',"
            "'actual_measured_seconds': 0.0,"
            "'timing_coverage': {'gpu_timestamps_supported': True,"
            "'rendered_frames': 0, 'timed_render_frames': 0}}))\n"
            "raise SystemExit(1)\n"
        )
        fake_binary.chmod(fake_binary.stat().st_mode | 0o111)
        output = Path(self.temporary.name) / "study"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/geometry_scale_native_study.py"),
                "--binary", str(fake_binary),
                "--output", str(output),
                "--duration", "0.1",
                "--warmup", "0",
                "--pairs", "1",
                "--tiers", "276",
                "--comparisons", "instancing_only_vs_culling_instancing",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        journal_path = output / "runs/rejected-attempts.json"
        attempts = json.loads(journal_path.read_text())
        self.assertEqual(len(attempts), 1)
        attempt = attempts[0]
        self.assertEqual(attempt["abort_reason"], "foreground_wait_timeout")
        self.assertEqual(attempt["process_return_code"], 1)
        self.assertEqual(attempt["rendered_frames"], 0)
        self.assertEqual(attempt["timed_render_frames"], 0)
        self.assertTrue(attempt["raw_report_retained"])
        self.assertEqual(attempt["provenance"]["tier"], 276)
        self.assertTrue(Path(attempt["raw_report_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
