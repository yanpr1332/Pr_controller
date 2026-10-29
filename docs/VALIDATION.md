# Validation

Premiere 26.0.1 on Windows. 25 isolated native checks passed, including localized gap-aware effects, linked video/audio, source-relative clocks, strict copying, transaction rollback, stream isolation, marker shifts, video/audio transitions, caption import/source export, photo wall/page fan, PNG preview and direct MP4 export.

20 offline tests passed in the bundled Python runtime, including optional image/PDF rendering. Python and JSX syntax checks passed. Wheel packaging was verified. See native-validation.json for individual cases. Native tests created synthetic-media projects only; production HP media/projects were not used as test targets.

CI runs the offline suite. A new Premiere version must be tested separately; this report does not imply universal support for third-party plugins or unavailable caption text APIs.
