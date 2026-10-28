import unittest

from delivery_layout import display_line, sample_typography, vertical_layout


class LayoutTests(unittest.TestCase):
    def test_typography_keeps_compact_spacing_and_larger_highlights(self):
        for seed in range(60):
            p = sample_typography(seed)
            self.assertTrue(56 <= p['body_size'] <= 64)
            self.assertTrue(68 <= p['highlight_size'] <= 82)
            self.assertTrue(1.2 <= p['highlight_size'] / p['body_size'] <= 1.3)
            self.assertTrue(8 <= p['body_gap'] <= 14)
            self.assertTrue(12 <= p['highlight_top_gap'] <= 20)
            self.assertTrue(12 <= p['highlight_bottom_gap'] <= 20)
            self.assertTrue(32 <= p['bottom_margin'] <= 48)

    def test_typography_samples_all_palettes_and_can_be_reproduced(self):
        samples = [sample_typography(seed) for seed in range(60)]
        self.assertEqual(len({p['body_color'] for p in samples}), 3)
        self.assertEqual(len({p['highlight_palette']['name'] for p in samples}), 3)
        self.assertGreater(len({p['body_size'] for p in samples}), 1)
        self.assertEqual(sample_typography(29), sample_typography(29))
        for p in samples:
            self.assertNotEqual(p['highlight_palette']['fill'], p['highlight_palette']['stroke'])
            self.assertEqual(p['highlight_stroke_width'], 5)
            self.assertEqual(p['outer_dark_edge_width'], 2)

    def test_square_video_fills_width_without_cropping(self):
        layout = vertical_layout(720, 720)
        self.assertEqual(layout["video_rect"], [0, 840, 1080, 1080])
        self.assertEqual(layout["upper_region"], [0, 0, 1080, 840])

    def test_video_height_follows_source_proportions(self):
        layout = vertical_layout(900, 800)
        self.assertEqual(layout["video_rect"], [0, 960, 1080, 960])

    def test_strip_only_one_final_comma_or_period(self):
        for value in ("开门，", "开门。", "开门,", "开门."):
            self.assertEqual(display_line(value), "开门")
        self.assertEqual(display_line("开门，。"), "开门，")
        self.assertEqual(display_line("开门。  "), "开门")

    def test_keep_questions_exclamations_and_internal_punctuation(self):
        for value in ("开门？", "开门！", "开门?", "开门!", "开门……", ""):
            self.assertEqual(display_line(value), value)
        self.assertEqual(display_line("门未开，军队停下。"), "门未开，军队停下")

    def test_no_text_space_or_bad_dimensions_raise(self):
        for dims in ((0, 720), (720, -1), (1080, 1920)):
            with self.assertRaises(ValueError):
                vertical_layout(*dims)


if __name__ == "__main__":
    unittest.main()
