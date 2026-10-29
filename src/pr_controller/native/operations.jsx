function resolveProjectItem(ref, includeBins) {
    var hits = [],
        stack = [{
            item: app.project.rootItem,
            trail: ''
        }],
        wanted = String(ref),
        seen = [];
    while (stack.length) {
        var entry = stack.pop(),
            parent = entry.item;
        for (var z = 0; z < parent.children.numItems; z++) {
            var item = parent.children[z],
                label = String(item.name),
                trail = entry.trail ? entry.trail + '/' + label : label,
                path = '';
            try {
                path = String(item.getMediaPath()).split('\\').join('/');
            } catch (ignore) {}
            seen.push(label);
            if ((includeBins || item.type !== 2) && (String(item.nodeId) === wanted || label === wanted || trail === wanted || (path && path.toLowerCase() === wanted.split('\\').join('/').toLowerCase()))) hits.push(item);
            if (item.type === 2) stack.push({
                item: item,
                trail: trail
            });
        }
    }
    if (hits.length !== 1) throw 'Project item selector: ' + wanted + '; matches=' + hits.length + '; seen=' + seen.join(',');
    return hits[0];
}

function time(s) {
    var t = new Time();
    t.seconds = s;
    return t;
}

function sequence(ref) {
    var found = [];
    for (var i = 0; i < app.project.sequences.numSequences; i++) {
        var s = app.project.sequences[i];
        if ((typeof ref === 'number' && i === ref) || String(s.sequenceID) === String(ref) || s.name === ref) found.push(s);
    }
    if (ref === null || ref === undefined) {
        if (!app.project.activeSequence) throw 'No active sequence';
        return app.project.activeSequence;
    }
    if (found.length !== 1) throw 'Sequence selector missing or ambiguous';
    return found[0];
}

function activate(s) {
    app.project.openSequence(s.sequenceID);
    if (app.project.activeSequence.sequenceID !== s.sequenceID) throw 'Could not activate target';
}

function qeClip(track, index) {
    var n = 0;
    for (var i = 0; i < track.numItems; i++) {
        var c = track.getItemAt(i);
        if (c && c.type === 'Clip') {
            if (n++ === index) return c;
        }
    }
    throw 'QE clip not found';
}

function media(ref) {
    return resolveProjectItem(ref, false);
}

function component(c, name) {
    for (var i = 0; i < c.components.numItems; i++)
        if (c.components[i].matchName === name || c.components[i].displayName === name) return c.components[i];
    throw 'Component missing: ' + name;
}

function description(c) {
    var path = '';
    try {
        path = c.projectItem.getMediaPath();
    } catch (e) {}
    return {
        name: c.name,
        clipId: c.nodeId,
        nodeId: c.projectItem.nodeId,
        path: path,
        start: c.start.seconds,
        end: c.end.seconds,
        inPoint: c.inPoint.seconds,
        outPoint: c.outPoint.seconds
    };
}

function inventory(s) {
    var r = {
        name: s.name,
        id: s.sequenceID,
        end: Number(s.end) / 254016000000,
        video: [],
        audio: [],
        markers: []
    };
    var st = s.getSettings();
    r.width = st.videoFrameWidth;
    r.height = st.videoFrameHeight;
    r.fps = 1 / st.videoFrameRate.seconds;
    for (var k = 0; k < 2; k++) {
        var tracks = k ? s.audioTracks : s.videoTracks,
            out = k ? r.audio : r.video;
        for (var t = 0; t < tracks.numTracks; t++) {
            var row = {
                index: t,
                name: tracks[t].name,
                clips: []
            };
            for (var i = 0; i < tracks[t].clips.numItems; i++) row.clips.push(description(tracks[t].clips[i]));
            out.push(row);
        }
    }
    var m = s.markers.getFirstMarker();
    while (m) {
        r.markers.push({
            name: m.name,
            start: m.start.seconds,
            end: Math.max(m.end.seconds, m.start.seconds)
        });
        m = s.markers.getNextMarker(m);
    }
    return r;
}

function collision(tr, a, b) {
    for (var i = 0; i < tr.clips.numItems; i++) {
        var c = tr.clips[i];
        if (c.start.seconds < b - 1e-7 && c.end.seconds > a + 1e-7) throw 'Destination overlaps ' + c.name;
    }
}

function located(tr, p, start) {
    for (var i = 0; i < tr.clips.numItems; i++) {
        var c = tr.clips[i];
        if (c.projectItem.nodeId === p.nodeId && Math.abs(c.start.seconds - start) < .001) return c;
    }
    throw 'Inserted clip cannot be identified; no fallback to last clip';
}

