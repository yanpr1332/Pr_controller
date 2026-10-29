function findItem(parent, name) {
    return resolveProjectItem(name, true);
}

function seq() {
    var s = app.project.activeSequence;
    if (!s) throw "No active sequence";
    return s;
}

function clip(trackType, ti, ci) {
    var s = seq(),
        ts = (trackType === "audio") ? s.audioTracks : s.videoTracks;
    return ts[ti].clips[ci];
}

function compByMatch(c, m) {
    for (var i = 0; i < c.components.numItems; i++)
        if (c.components[i].matchName === m) return c.components[i];
    return null;
}


function legacyAction(a) {
    var d;
    if (a.op === "status") {
        d = "version=" + app.version + ";project=" + (app.project ? app.project.name : "") + ";sequence=" + (app.project && app.project.activeSequence ? app.project.activeSequence.name : "");
    } else if (a.op === "new_project") {
        d = app.newProject(a.path);
    } else if (a.op === "open_project") {
        d = app.openDocument(a.path);
    } else if (a.op === "save_project") {
        d = app.project.save();
    } else if (a.op === "eval_file") {
        var sf = new File(a.path);
        if (!sf.exists) throw "Script not found: " + a.path;
        d = $.evalFile(sf);
    } else if (a.op === "create_bin") {
        d = app.project.rootItem.createBin(a.name).name;
    } else if (a.op === "import_files") {
        var dest = a.bin ? findItem(app.project.rootItem, a.bin) : app.project.rootItem;
        d = app.project.importFiles(a.paths, true, dest, false);
    } else if (a.op === "create_sequence_from_clips") {
        var dest2 = a.bin ? findItem(app.project.rootItem, a.bin) : app.project.rootItem;
        var its = [];
        for (var ii = 0; ii < a.items.length; ii++) {
            var it = findItem(app.project.rootItem, a.items[ii]);
            if (!it) throw "Missing item " + a.items[ii];
            its.push(it);
        }
        var ns = app.project.createNewSequenceFromClips(a.name, its, dest2);
        d = ns ? ns.name : "";


    } else if (a.op === "add_marker") {
        var m = seq().markers.createMarker(a.seconds);
        m.name = a.name || "";
        m.comments = a.comments || "";
        d = m.name;
    } else if (a.op === "set_clip_property") {
        var cl = clip(a.trackType || "video", a.trackIndex || 0, a.clipIndex || 0);
        var cp = compByMatch(cl, a.component);
        if (!cp) throw "Missing component " + a.component;
        d = cp.properties[a.propertyIndex].setValue(a.value, a.updateUI !== false);
    } else if (a.op === "set_keyframes") {
        var cl2 = clip(a.trackType || "video", a.trackIndex || 0, a.clipIndex || 0);
        var cp2 = compByMatch(cl2, a.component);
        if (!cp2) throw "Missing component " + a.component;
        var pr = cp2.properties[a.propertyIndex];
        pr.setTimeVarying(true);
        for (var k = 0; k < a.keys.length; k++) {
            var t = new Time();
            t.seconds = a.keys[k].seconds;
            pr.addKey(t);
            pr.setValueAtKey(t, a.keys[k].value, true);
        }
        d = a.keys.length;
    } else if (a.op === "add_video_effect") {
        app.enableQE();
        var q = qe.project.getActiveSequence();
        var qc = qeClip(q.getVideoTrackAt(a.trackIndex || 0), a.clipIndex || 0);
        var e = qe.project.getVideoEffectByName(a.name);
        if (!e) throw "Effect not found";
        d = qc.addVideoEffect(e);
    } else if (a.op === "add_transition") {
        app.enableQE();
        var q2 = qe.project.getActiveSequence();
        var qc2 = qeClip(q2.getVideoTrackAt(a.trackIndex || 0), a.clipIndex || 0);
        var tr = qe.project.getVideoTransitionByName(a.name || "Cross Dissolve");
        if (!tr) throw "Transition not found";
        d = qc2.addTransition(tr, !!a.isIncoming, a.duration || "00:00:00:12");
    } else if (a.op === "create_caption_track") {
        var srt = findItem(app.project.rootItem, a.srtName);
        if (!srt) throw "SRT not found";
        d = seq().createCaptionTrack(srt, a.startSeconds || 0);
    } else if (a.op === "import_mogrt") {
        var mt = seq().importMGT(a.path, String(a.timeSeconds || 0), a.videoTrackIndex || 1, a.audioTrackIndex || 0);
        d = mt ? mt.name : "";
    } else if (a.op === "auto_reframe") {
        var ar = seq().autoReframeSequence(a.numerator, a.denominator, a.motionPreset || "default", a.name, !!a.nest);
        d = ar ? ar.name : "";
    } else if (a.op === "set_track_mute") {
        var s3 = seq(),
            tt = (a.trackType === "audio") ? s3.audioTracks : s3.videoTracks;
        d = tt[a.trackIndex || 0].setMute(a.muted ? 1 : 0);
    } else if (a.op === "set_track_lock") {
        var s4 = seq(),
            tt2 = (a.trackType === "audio") ? s4.audioTracks : s4.videoTracks;
        d = tt2[a.trackIndex || 0].setLocked(a.locked ? 1 : 0);
    } else throw "Unsupported op " + a.op;

    return d;
}
