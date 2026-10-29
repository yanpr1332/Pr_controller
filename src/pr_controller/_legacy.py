from __future__ import annotations
import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"D:\computer\Adobe\Premiere Pro")
PREMIERE_EXE = ROOT / "Adobe Premiere Pro 2026" / "Adobe Premiere Pro.exe"
STARTUP_RUNNER = ROOT / "Adobe Premiere Pro 2026" / "Scripts" / "Startup" / "99_chatgpt_controller_runner.jsx"
SOURCE_RUNNER = ROOT / "scripts" / "controller_runner.jsx"
RUNTIME_DIR = ROOT / "_runtime"
TASK_FILE = RUNTIME_DIR / "task.jsxinc"
RESULT_FILE = RUNTIME_DIR / "result.txt"
READY_FILE = RUNTIME_DIR / "bridge_ready.txt"
HEARTBEAT_FILE = RUNTIME_DIR / "bridge_heartbeat.txt"


class PremiereController:
    """Modular controller for Premiere Pro 2026.

    Premiere uses a Startup JSX runner that stays alive through
    app.setTimeout(). Tasks are written to _runtime and picked up
    while Premiere is already running, so normal commands do not require a
    restart.

    Safety: restart=True is still available as an explicit one-time reload
    mechanism for the bridge; otherwise an active Premiere session is not
    force-closed.
    """

    def __init__(self, premiere_exe: Path = PREMIERE_EXE):
        self.premiere_exe = Path(premiere_exe)
        if not self.premiere_exe.exists():
            raise FileNotFoundError(self.premiere_exe)
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_runner()

    def _ensure_runner(self) -> None:
        if not SOURCE_RUNNER.exists():
            raise FileNotFoundError(SOURCE_RUNNER)
        if (not STARTUP_RUNNER.exists() or
                STARTUP_RUNNER.read_bytes() != SOURCE_RUNNER.read_bytes()):
            STARTUP_RUNNER.parent.mkdir(parents=True, exist_ok=True)
            STARTUP_RUNNER.write_bytes(SOURCE_RUNNER.read_bytes())

    @staticmethod
    def _premiere_running() -> bool:
        p = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Adobe Premiere Pro.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace"
        )
        return '"Adobe Premiere Pro.exe"' in p.stdout

    @staticmethod
    def _js_payload(actions: list[dict[str, Any]]) -> str:
        # JSON is a valid JavaScript object literal for these primitive payloads.
        return "var __CHATGPT_TASK = " + json.dumps(
            {"actions": actions}, ensure_ascii=False
        ) + ";\n"


    def _bridge_ready(self, max_age: float = 5.0) -> bool:
        if not READY_FILE.exists() or not HEARTBEAT_FILE.exists():
            return False
        try:
            return (time.time() - HEARTBEAT_FILE.stat().st_mtime) <= max_age
        except OSError:
            return False

    def run(self, actions: list[dict[str, Any]], *, restart: bool = False,
            timeout: float = 90.0) -> list[dict[str, str]]:
        if not actions:
            return []

        self._ensure_runner()

        running = self._premiere_running()

        if running and restart:
            subprocess.run(
                ["taskkill", "/F", "/IM", "Adobe Premiere Pro.exe"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(1.0)
            running = False

        if running and not self._bridge_ready():
            # Long Premiere operations can pause the JSX event loop briefly even
            # after their result has been written. Give the runner a short grace
            # window to resume before declaring the bridge dead.
            grace_deadline = time.time() + 5.0
            while time.time() < grace_deadline and not self._bridge_ready():
                time.sleep(0.25)
            if not self._bridge_ready():
                raise RuntimeError(
                    "Premiere is running, but the persistent bridge is not active. "
                    "Use restart=True once to reload the Startup runner safely, "
                    "or close Premiere and retry."
                )

        if TASK_FILE.exists():
            raise RuntimeError(
                "Another Premiere task is still pending. Wait for it to finish "
                "before submitting a new task."
            )

        if RESULT_FILE.exists():
            RESULT_FILE.unlink()

        TASK_FILE.write_text(self._js_payload(actions), encoding="utf-8-sig")

        if not running:
            for f in (READY_FILE, HEARTBEAT_FILE):
                try:
                    if f.exists():
                        f.unlink()
                except OSError:
                    pass
            subprocess.Popen(
                [str(self.premiere_exe)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        deadline = time.time() + timeout
        while time.time() < deadline:
            if RESULT_FILE.exists():
                text = RESULT_FILE.read_text(encoding="utf-8-sig", errors="replace")
                if text.strip():
                    rows = []
                    for line in text.splitlines():
                        parts = line.split("|", 2)
                        rows.append({
                            "status": parts[0],
                            "op": parts[1] if len(parts) > 1 else "",
                            "data": parts[2] if len(parts) > 2 else "",
                        })
                    return rows
            time.sleep(0.10)

        raise TimeoutError("Premiere task did not complete before timeout.")

    def status(self, *, restart: bool = False):
        return self.run([{"op": "status"}], restart=restart)

    def new_project(self, path: str, *, restart: bool = False):
        return self.run([{"op": "new_project", "path": str(Path(path))}], restart=restart)

    def open_project(self, path: str, *, restart: bool = False):
        return self.run([{"op": "open_project", "path": str(Path(path))}], restart=restart)

    def save_project(self, *, restart: bool = False):
        return self.run([{"op": "save_project"}], restart=restart)

    def run_script_file(self, path: str, *, restart: bool = False):
        return self.run([{"op": "eval_file", "path": str(Path(path))}], restart=restart)

    def _run_inline_jsx(self, source: str, label: str = "inline"):
        path = RUNTIME_DIR / f"{label}_{int(time.time() * 1000)}.jsx"
        path.write_text(source, encoding="utf-8-sig")
        try:
            return self.run_script_file(str(path))
        finally:
            try:
                path.unlink()
            except OSError:
                pass

    def create_bin(self, name: str, *, restart: bool = False):
        return self.run([{"op": "create_bin", "name": name}], restart=restart)

    def import_files(self, paths: list[str], bin_name: str | None = None,
                     *, restart: bool = False):
        a = {"op": "import_files", "paths": [str(Path(p)) for p in paths]}
        if bin_name:
            a["bin"] = bin_name
        return self.run([a], restart=restart)


    def create_sequence_from_clips(self, name: str, item_names: list[str],
                                   bin_name: str | None = None,
                                   *, restart: bool = False):
        a = {"op": "create_sequence_from_clips", "name": name, "items": item_names}
        if bin_name:
            a["bin"] = bin_name
        return self.run([a], restart=restart)

    def set_sequence_in_out(self, in_seconds: float, out_seconds: float, *,
                            sequence_index: int | None = None):
        if float(out_seconds) <= float(in_seconds):
            raise ValueError("out_seconds must be greater than in_seconds")
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 var ti=new Time();ti.seconds={float(in_seconds)};
 var to=new Time();to.seconds={float(out_seconds)};
 var ri=s.setInPoint(ti),ro=s.setOutPoint(to);
 return "sequence="+s.name+";in="+s.getInPoint()+";out="+s.getOutPoint()+";retIn="+ri+";retOut="+ro;
}})();"""
        return self._run_inline_jsx(source, "set_sequence_in_out")

    def clone_sequence(self, *, sequence_index: int | None = None):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 var before=app.project.sequences.numSequences;
 var ret=s.clone();$.sleep(120);
 var after=app.project.sequences.numSequences;
 var active=app.project.activeSequence?String(app.project.activeSequence.name):"";
 return "source="+s.name+";ret="+ret+";before="+before+";after="+after+";activeClone="+active;
}})();"""
        return self._run_inline_jsx(source, "clone_sequence")

    def create_subsequence(self, *, sequence_index: int | None = None,
                           ignore_track_targeting: bool = False):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 var before=app.project.sequences.numSequences;
 var sub=s.createSubsequence({"true" if ignore_track_targeting else "false"});
 $.sleep(120);
 var after=app.project.sequences.numSequences;
 if(!sub)throw "createSubsequence returned null";
 return "source="+s.name+";sub="+sub.name+";before="+before+";after="+after+
        ";videoTracks="+sub.videoTracks.numTracks+";audioTracks="+sub.audioTracks.numTracks;
}})();"""
        return self._run_inline_jsx(source, "create_subsequence")

    def set_clip_disabled(self, disabled: bool, *, sequence_index: int | None = None,
                          video_track_index: int = 0, clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c)throw "Video clip not found";
 var before=c.disabled;c.disabled={"true" if disabled else "false"};
 return "sequence="+s.name+";before="+before+";after="+c.disabled;
}})();"""
        return self._run_inline_jsx(source, "set_clip_disabled")

    def set_clip_color_label(self, label_index: int, *, sequence_index: int | None = None,
                             video_track_index: int = 0, clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c||!c.projectItem)throw "Project item not found";
 var p=c.projectItem,before=p.getColorLabel(),ret=p.setColorLabel({int(label_index)}),after=p.getColorLabel();
 return "sequence="+s.name+";item="+p.name+";before="+before+";after="+after+";ret="+ret;
}})();"""
        return self._run_inline_jsx(source, "set_clip_color_label")

    def relink_clip_media(self, new_path: str, *, sequence_index: int | None = None,
                          video_track_index: int = 0, clip_index: int = 0,
                          override_checks: bool = True):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        path_js = json.dumps(str(Path(new_path)), ensure_ascii=False)
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c||!c.projectItem)throw "Project item not found";
 var p=c.projectItem,before=p.getMediaPath(),can=p.canChangeMediaPath();
 if(!can)throw "ProjectItem cannot change media path";
 var ret=p.changeMediaPath({path_js},{"true" if override_checks else "false"});
 return "sequence="+s.name+";item="+p.name+";before="+before+";after="+p.getMediaPath()+";ret="+ret;
}})();"""
        return self._run_inline_jsx(source, "relink_clip_media")

    def add_tracks(self, *, sequence_index: int | None = None):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";try{{s.openInTimeline();}}catch(e){{}}app.enableQE();
 var q=qe.project.getActiveSequence(),bv=q.numVideoTracks,ba=q.numAudioTracks,ret=q.addTracks();$.sleep(80);
 return "sequence="+s.name+";ret="+ret+";video="+bv+"->"+q.numVideoTracks+";audio="+ba+"->"+q.numAudioTracks;
}})();"""
        return self._run_inline_jsx(source, "add_tracks")

    def remove_empty_tracks(self, *, sequence_index: int | None = None):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";try{{s.openInTimeline();}}catch(e){{}}app.enableQE();
 var q=qe.project.getActiveSequence(),bv=q.numVideoTracks,ba=q.numAudioTracks;
 var rv=q.removeEmptyVideoTracks(),ra=q.removeEmptyAudioTracks();$.sleep(80);
 return "sequence="+s.name+";video="+bv+"->"+q.numVideoTracks+";audio="+ba+"->"+q.numAudioTracks+
        ";retVideo="+rv+";retAudio="+ra;
}})();"""
        return self._run_inline_jsx(source, "remove_empty_tracks")

    def remove_video_track(self, track_index: int, *, sequence_index: int | None = None):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";try{{s.openInTimeline();}}catch(e){{}}app.enableQE();
 var q=qe.project.getActiveSequence(),before=q.numVideoTracks;
 var ret=q.removeVideoTrack({int(track_index)});$.sleep(80);
 return "sequence="+s.name+";before="+before+";after="+q.numVideoTracks+";ret="+ret;
}})();"""
        return self._run_inline_jsx(source, "remove_video_track")

    def remove_audio_track(self, track_index: int, *, sequence_index: int | None = None):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";try{{s.openInTimeline();}}catch(e){{}}app.enableQE();
 var q=qe.project.getActiveSequence(),before=q.numAudioTracks;
 var ret=q.removeAudioTrack({int(track_index)});$.sleep(80);
 return "sequence="+s.name+";before="+before+";after="+q.numAudioTracks+";ret="+ret;
}})();"""
        return self._run_inline_jsx(source, "remove_audio_track")

    def add_marker(self, seconds: float, name: str = "", comments: str = "",
                   *, restart: bool = False):
        return self.run([{
            "op": "add_marker", "seconds": float(seconds),
            "name": name, "comments": comments
        }], restart=restart)

    def set_clip_property(self, component_match_name: str, property_index: int,
                          value: Any, *, track_type: str = "video",
                          track_index: int = 0, clip_index: int = 0,
                          update_ui: bool = True, restart: bool = False):
        return self.run([{
            "op": "set_clip_property",
            "component": component_match_name,
            "propertyIndex": int(property_index),
            "value": value,
            "trackType": track_type,
            "trackIndex": int(track_index),
            "clipIndex": int(clip_index),
            "updateUI": bool(update_ui),
        }], restart=restart)

    def set_motion(self, *, position=None, scale=None, rotation=None, crop_left=None,
                   track_index: int = 0, clip_index: int = 0,
                   restart: bool = False):
        actions = []
        def add(index, value):
            actions.append({
                "op": "set_clip_property",
                "component": "AE.ADBE Motion",
                "propertyIndex": index,
                "value": value,
                "trackType": "video",
                "trackIndex": track_index,
                "clipIndex": clip_index,
            })
        if position is not None: add(0, list(position))
        if scale is not None: add(1, float(scale))
        if rotation is not None: add(4, float(rotation))
        if crop_left is not None: add(7, float(crop_left))
        return self.run(actions, restart=restart)

    def set_opacity(self, value: float, *, track_index: int = 0,
                    clip_index: int = 0, restart: bool = False):
        return self.set_clip_property(
            "AE.ADBE Opacity", 0, float(value),
            track_index=track_index, clip_index=clip_index, restart=restart
        )


    def set_opacity_keyframes(self, keys: list[tuple[float, float]], *,
                              track_index: int = 0, clip_index: int = 0,
                              restart: bool = False):
        return self.run([{
            "op": "set_keyframes",
            "component": "AE.ADBE Opacity",
            "propertyIndex": 0,
            "trackType": "video",
            "trackIndex": track_index,
            "clipIndex": clip_index,
            "keys": [{"seconds": float(t), "value": float(v)} for t, v in keys],
        }], restart=restart)

    def add_video_effect(self, name: str, *, track_index: int = 0,
                         clip_index: int = 0, restart: bool = False):
        return self.run([{
            "op": "add_video_effect", "name": name,
            "trackIndex": track_index, "clipIndex": clip_index
        }], restart=restart)

    def list_video_effect_names(self, effect_type: int = 0):
        source = f"""#target premierepro
(function(){{
 app.enableQE();
 var list=qe.project.getVideoEffectList({int(effect_type)});
 var a=[];
 if(list) for(var i=0;i<list.length;i++) a.push(String(list[i]));
 return a.join("~");
}})();"""
        rows = self._run_inline_jsx(source, "list_video_effects")
        for row in rows:
            if row.get("status") == "OK":
                payload = row.get("data", "")
                return payload.split("~") if payload else []
        return []

    def inspect_clip_components(self, *, sequence_index: int | None = None,
                                track_type: str = "video",
                                track_index: int = 0, clip_index: int = 0,
                                include_keyframes: bool = False):
        if track_type not in {"video", "audio"}:
            raise ValueError("track_type must be video or audio")
        from urllib.parse import unquote
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        track_expr = "videoTracks" if track_type == "video" else "audioTracks"
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 var c=s.{track_expr}[{int(track_index)}].clips[{int(clip_index)}];
 if(!c)throw "Clip not found";
 function esc(v){{try{{return encodeURIComponent(String(v));}}catch(e){{return "";}}}}
 function val(v){{
   if(v===undefined)return ["undefined",""];
   if(v===null)return ["null",""];
   var t=typeof v;
   if(t==="number"||t==="boolean"||t==="string")return [t,esc(v)];
   try{{
     if(v.length!==undefined && typeof v!=="string"){{
       var a=[];for(var i=0;i<v.length;i++)a.push(v[i]);
       return ["array",esc(a.join(","))];
     }}
   }}catch(e){{}}
   return ["string",esc(v)];
 }}
 var a=["S^"+esc(s.name)+"^{track_type}^{int(track_index)}^{int(clip_index)}"];
 for(var ci=0;ci<c.components.numItems;ci++){{
   var cp=c.components[ci];
   a.push("C^"+ci+"^"+esc(cp.displayName)+"^"+esc(cp.matchName));
   for(var pi=0;pi<cp.properties.numItems;pi++){{
     var pr=cp.properties[pi],v;
     try{{v=pr.getValue();}}catch(e0){{v=undefined;}}
     var vv=val(v);
     a.push("P^"+ci+"^"+pi+"^"+esc(pr.displayName)+"^"+esc(pr.matchName)+"^"+vv[0]+"^"+vv[1]);
     if({"true" if include_keyframes else "false"}){{
       try{{
         var kk=pr.getKeys();
         if(kk&&kk.length){{
           for(var ki=0;ki<kk.length;ki++){{
             var kv;try{{kv=pr.getValueAtKey(kk[ki]);}}catch(e1){{kv=undefined;}}
             var kve=val(kv);
             a.push("K^"+ci+"^"+pi+"^"+kk[ki].seconds+"^"+kve[0]+"^"+kve[1]);
           }}
         }}
       }}catch(e2){{}}
     }}
   }}
 }}
 return a.join("~");
}})();"""
        rows = self._run_inline_jsx(source, "inspect_clip_components")
        payload = ""
        for row in rows:
            if row.get("status") == "OK":
                payload = row.get("data", "")
                break
        out = {
            "sequence": None,
            "track_type": track_type,
            "track_index": int(track_index),
            "clip_index": int(clip_index),
            "components": [],
        }
        comps = {}
        for rec in payload.split("~") if payload else []:
            parts = rec.split("^")
            if not parts:
                continue
            if parts[0] == "S" and len(parts) >= 2:
                out["sequence"] = unquote(parts[1])
            elif parts[0] == "C" and len(parts) >= 4:
                ci = int(parts[1])
                comp = {
                    "index": ci,
                    "displayName": unquote(parts[2]),
                    "matchName": unquote(parts[3]),
                    "properties": [],
                }
                comps[ci] = comp
                out["components"].append(comp)
            elif parts[0] == "P" and len(parts) >= 7:
                ci, pi = int(parts[1]), int(parts[2])
                raw = unquote(parts[6])
                kind = parts[5]
                if kind == "number":
                    try: value = float(raw)
                    except Exception: value = raw
                elif kind == "boolean":
                    value = raw.lower() == "true"
                elif kind == "array":
                    vals = []
                    if raw:
                        for x in raw.split(","):
                            try: vals.append(float(x))
                            except Exception: vals.append(x)
                    value = vals
                elif kind in {"undefined", "null"}:
                    value = None
                else:
                    value = raw
                prop = {
                    "index": pi,
                    "displayName": unquote(parts[3]),
                    "matchName": unquote(parts[4]),
                    "kind": kind,
                    "value": value,
                    "keyframes": [],
                }
                if ci in comps:
                    comps[ci]["properties"].append(prop)
            elif parts[0] == "K" and len(parts) >= 6:
                ci, pi = int(parts[1]), int(parts[2])
                raw = unquote(parts[5])
                kind = parts[4]
                if kind == "number":
                    try: value = float(raw)
                    except Exception: value = raw
                elif kind == "boolean":
                    value = raw.lower() == "true"
                elif kind == "array":
                    value = []
                    if raw:
                        for x in raw.split(","):
                            try: value.append(float(x))
                            except Exception: value.append(x)
                elif kind in {"undefined", "null"}:
                    value = None
                else:
                    value = raw
                if ci in comps:
                    for prop in comps[ci]["properties"]:
                        if prop["index"] == pi:
                            prop["keyframes"].append({
                                "seconds": float(parts[3]),
                                "kind": kind,
                                "value": value,
                            })
                            break
        return out

    def set_clip_component_property(self, component_name: str, property_index: int, value, *,
                                    sequence_index: int | None = None,
                                    track_type: str = "video",
                                    track_index: int = 0, clip_index: int = 0):
        if track_type not in {"video", "audio"}:
            raise ValueError("track_type must be video or audio")
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        track_expr = "videoTracks" if track_type == "video" else "audioTracks"
        name_js = json.dumps(component_name, ensure_ascii=False)
        value_js = json.dumps(value, ensure_ascii=False)
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 var c=s.{track_expr}[{int(track_index)}].clips[{int(clip_index)}];
 if(!c)throw "Clip not found";
 var cp=null;
 for(var i=0;i<c.components.numItems;i++){{
   var x=c.components[i];
   if(String(x.matchName)==={name_js}||String(x.displayName)==={name_js}){{cp=x;break;}}
 }}
 if(!cp)throw "Component not found: "+{name_js};
 if({int(property_index)}<0||{int(property_index)}>=cp.properties.numItems)throw "Property index out of range";
 var p=cp.properties[{int(property_index)}],before="";
 try{{before=String(p.getValue());}}catch(e){{}}
 var ok=p.setValue({value_js},true);
 var after="";try{{after=String(p.getValue());}}catch(e2){{}}
 return "sequence="+s.name+";component="+cp.matchName+";property="+{int(property_index)}+
        ";before="+before+";after="+after+";ok="+ok;
}})();"""
        return self._run_inline_jsx(source, "set_component_property")

    def set_clip_component_keyframes(self, component_name: str, property_index: int,
                                     keyframes: list[dict], *,
                                     sequence_index: int | None = None,
                                     track_type: str = "video",
                                     track_index: int = 0, clip_index: int = 0,
                                     clear_existing: bool = False):
        if track_type not in {"video", "audio"}:
            raise ValueError("track_type must be video or audio")
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        track_expr = "videoTracks" if track_type == "video" else "audioTracks"
        name_js = json.dumps(component_name, ensure_ascii=False)
        keys_js = json.dumps(keyframes, ensure_ascii=False)
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 var c=s.{track_expr}[{int(track_index)}].clips[{int(clip_index)}];
 if(!c)throw "Clip not found";
 var cp=null;
 for(var i=0;i<c.components.numItems;i++){{
   var x=c.components[i];
   if(String(x.matchName)==={name_js}||String(x.displayName)==={name_js}){{cp=x;break;}}
 }}
 if(!cp)throw "Component not found: "+{name_js};
 if({int(property_index)}<0||{int(property_index)}>=cp.properties.numItems)throw "Property index out of range";
 var p=cp.properties[{int(property_index)}],keys={keys_js};
 p.setTimeVarying(true);
 if({"true" if clear_existing else "false"}){{
   try{{
     var old=p.getKeys();
     if(old&&old.length)for(var r=old.length-1;r>=0;r--)p.removeKey(old[r]);
   }}catch(clearErr){{}}
 }}
 var n=0;
 for(var k=0;k<keys.length;k++){{
   var t=new Time();t.seconds=Number(keys[k].seconds);
   p.addKey(t);p.setValueAtKey(t,keys[k].value,true);n++;
 }}
 var got=[];try{{
   var now=p.getKeys();for(var j=0;j<now.length;j++)got.push(now[j].seconds+":"+String(p.getValueAtKey(now[j])));
 }}catch(e){{}}
 return "sequence="+s.name+";component="+cp.matchName+";property="+{int(property_index)}+
        ";written="+n+";keys="+got.join(",");
}})();"""
        return self._run_inline_jsx(source, "set_component_keyframes")

    def list_audio_effect_names(self, effect_type: int = 0):
        source = f"""#target premierepro
