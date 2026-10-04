"""Behavioral cases traced to upstream Player/Steps, not a visual-parity claim.

Upstream revision 76a24da5f74daa4f1587d1cb8ef2d027f163d631:
packages/core/src/app/components/player.tsx:96-125, 322-330
packages/core/src/app/lib/step-context.tsx:183-227
packages/core/src/app/components/slide-canvas.tsx:31-47
"""

import math
import unittest

from openslide_tk.navigation import Navigator, fit_canvas


class NavigationTests(unittest.TestCase):
    def test_direct_entry_matches_upstream_jump_reveals_all_steps(self):
        navigation = Navigator([0, 3, 2], 1)
        self.assertEqual((navigation.index, navigation.revealed, navigation.direction), (1, 3, "jump"))

    def test_forward_reveals_then_advances_and_backward_hides_then_retreats(self):
        navigation = Navigator([0, 2, 0])
        expected = [(1, 0), (1, 1), (1, 2), (2, 0), (1, 2), (1, 1), (1, 0), (0, 0)]
        operations = ["next"] * 4 + ["previous"] * 4
        for operation, state in zip(operations, expected):
            with self.subTest(operation=operation, state=state):
                self.assertTrue(getattr(navigation, operation)())
                self.assertEqual((navigation.index, navigation.revealed), state)

    def test_home_end_follow_numeric_delta_not_button_name(self):
        navigation = Navigator([1, 2, 3])
        navigation.jump(2)
        self.assertEqual((navigation.revealed, navigation.direction), (3, "jump"))
        navigation.jump(0)
        self.assertEqual((navigation.revealed, navigation.direction), (1, "jump"))
        navigation.jump(1)
        self.assertEqual((navigation.revealed, navigation.direction), (0, "forward"))
        navigation.jump(2)
        self.assertEqual((navigation.revealed, navigation.direction), (0, "forward"))
        navigation.jump(1)
        self.assertEqual((navigation.revealed, navigation.direction), (2, "backward"))

    def test_boundary_page_still_allows_step_changes(self):
        navigation = Navigator([2])
        self.assertFalse(navigation.next())
        self.assertTrue(navigation.previous())
        self.assertTrue(navigation.previous())
        self.assertFalse(navigation.previous())
        self.assertTrue(navigation.next())
        self.assertEqual((navigation.index, navigation.revealed), (0, 1))

    def test_jump_clamps_and_same_page_keeps_current_step(self):
        navigation = Navigator([2, 3])
        navigation.previous()
        self.assertFalse(navigation.jump(-100))
        self.assertEqual((navigation.index, navigation.revealed), (0, 1))
        navigation.jump(100)
        self.assertEqual((navigation.index, navigation.revealed), (1, 0))
        self.assertFalse(navigation.jump(100))

    def test_empty_deck_rejected(self):
        with self.assertRaises(ValueError):
            Navigator([])


class CanvasFitTests(unittest.TestCase):
    def test_letterboxing_matches_upstream_min_scale(self):
        scale, left, top = fit_canvas(1000, 1000)
        self.assertAlmostEqual(scale, 1000 / 1920)
        self.assertAlmostEqual(left, 0)
        self.assertAlmostEqual(top, 218.75)
        self.assertEqual(fit_canvas(3840, 2160), (2, 0, 0))
        self.assertEqual(fit_canvas(1920, 2160), (1, 0, 540))

    def test_custom_canvas_keeps_its_aspect_ratio(self):
        self.assertEqual(fit_canvas(1000, 500, 1000, 1000), (.5, 250, 0))

    def test_hidden_or_invalid_size_never_divides_by_zero(self):
        for dimensions in [(0, 100), (100, 0), (-1, 100), (100, 100, 0, 1080)]:
            with self.subTest(dimensions=dimensions):
                self.assertEqual(fit_canvas(*dimensions), (0, 0, 0))

    def test_nonfinite_sizes_are_rejected_or_return_finite_safe_values(self):
        for bad in [math.nan, math.inf, -math.inf]:
            for position in range(4):
                dimensions = [1920, 1080, 1920, 1080]
                dimensions[position] = bad
                with self.subTest(bad=bad, position=position):
                    try:
                        result = fit_canvas(*dimensions)
                    except ValueError:
                        continue
                    self.assertTrue(all(math.isfinite(value) for value in result), result)


if __name__ == "__main__":
    unittest.main()
