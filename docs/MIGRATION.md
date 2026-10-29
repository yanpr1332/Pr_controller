# Migration from the original script

- Install the package or use the repository-root premiere_controller.py compatibility entry.
- Construction does not install/start/restart Adobe. Run install explicitly and launch Premiere.
- Set PREMIERE_EXE and the runtime consistently. A bridge installed for a different runtime cannot serve this client.
- restart=True now raises rather than killing Premiere and potentially losing edits.
- Prefer sequenceID and nodeId selectors. Legacy sequence_index parameters remain available.
- New editing interfaces use project snapshots and transactional recovery. Successful edits can remain dirty until save_project; failed transactions reload the saved baseline, invalidating cached native object references.
- New inspection APIs return dictionaries. Compatibility operations use status/op/data records, but strict clone/move data is JSON rather than the old semicolon diagnostic string.
- Batch failures raise NativeError and include completed action information. Arbitrary JSX must throw exceptions for failures; returning a string saying ERROR is data.
- Source, clip-relative and timeline keyframe clocks are explicit. Use frame_ticks for fractional frame rates.
- Legacy add_tracks has historical placement behavior. Use ensure_tracks for deliberate append semantics.
- Selective stream placement isolates and removes the unrequested partner on a temporary track; user sound/picture tracks are preserved.
- Caption text export uses registered source files where the native text API is unavailable. It does not pretend to track manual native subtitle edits.
