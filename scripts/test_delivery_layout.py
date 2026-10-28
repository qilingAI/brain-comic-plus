import unittest

from delivery_layout import display_line, vertical_layout


class LayoutTests(unittest.TestCase):
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