function streamPlacement(s, p, a) {
    var fn = a.mode === 'insert' ? 'insertClip' : 'overwriteClip',
        when = a.mode === 'insert' ? time(a.at) : time(a.at).ticks;
    if (a.media === 'both') {
        s[fn](p, when, a.video_track, a.audio_track);
        return;
    }
    var path = '';
    try {
        path = String(p.getMediaPath()).toLowerCase();
    } catch (e) {}
    if (a.media === 'video' && /\.(png|jpe?g|bmp|tiff?|exr|gif)$/.test(path)) {
        s.videoTracks[a.video_track][fn](p, a.at);
        return;
    }
    if (a.media === 'audio' && /\.(wav|mp3|aac|flac|aiff?|m4a)$/.test(path)) {
        s.audioTracks[a.audio_track][fn](p, a.at);
        return;
    }
    activate(s);
    app.enableQE();
    var q = qe.project.getActiveSequence(),
        audioAux = a.media === 'video',
        tracks = audioAux ? s.audioTracks : s.videoTracks,
        ids = {},
        count = tracks.numTracks;
    for (var i = 0; i < count; i++) ids[String(tracks[i].id)] = true;
    if (audioAux) q.addTracks(0, 0, 1, 0, count);
    else q.addTracks(1, count, 0);
    tracks = audioAux ? s.audioTracks : s.videoTracks;
    var aux = null,
        index = -1;
    for (var i = 0; i < tracks.numTracks; i++)
        if (!ids[String(tracks[i].id)]) {
            if (aux) throw 'Unexpected auxiliary tracks; placement stopped';
            aux = tracks[i];
            index = i;
        } if (!aux || aux.clips.numItems) throw 'Could not allocate isolated partner track';
    s[fn](p, when, audioAux ? a.video_track : index, audioAux ? index : a.audio_track);
    for (var i = aux.clips.numItems - 1; i >= 0; i--) {
        if (aux.clips[i].projectItem.nodeId !== p.nodeId) throw 'Unexpected media in auxiliary track; retained';
        aux.clips[i].remove(false, false);
    }
    if (audioAux) q.removeAudioTrack(index);
    else q.removeVideoTrack(index);
}

function projectSnapshot() {
    if ($.global.__prTransactionDepth && $.global.__prTransactionSnapshot) return $.global.__prTransactionSnapshot;
    if (!app.project.path) throw 'Save the project before a transactional edit';
    app.project.save();
    var folder = new Folder($.global.__prControllerRuntime + '/snapshots');
    if (!folder.exists && !folder.create()) throw 'Snapshot directory unavailable';
    var output = new File(folder.fsName + '/' + (new Date()).getTime() + '_' + Math.floor(Math.random() * 1000000000) + '.prproj'),
        source = new File(app.project.path);
    if (!source.exists || !source.copy(output.fsName)) throw 'Project snapshot failed';
    return output.fsName;
}

function clipIdentity(c, kind, track) {
    return [kind, track, c.nodeId || '', c.projectItem.nodeId, c.start.seconds, c.end.seconds, c.inPoint.seconds, c.outPoint.seconds].join('|');
}

function sameClip(a, b) {
    return a && b && String(a.mediaType) === String(b.mediaType) && a.projectItem.nodeId === b.projectItem.nodeId && Math.abs(a.start.seconds - b.start.seconds) < 1e-7 && Math.abs(a.end.seconds - b.end.seconds) < 1e-7 && Math.abs(a.inPoint.seconds - b.inPoint.seconds) < 1e-7 && Math.abs(a.outPoint.seconds - b.outPoint.seconds) < 1e-7;
}