(function(){{
 app.enableQE();
 var list=qe.project.getAudioEffectList({int(effect_type)});
 var a=[];
 if(list) for(var i=0;i<list.length;i++) a.push(String(list[i]));
 return a.join("~");
}})();"""
        rows = self._run_inline_jsx(source, "list_audio_effects")
        for row in rows:
            if row.get("status") == "OK":
                payload = row.get("data", "")
                return payload.split("~") if payload else []
        return []

    def add_audio_effect(self, name: str, *, sequence_index: int | None = None,
                         audio_track_index: int = 0, clip_index: int = 0,
                         channel_type: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        name_js = json.dumps(name, ensure_ascii=False)
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}$.sleep(120);app.enableQE();
 var qs=qe.project.getActiveSequence();if(!qs)throw "No QE active sequence";
 if(String(qs.name)!==String(s.name))throw "QE active sequence mismatch: "+qs.name;
 var qt=qs.getAudioTrackAt({int(audio_track_index)});if(!qt)throw "QE audio track not found";
 var qi=null,seen=-1;
 for(var i=0;i<qt.numItems;i++){{
   var it=qt.getItemAt(i);if(it&&it.type==="Clip"){{seen++;if(seen==={int(clip_index)}){{qi=it;break;}}}}
 }}
 if(!qi)throw "QE audio clip not found";
 var eff=qe.project.getAudioEffectByName({name_js},{int(channel_type)});
 if(!eff)throw "Audio effect not found: "+{name_js};
 var c=s.audioTracks[{int(audio_track_index)}].clips[{int(clip_index)}];
 var before=c.components.numItems;
 var ok=qi.addAudioEffect(eff);$.sleep(180);
 var after=c.components.numItems;
 return "sequence="+s.name+";effect="+{name_js}+";channelType="+{int(channel_type)}+
        ";ok="+ok+";before="+before+";after="+after;
}})();"""
        return self._run_inline_jsx(source, "add_audio_effect")

    def list_audio_transition_names(self):
        source = """#target premierepro
(function(){
 app.enableQE();
 var list=qe.project.getAudioTransitionList(),a=[];
 if(list)for(var i=0;i<list.length;i++)a.push(String(list[i]));
 return a.join("~");
})();"""
        rows = self._run_inline_jsx(source, "list_audio_transition_names")
        for row in rows:
            if row.get("status") == "OK":
                payload = row.get("data", "")
                return payload.split("~") if payload else []
        return []

    def add_audio_transition(self, name: str, duration_tc: str = "00:00:00:12", *,
                             sequence_index: int | None = None,
                             audio_track_index: int = 0, clip_index: int = 0,
                             incoming: bool = False):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        name_js = json.dumps(name, ensure_ascii=False)
        dur_js = json.dumps(duration_tc)
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}app.enableQE();
 var qs=qe.project.getActiveSequence(),qt=qs.getAudioTrackAt({int(audio_track_index)});
 if(!qt)throw "Audio track not found";
 var qclip=null,seen=-1;
 for(var i=0;i<qt.numItems;i++){{
   var it=qt.getItemAt(i);
   if(it&&it.type==="Clip"){{seen++;if(seen==={int(clip_index)}){{qclip=it;break;}}}}
 }}
 if(!qclip)throw "QE audio clip not found";
 var tr=qe.project.getAudioTransitionByName({name_js});
 if(!tr)throw "Audio transition not found: "+{name_js};
 function realCount(){{
   var n=0;for(var j=0;j<qt.numTransitions;j++){{var x=qt.getTransitionAt(j),nm="";try{{nm=String(x.name);}}catch(e){{}}if(nm)n++;}}return n;
 }}
 var before=realCount(),ret=qclip.addTransition(tr,{"true" if incoming else "false"},{dur_js});$.sleep(150),after=realCount();
 return "sequence="+s.name+";name="+{name_js}+";ret="+ret+";before="+before+";after="+after;
}})();"""
        return self._run_inline_jsx(source, "add_audio_transition")

    def list_audio_transitions(self, *, sequence_index: int | None = None,
                               audio_track_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}app.enableQE();
 var qt=qe.project.getActiveSequence().getAudioTrackAt({int(audio_track_index)}),a=[];
 for(var i=0;i<qt.numTransitions;i++){{
   var t=qt.getTransitionAt(i),nm="";try{{nm=String(t.name);}}catch(e){{}}
   if(!nm)continue;
   var st="",en="";try{{st=t.start.frames;}}catch(e2){{}}try{{en=t.end.frames;}}catch(e3){{}}
   a.push(encodeURIComponent(nm)+"|"+st+"|"+en);
 }}
 return a.join("~");
}})();"""
        rows = self._run_inline_jsx(source, "list_audio_transitions")
        payload = ""
        for row in rows:
            if row.get("status") == "OK":
                payload = row.get("data", "")
                break
        from urllib.parse import unquote
        out = []
        for rec in payload.split("~") if payload else []:
            parts = rec.split("|")
            if len(parts) >= 3:
                try:
                    st = int(float(parts[1])); en = int(float(parts[2]))
                except Exception:
                    continue
                out.append({
                    "name": unquote(parts[0]),
                    "start_frame": st,
                    "end_frame": en,
                    "duration_frames": en - st,
                })
        return out

    def copy_audio_group_transitions(self, source_clip_indices: list[int], *,
                                     sequence_index: int | None = None,
                                     source_audio_track_index: int = 0,
                                     target_audio_track_index: int = 1):
        indices = sorted({int(x) for x in source_clip_indices})
        if not indices:
            return []
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        idx_js = json.dumps(indices)
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}app.enableQE();
 var srcTrack=s.audioTracks[{int(source_audio_track_index)}],dstTrack=s.audioTracks[{int(target_audio_track_index)}];
 if(!srcTrack||!dstTrack)throw "Audio track not found";
 var idx={idx_js},selected=[];
 for(var i=0;i<idx.length;i++){{
   var c=srcTrack.clips[idx[i]];if(!c)throw "Source audio clip missing";
   selected.push({{start:c.start.seconds,end:c.end.seconds}});
 }}
 var qs=qe.project.getActiveSequence(),sqt=qs.getAudioTrackAt({int(source_audio_track_index)}),dqt=qs.getAudioTrackAt({int(target_audio_track_index)});
 var settings=s.getSettings(),fps=Math.round(1/settings.videoFrameRate.seconds);
 function tc(fr){{
   var hh=Math.floor(fr/(fps*3600));fr-=hh*fps*3600;var mm=Math.floor(fr/(fps*60));fr-=mm*fps*60;
   var ss=Math.floor(fr/fps),ff=fr-ss*fps;function p2(x){{return (x<10?"0":"")+x;}}
   return p2(hh)+":"+p2(mm)+":"+p2(ss)+":"+p2(ff);
 }}
 function findDst(st,en){{
   var ord=-1;for(var j=0;j<dstTrack.clips.numItems;j++){{var d=dstTrack.clips[j];if(Math.abs(d.start.seconds-st)<0.0005&&Math.abs(d.end.seconds-en)<0.0005){{ord=j;break;}}}}
   if(ord<0)return null;var seen=-1;for(var q=0;q<dqt.numItems;q++){{var it=dqt.getItemAt(q);if(it&&it.type==="Clip"){{seen++;if(seen===ord)return it;}}}}return null;
 }}
 var used={{}},copied=0,out=[];
 for(var ti=0;ti<sqt.numTransitions;ti++){{
   var tr=sqt.getTransitionAt(ti),nm="";try{{nm=String(tr.name);}}catch(e){{}}if(!nm)continue;
   var stf="",enf="";try{{stf=tr.start.frames;enf=tr.end.frames;}}catch(e2){{continue;}}
   var stSec=Number(stf)/fps,enSec=Number(enf)/fps,center=(stSec+enSec)/2;
   var left=-1,right=-1;
   for(var si=0;si<selected.length;si++){{
     if(Math.abs(stSec-selected[si].end)<0.06 || Math.abs(center-selected[si].end)<0.06)left=si;
     if(Math.abs(enSec-selected[si].start)<0.06 || Math.abs(center-selected[si].start)<0.06)right=si;
   }}
   if(left<0&&right<0)continue;
   var key=nm+"|"+stf+"|"+enf;if(used[key])continue;used[key]=true;
   var use=(left>=0)?left:right,incoming=(left<0&&right>=0),dq=findDst(selected[use].start,selected[use].end);
   if(!dq){{out.push("missingTarget");continue;}}
   var qtr=qe.project.getAudioTransitionByName(nm);if(!qtr){{out.push("missing:"+nm);continue;}}
   var frames=Math.max(1,Math.round(enf-stf)),ok=dq.addTransition(qtr,incoming,tc(frames));
   out.push(nm+":"+(incoming?"in":"out")+":"+frames+":"+ok);if(ok)copied++;
 }}
 return "copied="+copied+";"+out.join("~");
}})();"""
        return self._run_inline_jsx(source, "copy_audio_group_transitions")

    def add_transition(self, name: str = "Cross Dissolve",
                       duration_tc: str = "00:00:00:12", *,
                       track_index: int = 0, clip_index: int = 0,
                       incoming: bool = False, restart: bool = False):
        return self.run([{
            "op": "add_transition", "name": name,
            "duration": duration_tc, "isIncoming": incoming,
            "trackIndex": track_index, "clipIndex": clip_index,
        }], restart=restart)

    def list_video_transitions(self, *, sequence_index: int | None = None,
                               video_track_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}app.enableQE();
 var qt=qe.project.getActiveSequence().getVideoTrackAt({int(video_track_index)}),a=[];
 for(var i=0;i<qt.numTransitions;i++){{
   var t=qt.getTransitionAt(i);
   if(t&&t.type==="Transition"){{
     a.push(String(t.name)+"|"+t.start.frames+"|"+t.end.frames+"|"+t.alignment);
   }}
 }}
 return a.join("~");
}})();"""
        rows = self._run_inline_jsx(source, "list_video_transitions")
        payload = ""
        for row in rows:
            if row.get("status") == "OK":
                payload = row.get("data", "")
                break
        out = []
        if payload:
            for item in payload.split("~"):
                parts = item.split("|")
                if len(parts) >= 4:
                    out.append({
                        "name": parts[0],
                        "start_frame": int(float(parts[1])),
                        "end_frame": int(float(parts[2])),
                        "alignment": float(parts[3]),
                        "duration_frames": int(float(parts[2])) - int(float(parts[1])),
                    })
        return out

    def copy_clip_edge_transitions(self, *, sequence_index: int | None = None,
                                   source_video_track_index: int = 0,
                                   source_clip_index: int = 0,
                                   target_video_track_index: int = 1,
                                   target_clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}app.enableQE();
 var src=s.videoTracks[{int(source_video_track_index)}].clips[{int(source_clip_index)}];
 var dst=s.videoTracks[{int(target_video_track_index)}].clips[{int(target_clip_index)}];
 if(!src||!dst)throw "Source/target clip not found";
 var qs=qe.project.getActiveSequence();
 var sqt=qs.getVideoTrackAt({int(source_video_track_index)});
 var dqt=qs.getVideoTrackAt({int(target_video_track_index)});
 var dq=null,seen=-1;
 for(var di=0;di<dqt.numItems;di++){{
   var dit=dqt.getItemAt(di);if(dit&&dit.type==="Clip"){{seen++;if(seen==={int(target_clip_index)}){{dq=dit;break;}}}}
 }}
 if(!dq)throw "Target QE clip not found";
 var settings=s.getSettings(),fps=Math.round(1/settings.videoFrameRate.seconds);
 function tc(fr){{
   var hh=Math.floor(fr/(fps*3600));fr-=hh*fps*3600;
   var mm=Math.floor(fr/(fps*60));fr-=mm*fps*60;
   var ss=Math.floor(fr/fps),ff=fr-ss*fps;
   function p2(x){{return (x<10?"0":"")+x;}}
   return p2(hh)+":"+p2(mm)+":"+p2(ss)+":"+p2(ff);
 }}
 var copied=0,a=[];
 for(var i=0;i<sqt.numTransitions;i++){{
   var tr=sqt.getTransitionAt(i);if(!tr||tr.type!=="Transition")continue;
   var center=(tr.start.secs+tr.end.secs)/2;
   var incoming=Math.abs(center-src.start.seconds)<0.06;
   var outgoing=Math.abs(center-src.end.seconds)<0.06;
   if(!incoming&&!outgoing)continue;
   var qtr=qe.project.getVideoTransitionByName(String(tr.name));if(!qtr)continue;
   var frames=Math.max(1,Math.round(tr.end.frames-tr.start.frames));
   var ok=dq.addTransition(qtr,incoming,tc(frames));
   a.push(tr.name+":"+(incoming?"in":"out")+":"+frames+":"+ok);
   if(ok)copied++;
 }}
 return "copied="+copied+";"+a.join("~");
}})();"""
        return self._run_inline_jsx(source, "copy_clip_transitions")

    def copy_video_group_transitions(self, source_clip_indices: list[int], *,
                                     sequence_index: int | None = None,
                                     source_video_track_index: int = 0,
                                     target_video_track_index: int = 1):
        indices = sorted({int(x) for x in source_clip_indices})
        if not indices:
            return []
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        indices_js = json.dumps(indices)
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}app.enableQE();
 var srcTrack=s.videoTracks[{int(source_video_track_index)}];
 var dstTrack=s.videoTracks[{int(target_video_track_index)}];
 if(!srcTrack||!dstTrack)throw "Track not found";
 var idx={indices_js}, selected=[];
 for(var i=0;i<idx.length;i++){{
   var c=srcTrack.clips[idx[i]];if(!c)throw "Source clip index missing: "+idx[i];
   selected.push({{clip:c,start:c.start.seconds,end:c.end.seconds}});
 }}
 var qs=qe.project.getActiveSequence(),sqt=qs.getVideoTrackAt({int(source_video_track_index)}),dqt=qs.getVideoTrackAt({int(target_video_track_index)});
 var settings=s.getSettings(),fps=Math.round(1/settings.videoFrameRate.seconds);
 function tc(fr){{
   var hh=Math.floor(fr/(fps*3600));fr-=hh*fps*3600;
   var mm=Math.floor(fr/(fps*60));fr-=mm*fps*60;
   var ss=Math.floor(fr/fps),ff=fr-ss*fps;
   function p2(x){{return (x<10?"0":"")+x;}}
   return p2(hh)+":"+p2(mm)+":"+p2(ss)+":"+p2(ff);
 }}
 function findDstByTimes(st,en){{
   var ord=-1;
   for(var j=0;j<dstTrack.clips.numItems;j++){{
     var d=dstTrack.clips[j];
     if(Math.abs(d.start.seconds-st)<0.0005&&Math.abs(d.end.seconds-en)<0.0005){{ord=j;break;}}
   }}
   if(ord<0)return null;
   var seen=-1;
   for(var q=0;q<dqt.numItems;q++){{
     var it=dqt.getItemAt(q);
     if(it&&it.type==="Clip"){{seen++;if(seen===ord)return it;}}
   }}
   return null;
 }}
 var copied=0,out=[],used={{}};
 for(var ti=0;ti<sqt.numTransitions;ti++){{
   var tr=sqt.getTransitionAt(ti);if(!tr||tr.type!=="Transition")continue;
   var center=(tr.start.secs+tr.end.secs)/2;
   var left=-1,right=-1;
   for(var si=0;si<selected.length;si++){{
     if(Math.abs(center-selected[si].end)<0.06)left=si;
     if(Math.abs(center-selected[si].start)<0.06)right=si;
   }}
   if(left<0&&right<0)continue;
   var key=String(tr.name)+"|"+tr.start.frames+"|"+tr.end.frames;
   if(used[key])continue;used[key]=true;
   var useIndex=(left>=0)?left:right;
   var incoming=(left<0&&right>=0);
   var dq=findDstByTimes(selected[useIndex].start,selected[useIndex].end);
   if(!dq){{out.push("missingTarget:"+useIndex);continue;}}
   var qtr=qe.project.getVideoTransitionByName(String(tr.name));if(!qtr){{out.push("missingTransition:"+tr.name);continue;}}
   var frames=Math.max(1,Math.round(tr.end.frames-tr.start.frames));
   var ok=dq.addTransition(qtr,incoming,tc(frames));
   out.push(String(tr.name)+":"+(incoming?"in":"out")+":"+frames+":"+ok);
   if(ok)copied++;
 }}
 return "copied="+copied+";"+out.join("~");
}})();"""
        return self._run_inline_jsx(source, "copy_video_group_transitions")

    def clone_video_group_to_track(self, clip_indices: list[int], target_video_track_index: int, *,
                                   sequence_index: int | None = None,
                                   source_video_track_index: int = 0,
                                   copy_transitions: bool = True):
        indices = sorted({int(x) for x in clip_indices})
        results = []
        for clip_index in indices:
            results.append(self.clone_video_clip_to_track(
                target_video_track_index,
                sequence_index=sequence_index,
                source_video_track_index=source_video_track_index,
                clip_index=clip_index,
            ))
        if copy_transitions and indices:
            results.append(self.copy_video_group_transitions(
                indices,
                sequence_index=sequence_index,
                source_video_track_index=source_video_track_index,
                target_video_track_index=target_video_track_index,
            ))
        return results

    def move_video_group_to_track(self, clip_indices: list[int], target_video_track_index: int, *,
                                  sequence_index: int | None = None,
                                  source_video_track_index: int = 0,
                                  copy_transitions: bool = True):
        indices = sorted({int(x) for x in clip_indices})
        results = self.clone_video_group_to_track(
            indices,
            target_video_track_index,
            sequence_index=sequence_index,
            source_video_track_index=source_video_track_index,
            copy_transitions=copy_transitions,
        )
        for clip_index in sorted(indices, reverse=True):
            results.append(self.remove_video_clip(
                sequence_index=sequence_index,
                video_track_index=source_video_track_index,
                clip_index=clip_index,
            ))
        return results

    def create_caption_track(self, srt_name: str, start_seconds: float = 0,
                             *, restart: bool = False):
        return self.run([{
            "op": "create_caption_track",
            "srtName": srt_name,
            "startSeconds": float(start_seconds),
        }], restart=restart)

    def import_mogrt(self, path: str, time_seconds: float = 0,
                     video_track_index: int = 1, audio_track_index: int = 0,
                     *, restart: bool = False):
        return self.run([{
            "op": "import_mogrt",
            "path": str(Path(path)),
            "timeSeconds": float(time_seconds),
            "videoTrackIndex": int(video_track_index),
            "audioTrackIndex": int(audio_track_index),
        }], restart=restart)

    def auto_reframe(self, numerator: int, denominator: int, name: str,
                     motion_preset: str = "default", nest: bool = False,
                     *, restart: bool = False):
        return self.run([{
            "op": "auto_reframe",
            "numerator": int(numerator),
            "denominator": int(denominator),
            "name": name,
            "motionPreset": motion_preset,
            "nest": bool(nest),
        }], restart=restart)


    def find_mogrt_clips(self):
        source = """#target premierepro
(function(){
 var a=[];
 for(var si=0;si<app.project.sequences.numSequences;si++){
   var s=app.project.sequences[si];
   for(var vt=0;vt<s.videoTracks.numTracks;vt++){
     var tr=s.videoTracks[vt];
     for(var ci=0;ci<tr.clips.numItems;ci++){
       var c=tr.clips[ci], is=false;
       try{is=c.isMGT();}catch(ignore){}
       if(is){
         a.push(si+"|"+s.name+"|"+vt+"|"+ci+"|"+c.name);
       }
     }
   }
 }
 return a.length?a.join("~"):"";
})();"""
        rows = self._run_inline_jsx(source, "find_mogrt")
        found = []
        payload = ""
        for row in rows:
            if row.get("status") == "OK":
                payload = row.get("data", "")
                break
        if not payload:
            return found
        for entry in payload.split("~"):
            parts = entry.split("|")
            if len(parts) >= 5:
                found.append({
                    "sequence_index": int(parts[0]),
                    "sequence_name": parts[1],
                    "video_track_index": int(parts[2]),
                    "clip_index": int(parts[3]),
                    "clip_name": "|".join(parts[4:]),
                })
        return found

    def set_mogrt_property(self, value: Any, *, sequence_index: int,
                           video_track_index: int = 1, clip_index: int = 0,
                           component_match_name: str = "AE.ADBE Text",
                           property_index: int = 0):
        value_js = json.dumps(value, ensure_ascii=False)
        match_js = json.dumps(component_match_name, ensure_ascii=False)
        source = f"""#target premierepro
(function(){{
 var s=app.project.sequences[{int(sequence_index)}];
 if(!s) throw "Sequence not found";
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c) throw "MOGRT clip not found";
 var comp=null;
 for(var i=0;i<c.components.numItems;i++){{
  if(c.components[i].matchName==={match_js}){{comp=c.components[i];break;}}
 }}
 if(!comp) throw "Component not found";
 var p=comp.properties[{int(property_index)}];
 var before=p.getValue();
 var ok=p.setValue({value_js},true);
 var after=p.getValue();
 return "before="+before+";set="+ok+";after="+after;
}})();"""
        return self._run_inline_jsx(source, "mogrt_property")

    def set_mogrt_text(self, text: str, *, sequence_index: int,
                       video_track_index: int = 1, clip_index: int = 0):
        return self.set_mogrt_property(
            text,
            sequence_index=sequence_index,
            video_track_index=video_track_index,
            clip_index=clip_index,
            component_match_name="AE.ADBE Text",
            property_index=0,
        )


    def set_mogrt_transform(self, *, sequence_index: int,
                            video_track_index: int = 1, clip_index: int = 0,
                            position: tuple[float, float] | None = None,
                            scale: float | None = None,
                            rotation: float | None = None,
                            opacity: float | None = None):
        values = []
        if position is not None:
            values.append((2, [float(position[0]), float(position[1])]))
        if scale is not None:
            values.append((3, float(scale)))
        if rotation is not None:
            values.append((6, float(rotation)))
        if opacity is not None:
            values.append((7, float(opacity)))
        if not values:
            return []
        pairs = json.dumps(
            [{"index": idx, "value": value} for idx, value in values],
            ensure_ascii=False
        )
        source = f"""#target premierepro
(function(){{
 var s=app.project.sequences[{int(sequence_index)}];
 if(!s) throw "Sequence not found";
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c) throw "MOGRT clip not found";
 var comp=null;
 for(var i=0;i<c.components.numItems;i++){{
   if(c.components[i].matchName==="AE.ADBE Text"){{comp=c.components[i];break;}}
 }}
 if(!comp) throw "Text component not found";
 var pairs={pairs}, out=[];
 for(var j=0;j<pairs.length;j++){{
   var pr=comp.properties[pairs[j].index];
   var before=pr.getValue();
   var ok=pr.setValue(pairs[j].value,true);
   out.push(pairs[j].index+":"+before+"->"+pr.getValue()+"("+ok+")");
 }}
 return out.join(";");
}})();"""
        return self._run_inline_jsx(source, "mogrt_transform")

    def scene_edit_detection(self, *, sequence_index: int | None = None,
                             video_track_index: int = 0,
                             clip_index: int = 0,
                             action: str = "ApplyCuts",
                             apply_cuts_to_linked_audio: bool = False,
                             sensitivity: str = "MediumSensitivity"):
        if action not in {"ApplyCuts", "CreateMarkers"}:
            raise ValueError("action must be ApplyCuts or CreateMarkers")
        if sensitivity not in {"LowSensitivity", "MediumSensitivity", "HighSensitivity"}:
            raise ValueError("invalid sensitivity")
        seq_expr = "app.project.activeSequence" if sequence_index is None else f"app.project.sequences[{int(sequence_index)}]"
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}
 for(var t=0;t<s.videoTracks.numTracks;t++){{
  var tr=s.videoTracks[t];
  for(var i=0;i<tr.clips.numItems;i++) tr.clips[i].setSelected(0,0);
 }}
 for(var at=0;at<s.audioTracks.numTracks;at++){{
  var ar=s.audioTracks[at];
  for(var ai=0;ai<ar.clips.numItems;ai++) ar.clips[ai].setSelected(0,0);
 }}
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c) throw "Clip not found";
 c.setSelected(1,1);
 var before=s.videoTracks[{int(video_track_index)}].clips.numItems;
 var ok=s.performSceneEditDetectionOnSelection(
   {json.dumps(action)},
   {"true" if apply_cuts_to_linked_audio else "false"},
   {json.dumps(sensitivity)}
 );
 var after=s.videoTracks[{int(video_track_index)}].clips.numItems;
 return "sequence="+s.name+";ok="+ok+";before="+before+";after="+after;
}})();"""
        return self._run_inline_jsx(source, "scene_detect")

    def set_video_clip_speed(self, rate: float, *,
                             sequence_index: int | None = None,
                             video_track_index: int = 0,
                             clip_index: int = 0,
                             reverse: bool = False,
                             stretch_timeline: bool = True):
        rate = float(rate)
        if rate <= 0:
            raise ValueError("rate must be > 0; use reverse=True for reverse playback")
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c) throw "Video clip not found";
 var sourceSpan=c.outPoint.seconds-c.inPoint.seconds;
 var beforeSpeed=c.getSpeed();
 var beforeRev=c.isSpeedReversed();
 var beforeDur=c.duration.seconds;

 app.enableQE();
 var qs=qe.project.getActiveSequence();
 var qt=qs.getVideoTrackAt({int(video_track_index)});
 var qc=null, seen=-1;
 for(var i=0;i<qt.numItems;i++){{
   var it=qt.getItemAt(i);
   if(it && it.type==="Clip"){{
     seen++;
     if(seen==={int(clip_index)}){{qc=it;break;}}
   }}
 }}
 if(!qc) throw "QE clip not found";
 var durationTC=qc.duration || "00;00;00;00";
 var ok=qc.setSpeed({rate},durationTC,{"true" if reverse else "false"},false,false);

 if({"true" if stretch_timeline else "false"}){{
   var targetDur=sourceSpan/{rate};
   var endTime=new Time();
   endTime.seconds=c.start.seconds+targetDur;
   c.end=endTime;
 }}

 return "ok="+ok+
        ";beforeSpeed="+beforeSpeed+
        ";afterSpeed="+c.getSpeed()+
        ";beforeReverse="+beforeRev+
        ";afterReverse="+c.isSpeedReversed()+
        ";beforeDuration="+beforeDur+
        ";afterDuration="+c.duration.seconds+
        ";sourceSpan="+sourceSpan;
}})();"""
        return self._run_inline_jsx(source, "video_speed")

    def ripple_trim_linked_av_end(self, seconds: float, *,
                                  sequence_index: int | None = None,
                                  video_track_index: int = 0,
                                  video_clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var vc=s.videoTracks[{int(video_track_index)}].clips[{int(video_clip_index)}];
 if(!vc) throw "Video clip not found";
 var oldEnd=vc.end.seconds, target={float(seconds)}, delta=target-oldEnd;
 var linked=vc.getLinkedItems();
 if(!linked || linked.numItems<1) throw "No linked items";
 var current=[];
 for(var i=0;i<linked.numItems;i++) current.push(linked[i]);

 var followers=[];
 for(var vt=0;vt<s.videoTracks.numTracks;vt++){{
   var tr=s.videoTracks[vt];
   for(var vi=0;vi<tr.clips.numItems;vi++){{
     var c=tr.clips[vi], isCurrent=false;
     for(var q=0;q<current.length;q++) if(c===current[q]) isCurrent=true;
     if(!isCurrent && c.start.seconds>=oldEnd-0.000001)
       followers.push({{clip:c,start:c.start.seconds,end:c.end.seconds}});
   }}
 }}
 for(var at=0;at<s.audioTracks.numTracks;at++){{
   var ar=s.audioTracks[at];
   for(var ai=0;ai<ar.clips.numItems;ai++){{
     var ac=ar.clips[ai], isCurrentA=false;
     for(var qa=0;qa<current.length;qa++) if(ac===current[qa]) isCurrentA=true;
     if(!isCurrentA && ac.start.seconds>=oldEnd-0.000001)
       followers.push({{clip:ac,start:ac.start.seconds,end:ac.end.seconds}});
   }}
 }}

 for(var j=0;j<current.length;j++){{
   var te=new Time(); te.seconds=target; current[j].end=te;
 }}
 for(var k=0;k<followers.length;k++){{
   var ns=new Time(); ns.seconds=followers[k].start+delta;
   var ne=new Time(); ne.seconds=followers[k].end+delta;
   followers[k].clip.start=ns; followers[k].clip.end=ne;
 }}
 return "sequence="+s.name+";end="+oldEnd+"->"+target+
        ";delta="+delta+";trimmed="+current.length+
        ";shifted="+followers.length;
}})();"""
        return self._run_inline_jsx(source, "ripple_trim_linked_av_end")

    def split_linked_av_at(self, seconds: float, *,
                           sequence_index: int | None = None,
                           video_track_index: int = 0,
                           video_clip_index: int = 0,
                           target_audio_track_index: int | None = None):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        audio_target_expr = "srcATrackIndex" if target_audio_track_index is None else str(int(target_audio_track_index))
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}
 var v=s.videoTracks[{int(video_track_index)}].clips[{int(video_clip_index)}];
 if(!v) throw "Video clip not found";
 var cut={float(seconds)};
 var vs=v.start.seconds,ve=v.end.seconds,vin=v.inPoint.seconds,vout=v.outPoint.seconds;
 if(cut<=vs || cut>=ve) throw "Cut must be inside clip";
 try{{if(Math.abs(v.getSpeed()-1)>0.0001) throw "Only 1x clips are supported";}}catch(speedErr){{if(String(speedErr).indexOf("Only 1x")>=0) throw speedErr;}}

 var li=v.getLinkedItems();
 if(!li||li.numItems<2) throw "No linked audio item";
 var audioSig=null;
 for(var i=0;i<li.numItems;i++){{
   var x=li[i],nm="";
   try{{nm=x.projectItem?String(x.projectItem.name):"";}}catch(e){{}}
   if(nm&&nm!==String(v.projectItem.name)){{audioSig={{name:nm,start:x.start.seconds,end:x.end.seconds}};break;}}
 }}
 if(!audioSig) throw "Linked audio signature not found";
 var a=null,srcATrackIndex=-1,srcAClipIndex=-1;
 for(var at=0;at<s.audioTracks.numTracks&&!a;at++){{
   var tr=s.audioTracks[at];
   for(var ai=0;ai<tr.clips.numItems;ai++){{
     var ac=tr.clips[ai],nm2="";
     try{{nm2=ac.projectItem?String(ac.projectItem.name):String(ac.name);}}catch(e2){{nm2=String(ac.name);}}
     if(nm2===audioSig.name&&Math.abs(ac.start.seconds-audioSig.start)<0.0005&&Math.abs(ac.end.seconds-audioSig.end)<0.0005){{a=ac;srcATrackIndex=at;break;}}
   }}
 }}
 if(!a) throw "Linked audio clip not found";
 var as=a.start.seconds,ae=a.end.seconds,ain=a.inPoint.seconds,aout=a.outPoint.seconds;
 if(Math.abs(as-vs)>0.001||Math.abs(ae-ve)>0.001) throw "Linked A/V boundaries differ";
 var offset=cut-vs;

 var vCutOut=new Time();vCutOut.seconds=vin+offset;v.outPoint=vCutOut;
 var vLeftEnd=new Time();vLeftEnd.seconds=cut;v.end=vLeftEnd;
 var aCutOut=new Time();aCutOut.seconds=ain+offset;a.outPoint=aCutOut;
 var aLeftEnd=new Time();aLeftEnd.seconds=cut;a.end=aLeftEnd;

 var vtr=s.videoTracks[{int(video_track_index)}];
 var atr=s.audioTracks[{audio_target_expr}];
 var vb=vtr.clips.numItems,ab=atr.clips.numItems;
 var vok=vtr.insertClip(v.projectItem,cut);
 var aok=atr.insertClip(a.projectItem,cut);
 $.sleep(150);
 if(vtr.clips.numItems<=vb||atr.clips.numItems<=ab) throw "Right-side insert failed";
 var rv=null,ra=null;
 for(var vi=0;vi<vtr.clips.numItems;vi++){{var q=vtr.clips[vi];if(vi!=={int(video_clip_index)}&&Math.abs(q.start.seconds-cut)<0.05){{rv=q;break;}}}}
 for(var aj=0;aj<atr.clips.numItems;aj++){{var z=atr.clips[aj];if(aj!==srcAClipIndex&&Math.abs(z.start.seconds-cut)<0.05){{ra=z;break;}}}}
 if(!rv||!ra) throw "Right-side clip lookup failed";

 var t=new Time();t.seconds=vin+offset;rv.inPoint=t;
 t=new Time();t.seconds=vout;rv.outPoint=t;
 t=new Time();t.seconds=cut;rv.start=t;
 t=new Time();t.seconds=ve;rv.end=t;
 t=new Time();t.seconds=ain+offset;ra.inPoint=t;
 t=new Time();t.seconds=aout;ra.outPoint=t;
 t=new Time();t.seconds=cut;ra.start=t;
 t=new Time();t.seconds=ae;ra.end=t;

 for(var vt=0;vt<s.videoTracks.numTracks;vt++)for(var vx=0;vx<s.videoTracks[vt].clips.numItems;vx++)s.videoTracks[vt].clips[vx].setSelected(0,0);
 for(var aa=0;aa<s.audioTracks.numTracks;aa++)for(var ax=0;ax<s.audioTracks[aa].clips.numItems;ax++)s.audioTracks[aa].clips[ax].setSelected(0,0);
 rv.setSelected(1,1);ra.setSelected(1,1);var lr=s.linkSelection();
 return "sequence="+s.name+";cut="+cut+";vok="+vok+";aok="+aok+
        ";leftV="+v.start.seconds+"-"+v.end.seconds+"|"+v.inPoint.seconds+"-"+v.outPoint.seconds+
        ";rightV="+rv.start.seconds+"-"+rv.end.seconds+"|"+rv.inPoint.seconds+"-"+rv.outPoint.seconds+
        ";leftA="+a.start.seconds+"-"+a.end.seconds+"|"+a.inPoint.seconds+"-"+a.outPoint.seconds+
        ";rightA="+ra.start.seconds+"-"+ra.end.seconds+"|"+ra.inPoint.seconds+"-"+ra.outPoint.seconds+
        ";link="+lr;
}})();"""
        return self._run_inline_jsx(source, "split_linked_av")

    def ripple_delete_linked_av(self, *,
                                sequence_index: int | None = None,
                                video_track_index: int = 0,
                                video_clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var vc=s.videoTracks[{int(video_track_index)}].clips[{int(video_clip_index)}];
 if(!vc) throw "Video clip not found";
 var start=vc.start.seconds, end=vc.end.seconds, dur=end-start;
 var linked=vc.getLinkedItems();
 if(!linked || linked.numItems<1) throw "No linked items";

 var doomed=[];
 for(var i=0;i<linked.numItems;i++) doomed.push(linked[i]);

 var followers=[];
 for(var vt=0;vt<s.videoTracks.numTracks;vt++){{
   var tr=s.videoTracks[vt];
   for(var vi=0;vi<tr.clips.numItems;vi++){{
     var c=tr.clips[vi], isDoomed=false;
     for(var d=0;d<doomed.length;d++) if(c===doomed[d]) isDoomed=true;
     if(!isDoomed && c.start.seconds>=end-0.000001)
       followers.push({{clip:c,start:c.start.seconds,end:c.end.seconds}});
   }}
 }}
 for(var at=0;at<s.audioTracks.numTracks;at++){{
   var ar=s.audioTracks[at];
   for(var ai=0;ai<ar.clips.numItems;ai++){{
     var ac=ar.clips[ai], isDoomedA=false;
     for(var da=0;da<doomed.length;da++) if(ac===doomed[da]) isDoomedA=true;
     if(!isDoomedA && ac.start.seconds>=end-0.000001)
       followers.push({{clip:ac,start:ac.start.seconds,end:ac.end.seconds}});
   }}
 }}

 for(var r=doomed.length-1;r>=0;r--) doomed[r].remove(0,0);
 $.sleep(80);

 for(var j=0;j<followers.length;j++){{
   var ns=new Time(); ns.seconds=followers[j].start-dur;
   var ne=new Time(); ne.seconds=followers[j].end-dur;
   followers[j].clip.start=ns; followers[j].clip.end=ne;
 }}
 return "sequence="+s.name+";deletedItems="+doomed.length+
        ";duration="+dur+";shifted="+followers.length;
}})();"""
        return self._run_inline_jsx(source, "ripple_delete_linked_av")

    def remove_linked_av(self, *,
                         sequence_index: int | None = None,
                         video_track_index: int = 0,
                         video_clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 var v=s.videoTracks[{int(video_track_index)}].clips[{int(video_clip_index)}];
 if(!v)throw "Video clip not found";
 var li=v.getLinkedItems();if(!li||li.numItems<2)throw "No linked audio item";
 var sig=null;
 for(var i=0;i<li.numItems;i++){{
   var x=li[i],nm="";
   try{{nm=x.projectItem?String(x.projectItem.name):"";}}catch(e){{}}
   if(nm&&nm!==String(v.projectItem.name)){{sig={{name:nm,start:x.start.seconds,end:x.end.seconds}};break;}}
 }}
 if(!sig)throw "Linked audio signature not found";
 var a=null;
 for(var at=0;at<s.audioTracks.numTracks&&!a;at++){{
   var tr=s.audioTracks[at];
   for(var ai=0;ai<tr.clips.numItems;ai++){{
     var c=tr.clips[ai],nm2="";
     try{{nm2=c.projectItem?String(c.projectItem.name):String(c.name);}}catch(e2){{nm2=String(c.name);}}
     if(nm2===sig.name&&Math.abs(c.start.seconds-sig.start)<0.0005&&Math.abs(c.end.seconds-sig.end)<0.0005){{a=c;break;}}
   }}
 }}
 if(!a)throw "Linked audio clip not found";
 var vs=v.start.seconds,ve=v.end.seconds,as=a.start.seconds,ae=a.end.seconds;
 a.remove(0,0);v.remove(0,0);$.sleep(80);
 return "sequence="+s.name+";video="+vs+"-"+ve+";audio="+as+"-"+ae;
}})();"""
        return self._run_inline_jsx(source, "remove_linked_av")

    def get_linked_audio_locations(self, video_clip_indices: list[int], *,
                                   sequence_index: int | None = None,
                                   source_video_track_index: int = 0):
        indices = sorted({int(x) for x in video_clip_indices})
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        idx_js = json.dumps(indices)
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};if(!s)throw "Sequence not found";
 var idx={idx_js},out=[];
 for(var n=0;n<idx.length;n++){{
   var v=s.videoTracks[{int(source_video_track_index)}].clips[idx[n]];
   if(!v)throw "Video clip missing: "+idx[n];
   var li=v.getLinkedItems();if(!li||li.numItems<2)throw "No linked audio for video index "+idx[n];
   var sig=null;
   for(var i=0;i<li.numItems;i++){{
     var x=li[i],nm="";
     try{{nm=x.projectItem?String(x.projectItem.name):"";}}catch(e){{}}
     if(nm&&nm!==String(v.projectItem.name)){{sig={{name:nm,start:x.start.seconds,end:x.end.seconds}};break;}}
   }}
   if(!sig)throw "Linked audio signature missing";
   var found=false;
   for(var at=0;at<s.audioTracks.numTracks&&!found;at++){{
     var tr=s.audioTracks[at];
     for(var ai=0;ai<tr.clips.numItems;ai++){{
       var a=tr.clips[ai],nm2="";
       try{{nm2=a.projectItem?String(a.projectItem.name):String(a.name);}}catch(e2){{nm2=String(a.name);}}
       if(nm2===sig.name&&Math.abs(a.start.seconds-sig.start)<0.0005&&Math.abs(a.end.seconds-sig.end)<0.0005){{
         out.push(idx[n]+"^"+at+"^"+ai);found=true;break;
       }}
     }}
   }}
   if(!found)throw "Linked audio clip not found for video index "+idx[n];
 }}
 return out.join("~");
}})();"""
        rows = self._run_inline_jsx(source, "linked_audio_locations")
        payload = ""
        for row in rows:
            if row.get("status") == "OK":
                payload = row.get("data", "")
                break
        out = []
        for rec in payload.split("~") if payload else []:
            parts = rec.split("^")
            if len(parts) >= 3:
                out.append({
                    "video_clip_index": int(parts[0]),
                    "audio_track_index": int(parts[1]),
                    "audio_clip_index": int(parts[2]),
                })
        return out

    def clone_linked_av_group_to_tracks(self, video_clip_indices: list[int],
                                        target_video_track_index: int,
                                        target_audio_track_index: int, *,
                                        sequence_index: int | None = None,
                                        source_video_track_index: int = 0,
                                        copy_transitions: bool = True):
        indices = sorted({int(x) for x in video_clip_indices})
        if not indices:
            return []
        locations = self.get_linked_audio_locations(
            indices,
            sequence_index=sequence_index,
            source_video_track_index=source_video_track_index,
        )
        tracks = {x["audio_track_index"] for x in locations}
        if len(tracks) != 1:
            raise ValueError("All linked audio clips must be on the same source audio track")
        source_audio_track_index = next(iter(tracks))
        audio_indices = [x["audio_clip_index"] for x in locations]
        results = []
        for clip_index in indices:
            results.append(self.clone_linked_av_to_tracks(
                target_video_track_index,
                target_audio_track_index,
                sequence_index=sequence_index,
                source_video_track_index=source_video_track_index,
                video_clip_index=clip_index,
            ))
        if copy_transitions:
            results.append(self.copy_video_group_transitions(
                indices,
                sequence_index=sequence_index,
                source_video_track_index=source_video_track_index,
                target_video_track_index=target_video_track_index,
            ))
            results.append(self.copy_audio_group_transitions(
                audio_indices,
                sequence_index=sequence_index,
                source_audio_track_index=source_audio_track_index,
                target_audio_track_index=target_audio_track_index,
            ))
        return results

    def move_linked_av_group_to_tracks(self, video_clip_indices: list[int],
                                       target_video_track_index: int,
                                       target_audio_track_index: int, *,
                                       sequence_index: int | None = None,
                                       source_video_track_index: int = 0,
                                       copy_transitions: bool = True):
        indices = sorted({int(x) for x in video_clip_indices})
        results = self.clone_linked_av_group_to_tracks(
            indices,
            target_video_track_index,
            target_audio_track_index,
            sequence_index=sequence_index,
            source_video_track_index=source_video_track_index,
            copy_transitions=copy_transitions,
        )
        for clip_index in sorted(indices, reverse=True):
            results.append(self.remove_linked_av(
                sequence_index=sequence_index,
                video_track_index=source_video_track_index,
                video_clip_index=clip_index,
            ))
        return results

    def move_linked_av_pairs_to_tracks(self, video_clip_indices: list[int],
                                      target_video_track_index: int,
                                      target_audio_track_index: int, *,
                                      sequence_index: int | None = None,
                                      source_video_track_index: int = 0):
        # Same two-phase strategy as video-only batch move: clone all pairs in
        # ascending order, then delete source pairs in descending index order.
        indices = sorted({int(x) for x in video_clip_indices})
        results = []
        for clip_index in indices:
            results.append(self.clone_linked_av_to_tracks(
                target_video_track_index,
                target_audio_track_index,
                sequence_index=sequence_index,
                source_video_track_index=source_video_track_index,
                video_clip_index=clip_index,
            ))
        for clip_index in sorted(indices, reverse=True):
            results.append(self.remove_linked_av(
                sequence_index=sequence_index,
                video_track_index=source_video_track_index,
                video_clip_index=clip_index,
            ))
        return results

    def clone_linked_av_to_tracks(self, target_video_track_index: int,
                                 target_audio_track_index: int, *,
                                 sequence_index: int | None = None,
                                 source_video_track_index: int = 0,
                                 video_clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignoreOpen){{}}

 var srcVTrack=s.videoTracks[{int(source_video_track_index)}];
 var dstVTrack=s.videoTracks[{int(target_video_track_index)}];
 var dstATrack=s.audioTracks[{int(target_audio_track_index)}];
 if(!srcVTrack||!dstVTrack||!dstATrack) throw "Target/source track missing";
 var srcV=srcVTrack.clips[{int(video_clip_index)}];
 if(!srcV) throw "Source video clip not found";

 var linked=srcV.getLinkedItems();
 if(!linked || linked.numItems<2) throw "No linked audio item";
 var audioSig=null;
 for(var li=0;li<linked.numItems;li++){{
   var lx=linked[li],lpi="";
   try{{lpi=lx.projectItem?String(lx.projectItem.name):"";}}catch(sigErr){{}}
   if(lpi && lpi!==String(srcV.projectItem.name)){{
     audioSig={{name:lpi,start:lx.start.seconds,end:lx.end.seconds}};
     break;
   }}
 }}
 if(!audioSig) throw "Linked audio signature not found";
 var srcA=null, srcATrackIndex=-1, srcAClipIndex=-1;
 for(var at=0;at<s.audioTracks.numTracks && !srcA;at++){{
   var ar=s.audioTracks[at];
   for(var ai=0;ai<ar.clips.numItems;ai++){{
     var ac=ar.clips[ai],acName="";
     try{{acName=ac.projectItem?String(ac.projectItem.name):String(ac.name);}}catch(nameErr){{acName=String(ac.name);}}
     if(acName===audioSig.name &&
        Math.abs(ac.start.seconds-audioSig.start)<0.0005 &&
        Math.abs(ac.end.seconds-audioSig.end)<0.0005){{
       srcA=ac;srcATrackIndex=at;srcAClipIndex=ai;break;
     }}
   }}
 }}
 if(!srcA) throw "Linked audio clip not found";

 function snapComponents(clip){{
   var state=[];
   for(var ci=0;ci<clip.components.numItems;ci++){{
     var sc=clip.components[ci];
     var cs={{match:String(sc.matchName),display:String(sc.displayName),props:[]}};
     for(var pi=0;pi<sc.properties.numItems;pi++){{
       var sp=sc.properties[pi],ps={{index:pi,value:null,keys:[]}};
       try{{ps.value=sp.getValue();}}catch(e0){{}}
       try{{
         var ks=sp.getKeys();
         if(ks&&ks.length){{
           for(var ki=0;ki<ks.length;ki++){{
             var kt=ks[ki],kv=null;
             try{{kv=sp.getValueAtKey(kt);}}catch(e1){{}}
             ps.keys.push({{seconds:kt.seconds,value:kv}});
           }}
         }}
       }}catch(e2){{}}
       cs.props.push(ps);
     }}
     state.push(cs);
   }}
   return state;
 }}
 function restoreComponents(clip,state){{
   var props=0,keys=0;
   for(var si=0;si<state.length;si++){{
     var dc=null;
     for(var di=0;di<clip.components.numItems;di++){{
       if(String(clip.components[di].matchName)===state[si].match){{dc=clip.components[di];break;}}
     }}
     if(!dc) continue;
     for(var pj=0;pj<state[si].props.length;pj++){{
       var snap=state[si].props[pj];
       if(snap.index>=dc.properties.numItems) continue;
       var dp=dc.properties[snap.index];
       if(snap.keys&&snap.keys.length){{
         try{{
           dp.setTimeVarying(true);
           for(var kk=0;kk<snap.keys.length;kk++){{
             var tm=new Time();tm.seconds=snap.keys[kk].seconds;
             dp.addKey(tm);dp.setValueAtKey(tm,snap.keys[kk].value,true);keys++;
           }}
         }}catch(e3){{}}
       }}else{{
         try{{dp.setValue(snap.value,true);props++;}}catch(e4){{}}
       }}
     }}
   }}
   return {{props:props,keys:keys}};
 }}

 var vStart=srcV.start.seconds,vEnd=srcV.end.seconds,vIn=srcV.inPoint.seconds,vOut=srcV.outPoint.seconds;
 var aStart=srcA.start.seconds,aEnd=srcA.end.seconds,aIn=srcA.inPoint.seconds,aOut=srcA.outPoint.seconds;
 var vItem=srcV.projectItem,aItem=srcA.projectItem;
 if(!vItem||!aItem) throw "Project item unavailable";
 var vState=snapComponents(srcV),aState=snapComponents(srcA);

 var beforeV=dstVTrack.clips.numItems,beforeA=dstATrack.clips.numItems;
 var vok=dstVTrack.insertClip(vItem,vStart);
 var aok=dstATrack.insertClip(aItem,aStart);
 $.sleep(180);
 if(dstVTrack.clips.numItems<=beforeV||dstATrack.clips.numItems<=beforeA) throw "Destination insert failed";

 var dstV=null,dstVOrdinal=-1;
 for(var vi=0;vi<dstVTrack.clips.numItems;vi++){{
   var vc=dstVTrack.clips[vi];
   if(Math.abs(vc.start.seconds-vStart)<0.0005&&vc.projectItem===vItem){{dstV=vc;dstVOrdinal=vi;break;}}
 }}
 if(!dstV){{dstVOrdinal=dstVTrack.clips.numItems-1;dstV=dstVTrack.clips[dstVOrdinal];}}
 var dstA=null,dstAOrdinal=-1;
 for(var aj=0;aj<dstATrack.clips.numItems;aj++){{
   var ac2=dstATrack.clips[aj];
   if(Math.abs(ac2.start.seconds-aStart)<0.0005&&ac2.projectItem===aItem){{dstA=ac2;dstAOrdinal=aj;break;}}
 }}
 if(!dstA){{dstAOrdinal=dstATrack.clips.numItems-1;dstA=dstATrack.clips[dstAOrdinal];}}

 var t=new Time();t.seconds=vIn;dstV.inPoint=t;
 t=new Time();t.seconds=vOut;dstV.outPoint=t;
 t=new Time();t.seconds=vStart;dstV.start=t;
 t=new Time();t.seconds=vEnd;dstV.end=t;
 t=new Time();t.seconds=aIn;dstA.inPoint=t;
 t=new Time();t.seconds=aOut;dstA.outPoint=t;
 t=new Time();t.seconds=aStart;dstA.start=t;
 t=new Time();t.seconds=aEnd;dstA.end=t;

 var rebuiltEffects=0;
 try{{
   app.enableQE();var qs=qe.project.getActiveSequence();
   var qtr=qs.getVideoTrackAt({int(target_video_track_index)}),qclip=null,seen=-1;
   for(var qi=0;qi<qtr.numItems;qi++){{
     var qit=qtr.getItemAt(qi);
     if(qit&&qit.type==="Clip"){{seen++;if(seen===dstVOrdinal){{qclip=qit;break;}}}}
   }}
   if(qclip){{
     for(var esi=vState.length-1;esi>=0;esi--){{
       var exists=false;
       for(var edi=0;edi<dstV.components.numItems;edi++){{
         if(String(dstV.components[edi].matchName)===vState[esi].match){{exists=true;break;}}
       }}
       if(!exists&&vState[esi].match!=="AE.ADBE Opacity"&&vState[esi].match!=="AE.ADBE Motion"){{
         var qeEff=qe.project.getVideoEffectByName(vState[esi].display);
         if(qeEff){{var added=qclip.addVideoEffect(qeEff);if(added){{rebuiltEffects++;$.sleep(160);}}}}
       }}
     }}
   }}
 }}catch(effectErr){{}}

 var rebuiltAudioEffects=0;
 try{{
   app.enableQE();try{{s.openInTimeline();}}catch(ignoreAudioOpen){{}}$.sleep(80);
   var qsa=qe.project.getActiveSequence();
   var qat=qsa.getAudioTrackAt({int(target_audio_track_index)}),qac=null,aseen=-1;
   for(var aq=0;aq<qat.numItems;aq++){{
     var ait=qat.getItemAt(aq);
     if(ait&&ait.type==="Clip"){{aseen++;if(aseen===dstAOrdinal){{qac=ait;break;}}}}
   }}
   if(qac){{
     for(var asi=aState.length-1;asi>=0;asi--){{
       var aexists=false;
       for(var adi=0;adi<dstA.components.numItems;adi++){{
         if(String(dstA.components[adi].matchName)===aState[asi].match){{aexists=true;break;}}
       }}
       if(!aexists &&
          aState[asi].match!=="Internal Volume Stereo" &&
          aState[asi].match!=="Internal Channel Volume Stereo"){{
         var aeff=qe.project.getAudioEffectByName(aState[asi].display,0);
         if(aeff){{var aadded=qac.addAudioEffect(aeff);if(aadded){{rebuiltAudioEffects++;$.sleep(160);}}}}
       }}
     }}
   }}
 }}catch(audioEffectErr){{}}

 var vr=restoreComponents(dstV,vState);
 var ar=restoreComponents(dstA,aState);

 for(var vt=0;vt<s.videoTracks.numTracks;vt++)
   for(var vx=0;vx<s.videoTracks[vt].clips.numItems;vx++)s.videoTracks[vt].clips[vx].setSelected(0,0);
 for(var aa=0;aa<s.audioTracks.numTracks;aa++)
   for(var ax=0;ax<s.audioTracks[aa].clips.numItems;ax++)s.audioTracks[aa].clips[ax].setSelected(0,0);
 dstV.setSelected(1,1);dstA.setSelected(1,1);
 var linkRet=s.linkSelection();
 var vlinks=dstV.getLinkedItems(),alinks=dstA.getLinkedItems();

 return "sequence="+s.name+
        ";video="+{int(source_video_track_index)}+"->"+{int(target_video_track_index)}+
        ";audio="+srcATrackIndex+"->"+{int(target_audio_track_index)}+
        ";vok="+vok+";aok="+aok+
        ";rebuiltEffects="+rebuiltEffects+
        ";rebuiltAudioEffects="+rebuiltAudioEffects+
        ";vProps="+vr.props+";vKeys="+vr.keys+
        ";aProps="+ar.props+";aKeys="+ar.keys+
        ";link="+linkRet+
        ";vLinked="+(vlinks?vlinks.numItems:0)+
        ";aLinked="+(alinks?alinks.numItems:0);
}})();"""
        return self._run_inline_jsx(source, "clone_linked_av_to_tracks")

    def move_linked_av_to_tracks(self, target_video_track_index: int,
                                 target_audio_track_index: int, *,
                                 sequence_index: int | None = None,
                                 source_video_track_index: int = 0,
                                 video_clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignoreOpen){{}}

 var srcVTrack=s.videoTracks[{int(source_video_track_index)}];
 var dstVTrack=s.videoTracks[{int(target_video_track_index)}];
 var dstATrack=s.audioTracks[{int(target_audio_track_index)}];
 if(!srcVTrack||!dstVTrack||!dstATrack) throw "Target/source track missing";
 var srcV=srcVTrack.clips[{int(video_clip_index)}];
 if(!srcV) throw "Source video clip not found";

 var linked=srcV.getLinkedItems();
 if(!linked || linked.numItems<2) throw "No linked audio item";
 var audioSig=null;
 for(var li=0;li<linked.numItems;li++){{
   var lx=linked[li],lpi="";
   try{{lpi=lx.projectItem?String(lx.projectItem.name):"";}}catch(sigErr){{}}
   if(lpi && lpi!==String(srcV.projectItem.name)){{
     audioSig={{name:lpi,start:lx.start.seconds,end:lx.end.seconds}};
     break;
   }}
 }}
 if(!audioSig) throw "Linked audio signature not found";
 var srcA=null, srcATrackIndex=-1, srcAClipIndex=-1;
 for(var at=0;at<s.audioTracks.numTracks && !srcA;at++){{
   var ar=s.audioTracks[at];
   for(var ai=0;ai<ar.clips.numItems;ai++){{
     var ac=ar.clips[ai],acName="";
     try{{acName=ac.projectItem?String(ac.projectItem.name):String(ac.name);}}catch(nameErr){{acName=String(ac.name);}}
     if(acName===audioSig.name &&
        Math.abs(ac.start.seconds-audioSig.start)<0.0005 &&
        Math.abs(ac.end.seconds-audioSig.end)<0.0005){{
       srcA=ac;srcATrackIndex=at;srcAClipIndex=ai;break;
     }}
   }}
 }}
 if(!srcA) throw "Linked audio clip not found";

 function snapComponents(clip){{
   var state=[];
   for(var ci=0;ci<clip.components.numItems;ci++){{
     var sc=clip.components[ci];
     var cs={{match:String(sc.matchName),display:String(sc.displayName),props:[]}};
     for(var pi=0;pi<sc.properties.numItems;pi++){{
       var sp=sc.properties[pi],ps={{index:pi,value:null,keys:[]}};
       try{{ps.value=sp.getValue();}}catch(e0){{}}
       try{{
         var ks=sp.getKeys();
         if(ks&&ks.length){{
           for(var ki=0;ki<ks.length;ki++){{
             var kt=ks[ki],kv=null;
             try{{kv=sp.getValueAtKey(kt);}}catch(e1){{}}
             ps.keys.push({{seconds:kt.seconds,value:kv}});
           }}
         }}
       }}catch(e2){{}}
       cs.props.push(ps);
     }}
     state.push(cs);
   }}
   return state;
 }}
 function restoreComponents(clip,state){{
   var props=0,keys=0;
   for(var si=0;si<state.length;si++){{
     var dc=null;
     for(var di=0;di<clip.components.numItems;di++){{
       if(String(clip.components[di].matchName)===state[si].match){{dc=clip.components[di];break;}}
     }}
     if(!dc) continue;
     for(var pj=0;pj<state[si].props.length;pj++){{
       var snap=state[si].props[pj];
       if(snap.index>=dc.properties.numItems) continue;
       var dp=dc.properties[snap.index];
       if(snap.keys&&snap.keys.length){{
         try{{
           dp.setTimeVarying(true);
           for(var kk=0;kk<snap.keys.length;kk++){{
             var tm=new Time();tm.seconds=snap.keys[kk].seconds;
             dp.addKey(tm);dp.setValueAtKey(tm,snap.keys[kk].value,true);keys++;
           }}
         }}catch(e3){{}}
       }}else{{
         try{{dp.setValue(snap.value,true);props++;}}catch(e4){{}}
       }}
     }}
   }}
   return {{props:props,keys:keys}};
 }}

 var vStart=srcV.start.seconds,vEnd=srcV.end.seconds,vIn=srcV.inPoint.seconds,vOut=srcV.outPoint.seconds;
 var aStart=srcA.start.seconds,aEnd=srcA.end.seconds,aIn=srcA.inPoint.seconds,aOut=srcA.outPoint.seconds;
 var vItem=srcV.projectItem,aItem=srcA.projectItem;
 if(!vItem||!aItem) throw "Project item unavailable";
 var vState=snapComponents(srcV),aState=snapComponents(srcA);

 var beforeV=dstVTrack.clips.numItems,beforeA=dstATrack.clips.numItems;
 var vok=dstVTrack.insertClip(vItem,vStart);
 var aok=dstATrack.insertClip(aItem,aStart);
 $.sleep(180);
 if(dstVTrack.clips.numItems<=beforeV||dstATrack.clips.numItems<=beforeA) throw "Destination insert failed";

 var dstV=null,dstVOrdinal=-1;
 for(var vi=0;vi<dstVTrack.clips.numItems;vi++){{
   var vc=dstVTrack.clips[vi];
   if(Math.abs(vc.start.seconds-vStart)<0.0005&&vc.projectItem===vItem){{dstV=vc;dstVOrdinal=vi;break;}}
 }}
 if(!dstV){{dstVOrdinal=dstVTrack.clips.numItems-1;dstV=dstVTrack.clips[dstVOrdinal];}}
 var dstA=null,dstAOrdinal=-1;
 for(var aj=0;aj<dstATrack.clips.numItems;aj++){{
   var ac2=dstATrack.clips[aj];
   if(Math.abs(ac2.start.seconds-aStart)<0.0005&&ac2.projectItem===aItem){{dstA=ac2;dstAOrdinal=aj;break;}}
 }}
 if(!dstA){{dstAOrdinal=dstATrack.clips.numItems-1;dstA=dstATrack.clips[dstAOrdinal];}}

 var t=new Time();t.seconds=vIn;dstV.inPoint=t;
 t=new Time();t.seconds=vOut;dstV.outPoint=t;
 t=new Time();t.seconds=vStart;dstV.start=t;
 t=new Time();t.seconds=vEnd;dstV.end=t;
 t=new Time();t.seconds=aIn;dstA.inPoint=t;
 t=new Time();t.seconds=aOut;dstA.outPoint=t;
 t=new Time();t.seconds=aStart;dstA.start=t;
 t=new Time();t.seconds=aEnd;dstA.end=t;

 var rebuiltEffects=0;
 try{{
   app.enableQE();var qs=qe.project.getActiveSequence();
   var qtr=qs.getVideoTrackAt({int(target_video_track_index)}),qclip=null,seen=-1;
   for(var qi=0;qi<qtr.numItems;qi++){{
     var qit=qtr.getItemAt(qi);
     if(qit&&qit.type==="Clip"){{seen++;if(seen===dstVOrdinal){{qclip=qit;break;}}}}
   }}
   if(qclip){{
     for(var esi=vState.length-1;esi>=0;esi--){{
       var exists=false;
       for(var edi=0;edi<dstV.components.numItems;edi++){{
         if(String(dstV.components[edi].matchName)===vState[esi].match){{exists=true;break;}}
       }}
       if(!exists&&vState[esi].match!=="AE.ADBE Opacity"&&vState[esi].match!=="AE.ADBE Motion"){{
         var qeEff=qe.project.getVideoEffectByName(vState[esi].display);
         if(qeEff){{var added=qclip.addVideoEffect(qeEff);if(added){{rebuiltEffects++;$.sleep(160);}}}}
       }}
     }}
   }}
 }}catch(effectErr){{}}

 var rebuiltAudioEffects=0;
 try{{
   app.enableQE();try{{s.openInTimeline();}}catch(ignoreAudioOpen){{}}$.sleep(80);
   var qsa=qe.project.getActiveSequence();
   var qat=qsa.getAudioTrackAt({int(target_audio_track_index)}),qac=null,aseen=-1;
   for(var aq=0;aq<qat.numItems;aq++){{
     var ait=qat.getItemAt(aq);
     if(ait&&ait.type==="Clip"){{aseen++;if(aseen===dstAOrdinal){{qac=ait;break;}}}}
   }}
   if(qac){{
     for(var asi=aState.length-1;asi>=0;asi--){{
       var aexists=false;
       for(var adi=0;adi<dstA.components.numItems;adi++){{
         if(String(dstA.components[adi].matchName)===aState[asi].match){{aexists=true;break;}}
       }}
       if(!aexists &&
          aState[asi].match!=="Internal Volume Stereo" &&
          aState[asi].match!=="Internal Channel Volume Stereo"){{
         var aeff=qe.project.getAudioEffectByName(aState[asi].display,0);
         if(aeff){{var aadded=qac.addAudioEffect(aeff);if(aadded){{rebuiltAudioEffects++;$.sleep(160);}}}}
       }}
     }}
   }}
 }}catch(audioEffectErr){{}}

 var vr=restoreComponents(dstV,vState);
 var ar=restoreComponents(dstA,aState);

 srcV.remove(0,0);srcA.remove(0,0);$.sleep(100);

 for(var vt=0;vt<s.videoTracks.numTracks;vt++)
   for(var vx=0;vx<s.videoTracks[vt].clips.numItems;vx++)s.videoTracks[vt].clips[vx].setSelected(0,0);
 for(var aa=0;aa<s.audioTracks.numTracks;aa++)
   for(var ax=0;ax<s.audioTracks[aa].clips.numItems;ax++)s.audioTracks[aa].clips[ax].setSelected(0,0);
 dstV.setSelected(1,1);dstA.setSelected(1,1);
 var linkRet=s.linkSelection();
 var vlinks=dstV.getLinkedItems(),alinks=dstA.getLinkedItems();

 return "sequence="+s.name+
        ";video="+{int(source_video_track_index)}+"->"+{int(target_video_track_index)}+
        ";audio="+srcATrackIndex+"->"+{int(target_audio_track_index)}+
        ";vok="+vok+";aok="+aok+
        ";rebuiltEffects="+rebuiltEffects+
        ";rebuiltAudioEffects="+rebuiltAudioEffects+
        ";vProps="+vr.props+";vKeys="+vr.keys+
        ";aProps="+ar.props+";aKeys="+ar.keys+
        ";link="+linkRet+
        ";vLinked="+(vlinks?vlinks.numItems:0)+
        ";aLinked="+(alinks?alinks.numItems:0);
}})();"""
        return self._run_inline_jsx(source, "move_linked_av_to_tracks")

    def move_linked_av(self, delta_seconds: float, *,
                       sequence_index: int | None = None,
                       video_track_index: int = 0,
                       video_clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var vc=s.videoTracks[{int(video_track_index)}].clips[{int(video_clip_index)}];
 if(!vc) throw "Video clip not found";
 var linked=vc.getLinkedItems();
 if(!linked || linked.numItems<1) throw "No linked items";
 var delta={float(delta_seconds)}, moved=0, out=[];
 for(var i=0;i<linked.numItems;i++){{
   var c=linked[i];
   var bs=c.start.seconds, be=c.end.seconds;
   var ns=new Time(); ns.seconds=bs+delta;
   var ne=new Time(); ne.seconds=be+delta;
   c.start=ns; c.end=ne;
   out.push(c.name+":"+bs+"-"+be+"->"+c.start.seconds+"-"+c.end.seconds);
   moved++;
 }}
 return "sequence="+s.name+";delta="+delta+";moved="+moved+";"+out.join("~");
}})();"""
        return self._run_inline_jsx(source, "move_linked_av")

    def trim_linked_av_start(self, seconds: float, *,
                             sequence_index: int | None = None,
                             video_track_index: int = 0,
                             video_clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var vc=s.videoTracks[{int(video_track_index)}].clips[{int(video_clip_index)}];
 if(!vc) throw "Video clip not found";
 var linked=vc.getLinkedItems();
 if(!linked || linked.numItems<1) throw "No linked items";
 var target={float(seconds)}, changed=0, out=[];
 for(var i=0;i<linked.numItems;i++){{
   var c=linked[i], before=c.start.seconds;
   var ts=new Time(); ts.seconds=target;
   c.start=ts;
   out.push(c.name+":"+before+"->"+c.start.seconds);
   changed++;
 }}
 return "sequence="+s.name+";target="+target+";changed="+changed+";"+out.join("~");
}})();"""
        return self._run_inline_jsx(source, "trim_linked_av_start")

    def trim_linked_av_end(self, seconds: float, *,
                           sequence_index: int | None = None,
                           video_track_index: int = 0,
                           video_clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var vc=s.videoTracks[{int(video_track_index)}].clips[{int(video_clip_index)}];
 if(!vc) throw "Video clip not found";
 var linked=vc.getLinkedItems();
 if(!linked || linked.numItems<1) throw "No linked items";
 var target={float(seconds)}, changed=0, out=[];
 for(var i=0;i<linked.numItems;i++){{
   var c=linked[i], before=c.end.seconds;
   var te=new Time(); te.seconds=target;
   c.end=te;
   out.push(c.name+":"+before+"->"+c.end.seconds);
   changed++;
 }}
 return "sequence="+s.name+";target="+target+";changed="+changed+";"+out.join("~");
}})();"""
        return self._run_inline_jsx(source, "trim_linked_av_end")

    def ripple_delete_video_clip_dom(self, *,
                                     sequence_index: int | None = None,
                                     video_track_index: int = 0,
                                     clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var tr=s.videoTracks[{int(video_track_index)}];
 var c=tr.clips[{int(clip_index)}];
 if(!c) throw "Video clip not found";
 var start=c.start.seconds, end=c.end.seconds, dur=end-start;
 var followers=[];
 for(var i=0;i<tr.clips.numItems;i++){{
   if(i==={int(clip_index)}) continue;
   var x=tr.clips[i];
   if(x.start.seconds>=end-0.000001){{
     followers.push({{clip:x,start:x.start.seconds,end:x.end.seconds}});
   }}
 }}
 c.remove(0,0);
 $.sleep(80);
 for(var j=0;j<followers.length;j++){{
   var ns=new Time(); ns.seconds=followers[j].start-dur;
   var ne=new Time(); ne.seconds=followers[j].end-dur;
   followers[j].clip.start=ns;
   followers[j].clip.end=ne;
 }}
 return "sequence="+s.name+";deleted="+start+"-"+end+
        ";duration="+dur+";shifted="+followers.length+
        ";remaining="+tr.clips.numItems;
}})();"""
        return self._run_inline_jsx(source, "ripple_delete_video_dom")

    def ripple_trim_video_clip_end(self, seconds: float, *,
                                   sequence_index: int | None = None,
                                   video_track_index: int = 0,
                                   clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var tr=s.videoTracks[{int(video_track_index)}];
 var c=tr.clips[{int(clip_index)}];
 if(!c) throw "Video clip not found";
 var beforeEnd=c.end.seconds;
 var target={float(seconds)};
 var delta=target-beforeEnd;
 var followers=[];
 for(var i=0;i<tr.clips.numItems;i++){{
   if(i==={int(clip_index)}) continue;
   var x=tr.clips[i];
   if(x.start.seconds>=beforeEnd-0.000001){{
     followers.push({{clip:x,start:x.start.seconds,end:x.end.seconds}});
   }}
 }}
 var te=new Time(); te.seconds=target; c.end=te;
 for(var j=0;j<followers.length;j++){{
   var ns=new Time(); ns.seconds=followers[j].start+delta;
   var ne=new Time(); ne.seconds=followers[j].end+delta;
   followers[j].clip.start=ns;
   followers[j].clip.end=ne;
 }}
 return "sequence="+s.name+";end="+beforeEnd+"->"+c.end.seconds+
        ";delta="+delta+";shifted="+followers.length;
}})();"""
        return self._run_inline_jsx(source, "ripple_trim_video_end")

    def trim_video_clip_start(self, seconds: float, *,
                              sequence_index: int | None = None,
                              video_track_index: int = 0,
                              clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c) throw "Video clip not found";
 var beforeStart=c.start.seconds, beforeEnd=c.end.seconds;
 var t=new Time(); t.seconds={float(seconds)};
 c.start=t;
 return "sequence="+s.name+";start="+beforeStart+"->"+c.start.seconds+
        ";end="+beforeEnd+"->"+c.end.seconds;
}})();"""
        return self._run_inline_jsx(source, "trim_video_start")

    def trim_video_clip_end(self, seconds: float, *,
                            sequence_index: int | None = None,
                            video_track_index: int = 0,
                            clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c) throw "Video clip not found";
 var beforeStart=c.start.seconds, beforeEnd=c.end.seconds;
 var t=new Time(); t.seconds={float(seconds)};
 c.end=t;
 return "sequence="+s.name+";start="+beforeStart+"->"+c.start.seconds+
        ";end="+beforeEnd+"->"+c.end.seconds;
}})();"""
        return self._run_inline_jsx(source, "trim_video_end")

    def move_video_clip(self, start_seconds: float, *,
                        sequence_index: int | None = None,
                        video_track_index: int = 0,
                        clip_index: int = 0,
                        preserve_duration: bool = True):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c) throw "Video clip not found";
 var beforeStart=c.start.seconds, beforeEnd=c.end.seconds;
 var duration=beforeEnd-beforeStart;
 var ts=new Time(); ts.seconds={float(start_seconds)};
 c.start=ts;
 if({"true" if preserve_duration else "false"}){{
   var te=new Time(); te.seconds={float(start_seconds)}+duration;
   c.end=te;
 }}
 return "sequence="+s.name+";start="+beforeStart+"->"+c.start.seconds+
        ";end="+beforeEnd+"->"+c.end.seconds+
        ";duration="+duration;
}})();"""
        return self._run_inline_jsx(source, "move_video_clip")

    def insert_audio_project_item(self, item_name: str, seconds: float, *,
                                  sequence_index: int | None = None,
                                  audio_track_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        item_js = json.dumps(item_name, ensure_ascii=False)
        source = f"""#target premierepro
