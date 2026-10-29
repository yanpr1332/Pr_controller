"""Registered subtitle sources, without pretending clip names are caption text."""
import json, uuid
from pathlib import Path
from .subtitles import Cue, parse, render, shift

def register(controller, source, *, sequence=None, offset=0, import_track=False):
    source = Path(source)
    cues = shift(parse(source.read_text(encoding='utf-8-sig')), offset)
    info = controller.invoke('resolve_sequence', sequence=sequence)
    ident = uuid.uuid4().hex
    folder = controller.runtime / 'caption_sources' / info['id']
    folder.mkdir(parents=True, exist_ok=True)
    subtitle = folder / (ident + '.srt')
    subtitle.write_text(render(cues, 'srt'), encoding='utf-8-sig')
    imported = False
    if import_track:
        result = controller.invoke('caption_import', sequence=info['id'], path=str(subtitle.resolve()))
        if not result['created']:
            raise RuntimeError('Premiere did not create the caption track')
        imported = True
    data = {'id': ident, 'sequence': info, 'source': str(source.resolve()), 'native_track_imported': imported, 'authority': 'registered subtitle source; manual PR edits are not reflected', 'cues': [vars(c) for c in cues]}
    (folder / (ident + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data

def load(controller, ident, *, sequence=None):
    if not __import__('re').fullmatch('[0-9a-f]{32}', ident):
        raise ValueError('Invalid caption source ID')
    info = controller.invoke('resolve_sequence', sequence=sequence)
    file = controller.runtime / 'caption_sources' / info['id'] / (ident + '.json')
    return (file, json.loads(file.read_text(encoding='utf-8')))

def export(controller, ident, destination, *, sequence=None, format='vtt', delta=0, from_time=0):
    _, data = load(controller, ident, sequence=sequence)
    cues = shift([Cue(**r) for r in data['cues']], delta, from_time)
    dest = Path(destination)
    if dest.exists():
        raise FileExistsError(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render(cues, format), encoding='utf-8')
    return {'path': str(dest), 'origin': data['authority'], 'count': len(cues), 'offset': delta, 'native_track_changed': False}
