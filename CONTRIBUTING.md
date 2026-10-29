# Contributing

Run `python -m unittest discover -s tests -v` before submitting changes. Native integration tests must use a new isolated project and generated media. Never use a production editing project as a test fixture.

Record the exact Premiere version and which operations were verified. Keep unavailable or unverified native capabilities explicit. Do not add Adobe binaries, user projects, credentials or recordings. A timed-out task may still be running; inspect its ID before retrying.