(function(){{
 function findItem(parent,name){{
   if(!parent||!parent.children)return null;
   for(var i=0;i<parent.children.numItems;i++){{
     var c=parent.children[i];
     if(c.name===name)return c;
     var r=findItem(c,name);if(r)return r;
   }}
   return null;
 }}
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var item=findItem(app.project.rootItem,{item_js});
 if(!item) throw "Project item not found: "+{item_js};
 var tr=s.audioTracks[{int(audio_track_index)}];
 if(!tr) throw "Audio track not found";
 var before=tr.clips.numItems;
 var ok=tr.insertClip(item,{float(seconds)});
 $.sleep(120);
 return "sequence="+s.name+";ok="+ok+";before="+before+
        ";after="+tr.clips.numItems+";seconds="+{float(seconds)};
}})();"""
        return self._run_inline_jsx(source, "insert_audio_project_item")

    def overwrite_audio_project_item(self, item_name: str, seconds: float, *,
                                     sequence_index: int | None = None,
                                     audio_track_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        item_js = json.dumps(item_name, ensure_ascii=False)
        source = f"""#target premierepro
(function(){{
 function findItem(parent,name){{
   if(!parent||!parent.children)return null;
   for(var i=0;i<parent.children.numItems;i++){{
     var c=parent.children[i];
     if(c.name===name)return c;
     var r=findItem(c,name);if(r)return r;
   }}
   return null;
 }}
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var item=findItem(app.project.rootItem,{item_js});
 if(!item) throw "Project item not found: "+{item_js};
 var tr=s.audioTracks[{int(audio_track_index)}];
 if(!tr) throw "Audio track not found";
 var before=tr.clips.numItems;
 var ok=tr.overwriteClip(item,{float(seconds)});
 $.sleep(120);
 return "sequence="+s.name+";ok="+ok+";before="+before+
        ";after="+tr.clips.numItems+";seconds="+{float(seconds)};
}})();"""
        return self._run_inline_jsx(source, "overwrite_audio_project_item")

    def insert_project_item(self, item_name: str, seconds: float, *,
                            sequence_index: int | None = None,
                            video_track_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        item_js = json.dumps(item_name, ensure_ascii=False)
        source = f"""#target premierepro
