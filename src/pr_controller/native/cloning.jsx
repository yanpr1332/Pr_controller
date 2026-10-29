// Strict copy/move support. Mutating the destination never deletes a source on failure.
function equalValue(a, b) {
    if (typeof a === 'number' && typeof b === 'number') return Math.abs(a - b) <= 1e-5 * Math.max(1, Math.abs(a));
    if (a && b && a.length !== undefined && b.length !== undefined && typeof a !== 'string') {
        if (a.length !== b.length) return false;
        for (var i = 0; i < a.length; i++)
            if (!equalValue(a[i], b[i])) return false;
        return true;
    }
    return String(a) === String(b);
}

function effectOccurrence(c, name, ordinal) {
    var n = 0;
    for (var i = 0; i < c.components.numItems; i++)
        if (c.components[i].matchName === name) {
            if (n++ === ordinal) return c.components[i];
        }
    return null;
}

function snapshotParameter(p, c, fps) {
    var keys = null,
        r = {
            value: null,
            keys: [],
            sampled: false
        };
    try {
        keys = p.getKeys();
    } catch (e) {
        if (p.isTimeVarying && p.isTimeVarying()) throw e;
    }
    if (!keys || !keys.length) {
        r.value = p.getValue();
        return r;
    }
    for (var i = 0; i < keys.length; i++) r.keys.push({
        seconds: keys[i].seconds,
        value: p.getValueAtKey(keys[i])
    });
    // Preserve native curves as evaluated frame values when their interpolation cannot be queried.
    if (p.getValueAtTime) {
        var samples = [],
            nonlinear = false,
            step = 1 / fps,
            j = 0;
        for (var sec = c.inPoint.seconds; sec < c.outPoint.seconds - 1e-7; sec += step) {
            while (j + 1 < r.keys.length && r.keys[j + 1].seconds < sec) j++;
            var v = p.getValueAtTime(time(sec)),
                left = r.keys[j],
                right = r.keys[Math.min(j + 1, r.keys.length - 1)],
                f = right.seconds === left.seconds ? 0 : Math.max(0, Math.min(1, (sec - left.seconds) / (right.seconds - left.seconds)));

            function blend(a, b, x) {
                if (typeof a === 'number' && typeof b === 'number') return a + (b - a) * x;
                if (a instanceof Array && b instanceof Array) {
                    var out = [];
                    for (var k = 0; k < a.length; k++) out.push(blend(a[k], b[k], x));
                    return out;
                }
                return x < 1 ? a : b;
            }
            if (!equalValue(v, blend(left.value, right.value, f))) nonlinear = true;
            samples.push({
                seconds: sec,
                value: v
            });
        }
        if (nonlinear) {
            samples.push({
                seconds: c.outPoint.seconds,
                value: p.getValueAtTime(c.outPoint)
            });
            r.keys = samples;
            r.sampled = true;
        }
    }
    return r;
}

function copyEdgeTransitions(s, sourceTrack, targetTrack, source, dest, audio) {
    var q = qe.project.getActiveSequence(),
        from = audio ? q.getAudioTrackAt(sourceTrack) : q.getVideoTrackAt(sourceTrack),
        to = audio ? q.getAudioTrackAt(targetTrack) : q.getVideoTrackAt(targetTrack),
        ordinal = -1,
        tracks = audio ? s.audioTracks : s.videoTracks;
    for (var i = 0; i < tracks[targetTrack].clips.numItems; i++)
        if (sameClip(tracks[targetTrack].clips[i], dest)) ordinal = i;
    if (ordinal < 0) throw 'Cannot identify transition destination';
    var dq = qeClip(to, ordinal),
        copied = 0,
        st = s.getSettings(),
        fps = 1 / st.videoFrameRate.seconds,
        tolerance = 1 / fps + .001;
    for (var i = 0; i < from.numTransitions; i++) {
        var tr = from.getTransitionAt(i);
        if (!tr || tr.type !== 'Transition' || !tr.name) continue;
        var a = tr.start.secs,
            b = tr.end.secs,
            incoming = a <= source.start.seconds + tolerance && b >= source.start.seconds - tolerance,
            outgoing = a <= source.end.seconds + tolerance && b >= source.end.seconds - tolerance;
        if (!incoming && !outgoing) continue;
        var exists = false;
        for (var j = 0; j < to.numTransitions; j++) {
            var dt = to.getTransitionAt(j);
            if (dt && dt.type === 'Transition' && String(dt.name) === String(tr.name) && Math.abs(dt.start.secs - a) < tolerance && Math.abs(dt.end.secs - b) < tolerance) exists = true;
        }
        if (exists) continue;
        var effect = audio ? qe.project.getAudioTransitionByName(String(tr.name)) : qe.project.getVideoTransitionByName(String(tr.name));
        if (!effect) throw 'Transition unavailable: ' + tr.name;
        var length = time(b - a).getFormatted(st.videoFrameRate, st.videoDisplayFormat);
        dq.addTransition(effect, incoming, length);
        var restored = false;
        for (var j = 0; j < to.numTransitions; j++) {
            var dt = to.getTransitionAt(j);
            if (dt && dt.type === 'Transition' && String(dt.name) === String(tr.name) && Math.abs(dt.start.secs - a) < tolerance && Math.abs(dt.end.secs - b) < tolerance) restored = true;
        }
        if (!restored) throw 'Transition bounds not restored; source retained: ' + tr.name;
        copied++;
    }
    return copied;
}

