from pathlib import Path
import hashlib, json, shutil

def collect(timelines, destination, *, dry_run=True):
    """Collect referenced files without changing a project. Manifest enables explicit relinking."""
    paths = set()
    for timeline in timelines:
        for kind in ('video', 'audio'):
            for track in timeline.get(kind, []):
                for clip in track['clips']:
                    if clip.get('path'):
                        paths.add(clip['path'])
    rows = []
    for source in sorted(paths):
        p = Path(source)
        if not p.is_file():
            raise FileNotFoundError(p)
        name = hashlib.sha256(str(p.resolve()).encode()).hexdigest()[:12] + '_' + p.name
        rows.append({'source': str(p.resolve()), 'relative': 'media/' + name, 'bytes': p.stat().st_size})
    report = {'files': rows, 'total_bytes': sum((x['bytes'] for x in rows)), 'project_modified': False}
    if not dry_run:
        dest = Path(destination)
        if dest.exists():
            raise FileExistsError('Use a new destination to avoid overwriting files')
        (dest / 'media').mkdir(parents=True)
        for row in rows:
            shutil.copy2(row['source'], dest / row['relative'])
        (dest / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report

def probe(source, *, ffprobe='ffprobe', wsl=False):
    import subprocess
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'):
        try:
            from PIL import Image, ImageOps
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image)
                return {'kind': 'image', 'width': image.width, 'height': image.height, 'pixel_aspect': 1, 'path': str(path.resolve())}
        except ImportError:
            pass
    value = str(path.resolve())
    if wsl:
        if not path.resolve().drive:
            raise ValueError('WSL probe expects a local Windows drive path')
        value = '/mnt/' + path.resolve().drive[0].lower() + path.resolve().as_posix()[2:]
    command = ['wsl.exe', '-d', 'Debian', '--', '/usr/bin/ffprobe'] if wsl else [ffprobe]
    result = subprocess.run(command + ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', value], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    if result.returncode:
        raise RuntimeError('Media probe failed: ' + result.stderr[-1000:])
    return json.loads(result.stdout)
