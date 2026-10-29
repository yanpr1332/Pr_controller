import argparse, json, sys
from pathlib import Path
from .client import PremiereController, Config

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description='Premiere controller')
    p.add_argument('--runtime')
    p.add_argument('--premiere-exe')
    sub = p.add_subparsers(dest='command', required=True)
    for name in ['doctor', 'install', 'status', 'save', 'capabilities']:
        sub.add_parser(name)
    for name in ['new-project', 'open-project']:
        q = sub.add_parser(name)
        q.add_argument('path')
    q = sub.add_parser('create-bin')
    q.add_argument('name')
    q = sub.add_parser('connect')
    q.add_argument('--launch', action='store_true')
    q = sub.add_parser('timeline')
    q.add_argument('--sequence')
    q = sub.add_parser('invoke')
    q.add_argument('operation')
    q.add_argument('--args', default='{}')
    q.add_argument('--args-file')
    q.add_argument('--timeout', type=float, default=90)
    for name in ['job-status', 'cancel-queued']:
        q = sub.add_parser(name)
        q.add_argument('id')
    q = sub.add_parser('subtitles')
    q.add_argument('source')
    q.add_argument('destination')
    q.add_argument('--format', choices=['srt', 'vtt', 'md'], default='vtt')
    q.add_argument('--offset', type=float, default=0)
    q.add_argument('--from-time', type=float, default=0)
    a = p.parse_args()
    config = Config()
    if a.runtime:
        config.runtime = Path(a.runtime)
    c = PremiereController(a.premiere_exe, config=config)
    try:
        if a.command == 'doctor':
            r = c.doctor()
        elif a.command == 'install':
            r = c.install_bridge()
        elif a.command == 'connect':
            r = c.connect(launch=a.launch)
        elif a.command == 'new-project':
            r = c.new_project(a.path)
        elif a.command == 'open-project':
            r = c.open_project(a.path)
        elif a.command == 'save':
            r = c.save_project()
        elif a.command == 'create-bin':
            r = c.create_bin(a.name)
        elif a.command == 'timeline':
            r = c.timeline(a.sequence)
        elif a.command == 'capabilities':
            r = c.capabilities()
        elif a.command == 'job-status':
            r = c.job_status(a.id)
        elif a.command == 'cancel-queued':
            r = c.cancel_queued(a.id)
        elif a.command == 'invoke':
            r = c._request(a.operation, json.loads(Path(a.args_file).read_text(encoding='utf-8-sig') if a.args_file else a.args), a.timeout)
        elif a.command == 'subtitles':
            from .subtitles import parse, shift, render
            dest = Path(a.destination)
            if dest.exists():
                raise FileExistsError(dest)
            cues = shift(parse(Path(a.source).read_text(encoding='utf-8-sig')), a.offset, a.from_time)
            dest.write_text(render(cues, a.format), encoding='utf-8')
            r = {'path': str(dest), 'cues': len(cues)}
        else:
            r = c.status()
        print(json.dumps(r, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