function strictClone(s, a) {
    var audio = a.kind === 'audio',
        tracks = audio ? s.audioTracks : s.videoTracks;
    if (a.track === a.target_track) throw 'Source and destination tracks must differ';
    if (!tracks[a.track] || !tracks[a.target_track]) throw 'Track missing';
    if (tracks[a.target_track].isLocked() || (a.move && tracks[a.track].isLocked())) throw 'Source or destination track is locked';
    var c = tracks[a.track].clips[a.clip];
    if (!c) throw 'Source clip missing';
    collision(tracks[a.target_track], c.start.seconds, c.end.seconds);
    activate(s);
    app.enableQE();
    var state = [],
        seen = {},
        fps = 1 / s.getSettings().videoFrameRate.seconds;
    for (var i = 0; i < c.components.numItems; i++) {
        var cp = c.components[i],
            name = String(cp.matchName),
            occurrence = seen[name] || 0;
        seen[name] = occurrence + 1;
        var row = {
            name: name,
            display: String(cp.displayName),
            ordinal: occurrence,
            props: []
        };
        for (var j = 0; j < cp.properties.numItems; j++) {
            var p = snapshotParameter(cp.properties[j], c, fps);
            p.index = j;
            row.props.push(p);
        }
        state.push(row);
    }
    var p = c.projectItem,
        oldIn = p.getInPoint().seconds,
        oldOut = p.getOutPoint().seconds;
    try {
        p.setInPoint(c.inPoint.seconds, 4);
        p.setOutPoint(c.outPoint.seconds, 4);
        streamPlacement(s, p, {
            media: audio ? 'audio' : 'video',
            mode: 'overwrite',
            at: c.start.seconds,
            video_track: a.target_track,
            audio_track: a.target_track
        });
    } finally {
        p.setInPoint(oldIn, 4);
        p.setOutPoint(oldOut, 4);
    }
    var dest = located(tracks[a.target_track], p, c.start.seconds),
        q = qe.project.getActiveSequence(),
        qt = audio ? q.getAudioTrackAt(a.target_track) : q.getVideoTrackAt(a.target_track),
        ordinal = -1;
    for (var i = 0; i < tracks[a.target_track].clips.numItems; i++)
        if (sameClip(tracks[a.target_track].clips[i], dest)) ordinal = i;
    if (ordinal < 0) throw 'No unambiguous destination; source retained';
    var dq = qeClip(qt, ordinal);
    // QE prepends effects. Reverse creation preserves the original custom effect stack.
    for (var i = state.length - 1; i >= 0; i--) {
        var row = state[i],
            guard = 0;
        while (!effectOccurrence(dest, row.name, row.ordinal) && guard++ < state.length + 1) {
            var effect = audio ? qe.project.getAudioEffectByName(row.display, 0) : qe.project.getVideoEffectByName(row.display);
            if (!effect) throw 'Effect unavailable; source retained: ' + row.display;
            var before = dest.components.numItems;
            if (audio) dq.addAudioEffect(effect);
            else dq.addVideoEffect(effect);
            if (dest.components.numItems <= before) throw 'Effect was not added; source retained: ' + row.display;
        }
    }
    var sampled = 0;
    for (var i = 0; i < state.length; i++) {
        var row = state[i],
            cp = effectOccurrence(dest, row.name, row.ordinal);
        if (!cp) throw 'Effect missing after reconstruction';
        for (var j = 0; j < row.props.length; j++) {
            var snap = row.props[j],
                p = cp.properties[snap.index];
            if (!p) throw 'Parameter missing';
            if (snap.keys.length) {
                p.setTimeVarying(true);
                var old = p.getKeys();
                if (old)
                    for (var k = old.length - 1; k >= 0; k--) p.removeKey(old[k]);
                for (var k = 0; k < snap.keys.length; k++) {
                    var key = snap.keys[k],
                        t = time(key.seconds);
                    p.addKey(t);
                    p.setValueAtKey(t, key.value, false);
                    if (p.setInterpolationTypeAtKey) p.setInterpolationTypeAtKey(t, 0, false);
                    if (!equalValue(p.getValueAtKey(t), key.value)) throw 'Keyframe verification failed';
                }
                if (snap.sampled) sampled++;
            } else {
                p.setValue(snap.value, false);
                if (!equalValue(p.getValue(), snap.value)) throw 'Parameter verification failed';
            }
        }
    }
    if (dest.components.numItems !== state.length) throw 'Effect stack length mismatch; source retained';
    for (var i = 0; i < state.length; i++)
        if (String(dest.components[i].matchName) !== state[i].name) throw 'Effect order mismatch; source retained';
    var transitions = a.copy_transitions === false ? 0 : copyEdgeTransitions(s, a.track, a.target_track, c, dest, audio);
    if (a.move) c.remove(false, false);
    return {
        destination: description(dest),
        sourceRemoved: !!a.move,
        sampledCurves: sampled,
        transitions: transitions
    };
}