(function(){{
 function findItem(parent,name){{
   if(!parent||!parent.children)return null;
   for(var i=0;i<parent.children.numItems;i++){{
     var c=parent.children[i];
     if(c.name===name)return c;
     var r=findItem(c,name);if(r)return r;
   }}
   return null;
 }}
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var item=findItem(app.project.rootItem,{item_js});
 if(!item) throw "Project item not found: "+{item_js};
 var tr=s.videoTracks[{int(video_track_index)}];
 if(!tr) throw "Video track not found";
 var before=tr.clips.numItems;
 var ok=tr.insertClip(item,{float(seconds)});
 $.sleep(120);
 var after=tr.clips.numItems;
 return "sequence="+s.name+";ok="+ok+";before="+before+";after="+after+";seconds="+{float(seconds)};
}})();"""
        return self._run_inline_jsx(source, "insert_project_item")

    def overwrite_project_item(self, item_name: str, seconds: float, *,
                               sequence_index: int | None = None,
                               video_track_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        item_js = json.dumps(item_name, ensure_ascii=False)
        source = f"""#target premierepro
(function(){{
 function findItem(parent,name){{
   if(!parent||!parent.children)return null;
   for(var i=0;i<parent.children.numItems;i++){{
     var c=parent.children[i];
     if(c.name===name)return c;
     var r=findItem(c,name);if(r)return r;
   }}
   return null;
 }}
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var item=findItem(app.project.rootItem,{item_js});
 if(!item) throw "Project item not found: "+{item_js};
 var tr=s.videoTracks[{int(video_track_index)}];
 if(!tr) throw "Video track not found";
 var before=tr.clips.numItems;
 var ok=tr.overwriteClip(item,{float(seconds)});
 $.sleep(120);
 var after=tr.clips.numItems;
 return "sequence="+s.name+";ok="+ok+";before="+before+";after="+after+";seconds="+{float(seconds)};
}})();"""
        return self._run_inline_jsx(source, "overwrite_project_item")

    def move_video_clips_to_track(self, clip_indices: list[int], target_video_track_index: int, *,
                                  sequence_index: int | None = None,
                                  source_video_track_index: int = 0):
        # Clone in ascending timeline/index order so Track.insertClip() does not
        # ripple previously cloned later clips. Delete originals only after all
        # destination clips have been created.
        indices = sorted({int(x) for x in clip_indices})
        results = []
        for clip_index in indices:
            results.append(self.clone_video_clip_to_track(
                target_video_track_index,
                sequence_index=sequence_index,
                source_video_track_index=source_video_track_index,
                clip_index=clip_index,
            ))
        for clip_index in sorted(indices, reverse=True):
            results.append(self.remove_video_clip(
                sequence_index=sequence_index,
                video_track_index=source_video_track_index,
                clip_index=clip_index,
            ))
        return results

    def clone_video_clip_to_track(self, target_video_track_index: int, *,
                                 sequence_index: int | None = None,
                                 source_video_track_index: int = 0,
                                 clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var srcTrack=s.videoTracks[{int(source_video_track_index)}];
 var dstTrack=s.videoTracks[{int(target_video_track_index)}];
 if(!srcTrack || !dstTrack) throw "Video track not found";
 var src=srcTrack.clips[{int(clip_index)}];
 if(!src) throw "Source clip not found";
 var item=src.projectItem;
 if(!item) throw "Project item unavailable";

 var start=src.start.seconds, end=src.end.seconds;
 var inSec=src.inPoint.seconds, outSec=src.outPoint.seconds;

 // Snapshot clip-level state for components that also exist on a fresh insert.
 var state=[];
 for(var ci=0;ci<src.components.numItems;ci++){{
   var sc=src.components[ci], cs={{match:String(sc.matchName), display:String(sc.displayName), props:[]}};
   for(var pi=0;pi<sc.properties.numItems;pi++){{
     var sp=sc.properties[pi], ps={{index:pi, value:null, keys:[]}};
     try{{ps.value=sp.getValue();}}catch(ignore){{}}
     try{{
       var ks=sp.getKeys();
       if(ks && ks.length){{
         for(var ki=0;ki<ks.length;ki++){{
           var kt=ks[ki], kv=null;
           try{{kv=sp.getValueAtKey(kt);}}catch(ignore2){{}}
           ps.keys.push({{seconds:kt.seconds,value:kv}});
         }}
       }}
     }}catch(ignore3){{}}
     cs.props.push(ps);
   }}
   state.push(cs);
 }}

 var beforeDst=dstTrack.clips.numItems;
 var ok=dstTrack.insertClip(item,start);
 $.sleep(120);
 if(dstTrack.clips.numItems<=beforeDst) throw "Target insert did not create clip";

 var dst=null, dstOrdinal=-1;
 for(var i=0;i<dstTrack.clips.numItems;i++){{
   var c=dstTrack.clips[i];
   if(Math.abs(c.start.seconds-start)<0.0005 && c.projectItem===item){{dst=c;dstOrdinal=i;break;}}
 }}
 if(!dst){{dstOrdinal=dstTrack.clips.numItems-1;dst=dstTrack.clips[dstOrdinal];}}

 var ti=new Time(); ti.seconds=inSec; dst.inPoint=ti;
 var to=new Time(); to.seconds=outSec; dst.outPoint=to;
 var ts=new Time(); ts.seconds=start; dst.start=ts;
 var te=new Time(); te.seconds=end; dst.end=te;

 var restoredProps=0, restoredKeys=0, rebuiltEffects=0;
 // Recreate missing non-base video effects using the source component displayName.
 try{{
   app.enableQE();
   try{{s.openInTimeline();}}catch(ignoreOpen){{}}
   var qs=qe.project.getActiveSequence();
   var qtr=qs.getVideoTrackAt({int(target_video_track_index)});
   var qclip=null, seen=-1;
   for(var qi=0;qi<qtr.numItems;qi++){{
     var qit=qtr.getItemAt(qi);
     if(qit && qit.type==="Clip"){{
       seen++;
       if(seen===dstOrdinal){{qclip=qit;break;}}
     }}
   }}
   if(qclip){{
     for(var esi=state.length-1;esi>=0;esi--){{
       var exists=false;
       for(var edi=0;edi<dst.components.numItems;edi++){{
         if(String(dst.components[edi].matchName)===state[esi].match){{exists=true;break;}}
       }}
       if(!exists && state[esi].match!=="AE.ADBE Opacity" && state[esi].match!=="AE.ADBE Motion"){{
         var effectName=state[esi].display;
         var qeEff=qe.project.getVideoEffectByName(effectName);
         if(qeEff){{
           var added=qclip.addVideoEffect(qeEff);
           if(added){{rebuiltEffects++; $.sleep(180);}}
         }}
       }}
     }}
   }}
 }}catch(ignoreRebuild){{}}

 for(var si=0;si<state.length;si++){{
   var dc=null;
   for(var di=0;di<dst.components.numItems;di++){{
     if(String(dst.components[di].matchName)===state[si].match){{dc=dst.components[di];break;}}
   }}
   if(!dc) continue;
   for(var pj=0;pj<state[si].props.length;pj++){{
     var snap=state[si].props[pj];
     if(snap.index>=dc.properties.numItems) continue;
     var dp=dc.properties[snap.index];
     if(snap.keys && snap.keys.length){{
       try{{
         dp.setTimeVarying(true);
         for(var kk=0;kk<snap.keys.length;kk++){{
           var tm=new Time(); tm.seconds=snap.keys[kk].seconds;
           dp.addKey(tm);
           dp.setValueAtKey(tm,snap.keys[kk].value,true);
           restoredKeys++;
         }}
       }}catch(ignore4){{}}
     }} else {{
       try{{dp.setValue(snap.value,true); restoredProps++;}}catch(ignore5){{}}
     }}
   }}
 }}

 return "sequence="+s.name+";ok="+ok+
        ";srcTrack="+{int(source_video_track_index)}+
        ";dstTrack="+{int(target_video_track_index)}+
        ";start="+dst.start.seconds+";end="+dst.end.seconds+
        ";in="+dst.inPoint.seconds+";out="+dst.outPoint.seconds+
        ";rebuiltEffects="+rebuiltEffects+
        ";restoredProps="+restoredProps+";restoredKeys="+restoredKeys;
}})();"""
        return self._run_inline_jsx(source, "clone_video_to_track")

    def move_video_clip_to_track(self, target_video_track_index: int, *,
                                 sequence_index: int | None = None,
                                 source_video_track_index: int = 0,
                                 clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var srcTrack=s.videoTracks[{int(source_video_track_index)}];
 var dstTrack=s.videoTracks[{int(target_video_track_index)}];
 if(!srcTrack || !dstTrack) throw "Video track not found";
 var src=srcTrack.clips[{int(clip_index)}];
 if(!src) throw "Source clip not found";
 var item=src.projectItem;
 if(!item) throw "Project item unavailable";

 var start=src.start.seconds, end=src.end.seconds;
 var inSec=src.inPoint.seconds, outSec=src.outPoint.seconds;

 // Snapshot clip-level state for components that also exist on a fresh insert.
 var state=[];
 for(var ci=0;ci<src.components.numItems;ci++){{
   var sc=src.components[ci], cs={{match:String(sc.matchName), display:String(sc.displayName), props:[]}};
   for(var pi=0;pi<sc.properties.numItems;pi++){{
     var sp=sc.properties[pi], ps={{index:pi, value:null, keys:[]}};
     try{{ps.value=sp.getValue();}}catch(ignore){{}}
     try{{
       var ks=sp.getKeys();
       if(ks && ks.length){{
         for(var ki=0;ki<ks.length;ki++){{
           var kt=ks[ki], kv=null;
           try{{kv=sp.getValueAtKey(kt);}}catch(ignore2){{}}
           ps.keys.push({{seconds:kt.seconds,value:kv}});
         }}
       }}
     }}catch(ignore3){{}}
     cs.props.push(ps);
   }}
   state.push(cs);
 }}

 var beforeDst=dstTrack.clips.numItems;
 var ok=dstTrack.insertClip(item,start);
 $.sleep(120);
 if(dstTrack.clips.numItems<=beforeDst) throw "Target insert did not create clip";

 var dst=null, dstOrdinal=-1;
 for(var i=0;i<dstTrack.clips.numItems;i++){{
   var c=dstTrack.clips[i];
   if(Math.abs(c.start.seconds-start)<0.0005 && c.projectItem===item){{dst=c;dstOrdinal=i;break;}}
 }}
 if(!dst){{dstOrdinal=dstTrack.clips.numItems-1;dst=dstTrack.clips[dstOrdinal];}}

 var ti=new Time(); ti.seconds=inSec; dst.inPoint=ti;
 var to=new Time(); to.seconds=outSec; dst.outPoint=to;
 var ts=new Time(); ts.seconds=start; dst.start=ts;
 var te=new Time(); te.seconds=end; dst.end=te;

 var restoredProps=0, restoredKeys=0, rebuiltEffects=0;
 // Recreate missing non-base video effects using the source component displayName.
 try{{
   app.enableQE();
   try{{s.openInTimeline();}}catch(ignoreOpen){{}}
   var qs=qe.project.getActiveSequence();
   var qtr=qs.getVideoTrackAt({int(target_video_track_index)});
   var qclip=null, seen=-1;
   for(var qi=0;qi<qtr.numItems;qi++){{
     var qit=qtr.getItemAt(qi);
     if(qit && qit.type==="Clip"){{
       seen++;
       if(seen===dstOrdinal){{qclip=qit;break;}}
     }}
   }}
   if(qclip){{
     for(var esi=state.length-1;esi>=0;esi--){{
       var exists=false;
       for(var edi=0;edi<dst.components.numItems;edi++){{
         if(String(dst.components[edi].matchName)===state[esi].match){{exists=true;break;}}
       }}
       if(!exists && state[esi].match!=="AE.ADBE Opacity" && state[esi].match!=="AE.ADBE Motion"){{
         var effectName=state[esi].display;
         var qeEff=qe.project.getVideoEffectByName(effectName);
         if(qeEff){{
           var added=qclip.addVideoEffect(qeEff);
           if(added){{rebuiltEffects++; $.sleep(180);}}
         }}
       }}
     }}
   }}
 }}catch(ignoreRebuild){{}}

 for(var si=0;si<state.length;si++){{
   var dc=null;
   for(var di=0;di<dst.components.numItems;di++){{
     if(String(dst.components[di].matchName)===state[si].match){{dc=dst.components[di];break;}}
   }}
   if(!dc) continue;
   for(var pj=0;pj<state[si].props.length;pj++){{
     var snap=state[si].props[pj];
     if(snap.index>=dc.properties.numItems) continue;
     var dp=dc.properties[snap.index];
     if(snap.keys && snap.keys.length){{
       try{{
         dp.setTimeVarying(true);
         for(var kk=0;kk<snap.keys.length;kk++){{
           var tm=new Time(); tm.seconds=snap.keys[kk].seconds;
           dp.addKey(tm);
           dp.setValueAtKey(tm,snap.keys[kk].value,true);
           restoredKeys++;
         }}
       }}catch(ignore4){{}}
     }} else {{
       try{{dp.setValue(snap.value,true); restoredProps++;}}catch(ignore5){{}}
     }}
   }}
 }}

 src.remove(0,0);
 $.sleep(80);

 return "sequence="+s.name+";ok="+ok+
        ";srcTrack="+{int(source_video_track_index)}+
        ";dstTrack="+{int(target_video_track_index)}+
        ";start="+dst.start.seconds+";end="+dst.end.seconds+
        ";in="+dst.inPoint.seconds+";out="+dst.outPoint.seconds+
        ";rebuiltEffects="+rebuiltEffects+
        ";restoredProps="+restoredProps+";restoredKeys="+restoredKeys;
}})();"""
        return self._run_inline_jsx(source, "move_video_to_track")

    def scale_video_to_frame_size(self, *,
                                  sequence_index: int | None = None,
                                  video_track_index: int = 0,
                                  clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c) throw "Video clip not found";
 if(!c.projectItem) throw "Project item unavailable";
 var ok=c.projectItem.setScaleToFrameSize();
 return "sequence="+s.name+";ok="+ok+";clip="+c.name;
}})();"""
        return self._run_inline_jsx(source, "scale_to_frame")

    def slip_video_clip(self, offset_frames: int, *,
                        sequence_index: int | None = None,
                        video_track_index: int = 0,
                        clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        frames_js = json.dumps(str(int(offset_frames)))
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}
 app.enableQE();
 var qs=qe.project.getActiveSequence();
 var qt=qs.getVideoTrackAt({int(video_track_index)});
 var qc=null, seen=-1;
 for(var i=0;i<qt.numItems;i++){{
   var it=qt.getItemAt(i);
   if(it && it.type==="Clip"){{
     seen++;
     if(seen==={int(clip_index)}){{qc=it;break;}}
   }}
 }}
 if(!qc) throw "QE video clip not found";
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 var beforeIn=c.inPoint.seconds, beforeOut=c.outPoint.seconds;
 var ok=qc.slip({frames_js});
 $.sleep(120);
 c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 return "sequence="+s.name+";ok="+ok+";frames="+{frames_js}+
        ";in="+beforeIn+"->"+c.inPoint.seconds+
        ";out="+beforeOut+"->"+c.outPoint.seconds;
}})();"""
        return self._run_inline_jsx(source, "slip_video")

    def slide_video_clip(self, offset_frames: int, *,
                         sequence_index: int | None = None,
                         video_track_index: int = 0,
                         clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        frames_js = json.dumps(str(int(offset_frames)))
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}
 app.enableQE();
 var qs=qe.project.getActiveSequence();
 var qt=qs.getVideoTrackAt({int(video_track_index)});
 var qc=null, seen=-1;
 for(var i=0;i<qt.numItems;i++){{
   var it=qt.getItemAt(i);
   if(it && it.type==="Clip"){{
     seen++;
     if(seen==={int(clip_index)}){{qc=it;break;}}
   }}
 }}
 if(!qc) throw "QE video clip not found";
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 var beforeStart=c.start.seconds, beforeEnd=c.end.seconds;
 var ok=qc.slide({frames_js});
 $.sleep(120);
 c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 return "sequence="+s.name+";ok="+ok+";frames="+{frames_js}+
        ";start="+beforeStart+"->"+c.start.seconds+
        ";end="+beforeEnd+"->"+c.end.seconds;
}})();"""
        return self._run_inline_jsx(source, "slide_video")

    def razor_video_track(self, timecode: str, *,
                          sequence_index: int | None = None,
                          video_track_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        tc_js = json.dumps(str(timecode))
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}
 app.enableQE();
 var qs=qe.project.getActiveSequence();
 var qt=qs.getVideoTrackAt({int(video_track_index)});
 if(!qt) throw "QE video track not found";
 var before=s.videoTracks[{int(video_track_index)}].clips.numItems;
 var ok=qt.razor({tc_js});
 $.sleep(120);
 var after=s.videoTracks[{int(video_track_index)}].clips.numItems;
 return "sequence="+s.name+";ok="+ok+";before="+before+";after="+after+";timecode="+{tc_js};
}})();"""
        return self._run_inline_jsx(source, "razor_video")

    def remove_video_clip(self, *,
                          sequence_index: int | None = None,
                          video_track_index: int = 0,
                          clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}
 app.enableQE();
 var qs=qe.project.getActiveSequence();
 var qt=qs.getVideoTrackAt({int(video_track_index)});
 var qc=null, seen=-1;
 for(var i=0;i<qt.numItems;i++){{
   var it=qt.getItemAt(i);
   if(it && it.type==="Clip"){{
     seen++;
     if(seen==={int(clip_index)}){{qc=it;break;}}
   }}
 }}
 if(!qc) throw "QE video clip not found";
 var before=s.videoTracks[{int(video_track_index)}].clips.numItems;
 var ok=qc.remove();
 $.sleep(120);
 var after=s.videoTracks[{int(video_track_index)}].clips.numItems;
 return "sequence="+s.name+";ok="+ok+";before="+before+";after="+after;
}})();"""
        return self._run_inline_jsx(source, "remove_video")

    def set_video_frame_blend(self, enabled: bool, *,
                              sequence_index: int | None = None,
                              video_track_index: int = 0,
                              clip_index: int = 0):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}
 app.enableQE();
 var qs=qe.project.getActiveSequence();
 var qt=qs.getVideoTrackAt({int(video_track_index)});
 var qc=null, seen=-1;
 for(var i=0;i<qt.numItems;i++){{
   var it=qt.getItemAt(i);
   if(it && it.type==="Clip"){{
     seen++;
     if(seen==={int(clip_index)}){{qc=it;break;}}
   }}
 }}
 if(!qc) throw "QE video clip not found";
 var ok=qc.setFrameBlend({"true" if enabled else "false"});
 return "sequence="+s.name+";ok="+ok+";enabled="+{"true" if enabled else "false"};
}})();"""
        return self._run_inline_jsx(source, "frame_blend")

    def set_video_time_interpolation(self, interpolation_type: int, *,
                                     sequence_index: int | None = None,
                                     video_track_index: int = 0,
                                     clip_index: int = 0):
        interpolation_type = int(interpolation_type)
        if interpolation_type not in {0, 1, 2}:
            raise ValueError("interpolation_type must be 0, 1, or 2")
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}
 app.enableQE();
 var qs=qe.project.getActiveSequence();
 var qt=qs.getVideoTrackAt({int(video_track_index)});
 var qc=null, seen=-1;
 for(var i=0;i<qt.numItems;i++){{
   var it=qt.getItemAt(i);
   if(it && it.type==="Clip"){{
     seen++;
     if(seen==={int(clip_index)}){{qc=it;break;}}
   }}
 }}
 if(!qc) throw "QE video clip not found";
 var ok=qc.setTimeInterpolationType({interpolation_type});
 return "sequence="+s.name+";ok="+ok+";type="+{interpolation_type};
}})();"""
        return self._run_inline_jsx(source, "time_interpolation")

    def set_audio_volume_linear(self, value: float, *, sequence_index: int,
                                audio_track_index: int = 0,
                                clip_index: int = 0):
        source = f"""#target premierepro
(function(){{
 var s=app.project.sequences[{int(sequence_index)}];
 var c=s.audioTracks[{int(audio_track_index)}].clips[{int(clip_index)}];
 if(!c) throw "Audio clip not found";
 var comp=null;
 for(var i=0;i<c.components.numItems;i++){{
  if(String(c.components[i].matchName).indexOf("Internal Volume")===0){{comp=c.components[i];break;}}
 }}
 if(!comp) throw "Volume component not found";
 var p=comp.properties[1];
 var before=p.getValue();
 var ok=p.setValue({float(value)},true);
 return "before="+before+";set="+ok+";after="+p.getValue();
}})();"""
        return self._run_inline_jsx(source, "audio_volume")

    def set_audio_volume_db(self, db: float, *, sequence_index: int,
                            audio_track_index: int = 0,
                            clip_index: int = 0):
        # Premiere's clip Volume > Level uses an internal 0..1 scale
        # where 0 dB == 10^(-15/20) ~= 0.17782794 and +15 dB == 1.0.
        linear = 10.0 ** ((float(db) - 15.0) / 20.0)
        return self.set_audio_volume_linear(
            linear,
            sequence_index=sequence_index,
            audio_track_index=audio_track_index,
            clip_index=clip_index,
        )

    def set_audio_volume_keyframes(self, keys: list[tuple[float, float]], *,
                                   sequence_index: int,
                                   audio_track_index: int = 0,
                                   clip_index: int = 0,
                                   values_are_db: bool = True,
                                   replace_existing: bool = True):
        normalized = []
        for seconds, value in keys:
            linear = (
                10.0 ** ((float(value) - 15.0) / 20.0)
                if values_are_db else float(value)
            )
            normalized.append((float(seconds), linear))
        key_js = json.dumps(
            [{"seconds": t, "value": v} for t, v in normalized],
            ensure_ascii=False
        )
        source = f"""#target premierepro
(function(){{
 var s=app.project.sequences[{int(sequence_index)}];
 var c=s.audioTracks[{int(audio_track_index)}].clips[{int(clip_index)}];
 if(!c) throw "Audio clip not found";
 var comp=null;
 for(var i=0;i<c.components.numItems;i++){{
  if(String(c.components[i].matchName).indexOf("Internal Volume")===0){{comp=c.components[i];break;}}
 }}
 if(!comp) throw "Volume component not found";
 var p=comp.properties[1];
 p.setTimeVarying(true);
 if({"true" if replace_existing else "false"}){{
   var old=p.getKeys();
   if(old && old.length){{
     for(var r=old.length-1;r>=0;r--){{try{{p.removeKey(old[r]);}}catch(ignore){{}}}}
   }}
 }}
 var keys={key_js};
 for(var k=0;k<keys.length;k++){{
   var tm=new Time(); tm.seconds=keys[k].seconds;
   p.addKey(tm);
   p.setValueAtKey(tm,keys[k].value,true);
 }}
 var count=0;try{{count=p.getKeys().length;}}catch(ignore2){{}}
 return "keys="+count+";timevary="+p.isTimeVarying();
}})();"""
        return self._run_inline_jsx(source, "audio_volume_keys")



    def set_lumetri_basic(self, *, sequence_index: int | None = None,
                          video_track_index: int = 0, clip_index: int = 0,
                          temperature: float | None = None,
                          tint: float | None = None,
                          saturation: float | None = None,
                          exposure: float | None = None,
                          contrast: float | None = None,
                          highlights: float | None = None,
                          shadows: float | None = None,
                          whites: float | None = None,
                          blacks: float | None = None):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        values = {
            14: temperature, 15: tint, 16: saturation,
            19: exposure, 20: contrast, 21: highlights,
            22: shadows, 23: whites, 24: blacks,
        }
        pairs = [(idx, val) for idx, val in values.items() if val is not None]
        js_pairs = json.dumps(
            [{"index": idx, "value": float(val)} for idx, val in pairs],
            ensure_ascii=False
        )
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c) throw "Video clip not found";
 var lum=null;
 for(var i=0;i<c.components.numItems;i++){{
   var cp=c.components[i];
   if(String(cp.displayName).indexOf("Lumetri")>=0 ||
      String(cp.matchName).indexOf("Lumetri")>=0 ||
      String(cp.displayName).indexOf("颜色")>=0){{
      lum=cp; break;
   }}
 }}
 if(!lum){{
   app.enableQE();
   var qs=qe.project.getActiveSequence();
   var qt=qs.getVideoTrackAt({int(video_track_index)});
   var qc=null, seen=-1;
   for(var q=0;q<qt.numItems;q++){{
     var it=qt.getItemAt(q);
     if(it && it.type==="Clip"){{
       seen++;
       if(seen==={int(clip_index)}){{qc=it;break;}}
     }}
   }}
   if(!qc) throw "QE clip not found";
   var eff=qe.project.getVideoEffectByName("Lumetri 颜色");
   if(!eff) eff=qe.project.getVideoEffectByName("Lumetri Color");
   if(!eff) throw "Lumetri effect not found";
   qc.addVideoEffect(eff);
   $.sleep(350);
   c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
   for(var j=0;j<c.components.numItems;j++){{
     var cp2=c.components[j];
     if(String(cp2.displayName).indexOf("Lumetri")>=0 ||
        String(cp2.matchName).indexOf("Lumetri")>=0 ||
        String(cp2.displayName).indexOf("颜色")>=0){{
       lum=cp2; break;
     }}
   }}
 }}
 if(!lum) throw "Lumetri component unavailable";
 var pairs={js_pairs}, out=[];
 for(var k=0;k<pairs.length;k++){{
   var pr=lum.properties[pairs[k].index];
   var before=pr.getValue();
   var ok=pr.setValue(pairs[k].value,true);
   out.push(pairs[k].index+":"+before+"->"+pr.getValue()+"("+ok+")");
 }}
 return "sequence="+s.name+";component="+lum.displayName+";"+out.join(";");
}})();"""
        return self._run_inline_jsx(source, "lumetri_basic")

    def encode_sequence_ame(self, output_path: str, preset_path: str, *,
                            sequence_index: int | None = None,
                            work_area: str = "entire",
                            remove_on_completion: bool = True,
                            start_batch: bool = True):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        work_map = {
            "entire": "app.encoder.ENCODE_ENTIRE",
            "in_to_out": "app.encoder.ENCODE_IN_TO_OUT",
            "workarea": "app.encoder.ENCODE_WORKAREA",
        }
        if work_area not in work_map:
            raise ValueError("work_area must be entire, in_to_out, or workarea")
        out_js = json.dumps(str(Path(output_path)), ensure_ascii=False)
        preset_js = json.dumps(str(Path(preset_path)), ensure_ascii=False)
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var launch="";try{{app.encoder.launchEncoder();launch="ok";}}catch(e){{launch=String(e);}}
 $.sleep(600);
 var job=app.encoder.encodeSequence(
   s,{out_js},{preset_js},{work_map[work_area]},{"1" if remove_on_completion else "0"}
 );
 var started="";
 if({"true" if start_batch else "false"}){{
   try{{started=app.encoder.startBatch();}}catch(e2){{started=String(e2);}}
 }}
 return "sequence="+s.name+";job="+job+";launch="+launch+";startBatch="+started+
        ";requestedOutput="+{out_js}+";preset="+{preset_js};
}})();"""
        return self._run_inline_jsx(source, "encode_sequence_ame")

    def create_freeze_frame_clip(self, timecode: str, output_base: str,
                                 timeline_seconds: float, duration_seconds: float, *,
                                 sequence_index: int | None = None,
                                 video_track_index: int = 1):
        if float(duration_seconds) <= 0:
            raise ValueError("duration_seconds must be > 0")
        base = str(Path(output_base))
        png_path = base + ".png"
        export_result = self.export_frame_png(
            timecode, base, sequence_index=sequence_index
        )
        import_result = self.import_files([png_path])
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        name_js = json.dumps(Path(png_path).name, ensure_ascii=False)
        source = f"""#target premierepro
(function(){{
 function findItem(parent,name){{
   if(!parent||!parent.children)return null;
   for(var i=0;i<parent.children.numItems;i++){{
     var c=parent.children[i];if(String(c.name)===name)return c;
     var r=findItem(c,name);if(r)return r;
   }}
   return null;
 }}
 var s={seq_expr};if(!s)throw "Sequence not found";
 var item=findItem(app.project.rootItem,{name_js});if(!item)throw "Freeze-frame ProjectItem not found";
 var tr=s.videoTracks[{int(video_track_index)}];if(!tr)throw "Target video track not found";
 var before=tr.clips.numItems,ok=tr.insertClip(item,{float(timeline_seconds)});$.sleep(120);
 if(tr.clips.numItems<=before)throw "Freeze-frame insert failed";
 var clip=null;
 for(var i=0;i<tr.clips.numItems;i++){{
   var c=tr.clips[i];
   if(Math.abs(c.start.seconds-{float(timeline_seconds)})<0.0005 &&
      c.projectItem && String(c.projectItem.name)==={name_js}){{clip=c;break;}}
 }}
 if(!clip)clip=tr.clips[tr.clips.numItems-1];
 var ts=new Time();ts.seconds={float(timeline_seconds)};clip.start=ts;
 var te=new Time();te.seconds={float(timeline_seconds)+float(duration_seconds)};clip.end=te;
 return "sequence="+s.name+";ok="+ok+";clip="+clip.name+
        ";start="+clip.start.seconds+";end="+clip.end.seconds+";png="+{json.dumps(png_path, ensure_ascii=False)};
}})();"""
        insert_result = self._run_inline_jsx(source, "create_freeze_frame_clip")
        return {
            "export": export_result,
            "import": import_result,
            "insert": insert_result,
            "png": png_path,
        }

    def export_frame_png(self, timecode: str, output_base: str, *,
                         sequence_index: int | None = None):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        base = str(Path(output_base))
        base_js = json.dumps(base, ensure_ascii=False)
        tc_js = json.dumps(timecode)
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}
 app.enableQE();
 var qs=qe.project.getActiveSequence();
 var ret=qs.exportFramePNG({tc_js},{base_js});
 return "sequence="+s.name+";ret="+ret+";png="+{base_js}+".png";
}})();"""
        return self._run_inline_jsx(source, "frame_png")

    def attach_proxy(self, proxy_path: str, *, sequence_index: int | None = None,
                     video_track_index: int = 0, clip_index: int = 0,
                     is_hi_res: bool = False, wait_ms: int = 1500):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        proxy_js = json.dumps(str(Path(proxy_path)), ensure_ascii=False)
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 var c=s.videoTracks[{int(video_track_index)}].clips[{int(clip_index)}];
 if(!c) throw "Video clip not found";
 var item=c.projectItem;
 if(!item) throw "ProjectItem not found";
 var before=item.hasProxy();
 var beforePath=""; try{{beforePath=item.getProxyPath();}}catch(ignore){{}}
 var ret=item.attachProxy({proxy_js},{"1" if is_hi_res else "0"});
 $.sleep({int(wait_ms)});
 var after=item.hasProxy();
 var afterPath=""; try{{afterPath=item.getProxyPath();}}catch(ignore2){{}}
 return "before="+before+"|"+beforePath+
        ";ret="+ret+
        ";after="+after+"|"+afterPath;
}})();"""
        return self._run_inline_jsx(source, "attach_proxy")

    def set_linked_selection(self, linked: bool, *,
                             sequence_index: int | None = None,
                             video_items: list[tuple[int, int]] | None = None,
                             audio_items: list[tuple[int, int]] | None = None):
        seq_expr = (
            "app.project.activeSequence"
            if sequence_index is None
            else f"app.project.sequences[{int(sequence_index)}]"
        )
        video_items = video_items or []
        audio_items = audio_items or []
        v_js = json.dumps([{"track": t, "clip": c} for t, c in video_items])
        a_js = json.dumps([{"track": t, "clip": c} for t, c in audio_items])
        op = "linkSelection" if linked else "unlinkSelection"
        source = f"""#target premierepro
(function(){{
 var s={seq_expr};
 if(!s) throw "Sequence not found";
 try{{s.openInTimeline();}}catch(ignore){{}}
 for(var vt=0;vt<s.videoTracks.numTracks;vt++){{
   for(var vi=0;vi<s.videoTracks[vt].clips.numItems;vi++)
     s.videoTracks[vt].clips[vi].setSelected(0,0);
 }}
 for(var at=0;at<s.audioTracks.numTracks;at++){{
   for(var ai=0;ai<s.audioTracks[at].clips.numItems;ai++)
     s.audioTracks[at].clips[ai].setSelected(0,0);
 }}
 var vs={v_js}, as={a_js};
 for(var i=0;i<vs.length;i++)
   s.videoTracks[vs[i].track].clips[vs[i].clip].setSelected(1,1);
 for(var j=0;j<as.length;j++)
   s.audioTracks[as[j].track].clips[as[j].clip].setSelected(1,1);
 var ret=s.{op}();
 var counts=[];
 for(var k=0;k<vs.length;k++){{
   var vc=s.videoTracks[vs[k].track].clips[vs[k].clip];
   var li=vc.getLinkedItems();
   counts.push("V"+k+"="+(li?li.numItems:0));
 }}
 for(var m=0;m<as.length;m++){{
   var ac=s.audioTracks[as[m].track].clips[as[m].clip];
   var la=ac.getLinkedItems();
   counts.push("A"+m+"="+(la?la.numItems:0));
 }}
 return "sequence="+s.name+";ret="+ret+";"+counts.join(";");
}})();"""
        return self._run_inline_jsx(source, "link_selection")

    def set_track_mute(self, track_type: str, track_index: int, muted: bool,
                       *, restart: bool = False):
        return self.run([{
            "op": "set_track_mute",
            "trackType": track_type,
            "trackIndex": int(track_index),
            "muted": bool(muted),
        }], restart=restart)

    def set_track_lock(self, track_type: str, track_index: int, locked: bool,
                       *, restart: bool = False):
        return self.run([{
            "op": "set_track_lock",
            "trackType": track_type,
            "trackIndex": int(track_index),
            "locked": bool(locked),
        }], restart=restart)


def main():
    p = argparse.ArgumentParser(description="Premiere Pro 2026 modular controller")
    p.add_argument("--restart", action="store_true",
                   help="Explicitly allow restarting Premiere to execute the Startup task")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    o = sub.add_parser("open-project"); o.add_argument("path")
    n = sub.add_parser("new-project"); n.add_argument("path")
    sub.add_parser("save")
    b = sub.add_parser("create-bin"); b.add_argument("name")

    args = p.parse_args()
    ctl = PremiereController()
    if args.cmd == "status":
        out = ctl.status(restart=args.restart)
    elif args.cmd == "open-project":
        out = ctl.open_project(args.path, restart=args.restart)
    elif args.cmd == "new-project":
        out = ctl.new_project(args.path, restart=args.restart)
    elif args.cmd == "save":
        out = ctl.save_project(restart=args.restart)
    elif args.cmd == "create-bin":
        out = ctl.create_bin(args.name, restart=args.restart)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