function dispatch(op, a) {
    if (op === 'legacy') {
        var out = [];
        for (var i = 0; i < a.actions.length; i++) {
            try {
                var value = legacyAction(a.actions[i]);
                out.push({
                    status: 'OK',
                    op: a.actions[i].op,
                    data: value
                });
            } catch (e) {
                throw {
                    message: String(e),
                    actionIndex: i,
                    completed: out
                };
            }
        }
        return out;
    }
    if (op === 'eval') {
        var value = eval(a.source);
        return value;
    }
    if (op === 'transaction') {
        var allowed = {
            place: 1,
            shift: 1,
            clone: 1,
            clone_av: 1,
            clone_group: 1,
            props: 1,
            animate: 1,
            settings: 1,
            effect: 1,
            transition: 1,
            track_state: 1,
            ensure_tracks: 1,
            relink: 1,
            build_layout: 1,
            caption_import: 1,
            compose: 1
        };
        for (var i = 0; i < a.actions.length; i++)
            if (!allowed[a.actions[i].operation]) throw 'Operation not allowed in a project transaction';
        var originalSequence = app.project.activeSequence ? app.project.activeSequence.sequenceID : null;
        var original = app.project.path,
            backup = projectSnapshot(),
            results = [];
        $.global.__prTransactionDepth = 1;
        $.global.__prTransactionSnapshot = backup;
        try {
            for (var i = 0; i < a.actions.length; i++) results.push(dispatch(a.actions[i].operation, a.actions[i].args || {}));
            if (a.save_after) app.project.save();
            return {
                results: results,
                backup: backup,
                saved: !!a.save_after
            };
        } catch (e) {
            var recovery = '';
            try {
                if (!app.project.closeDocument(0, 0)) throw 'Close failed';
                if (!new File(backup).copy(original)) throw 'Snapshot restore failed';
                if (!app.openDocument(original)) throw 'Reopen failed';
                if (originalSequence) app.project.openSequence(originalSequence);
                recovery = 'restored';
            } catch (restoreError) {
                recovery = 'manual restore required: ' + restoreError;
            }
            throw 'Transaction failed: ' + String(e) + '; recovery=' + recovery + '; backup=' + backup;
        } finally {
            $.global.__prTransactionDepth = 0;
            $.global.__prTransactionSnapshot = null;
        }
    }
    if (op === 'capabilities') {
        app.enableQE();
        return {
            premiere: app.version,
            qe: !!qe,
            sequenceCount: app.project.sequences.numSequences,
            exportDirect: !!(app.project.activeSequence && app.project.activeSequence.exportAsMediaDirect),
            captionAPI: !!(app.project.activeSequence && app.project.activeSequence.captionTracks)
        };
    }

    if (op === 'catalog') {
        var out = [],
            stack = [{
                node: app.project.rootItem,
                path: ''
            }];
        while (stack.length) {
            var row = stack.pop();
            for (var i = 0; i < row.node.children.numItems; i++) {
                var p = row.node.children[i],
                    label = row.path ? row.path + '/' + p.name : String(p.name),
                    path = '',
                    offline = false;
                try {
                    path = String(p.getMediaPath());
                    offline = !!p.isOffline();
                } catch (e) {}
                out.push({
                    nodeId: p.nodeId,
                    name: String(p.name),
                    binPath: label,
                    path: path,
                    offline: offline,
                    type: p.type
                });
                if (p.type === 2) stack.push({
                    node: p,
                    path: label
                });
            }
        }
        return out;
    }
    if (op === 'compose') {
        for (var i = 0; i < app.project.sequences.numSequences; i++)
            if (app.project.sequences[i].name === a.name) throw 'Composition name already exists';
        var p = media(a.background.item),
            oldIn = p.getInPoint().seconds,
            oldOut = p.getOutPoint().seconds,
            ns = null;
        try {
            p.setInPoint(0, 4);
            p.setOutPoint(a.duration, 4);
            ns = app.project.createNewSequenceFromClips(a.name, [p], app.project.rootItem);
        } finally {
            p.setInPoint(oldIn, 4);
            p.setOutPoint(oldOut, 4);
        }
        if (!ns) throw 'Composition creation failed';
        dispatch('settings', {
            sequence: ns.sequenceID,
            width: a.width,
            height: a.height,
            fps: a.fps
        });
        var c = ns.videoTracks[0].clips[0];
        c.inPoint = time(0);
        c.outPoint = time(a.duration);
        c.start = time(0);
        c.end = time(a.duration);
        var m = component(c, 'AE.ADBE Motion');
        m.properties[0].setValue([.5, .5], false);
        m.properties[1].setValue(Math.max(a.width / a.background.width, a.height / a.background.height) * 100, true);
        return inventory(ns);
    }
    var s = sequence(a.sequence);
    if (op === 'timeline') return inventory(s);
    if (op === 'effect') {
        activate(s);
        app.enableQE();
        var audio = a.kind === 'audio',
            tracks = audio ? s.audioTracks : s.videoTracks,
            c = tracks[a.track].clips[a.clip],
            qt = audio ? qe.project.getActiveSequence().getAudioTrackAt(a.track) : qe.project.getActiveSequence().getVideoTrackAt(a.track),
            qc = qeClip(qt, a.clip),
            names = [a.name],
            aliases = {
                'Crop': ['裁剪'],
                'Lumetri Color': ['Lumetri 颜色', 'Lumetri颜色'],
                'Parametric Equalizer': ['参数均衡器']
            };
        if (aliases[a.name]) names = names.concat(aliases[a.name]);
        var list = audio ? qe.project.getAudioEffectList(a.channel_type || 0) : qe.project.getVideoEffectList(0),
            selected = null;
        for (var i = 0; i < names.length && !selected; i++)
            for (var j = 0; j < list.length; j++)
                if (String(list[j]).toLowerCase() === String(names[i]).toLowerCase()) selected = String(list[j]);
        if (!selected) selected = a.name;
        var effect = audio ? qe.project.getAudioEffectByName(selected, a.channel_type || 0) : qe.project.getVideoEffectByName(selected, String(selected).indexOf('AE.') === 0);
        if (!effect) throw 'Effect unavailable';
        var before = c.components.numItems,
            ret = audio ? qc.addAudioEffect(effect) : qc.addVideoEffect(effect);
        if (c.components.numItems <= before) throw 'Premiere did not add the effect: ' + selected;
        return {
            added: true,
            name: selected,
            returnValue: ret,
            components: c.components.numItems
        };
    }
    if (op === 'transition') {
        activate(s);
        app.enableQE();
        var audio = a.kind === 'audio';
        var qt = audio ? qe.project.getActiveSequence().getAudioTrackAt(a.track) : qe.project.getActiveSequence().getVideoTrackAt(a.track),
            qc = qeClip(qt, a.clip),
            names = [a.name];
        if (a.name === 'Cross Dissolve') names.push('交叉溶解');
        if (a.name === 'Constant Power') names.push('恒定功率');
        if (a.name === 'Constant Gain') names.push('恒定增益');
        if (a.name === 'Exponential Fade') names.push('指数淡化');
        var list = audio ? qe.project.getAudioTransitionList() : qe.project.getVideoTransitionList(),
            selected = null;
        for (var i = 0; i < names.length && !selected; i++)
            for (var j = 0; j < list.length; j++)
                if (String(list[j]).toLowerCase() === String(names[i]).toLowerCase()) selected = String(list[j]);
        if (!selected) selected = a.name;
        var effect = audio ? qe.project.getAudioTransitionByName(selected) : qe.project.getVideoTransitionByName(selected);
        if (!effect) throw 'Transition unavailable';

        function sig() {
            var out = [];
            for (var i = 0; i < qt.numTransitions; i++) {
                var tr = qt.getTransitionAt(i);
                if (tr && tr.type === 'Transition' && tr.name) out.push(String(tr.name) + ':' + tr.start.secs + ':' + tr.end.secs);
            }
            return out.join(';');
        }
        var before = sig(),
            ret = qc.addTransition(effect, !!a.incoming, a.duration),
            after = sig();
        if (before === after) throw 'Premiere did not change transitions: ' + selected;
        return {
            name: selected,
            returnValue: ret,
            transitions: after
        };
    }

    if (op === 'caption_import') {
        if (!new File(a.path).exists) throw 'Caption file missing';
        app.project.importFiles([a.path], true, app.project.rootItem, false);
        var p = media(a.path),
            created = s.createCaptionTrack(p, 0);
        return {
            created: !!created,
            sequence: s.sequenceID,
            source: a.path
        };
    }
    if (op === 'backup_project') {
        var target = new File(a.destination);
        if (target.exists) throw 'Backup exists';
        app.project.save();
        var source = new File(app.project.path);
        if (!source.exists || !source.copy(target.fsName)) throw 'Project snapshot failed';
        return {
            path: target.fsName,
            bytes: target.length
        };
    }

    if (op === 'clone_group') {
        var results = [],
            refs = [],
            ids = {};
        for (var i = 0; i < a.indices.length; i++) {
            var index = a.indices[i],
                c = s.videoTracks[a.track].clips[index];
            if (!c) throw 'Group source missing';
            if (ids[clipIdentity(c, 'video', a.track)]) throw 'Duplicate group source';
            ids[clipIdentity(c, 'video', a.track)] = true;
            refs.push({
                kind: 'video',
                track: a.track,
                clip: index,
                id: clipIdentity(c, 'video', a.track)
            });
            var r;
            if (a.target_audio_track !== null && a.target_audio_track !== undefined) {
                r = dispatch('clone_av', {
                    sequence: s.sequenceID,
                    track: a.track,
                    clip: index,
                    target_track: a.target_track,
                    target_audio_track: a.target_audio_track,
                    move: false,
                    copy_transitions: a.copy_transitions
                });
                var ac = s.audioTracks[r.sourceAudioTrack].clips[r.sourceAudioIndex];
                if (ids[clipIdentity(ac, 'audio', r.sourceAudioTrack)]) throw 'Shared linked audio requires explicit mapping; sources retained';
                ids[clipIdentity(ac, 'audio', r.sourceAudioTrack)] = true;
                refs.push({
                    kind: 'audio',
                    track: r.sourceAudioTrack,
                    clip: r.sourceAudioIndex,
                    id: clipIdentity(ac, 'audio', r.sourceAudioTrack)
                });
            } else r = strictClone(s, {
                track: a.track,
                clip: index,
                target_track: a.target_track,
                move: false,
                copy_transitions: a.copy_transitions
            });
            results.push(r);
        }
        if (a.move) dispatch('remove_originals', {
            sequence: s.sequenceID,
            refs: refs
        });
        return {
            results: results,
            sourceRemoved: !!a.move
        };
    }

    if (op === 'resolve_sequence') {
        for (var i = 0; i < app.project.sequences.numSequences; i++)
            if (app.project.sequences[i].sequenceID === s.sequenceID) return {
                id: s.sequenceID,
                index: i,
                name: s.name
            };
    }
    if (op === 'build_layout') {
        for (var i = 0; i < a.plan.length; i++) {
            var r = a.plan[i];
            if (s.videoTracks[r.track]) collision(s.videoTracks[r.track], r.start, r.end);
        }
        dispatch('ensure_tracks', {
            sequence: s.sequenceID,
            video: a.plan.length + 1,
            audio: s.audioTracks.numTracks
        });
        var made = [];
        for (var i = 0; i < a.plan.length; i++) {
            var r = a.plan[i],
                placed = dispatch('place', {
                    sequence: s.sequenceID,
                    item: r.item,
                    source_in: 0,
                    source_out: r.end - r.start,
                    at: r.start,
                    video_track: r.track,
                    audio_track: 0,
                    media: 'video',
                    mode: 'overwrite',
                    allow_overlap: false
                }),
                tr = s.videoTracks[r.track],
                ordinal = -1;
            for (var j = 0; j < tr.clips.numItems; j++)
                if (Math.abs(tr.clips[j].start.seconds - r.start) < .001) ordinal = j;
            if (ordinal < 0) throw 'Layout clip not found';
            dispatch('animate', {
                sequence: s.sequenceID,
                track: r.track,
                clip: ordinal,
                properties: r.properties,
                time_space: 'clip',
                ease: false
            });
            made.push(placed);
        }
        return {
            created: made
        };
    }
    if (op === 'remove_originals') {
        var refs = [];
        for (var i = 0; i < a.refs.length; i++) {
            var r = a.refs[i],
                tracks = r.kind === 'audio' ? s.audioTracks : s.videoTracks,
                c = tracks[r.track].clips[r.clip];
            if (!c || tracks[r.track].isLocked() || clipIdentity(c, r.kind, r.track) !== r.id) throw 'Source identity changed; originals retained';
            refs.push(c);
        }
        for (var i = refs.length - 1; i >= 0; i--) refs[i].remove(false, false);
        return {
            removed: refs.length
        };
    }

    if (op === 'track_state') {
        var tracks = a.kind === 'audio' ? s.audioTracks : s.videoTracks,
            tr = tracks[a.track];
        if (!tr) throw 'Track missing';
        if (a.muted !== undefined) tr.setMute(a.muted ? 1 : 0);
        if (a.locked !== undefined) tr.setLocked(a.locked ? 1 : 0);
        return {
            muted: tr.isMuted(),
            locked: tr.isLocked()
        };
    }
    if (op === 'props') {
        var tracks = a.kind === 'audio' ? s.audioTracks : s.videoTracks,
            c = tracks[a.track].clips[a.clip],
            ps = [];
        for (var i = 0; i < a.properties.length; i++) {
            var r = a.properties[i],
                cp = component(c, r.component);
            if (r.index < 0 || r.index >= cp.properties.numItems) throw 'Property missing';
            ps.push(cp.properties[r.index]);
        }
        for (var i = 0; i < ps.length; i++) {
            ps[i].setValue(a.properties[i].value, !!a.update_ui && i === ps.length - 1);
            if (!equalValue(ps[i].getValue(), a.properties[i].value)) throw 'Parameter write verification failed';
        }
        return {
            written: ps.length
        };
    }

    if (op === 'components') {
        var tracks = a.kind === 'audio' ? s.audioTracks : s.videoTracks,
            c = tracks[a.track].clips[a.clip],
            out = [];
        for (var i = 0; i < c.components.numItems; i++) {
            var cp = c.components[i],
                props = [];
            for (var j = 0; j < cp.properties.numItems; j++) {
                var p = cp.properties[j],
                    value = null,
                    ks = [];
                try {
                    value = p.getValue();
                    var keys = p.getKeys();
                    if (keys)
                        for (var k = 0; k < keys.length; k++) ks.push({
                            seconds: keys[k].seconds,
                            value: p.getValueAtKey(keys[k])
                        });
                } catch (e) {}
                props.push({
                    index: j,
                    name: p.displayName,
                    value: value,
                    keys: ks
                });
            }
            out.push({
                matchName: cp.matchName,
                name: cp.displayName,
                properties: props
            });
        }
        return out;
    }

    if (op === 'settings') {
        var st = s.getSettings();
        st.videoFrameWidth = a.width;
        st.videoFrameHeight = a.height;
        st.videoFrameRate = time(1 / a.fps);
        s.setSettings(st);
        return inventory(s);
    }
    if (op === 'preview') {
        activate(s);
        app.enableQE();
        var st = s.getSettings(),
            tc = time(a.time).getFormatted(st.videoFrameRate, st.videoDisplayFormat);
        return {
            ok: qe.project.getActiveSequence().exportFramePNG(tc, a.output),
            path: a.output + '.png'
        };
    }
    if (op === 'export') {
        if (new File(a.output).exists) throw 'Output exists';
        if (!new File(a.preset).exists) throw 'Preset missing';
        activate(s);
        return {
            result: s.exportAsMediaDirect(a.output, a.preset, 0),
            exists: new File(a.output).exists,
            bytes: new File(a.output).length
        };
    }
    if (op === 'ensure_tracks') {
        activate(s);
        app.enableQE();
        var q = qe.project.getActiveSequence(),
            guard = 0;
        while ((s.videoTracks.numTracks < a.video || s.audioTracks.numTracks < a.audio) && guard++ < 64) {
            var v = s.videoTracks.numTracks < a.video ? 1 : 0,
                au = s.audioTracks.numTracks < a.audio ? 1 : 0;
            q.addTracks(v, s.videoTracks.numTracks, au, 0, s.audioTracks.numTracks);
        }
        if (s.videoTracks.numTracks < a.video || s.audioTracks.numTracks < a.audio) throw 'Track count not reached';
        return {
            video: s.videoTracks.numTracks,
            audio: s.audioTracks.numTracks
        };
    }
    if (op === 'place') {
        var p = media(a.item),
            end = a.at + a.source_out - a.source_in,
            vt = a.media === 'audio' ? null : s.videoTracks[a.video_track],
            at = a.media === 'video' ? null : s.audioTracks[a.audio_track];
        if (a.media !== 'audio' && !vt || a.media !== 'video' && !at) throw 'Target track missing';
        if (!a.allow_overlap) {
            if (vt) collision(vt, a.at, end);
            if (at) collision(at, a.at, end);
        }
        if ((vt && vt.isLocked()) || (at && at.isLocked())) throw 'Destination track is locked';
        var oldIn = p.getInPoint().seconds,
            oldOut = p.getOutPoint().seconds;
        var created = [];
        try {
            p.setInPoint(a.source_in, 4);
            p.setOutPoint(a.source_out, 4);
            streamPlacement(s, p, a);
            if (vt) created.push(description(located(vt, p, a.at)));
            if (at) created.push(description(located(at, p, a.at)));
        } finally {
            p.setInPoint(oldIn, 4);
            p.setOutPoint(oldOut, 4);
        }
        return {
            created: created,
            media: a.media
        };
    }
    if (op === 'shift') {
        var clips = [],
            markers = [],
            targets = [];
        for (var k = 0; k < 2; k++) {
            var ts = k ? s.audioTracks : s.videoTracks;
            for (var t = 0; t < ts.numTracks; t++) {
                if (ts[t].isLocked && ts[t].isLocked()) throw 'Locked track';
                for (var i = 0; i < ts[t].clips.numItems; i++) {
                    var c = ts[t].clips[i];
                    if (c.start.seconds < a.at - 1e-7 && c.end.seconds > a.at + 1e-7) throw 'Shift boundary crosses clip';
                    if (c.start.seconds >= a.at - 1e-7) {
                        if (c.start.seconds + a.delta < 0) throw 'Negative destination';
                        targets.push({
                            c: c,
                            start: c.start.seconds,
                            end: c.end.seconds
                        });
                        clips.push(description(c));
                    }
                }
            }
        }
        if (a.delta < 0) {
            for (var typ = 0; typ < 2; typ++) {
                var ts = typ ? s.audioTracks : s.videoTracks;
                for (var t = 0; t < ts.numTracks; t++)
                    for (var i = 0; i < ts[t].clips.numItems; i++) {
                        var moving = ts[t].clips[i];
                        if (moving.start.seconds < a.at - 1e-7) continue;
                        for (var j = 0; j < ts[t].clips.numItems; j++) {
                            var fixed = ts[t].clips[j];
                            if (fixed.start.seconds >= a.at - 1e-7) continue;
                            if (moving.start.seconds + a.delta < fixed.end.seconds - 1e-7 && moving.end.seconds + a.delta > fixed.start.seconds + 1e-7) throw 'Negative shift collides with fixed clip';
                        }
                    }
            }
        }
        var m = s.markers.getFirstMarker();
        while (m) {
            if (m.start.seconds >= a.at - 1e-7) markers.push({
                m: m,
                start: m.start.seconds,
                end: Math.max(m.end.seconds, m.start.seconds)
            });
            m = s.markers.getNextMarker(m);
        }
        if (!a.dry_run) {
            targets.sort(function(x, y) {
                return a.delta >= 0 ? y.start - x.start : x.start - y.start;
            });
            for (var i = 0; i < targets.length; i++) {
                var x = targets[i];
                x.c.start = time(x.start + a.delta);
                x.c.end = time(x.end + a.delta);
            }
            for (var i = 0; i < markers.length; i++) {
                var x = markers[i];
                x.m.start = x.start + a.delta;
                x.m.end = x.end + a.delta;
            }
        }
        return {
            dryRun: a.dry_run,
            clips: clips,
            markers: markers.length,
            delta: a.delta
        };
    }
    if (op === 'fit') {
        var c = s.videoTracks[a.track].clips[a.clip],
            st = s.getSettings(),
            sw = a.source_width * a.pixel_aspect,
            sh = a.source_height,
            ratio = a.mode === 'contain' ? Math.min(st.videoFrameWidth / sw, st.videoFrameHeight / sh) : Math.max(st.videoFrameWidth / sw, st.videoFrameHeight / sh),
            m = component(c, 'AE.ADBE Motion');
        m.properties[0].setValue([.5, .5], true);
        m.properties[1].setValue(ratio * 100, true);
        return {
            scale: ratio * 100,
            mode: a.mode
        };
    }
    if (op === 'animate') {
        var c = s.videoTracks[a.track].clips[a.clip];
        for (var i = 0; i < a.properties.length; i++) {
            var spec = a.properties[i],
                p = component(c, spec.component).properties[spec.index];
            if (!p) throw 'Property missing';
            var prior = p.getKeys();
            if (p.areKeyframesSupported && !p.areKeyframesSupported()) throw 'Property does not support keyframes';
            p.setTimeVarying(true);
            if (!prior || !prior.length) {
                var initial = p.getKeys();
                if (initial)
                    for (var z = initial.length - 1; z >= 0; z--) p.removeKey(initial[z]);
            }
            if (!p.isTimeVarying()) throw 'Could not enable keyframes';
            var keys = spec.keys;
            for (var j = 0; j < keys.length; j++) {
                var key = keys[j],
                    sec = key.seconds;
                if (a.time_space === 'clip') sec += c.inPoint.seconds;
                if (a.time_space === 'sequence') sec += c.inPoint.seconds - c.start.seconds;
                var t = time(sec);
                p.addKey(t);
                p.setValueAtKey(t, key.value, false);
                if (a.ease) {
                    if (!p.setInterpolationTypeAtKey) throw 'Easing unsupported';
                    p.setInterpolationTypeAtKey(t, 5, false);
                }
            }
        }
        return {
            properties: a.properties.length,
            timeSpace: a.time_space
        };
    }
    if (op === 'relink') {
        var p = media(a.item),
            affected = [];
        for (var z = 0; z < app.project.sequences.numSequences; z++) {
            var inv = inventory(app.project.sequences[z]);
            for (var k = 0; k < 2; k++) {
                var ts = k ? inv.audio : inv.video;
                for (var t = 0; t < ts.length; t++)
                    for (var i = 0; i < ts[t].clips.length; i++)
                        if (ts[t].clips[i].nodeId === p.nodeId) affected.push({
                            sequence: inv.id,
                            clip: ts[t].clips[i]
                        });
            }
        }
        if (!a.dry_run) {
            if (!new File(a.path).exists) throw 'Replacement file missing';
            if (!p.canChangeMediaPath()) throw 'Media cannot be relinked';
            var previous = p.getMediaPath();
            p.changeMediaPath(a.path, !!a.override_checks);
            if (String(p.getMediaPath()).split('\\').join('/').toLowerCase() !== String(new File(a.path).fsName).split('\\').join('/').toLowerCase()) {
                if (new File(previous).exists) p.changeMediaPath(previous, true);
                throw 'Relink verification failed';
            }
        }
        return {
            scope: 'ProjectItem; all instances',
            affected: affected,
            dryRun: a.dry_run
        };
    }
    if (op === 'clone') return strictClone(s, a);
    if (op === 'clone_av') {
        var v = s.videoTracks[a.track].clips[a.clip],
            linked = v.getLinkedItems(),
            sourceA = null,
            sourceAT = -1,
            sourceAI = -1;
        for (var t = 0; t < s.audioTracks.numTracks; t++)
            for (var i = 0; i < s.audioTracks[t].clips.numItems; i++) {
                var ac = s.audioTracks[t].clips[i];
                for (var k = 0; k < linked.numItems; k++)
                    if (ac === linked[k] || (ac.nodeId && linked[k].nodeId && String(ac.nodeId)===String(linked[k].nodeId))) {
                        if (sourceA && (sourceAT!==t || sourceAI!==i)) throw 'Multiple linked audio clips need explicit mapping';
                        sourceA = ac;
                        sourceAT = t;
                        sourceAI = i;
                    }
            }
        if (!sourceA) throw 'Linked audio not found';
        var vd = dispatch('clone', {
                sequence: s.sequenceID,
                track: a.track,
                clip: a.clip,
                target_track: a.target_track,
                move: false,
                copy_transitions: a.copy_transitions
            }),
            ad = dispatch('clone', {
                sequence: s.sequenceID,
                track: sourceAT,
                clip: sourceAI,
                target_track: a.target_audio_track,
                kind: 'audio',
                move: false,
                copy_transitions: a.copy_transitions
            }),
            dv = located(s.videoTracks[a.target_track], v.projectItem, v.start.seconds),
            da = located(s.audioTracks[a.target_audio_track], sourceA.projectItem, sourceA.start.seconds);
        for (var typ = 0; typ < 2; typ++) {
            var ts = typ ? s.audioTracks : s.videoTracks;
            for (var t = 0; t < ts.numTracks; t++)
                for (var i = 0; i < ts[t].clips.numItems; i++) ts[t].clips[i].setSelected(0, 0);
        }
        dv.setSelected(1, 1);
        da.setSelected(1, 1);
        s.linkSelection();
        if (dv.getLinkedItems().numItems < 2) throw 'Destination pair not linked; sources retained';
        if (a.move) {
            v.remove(false, false);
            sourceA.remove(false, false);
        }
        return {
            video: vd,
            audio: ad,
            sourceAudioTrack: sourceAT,
            sourceAudioIndex: sourceAI,
            sourceRemoved: a.move
        };
    }
    if (op === 'captions') {
        if (!s.captionTracks) throw 'This Premiere version does not expose caption tracks. Use registered subtitle sources for text/export.';
        var cues = [],
            refs = [];
        for (var t = 0; t < s.captionTracks.numTracks; t++) {
            var tr = s.captionTracks[t];
            if (!tr.clips) throw 'Caption contents unavailable; use registered subtitle sources';
            for (var i = 0; i < tr.clips.numItems; i++) {
                var c = tr.clips[i],
                    text = null;
                if (c.getText) text = c.getText();
                else if (typeof c.text === 'string') text = c.text;
                else throw 'Caption text unavailable; clip names are not used as subtitle text';
                var start = c.start.seconds,
                    end = c.end.seconds,
                    delta = start >= a.from_time ? a.shift : 0;
                if (start + delta < 0) throw 'Negative caption time';
                cues.push({
                    track: t,
                    start: start + delta,
                    end: end + delta,
                    text: text
                });
                refs.push({
                    clip: c,
                    start: start,
                    end: end,
                    delta: delta
                });
            }
        }
        if (!a.dry_run)
            for (var i = 0; i < refs.length; i++) {
                var r = refs[i];
                r.clip.start = time(r.start + r.delta);
                r.clip.end = time(r.end + r.delta);
            }
        return {
            cues: cues,
            dryRun: a.dry_run,
            textSource: 'native text API'
        };
    }
    throw 'Unsupported operation ' + op;
}
