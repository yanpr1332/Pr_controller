#target premierepro
(function() {
    var root = __RUNTIME__,
        nativeDir = __NATIVE__;

    function read(f) {
        f.encoding = 'UTF8';
        if (!f.open('r')) throw 'Read failed';
        var s = f.read();
        f.close();
        return s;
    }

    function jsonQuote(v) {
        var out = '"';
        for (var i = 0; i < v.length; i++) {
            var c = v.charCodeAt(i);
            if (c === 34) out += String.fromCharCode(92, 34);
            else if (c === 92) out += String.fromCharCode(92, 92);
            else if (c < 32 || c === 8232 || c === 8233) out += String.fromCharCode(92) + 'u' + ('0000' + c.toString(16)).slice(-4);
            else out += v.charAt(i);
        }
        return out + '"';
    }

    function serialize(v, depth) {
        depth = depth || 0;
        if (depth > 32) throw 'Response nesting exceeds 32 levels';
        if (v === undefined || v === null) return 'null';
        if (typeof v === 'string') return jsonQuote(v);
        if (typeof v === 'number') return isFinite(v) ? String(v) : 'null';
        if (typeof v === 'boolean') return String(v);
        var a = [];
        if (v instanceof Array) {
            for (var i = 0; i < v.length; i++) a.push(serialize(v[i], depth + 1));
            return '[' + a.join(',') + ']';
        }
        for (var k in v)
            if (Object.prototype.hasOwnProperty.call(v, k)) a.push(jsonQuote(k) + ':' + serialize(v[k], depth + 1));
        return '{' + a.join(',') + '}';
    }

    function write(f, v) {
        f.encoding = 'UTF8';
        if (!f.open('w')) throw 'Write failed';
        f.write(serialize(v));
        f.close();
    }
    eval(read(new File(nativeDir + '/legacy.jsx')).replace(/^\uFEFF/, ''));
    eval(read(new File(nativeDir + '/operations.jsx')).replace(/^\uFEFF/, ''));
    eval(read(new File(nativeDir + '/cloning.jsx')).replace(/^\uFEFF/, ''));
    var generation = String((new Date()).getTime()) + String(Math.random());
    $.global.__prControllerGeneration = $.global.__prControllerGeneration || {};
    $.global.__prControllerGeneration[root] = generation;
    var busy = false;

    function poll() {
        if ($.global.__prControllerGeneration[root] !== generation) return;
        if (!busy) {
            busy = true;
            try {
                write(new File(root + '/heartbeat.json'), {
                    version: app.version,
                    time: (new Date()).getTime()
                });
                var jobs = new Folder(root).getFiles('*.job.json');
                jobs.sort(function(a, b) {
                    var x = read(a).match(/"submitted"\s*:\s*"(\d+)"/),
                        y = read(b).match(/"submitted"\s*:\s*"(\d+)"/);
                    var left = x ? x[1] : String(a.modified.getTime()) + '000000',
                        right = y ? y[1] : String(b.modified.getTime()) + '000000';
                    return left < right ? -1 : left > right ? 1 : 0;
                });
                if (jobs.length) {
                    var f = jobs[0];
                    if (!f.rename(f.name.replace('.job.json', '.running.json'))) {
                        busy = false;
                        app.setTimeout(poll, 200);
                        return;
                    }
                    var task = eval('(' + read(f) + ')'),
                        reply = {
                            id: task.id,
                            complete: true,
                            ok: false
                        };
                    try {
                        $.global.__prControllerRuntime = root;
                        $.global.__prTransactionDepth = 0;
                        $.global.__prTransactionSnapshot = null;
                        reply.data = dispatch(task.operation, task.args);
                        reply.ok = true;
                    } catch (e) {
                        reply.error = e.message || String(e);
                        reply.line = e.line || null;
                        reply.completed = e.completed || null;
                        reply.failedAction = e.actionIndex === undefined ? null : e.actionIndex;
                    }
                    var out = new File(root + '/' + task.id + '.result.json'),
                        tmp = new File(root + '/' + task.id + '.writing');
                    try {
                        write(tmp, reply);
                    } catch (encodingError) {
                        reply = {
                            id: task.id,
                            complete: true,
                            ok: false,
                            error: 'Response serialization failed: ' + String(encodingError)
                        };
                        write(tmp, reply);
                    }
                    if (!tmp.rename(out.name)) throw 'Response publish failed';
                    f.remove();
                }
            } catch (e) {
                try {
                    write(new File(root + '/bridge_error.json'), {
                        error: String(e)
                    });
                } catch (ignore) {}
            }
            busy = false;
        }
        app.setTimeout(poll, 200);
    }
    poll();
})();
