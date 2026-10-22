# Standalone participant toolkit

`ctf-event-mode.zip` contains only the Linux toolkit, example settings, provenance,
documentation and tests. It excludes CTF application source/solutions, event data,
actual lab configuration, caches and test outputs. Do not copy the complete CTF
repository to participant machines.

Rebuild from the repository root after source/doc changes:

```sh
python3 tools/event-mode/build_bundle.py --output downloads/ctf-event-mode.zip
```

On Linux, extract the ZIP and verify its file manifest before the administrator pilot:

```sh
unzip ctf-event-mode.zip
cd ctf-event-mode
sha256sum -c MANIFEST.sha256
```

Follow the included README. This bundle is not an automatically activated policy.
