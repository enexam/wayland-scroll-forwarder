import unittest

from scroll_forwarder import AxisFrame, WheelNormalizer, parse_args


class WheelNormalizerTests(unittest.TestCase):
    def test_legacy_event(self):
        normalizer = WheelNormalizer()
        self.assertEqual(normalizer.steps("vertical", AxisFrame(legacy=-2, saw_legacy=True)), -2)

    def test_paired_events_are_not_doubled(self):
        normalizer = WheelNormalizer()
        frame = AxisFrame(legacy=1, hi_res=120, saw_legacy=True, saw_hi_res=True)
        self.assertEqual(normalizer.steps("vertical", frame), 1)

    def test_high_resolution_events_accumulate(self):
        normalizer = WheelNormalizer()
        partial = AxisFrame(hi_res=40, saw_hi_res=True)
        self.assertEqual(normalizer.steps("vertical", partial), 0)
        self.assertEqual(normalizer.steps("vertical", partial), 0)
        self.assertEqual(normalizer.steps("vertical", partial), 1)

    def test_axes_have_independent_remainders(self):
        normalizer = WheelNormalizer()
        partial = AxisFrame(hi_res=-60, saw_hi_res=True)
        self.assertEqual(normalizer.steps("vertical", partial), 0)
        self.assertEqual(normalizer.steps("horizontal", partial), 0)
        self.assertEqual(normalizer.steps("vertical", partial), -1)
        self.assertEqual(normalizer.steps("horizontal", partial), -1)


class ArgumentTests(unittest.TestCase):
    def test_required_runtime_values_parse(self):
        args = parse_args(["GeForceNOW", "--device", "/dev/input/event7", "--allow-unfocused"])
        self.assertEqual(args.window_class, "GeForceNOW")
        self.assertEqual(args.device, "/dev/input/event7")
        self.assertTrue(args.allow_unfocused)


if __name__ == "__main__":
    unittest.main()
