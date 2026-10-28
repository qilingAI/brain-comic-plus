"""Shared display rules for the vertical video composition."""


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
