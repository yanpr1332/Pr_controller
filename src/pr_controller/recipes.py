"""Reusable native-keyframe plans. Rendering PDF pages and shadows stays external."""

def fade(duration, fade_in=0.4, fade_out=0.4):
    if duration <= 0 or min(fade_in, fade_out) < 0 or fade_in + fade_out > duration:
        raise ValueError('Invalid fade durations')
    keys = [{'seconds': 0, 'value': 0}, {'seconds': fade_in, 'value': 100}, {'seconds': duration - fade_out, 'value': 100}, {'seconds': duration, 'value': 0}]
    return {'component': 'AE.ADBE Opacity', 'index': 0, 'keys': keys}

def pan_zoom(duration, start_position=(0.5, 0.5), end_position=(0.5, 0.5), start_scale=100, end_scale=103):
    if duration <= 0 or min(start_scale, end_scale) <= 0:
        raise ValueError('Invalid pan/zoom')
    return [{'component': 'AE.ADBE Motion', 'index': 0, 'keys': [{'seconds': 0, 'value': list(start_position)}, {'seconds': duration, 'value': list(end_position)}]}, {'component': 'AE.ADBE Motion', 'index': 1, 'keys': [{'seconds': 0, 'value': start_scale}, {'seconds': duration, 'value': end_scale}]}]

def photo_wall(items, duration, *, columns=3, stagger=0.3, margin=0.04):
    """Return normalized centers and staggered entries; caller applies contain-fit."""
    import math
    if not items or columns < 1 or duration <= 0 or (not 0 <= margin < 0.5):
        raise ValueError('Invalid wall')
    rows = math.ceil(len(items) / columns)
    out = []
    for i, item in enumerate(items):
        start = i * stagger
        if start + 0.4 >= duration:
            raise ValueError('Not enough wall display time')
        out.append({'item': item, 'start': start, 'end': duration, 'track': i + 1, 'position': [(i % columns + 0.5) / columns, (i // columns + 0.5) / rows], 'box': [(1 - 2 * margin) / columns, (1 - 2 * margin) / rows]})
    return out

def page_fan(items, *, center=(0.65, 0.5), angle_step=5, offset=0.045):
    if not items:
        raise ValueError('At least one page is required')
    mid = (len(items) - 1) / 2
    return [{'item': x, 'track': i + 1, 'position': [center[0] + (i - mid) * offset, center[1]], 'rotation': (i - mid) * angle_step} for i, x in enumerate(items)]
