"""Offline SRT/VTT/Markdown utilities. No recognition or translation is performed."""
from dataclasses import dataclass
import re

@dataclass
class Cue:
    start: float
    end: float
    text: str
    settings: str = ''

def seconds(s):
    value = s.replace(',', '.')
    if not re.fullmatch('(?:\\d{2,}:)?[0-5]\\d:[0-5]\\d\\.\\d{3}', value):
        raise ValueError('Invalid subtitle timestamp: ' + s)
    parts = value.split(':')
    if len(parts) == 2:
        parts.insert(0, '00')
    h, m, x = parts
    return int(h) * 3600 + int(m) * 60 + float(x)

def timestamp(t, comma=False):
    n = round(t * 1000)
    return f'{n // 3600000:02}:{n // 60000 % 60:02}:{n // 1000 % 60:02}' + (',' if comma else '.') + f'{n % 1000:03}'

def parse(text):
    cues = []
    for block in re.split('\\r?\\n\\s*\\r?\\n', text.strip()):
        lines = block.splitlines()
        if not lines or lines[0].startswith(('WEBVTT', 'NOTE')):
            continue
        idx = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if idx is None:
            continue
        a, b = lines[idx].strip().strip('*').split('-->')
        parts = b.strip().split(maxsplit=1)
        cues.append(Cue(seconds(a.strip()), seconds(parts[0]), '\n'.join((x.rstrip() for x in lines[idx + 1:])), parts[1] if len(parts) > 1 else ''))
    validate(cues)
    return cues

def validate(cues):
    import math
    previous = 0
    for c in cues:
        if not math.isfinite(c.start) or not math.isfinite(c.end) or c.start < 0 or (c.end <= c.start) or (c.start < previous - 1e-06):
            raise ValueError('Invalid, overlapping or unsorted cue')
        previous = c.end

def shift(cues, delta, from_time=0):
    out = [Cue(c.start + delta if c.start >= from_time else c.start, c.end + delta if c.start >= from_time else c.end, c.text, c.settings) for c in cues]
    validate(out)
    return out

def render(cues, format='vtt'):
    if format not in ('vtt', 'srt', 'md'):
        raise ValueError('Unsupported format')
    validate(cues)
    blocks = []
    for i, c in enumerate(cues, 1):
        header = f"{timestamp(c.start, format == 'srt')} --> {timestamp(c.end, format == 'srt')}"
        if format == 'vtt' and c.settings:
            header += ' ' + c.settings
        blocks.append((str(i) + '\n' if format == 'srt' else '') + header + '\n' + c.text)
    return ('WEBVTT\n\n' if format == 'vtt' else '') + '\n\n'.join(blocks) + '\n'
