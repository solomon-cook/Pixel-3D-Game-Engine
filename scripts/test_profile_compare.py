import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import profile_compare


class ProfileCompareTests(unittest.TestCase):
    def test_percentiles_use_nearest_rank(self):
        self.assertEqual(profile_compare.percentile([4.0, 1.0, 3.0, 2.0], 0.5), 2.0)
        self.assertEqual(profile_compare.percentile([4.0, 1.0, 3.0, 2.0], 0.95), 4.0)
        self.assertIsNone(profile_compare.percentile([], 0.95))

    def test_missing_stage_samples_do_not_shift_pair_alignment(self):
        self.assertEqual(
            profile_compare.paired_deltas([2.0, None, 8.0], [3.0, 7.0, None]),
            [1.0],
        )

    def test_summary_keeps_sample_count(self):
        self.assertEqual(
            profile_compare.summarize([2.0, 4.0]),
            {"median_ms": 2.0, "p95_ms": 4.0, "samples": 2},
        )

    def test_scene_asset_paths_resolve_glb_paths_from_scene_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "models").mkdir()
            model = root / "models" / "tree.glb"
            model.write_bytes(b"test glb payload")
            scene = root / "scene.json"
            scene.write_text(json.dumps({
                "objects": [
                    {"geometry": {"kind": "glb", "path": "models/tree.glb"}},
                    {"geometry": {"kind": "sphere"}},
                    {"geometry": {"kind": "glb", "path": ""}},
                ]
            }))

            self.assertEqual(profile_compare.scene_asset_paths(scene), [model.resolve()])

    def test_scene_route_ids_keep_only_string_ids_in_scene_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            scene = Path(temporary) / "scene.json"
            scene.write_text(json.dumps({
                "routes": [{"id": "orbit"}, {"name": "missing"}, {"id": 4}, {"id": "closeup"}]
            }))

            self.assertEqual(profile_compare.scene_route_ids(scene), ["orbit", "closeup"])

    def test_fingerprints_cover_nested_files_and_hash_their_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "nested"
            nested.mkdir()
            first = root / "scene.json"
            second = nested / "shader.wgsl"
            first.write_text("{}\n")
            second.write_text("fn main() {}\n")

            report = profile_compare.fingerprints([root])

            self.assertEqual(set(report), {str(first), str(second)})
            self.assertEqual(report[str(first)], hashlib.sha256(first.read_bytes()).hexdigest())
            self.assertEqual(report[str(second)], hashlib.sha256(second.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
