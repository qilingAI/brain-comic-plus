"""Shared display rules for the vertical video composition."""
import json
import math
from pathlib import Path
import random


def sample_typography(seed=None):
    """Sample once per video; persist this result and reuse it on render retries."""
    config = json.loads((Path(__file__).resolve().parents[1] / 'references/typography.json').read_text())
    rng = random.Random(seed)
    body_size = rng.randint(*config['body_size'])
    minimum = max(config['highlight_size'][0], math.ceil(body_size * config['highlight_scale'][0]))
    maximum = min(config['highlight_size'][1], math.floor(body_size * config['highlight_scale'][1]))
    palette = rng.choice(config['highlight_palettes'])
    return dict(
        body_size=body_size, highlight_size=rng.randint(minimum, maximum),
        body_gap=rng.randint(*config['body_gap']),
        highlight_top_gap=rng.randint(*config['highlight_top_gap']),
        highlight_bottom_gap=rng.randint(*config['highlight_bottom_gap']),
        bottom_margin=rng.randint(*config['bottom_margin']),
        body_color=rng.choice(config['body_colors']), highlight_palette=palette,
        body_stroke_width=config['body_stroke_width'],
        highlight_stroke_width=config['highlight_stroke_width'],
        outer_dark_edge_width=config['outer_dark_edge_width'],
        dark_edge_color=config['dark_edge_color'],
        highlight_glyph_expansion=rng.randint(*config['highlight_glyph_expansion']))


def display_line(text):
    """Remove only a final comma or period, keeping the manuscript unchanged."""
    text = text.rstrip()
    return text[:-1] if text.endswith(("，", "。", ",", ".")) else text


def vertical_layout(source_width, source_height, width=1080, height=1920):
    if any(type(n) is not int or n <= 0 for n in (source_width, source_height, width, height)):
        raise ValueError("素材与画布尺寸须为正整数")
    video_height = round(width * source_height / source_width / 2) * 2
    upper_height = height - video_height
    if video_height <= 0 or upper_height <= 0:
        raise ValueError("素材等比铺满宽度后没有文字空间，需要另外确定布局")
    return dict(canvas=[width, height], upper_region=[0, 0, width, upper_height],
                video_rect=[0, upper_height, width, video_height])
