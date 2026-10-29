# Premiere Controller

[中文](README.md) | English

A local automation controller for Adobe Premiere Pro on Windows. The Python package, bridge scripts, examples and tests are maintained separately from the Adobe installation. Version 0.2.0 has been tested in Premiere Pro **26.0.1**. Run capability checks and isolated tests before using it with another version.

## Requirements and installation

You need Windows, Python 3.10 or later, and an installed copy of Premiere Pro. The core package uses only the Python standard library. Install the optional `visual` dependencies for photo cards and PDF rendering.

Run these commands from the repository directory, replacing the executable path with your installation:

```powershell
python -m pip install -e ".[visual]"
$env:PREMIERE_EXE = 'D:\computer\Adobe\Premiere Pro\Adobe Premiere Pro 2026\Adobe Premiere Pro.exe'
pr-controller doctor
pr-controller install
```

Bridge installation is explicit: it writes a startup script into Premiere's Startup directory. Creating a Python controller object does not modify the Adobe installation. Save your work and restart Premiere after installing the bridge. The controller does not forcibly terminate Premiere.

The default runtime directory is `AppData/Local/PrController/runtime` under your Windows user profile. Override it with `PR_CONTROLLER_RUNTIME` or `Config(runtime=...)`. The development installation on this machine uses the repository's `runtime-v2` directory; use the same runtime when connecting to that instance. Run installation again after moving the repository so the startup script points to the new source location.

The obsolete legacy startup bridge has been removed from this machine. See [Local installation layout](docs/LOCAL_LAYOUT.md) for the archived fixtures and cleanup details.

## Quick start

```python
from pathlib import Path
from pr_controller import PremiereController, Config

c = PremiereController(config=Config(runtime=Path('runtime-v2').resolve()))
print(c.doctor())
print(c.capabilities())
print(c.timeline('Main Sequence'))
print(c.shift_timeline(30, 5, sequence='Main Sequence', dry_run=True))
```

Replace `Main Sequence` with your sequence name. Select sequences and media by stable sequence IDs, media node IDs, full paths or bin paths where supported. Ambiguous names raise an error. The original public methods remain available. New structured methods return dictionaries; legacy compatibility methods generally return lists of `status`, `op` and `data` records. See the [migration guide](docs/MIGRATION.md) for changes to validation and return data.

| Feature | Entry points |
| --- | --- |
| Diagnostics, explicit bridge installation and connection | `doctor`, `install_bridge`, `connect` |
| Job submission, status and cancellation before execution | `submit`, `job_status`, `cancel_queued` |
| Timeline inspection, media catalog and offline media | `timeline`, `catalog` |
| Sequence settings and explicit track creation | `configure_sequence`, `ensure_tracks` |
| Targeted video, audio or linked audiovisual insertion | `place_media` |
| Timeline shifts, including markers, with a dry run | `shift_timeline` |
| Batched parameters, keyframes, time coordinates and easing | `set_motion`, `animate` |
| Fit or fill a frame | `fit_clip` |
| Effects and transitions with gap filtering and localized names | `add_video_effect`, `add_audio_effect`, `add_transition`, `add_audio_transition` |
| Validated copies, moves, linked audiovisual clips and groups | `clone_or_move`, `clone_av`, `clone_group` |
| Project snapshots and rollback | `backup_project`, `transaction` |
| Native PNG previews, direct export and legacy AME export | `preview`, `export_direct`, `encode_sequence_ame` |
| Photo walls, layered pages and page focus layouts | `create_composition`, `build_photo_wall`, `build_page_fan` |
| SRT, VTT and Markdown subtitles with time offsets | `pr_controller.subtitles` |
| Subtitle source registration, track import and source export | `register_subtitle_source`, `export_subtitle_source` |
| Photo cards, PDF pages and media collection | `visual.photo_card`, `visual.pdf_pages`, `media.collect`, `media.probe` |

## Editing behavior and recovery

The new high-level editing methods protect major changes with transactions. They save the current project and create a snapshot before editing, then reopen the restored project if an operation fails. Group supported edits with `transaction()` to reduce repeated saves. Transactions reject arbitrary evaluation, opening other projects, exporting and other operations that a project snapshot cannot undo.

Copy operations verify parameter values and effect order. An unreadable or unrecoverable property raises an error; a move does not proceed to delete its source after a failed copy. Raw script execution, `invoke()` and older low-level methods are advanced entry points. Wrap supported changes in a transaction explicitly where appropriate. Avoid editing the same timeline manually while automation is running, and call `save_project` to save the final state after successful edits.

Keyframes support `clip`, `source` and `sequence` time coordinates. The legacy opacity interface defaults to `source`; the new `animate` method defaults to `clip`. When nonlinear curves can be evaluated, copying rebuilds them from samples at rendered frame times. This preserves the parameter trajectory at the current frame rate, without preserving the original Bézier handles. Unreadable plugin parameters cause copying to fail.

A timeout does not cancel a job. Its ID and runtime records remain available. Increase the timeout for long exports or use `submit` and `job_status`. A running native direct export cannot be safely force-cancelled. `cancel_queued` only cancels jobs that Premiere has not claimed.

## Subtitle limitations

Offline subtitle tools read and write SRT, VTT and Markdown, including time offsets for individual sections. A registered source can generate an SRT file and create a Premiere caption track; later exports and timing changes use that registered source.

Premiere 26's ExtendScript interface does not fully expose caption text for reading and writing. When a caption text API is unavailable, the controller reports an explicit error. It never substitutes clip names for caption text. If you edit captions manually in Premiere, provide an updated source file: source exports do not read those manual changes back from the project.

## Tests

```powershell
python -m unittest discover -s tests -v
python tools/generate_fixtures.py runtime/fixtures --wsl
python tools/native_smoke.py --runtime runtime-v2 --workspace runtime-v2/native-smoke --media-directory runtime/fixtures --visual --preset "path/to/your-h264-preset.epr"
```

Close production projects before running native tests. Native tests create a separate project in the specified test workspace and use generated video and silent audio. The fixture command shown above uses WSL. GitHub CI runs offline tests without Adobe software.

See [validation results](docs/VALIDATION.md), the [feature matrix](docs/FEATURE_MATRIX.md) and the [historical validation notes](docs/legacy-validation.md) for the scope of testing and known boundaries. These supporting documents are currently in Chinese.

## License

This repository uses the [MIT License](LICENSE). It does not distribute Adobe software, commercial plugins, user projects or recordings. Adobe software and third-party dependencies remain subject to their respective licenses.
