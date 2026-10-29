# Local installation layout

The installation parent directory now contains only the Premiere Pro application directory and this repository. Use the repository-level `premiere_controller.py` adapter or the installed `pr_controller` package for new work.

## Active bridge

`98_pr_controller_v2.jsx` remains installed in the application Startup directory. It points to this repository's `src/pr_controller/native` directory and `runtime-v2` directory. The obsolete `99_chatgpt_controller_runner.jsx` startup script has been removed from Startup. Restart Premiere at a convenient time to unload any legacy polling loop already in memory; an open production session was not closed during cleanup.

## Local historical fixtures

The former `pr_dev_test` directory, original legacy runner and its installed copy are retained under `runtime/legacy-archive/`. These files stay local and are excluded from Git. The old test project contains historical absolute media paths; relink its media to the archived fixture directory if reopening it. New regression runs should use `tools/generate_fixtures.py` and `tools/native_smoke.py` instead.

The duplicate parent-level Python controller and README were removed after byte-for-byte comparison with `src/pr_controller/_legacy.py` and `docs/legacy-validation.md`. Obsolete heartbeat and result files were deleted. Historical documentation describes the old installation and does not define current paths.
