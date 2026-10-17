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


if __name__ == "__main__":
    unittest.main()
