from __future__ import annotations
import json, os, re, subprocess, time, uuid
from dataclasses import dataclass, field
from pathlib import Path
from ._legacy import PremiereController as Legacy

class NativeError(RuntimeError):
    pass

@dataclass
class Config:
    premiere_exe: Path = field(default_factory=lambda: Path(os.environ.get('PREMIERE_EXE', 'D:\\computer\\Adobe\\Premiere Pro\\Adobe Premiere Pro 2026\\Adobe Premiere Pro.exe')))
    runtime: Path = field(default_factory=lambda: Path(os.environ.get('PR_CONTROLLER_RUNTIME', str(Path.home() / 'AppData/Local/PrController/runtime'))))

def ticks(seconds):
    import math
    if not math.isfinite(float(seconds)):
        raise ValueError('Nonfinite time')
    return str(round(float(seconds) * 254016000000))

def frame_ticks(frames, fps='30'):
    from fractions import Fraction
    rate = Fraction(str(fps))
    if rate <= 0:
        raise ValueError('Frame rate must be positive')
    return str(round(Fraction(frames) * 254016000000 / rate))

class PremiereController(Legacy):
    """93 legacy operations plus a job-based native API. Construction never modifies Adobe."""

    def __init__(self, premiere_exe=None, *, config=None):
        self.config = config or Config()
        self.premiere_exe = Path(premiere_exe or self.config.premiere_exe).expanduser().resolve()
        self.runtime = Path(self.config.runtime).expanduser().resolve()

    def install_bridge(self):
        if not self.premiere_exe.is_file():
            raise FileNotFoundError(self.premiere_exe)
        self.runtime.mkdir(parents=True, exist_ok=True)
        source = Path(__file__).resolve().parent / 'native' / 'runner.jsx'
        text = source.read_text(encoding='utf-8-sig').replace('__RUNTIME__', json.dumps(self.runtime.as_posix())).replace('__NATIVE__', json.dumps(source.parent.as_posix()))
        target = self.premiere_exe.parent / 'Scripts/Startup/98_pr_controller_v2.jsx'
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_text(encoding='utf-8-sig') != text:
            target.with_suffix('.jsx.bak').write_bytes(target.read_bytes())
        target.write_text(text, encoding='utf-8-sig')
        return {'startup': str(target), 'restart_required': 'Open Premiere after installing; no processes were stopped.'}

    def doctor(self):
        heartbeat = self.runtime / 'heartbeat.json'
        return {'executable_exists': self.premiere_exe.is_file(), 'startup_installed': (self.premiere_exe.parent / 'Scripts/Startup/98_pr_controller_v2.jsx').exists(), 'bridge_recent': heartbeat.exists() and time.time() - heartbeat.stat().st_mtime < 10, 'runtime': str(self.runtime)}

    def _request(self, operation, args, timeout=90):
        ident = self.submit(operation, args)
        response = self.runtime / (ident + '.result.json')
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if (self.runtime / (ident + '.cancelled.json')).exists():
                raise NativeError('Job cancelled before execution: ' + ident)
            if response.exists():
                r = json.loads(response.read_text(encoding='utf-8-sig'))
                if r.get('id') != ident or not r.get('complete'):
                    raise NativeError('Invalid task response')
                if not r.get('ok'):
                    raise NativeError(json.dumps(r, ensure_ascii=False))
                return r['data']
            time.sleep(0.1)
        raise TimeoutError(f'Job {ident} remains queued/running. Do not blindly resubmit. Runtime: {self.runtime}')

    def job_status(self, ident):
        if not re.fullmatch('[0-9a-f]{32}', ident):
            raise ValueError('Invalid job ID')
        f = self.runtime / (ident + '.result.json')
        if f.exists():
            return json.loads(f.read_text(encoding='utf-8-sig'))
        state = next((suffix for suffix in ('job', 'running', 'cancelled') if (self.runtime / (ident + '.' + suffix + '.json')).exists()), 'unknown')
        return {'id': ident, 'complete': state == 'cancelled', 'state': state, 'bridge_recent': self.doctor()['bridge_recent']}

    def cancel_queued(self, ident):
        self.job_status(ident)
        source = self.runtime / (ident + '.job.json')
        try:
            source.rename(self.runtime / (ident + '.cancelled.json'))
        except FileNotFoundError:
            raise NativeError('Job already claimed or completed; running jobs are not cancelled')
        return {'id': ident, 'state': 'cancelled'}

    def run(self, actions, *, restart=False, timeout=90):
        if restart:
            raise ValueError('Forced restart disabled; save and restart Premiere explicitly.')
        rows = self._request('legacy', {'actions': actions}, timeout) if actions else []
        for row in rows:
            if not isinstance(row['data'], str):
                row['data'] = json.dumps(row['data'], ensure_ascii=False)
        return rows

    def invoke(self, operation, **args):
        return self._request(operation, args)

    def _run_inline_jsx(self, source, label='inline'):
        source = re.sub('(\\w+)\\.openInTimeline\\(\\)', 'app.project.openSequence(\\1.sequenceID)', source)
        source = re.sub('function findItem\\(parent,name\\)\\{.*?\\n \\}', 'function findItem(parent,name){return resolveProjectItem(name,true);}', source, flags=re.S)
        selected = re.search('app\\.project\\.sequences\\[(\\d+)\\]', source)
        if selected:
            source = 'activate(app.project.sequences[' + selected.group(1) + ']);\n' + source
        value = self._request('eval', {'source': re.sub('^\\s*#target[^\\n]*', '', source, flags=re.M)})
        return [{'status': 'OK', 'op': 'eval_file', 'data': value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}]

    def run_script_file(self, path, *, restart=False):
        if restart:
            raise ValueError('Restart explicitly')
        return self._run_inline_jsx(Path(path).read_text(encoding='utf-8-sig'))

    def timeline(self, sequence=None):
        return self.invoke('timeline', sequence=sequence)

    def capabilities(self):
        return self.invoke('capabilities')

    def ensure_tracks(self, video=3, audio=3, *, sequence=None):
        if min(video, audio) < 0:
            raise ValueError('Invalid track count')
        return self._edit('ensure_tracks', dict(sequence=sequence, video=video, audio=audio), transactional=True, timeout=600)

    def inspect_native(self, track, clip, *, sequence=None, kind='video'):
        return self.invoke('components', sequence=sequence, track=track, clip=clip, kind=kind)

    @staticmethod
    def _compat(value):
        return [{'status': 'OK', 'op': 'native', 'data': json.dumps(value, ensure_ascii=False)}]

    def set_clip_property(self, component_match_name, property_index, value, *, track_type='video', track_index=0, clip_index=0, update_ui=True, restart=False, sequence=None):
        if restart:
            raise ValueError('Restart explicitly')
        return self._compat(self._edit('props', dict(sequence=sequence, kind=track_type, track=track_index, clip=clip_index, properties=[{'component': component_match_name, 'index': property_index, 'value': value}], update_ui=update_ui), transactional=True, timeout=600))

    def set_motion(self, *, position=None, scale=None, rotation=None, crop_left=None, crop_top=None, crop_right=None, crop_bottom=None, track_index=0, clip_index=0, restart=False, sequence=None, coordinate_space='normalized'):
        if restart:
            raise ValueError('Restart explicitly')
        if coordinate_space not in ('normalized', 'pixels'):
            raise ValueError('Invalid coordinate space')
        if position is not None and coordinate_space == 'pixels':
            st = self.timeline(sequence)
            position = [position[0] / st['width'], position[1] / st['height']]
        values = [(0, list(position) if position is not None else None), (1, scale), (4, rotation), (7, crop_left), (8, crop_top), (9, crop_right), (10, crop_bottom)]
        properties = [{'component': 'AE.ADBE Motion', 'index': i, 'value': v} for i, v in values if v is not None]
        return self._compat(self._edit('props', dict(sequence=sequence, kind='video', track=track_index, clip=clip_index, properties=properties, update_ui=True), transactional=True, timeout=600))

    def set_opacity(self, value, *, track_index=0, clip_index=0, restart=False, sequence=None):
        if not 0 <= value <= 100:
            raise ValueError('Opacity must be 0..100')
        return self.set_clip_property('AE.ADBE Opacity', 0, value, track_index=track_index, clip_index=clip_index, restart=restart, sequence=sequence)

    def set_opacity_keyframes(self, keys, *, track_index=0, clip_index=0, restart=False, sequence=None, time_space='source'):
        if restart:
            raise ValueError('Restart explicitly')
        return self._compat(self.animate(track_index, clip_index, [{'component': 'AE.ADBE Opacity', 'index': 0, 'keys': [{'seconds': t, 'value': v} for t, v in keys]}], sequence=sequence, time_space=time_space))

    def set_track_mute(self, track_type, track_index, muted, *, restart=False, sequence=None):
        if restart:
            raise ValueError('Restart explicitly')
        return self._compat(self._edit('track_state', dict(sequence=sequence, kind=track_type, track=track_index, muted=bool(muted)), transactional=True, timeout=600))

    def set_track_lock(self, track_type, track_index, locked, *, restart=False, sequence=None):
        if restart:
            raise ValueError('Restart explicitly')
        return self._compat(self._edit('track_state', dict(sequence=sequence, kind=track_type, track=track_index, locked=bool(locked)), transactional=True, timeout=600))

    def clone_av(self, track, clip, target_track, target_audio_track, *, sequence=None, move=False, copy_transitions=True):
        return self._edit('clone_av', dict(sequence=sequence, track=track, clip=clip, target_track=target_track, target_audio_track=target_audio_track, move=move, copy_transitions=copy_transitions), transactional=True)

    def configure_sequence(self, sequence=None, *, width=1920, height=1080, fps=30):
        if min(width, height, fps) <= 0:
            raise ValueError('Positive dimensions and frame rate required')
        return self._edit('settings', dict(sequence=sequence, width=width, height=height, fps=fps), transactional=True, timeout=600)

    def place_media(self, item, at, *, source_in=0, source_out, sequence=None, video_track=0, audio_track=0, media='both', mode='overwrite', allow_overlap=False):
        if source_out <= source_in or source_in < 0 or at < 0:
            raise ValueError('Invalid media range')
        if media not in ('both', 'video', 'audio') or mode not in ('insert', 'overwrite'):
            raise ValueError('Invalid placement mode')
        return self._edit('place', dict(item=item, at=at, source_in=source_in, source_out=source_out, sequence=sequence, video_track=video_track, audio_track=audio_track, media=media, mode=mode, allow_overlap=allow_overlap), transactional=True, timeout=600)

    def shift_timeline(self, at, delta, *, sequence=None, dry_run=True):
        return self._edit('shift', dict(sequence=sequence, at=at, delta=delta, dry_run=dry_run), transactional=not dry_run)

    def fit_clip(self, track, clip, *, sequence=None, mode='contain', source_width, source_height, pixel_aspect=1):
        if mode not in ('contain', 'cover') or min(source_width, source_height, pixel_aspect) <= 0:
            raise ValueError('Invalid fit')
        return self.invoke('fit', sequence=sequence, track=track, clip=clip, mode=mode, source_width=source_width, source_height=source_height, pixel_aspect=pixel_aspect)

    def animate(self, track, clip, properties, *, sequence=None, time_space='clip', ease=False):
        if time_space not in ('clip', 'source', 'sequence'):
            raise ValueError('Invalid time space')
        from copy import deepcopy
        properties = deepcopy(properties)
        for prop in properties:
            keys = prop['keys']
            if any((a['seconds'] >= b['seconds'] for a, b in zip(keys, keys[1:]))):
                raise ValueError('Keys must be strictly ordered')
            if ease:

                def mix(a, b, t):
                    if isinstance(a, list) and isinstance(b, list) and (len(a) == len(b)):
                        return [mix(x, y, t) for x, y in zip(a, b)]
                    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                        return a + (b - a) * t
                    raise ValueError('Easing requires numeric scalars or arrays')
                expanded = []
                for a, b in zip(keys, keys[1:]):
                    for i in range(16):
                        t = i / 16
                        e = t * t * (3 - 2 * t)
                        expanded.append({'seconds': a['seconds'] + (b['seconds'] - a['seconds']) * t, 'value': mix(a['value'], b['value'], e)})
                if keys:
                    expanded.append(keys[-1])
                prop['keys'] = expanded
        return self._edit('animate', dict(sequence=sequence, track=track, clip=clip, properties=properties, time_space=time_space, ease=False), transactional=True, timeout=600)

    def relink(self, item, path, *, sequence=None, dry_run=True):
        return self._edit('relink', dict(item=item, path=str(Path(path).resolve()), sequence=sequence, dry_run=dry_run), transactional=not dry_run, timeout=600)

    def clone_or_move(self, track, clip, target_track, *, sequence=None, move=False, copy_transitions=True):
        return self._edit('clone', dict(sequence=sequence, track=track, clip=clip, target_track=target_track, move=move, copy_transitions=copy_transitions), transactional=True)

    def clone_video_clip_to_track(self, target_video_track_index, *, sequence_index=None, source_video_track_index=0, clip_index=0):
        return self._compat(self.clone_or_move(source_video_track_index, clip_index, target_video_track_index, sequence=sequence_index))

    def move_video_clip_to_track(self, target_video_track_index, *, sequence_index=None, source_video_track_index=0, clip_index=0):
        return self._compat(self.clone_or_move(source_video_track_index, clip_index, target_video_track_index, sequence=sequence_index, move=True))

    def export_direct(self, output, preset, *, sequence=None, timeout=1800):
        return self._request('export', {'sequence': sequence, 'output': str(Path(output).resolve()), 'preset': str(Path(preset).resolve())}, timeout)

    def preview(self, output, time_seconds, *, sequence=None):
        return self.invoke('preview', sequence=sequence, output=str(Path(output).resolve()), time=time_seconds)

    def captions(self, *, sequence=None, shift=0, from_time=0, dry_run=True):
        return self.invoke('captions', sequence=sequence, shift=shift, from_time=from_time, dry_run=dry_run)

    def clone_group(self, indices, target_track, *, sequence=None, source_track=0, target_audio_track=None, move=False, copy_transitions=True):
        return self._edit('clone_group', dict(sequence=sequence, indices=sorted(set(indices)), track=source_track, target_track=target_track, target_audio_track=target_audio_track, move=move, copy_transitions=copy_transitions), transactional=True, timeout=600)

    def clone_video_group_to_track(self, clip_indices, target_video_track_index, *, sequence_index=None, source_video_track_index=0, copy_transitions=True):
        return self._compat(self.clone_group(clip_indices, target_video_track_index, sequence=sequence_index, source_track=source_video_track_index, copy_transitions=copy_transitions))

    def move_video_group_to_track(self, clip_indices, target_video_track_index, *, sequence_index=None, source_video_track_index=0, copy_transitions=True):
        return self._compat(self.clone_group(clip_indices, target_video_track_index, sequence=sequence_index, source_track=source_video_track_index, move=True, copy_transitions=copy_transitions))

    def move_video_clips_to_track(self, clip_indices, target_video_track_index, *, sequence_index=None, source_video_track_index=0):
        return self.move_video_group_to_track(clip_indices, target_video_track_index, sequence_index=sequence_index, source_video_track_index=source_video_track_index)

    def clone_linked_av_to_tracks(self, target_video_track_index, target_audio_track_index, *, sequence_index=None, source_video_track_index=0, video_clip_index=0):
        return self._compat(self.clone_av(source_video_track_index, video_clip_index, target_video_track_index, target_audio_track_index, sequence=sequence_index))

    def move_linked_av_to_tracks(self, target_video_track_index, target_audio_track_index, *, sequence_index=None, source_video_track_index=0, video_clip_index=0):
        return self._compat(self.clone_av(source_video_track_index, video_clip_index, target_video_track_index, target_audio_track_index, sequence=sequence_index, move=True))

    def clone_linked_av_group_to_tracks(self, video_clip_indices, target_video_track_index, target_audio_track_index, *, sequence_index=None, source_video_track_index=0, copy_transitions=True):
        return self._compat(self.clone_group(video_clip_indices, target_video_track_index, sequence=sequence_index, source_track=source_video_track_index, target_audio_track=target_audio_track_index, copy_transitions=copy_transitions))

    def move_linked_av_group_to_tracks(self, video_clip_indices, target_video_track_index, target_audio_track_index, *, sequence_index=None, source_video_track_index=0, copy_transitions=True):
        return self._compat(self.clone_group(video_clip_indices, target_video_track_index, sequence=sequence_index, source_track=source_video_track_index, target_audio_track=target_audio_track_index, move=True, copy_transitions=copy_transitions))

    def move_linked_av_pairs_to_tracks(self, video_clip_indices, target_video_track_index, target_audio_track_index, *, sequence_index=None, source_video_track_index=0):
        return self.move_linked_av_group_to_tracks(video_clip_indices, target_video_track_index, target_audio_track_index, sequence_index=sequence_index, source_video_track_index=source_video_track_index)

    def build_photo_wall(self, items, duration, *, sequence=None, columns=3, stagger=0.3):
        from .recipes import photo_wall
        st = self.timeline(sequence)
        rows = photo_wall(items, duration, columns=columns, stagger=stagger)
        self._import_layout_media(items)
        plan = []
        for row in rows:
            item = row['item']
            scale = min(row['box'][0] * st['width'] / item['width'], row['box'][1] * st['height'] / item['height']) * 100
            d = row['end'] - row['start']
            properties = [{'component': 'AE.ADBE Motion', 'index': 0, 'keys': [{'seconds': 0, 'value': [row['position'][0], row['position'][1] + 0.03]}, {'seconds': 0.6, 'value': row['position']}, {'seconds': d, 'value': row['position']}]}, {'component': 'AE.ADBE Motion', 'index': 1, 'keys': [{'seconds': 0, 'value': scale * 0.97}, {'seconds': 0.6, 'value': scale}, {'seconds': d, 'value': scale * 1.01}]}, {'component': 'AE.ADBE Opacity', 'index': 0, 'keys': [{'seconds': 0, 'value': 0}, {'seconds': 0.5, 'value': 100}, {'seconds': d, 'value': 100}]}]
            plan.append(dict(item=item['item'], track=row['track'], start=row['start'], end=row['end'], properties=properties))
        return self._edit('build_layout', dict(sequence=sequence, plan=plan), transactional=True, timeout=600)

    def build_page_fan(self, items, duration, *, sequence=None, focus_index=None):
        from .recipes import page_fan
        if duration < 3:
            raise ValueError('Page fan needs at least 3 seconds')
        if focus_index is not None and (not 0 <= focus_index < len(items)):
            raise ValueError('Invalid focus index')
        st = self.timeline(sequence)
        rows = page_fan(items)
        self._import_layout_media(items)
        plan = []
        for i, row in enumerate(rows):
            item = row['item']
            scale = min(st['height'] * 0.72 / item['height'], st['width'] * 0.45 / item['width']) * 100
            pos = [{'seconds': 0, 'value': [0.65, 0.52]}, {'seconds': 1.2, 'value': row['position']}, {'seconds': duration, 'value': row['position']}]
            sc = [{'seconds': 0, 'value': scale * 0.97}, {'seconds': 1.2, 'value': scale}, {'seconds': duration, 'value': scale}]
            rot = [{'seconds': 0, 'value': 0}, {'seconds': 1.2, 'value': row['rotation']}, {'seconds': duration, 'value': row['rotation']}]
            opacity = [{'seconds': 0, 'value': 0}, {'seconds': 0.5, 'value': 100}, {'seconds': duration, 'value': 100}]
            if focus_index is not None:
                at = duration * 0.55
                if i == focus_index:
                    pos[-1:] = [{'seconds': at, 'value': row['position']}, {'seconds': at + 0.7, 'value': [0.65, 0.5]}, {'seconds': duration, 'value': [0.65, 0.5]}]
                    sc[-1:] = [{'seconds': at, 'value': scale}, {'seconds': at + 0.7, 'value': min(st['height'] * 0.9 / item['height'], st['width'] * 0.6 / item['width']) * 100}, {'seconds': duration, 'value': min(st['height'] * 0.9 / item['height'], st['width'] * 0.6 / item['width']) * 100}]
                    rot[-1:] = [{'seconds': at, 'value': row['rotation']}, {'seconds': at + 0.7, 'value': 0}, {'seconds': duration, 'value': 0}]
                else:
                    opacity[-1:] = [{'seconds': at, 'value': 100}, {'seconds': at + 0.7, 'value': 0}, {'seconds': duration, 'value': 0}]
            properties = [dict(component='AE.ADBE Motion', index=0, keys=pos), dict(component='AE.ADBE Motion', index=1, keys=sc), dict(component='AE.ADBE Motion', index=4, keys=rot), dict(component='AE.ADBE Opacity', index=0, keys=opacity)]
            plan.append(dict(item=item['item'], track=row['track'], start=0, end=duration, properties=properties))
        return self._edit('build_layout', dict(sequence=sequence, plan=plan), transactional=True, timeout=600)

    def register_subtitle_source(self, path, *, sequence=None, offset=0, import_track=False):
        from .caption_sources import register
        return register(self, path, sequence=sequence, offset=offset, import_track=import_track)

    def export_subtitle_source(self, source_id, destination, *, sequence=None, format='vtt', delta=0, from_time=0):
        from .caption_sources import export
        return export(self, source_id, destination, sequence=sequence, format=format, delta=delta, from_time=from_time)

    def connect(self, *, launch=False, timeout=30):
        if launch:
            if not self.premiere_exe.exists():
                raise FileNotFoundError(self.premiere_exe)
            subprocess.Popen([str(self.premiere_exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if self.doctor()['bridge_recent']:
                return self.capabilities()
            time.sleep(0.2)
        raise NativeError('Bridge unavailable. Install for this runtime and open Premiere. No process was terminated.')

    def backup_project(self, destination):
        return self.invoke('backup_project', destination=str(Path(destination).resolve()))

    def submit(self, operation, args=None):
        self.runtime.mkdir(parents=True, exist_ok=True)
        ident = uuid.uuid4().hex
        pending = self.runtime / (ident + '.job.json')
        tmp = pending.with_suffix('.tmp')
        tmp.write_text(json.dumps({'id': ident, 'operation': operation, 'args': args or {}, 'submitted': str(time.time_ns())}, ensure_ascii=True, allow_nan=False), encoding='utf-8')
        os.replace(tmp, pending)
        return ident

    def catalog(self):
        return self.invoke('catalog')

    def _import_layout_media(self, items):
        for item in items:
            if not item.get('item') or min(item.get('width', 0), item.get('height', 0)) <= 0:
                raise ValueError('Image descriptors require positive width/height')
        catalog = self.catalog()
        paths = []
        for item in items:
            ref = str(item['item'])
            if any((x['nodeId'] == ref or x['binPath'] == ref or x['name'] == ref or (x['path'].replace('\\', '/').lower() == ref.replace('\\', '/').lower()) for x in catalog)):
                continue
            path = Path(ref)
            if not path.is_file():
                raise FileNotFoundError(path)
            paths.append(str(path.resolve()))
        if paths:
            self.import_files(list(dict.fromkeys(paths)))

    def relink_clip_media(self, new_path, *, sequence_index=None, video_track_index=0, clip_index=0, override_checks=True):
        clip = self.timeline(sequence_index)['video'][video_track_index]['clips'][clip_index]
        return self._compat(self._edit('relink', dict(item=clip['nodeId'], path=str(Path(new_path).resolve()), sequence=sequence_index, dry_run=False, override_checks=override_checks), transactional=True, timeout=600))

    def add_video_effect(self, name, *, track_index=0, clip_index=0, restart=False, sequence=None):
        if restart:
            raise ValueError('Restart explicitly')
        return self._compat(self._edit('effect', dict(sequence=sequence, kind='video', name=name, track=track_index, clip=clip_index), transactional=True, timeout=600))

    def add_audio_effect(self, name, *, sequence_index=None, audio_track_index=0, clip_index=0, channel_type=0):
        return self._compat(self._edit('effect', dict(sequence=sequence_index, kind='audio', name=name, track=audio_track_index, clip=clip_index, channel_type=channel_type), transactional=True, timeout=600))

    def add_transition(self, name='Cross Dissolve', duration_tc='00:00:00:12', *, track_index=0, clip_index=0, incoming=False, restart=False, sequence=None):
        if restart:
            raise ValueError('Restart explicitly')
        return self._compat(self._edit('transition', dict(sequence=sequence, name=name, duration=duration_tc, track=track_index, clip=clip_index, incoming=incoming), transactional=True, timeout=600))

    def transaction(self, actions, *, save_after=False, timeout=600):
        return self._request('transaction', {'actions': actions, 'save_after': save_after}, timeout)

    def _edit(self, operation, args, *, transactional=False, timeout=90):
        if transactional:
            return self.transaction([{'operation': operation, 'args': args}], timeout=max(timeout, 600))['results'][0]
        return self._request(operation, args, timeout)

    def create_composition(self, name, background, duration, *, width=1920, height=1080, fps=30):
        if not name or duration <= 0:
            raise ValueError('Invalid composition')
        self._import_layout_media([background])
        return self._edit('compose', dict(name=name, background=background, duration=duration, width=width, height=height, fps=fps), transactional=True, timeout=600)

    def add_audio_transition(self, name, duration_tc='00:00:00:12', *, sequence_index=None, audio_track_index=0, clip_index=0, incoming=False, sequence=None):
        target = sequence if sequence is not None else sequence_index
        return self._compat(self._edit('transition', dict(sequence=target, kind='audio', name=name, duration=duration_tc, track=audio_track_index, clip=clip_index, incoming=incoming), transactional=True, timeout=600))
