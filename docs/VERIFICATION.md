# Verification record

The revised application was exercised on Linux/Python 3.12 in the cloud workspace. Each browser run and application test used disposable event data. These results do not establish Windows execution or physical LAN/headphone behavior.

## Application checks

`python -m pytest -q`: **46 passed**, no skipped or expected-failure tests. `pip check`: no broken requirements. `bash scripts/setup-linux.sh` completed again, preserving state; `manage.py check` verified all 16 assets and both hotspot boxes.

Checks include:

- Complete canonical progression and route aliases; new credentials accept surrounding whitespace and mixed case, and previous astronomy-only passwords fail. All complete passwords remain backend-only.
- Exact level 4 ASCII decoding to `The Hunter's Red Shoulder - seal 5831`, preserving the acrostic and CSS hints. The helper decodes through explicit, non-wrapping keyboard rows to `the seven beyond the bulls eye - key crypt`; spaces and hyphen are preserved.
- Level 2's initial HTML and delivered CSS/JS contain no `TheBrightest.htm` string. The authenticated endpoint returns precisely that text with `no-store`. Anonymous, pre-level-2, blocked, and before-start requests cannot retrieve it. The live DOM and network response remain inspectable by design.
- Five failed submissions start a persistent 60-second cooldown. Correct submissions during cooldown are rejected without credential comparison or timestamp extension. Expiry and successful unlock reset the counter. Already unlocked pages/assets remain available.
- Twenty concurrent requests produce exactly **five failures and fifteen cooldown rejections**, with failure counts 1–5 recorded once. Sign-out/sign-in, another session, changed IP, and application restart do not bypass the restriction. Other participants and destination gates have independent counters.
- Organizer cooldown resets require organizer authentication, CSRF, a valid destination, and an audit reason. Reset affects only the chosen counter and records the operator, destination, previous state and reason, without recording submitted passwords.
- A populated legacy database migrates twice without changing any rows in its seven existing tables. Event clocks, completion/elapsed times, progress, allowance use, sessions, unlocks and audit records survive. Exactly one consistent pre-migration backup is produced, and both databases pass SQLite integrity checks.
- Audio synchronization is repeatable, preserves participant state/unrelated assets, and refuses unknown recordings before writing any changes. The organizer CLI uses its selected database, trims newly supplied account names, and reports paths/accounts without disclosing passwords.
- Existing protection and event tests remain: future pages/assets, helper, GIF/audio, aliases and completion image authorization at every stage; opaque sessions; recovery/blocking; six-hour timing; once-only completion; concurrent AI allowance enforcement; CSV audit; CSRF; local runtime references; private filesystem paths.
- Twelve unaffected assets match the original archive byte for byte. The four original audio backups match that archive. The GIF still has 16 frames; original hotspot geometry and Morse behavior remain intact.

## Real browsers

`tests/browser_check.py` passed against real Waitress processes in **Chromium and Firefox ESR**, using separate temporary databases. Each completed organizer sign-in/participant creation/event start, participant sign-in, door interaction, wrong credentials, all levels/helper/completion, and organizer results.

Both engines checked 800×600, 1024×768, 1366×768 and 1920×1080 layouts. Hotspots remained aligned. Every level 4 binary bit stayed inside the viewport and outside the central image. Level 2 required scrolling; its black text was selectable with a contrasting selection highlight. Other puzzle images fitted the tested viewports without page scrolling.

Chromium additionally intercepted the delayed clue request and verified that it started after `document.readyState === 'complete'`, with an empty container already below the viewport and at least 24 pixels high. A simulated fetch failure left the reserved container empty with no fallback clue. The initial HTTP source lacked the route text; the successful request populated the live DOM via `textContent`.

Chromium reported no JavaScript page errors or external page requests. Its audio context entered running state after a click and could be muted. Firefox's cloud audio backend was unavailable; the control truthfully retained “Enable sound”. Firefox's console is not collected by this checker; DOM behavior and same-origin resource entries were checked directly. Firefox needed the approved unsandboxed command to start rendering; its test proxy blocked browser traffic outside loopback.

Screenshots and machine-readable outcomes are in ignored `test-results/chromium/` and `test-results/firefox/`. These contain puzzle clues and are private organizer material. Re-running clears stale result/failure markers.

## Audio verification

The four revised MP3s append locally synthesized English speech at the existing 4×/4×/3×/3× rates. The builder copied the original poem packets without re-encoding them, matched synthesized loudness to each source, and added short pauses/fades. Byte-for-byte original files are private backups outside serving routes.

`PYTHONPATH=/workspace/void-tools/speech-qa .venv/bin/python scripts/verify_audio.py --recognize` passed using FFmpeg and PocketSphinx 5.1.0 installed as optional QA tooling outside application dependencies. Recognition chose among **all ten digits**, using the delivered MP3 tails after slowing, rather than synthesis input WAVs.

| Clip | Preserved original MP3 packets | Recognized slowed tail | Decoded peak |
| --- | ---: | --- | ---: |
| elodie_clue_4x.mp3 | 49 | seven | 0.888 |
| elodie_line2_4x.mp3 | 53 | two | 0.870 |
| elodie_line3_3x.mp3 | 55 | nine | 0.771 |
| elodie_line4_3x.mp3 | 69 | four | 0.884 |

The assembled digits are **7294**. All peaks are below clipping. Tests verify appended packets and absence of digit words/codes in public audio metadata. Full QA output is in ignored `test-results/audio.json`. There is no outstanding audio asset generation.

The preserved poem recordings and unchanged hint were not independently transcribed by ear here. Speech recognition of isolated digits does not establish physical playback quality or confirm the original poem/hint wording. Listen to the full slowed clips and hint on event equipment.

The unchanged Morse track was previously decoded as `THE EYE OF THE BULL IN THE SKY`; the original GIF's actual parent-relative music link and faint image observations are documented in the organizer guide.

## Event setup checks still required

- Execute setup/startup on the Windows host; the scripts were reviewed but not run on Windows here.
- Verify real participant-to-laptop LAN access, firewall/client isolation and any managed-browser rules.
- Listen through actual headphones/speakers: full original poem, four appended digits, unchanged hint and Morse.
- Rehearse expected load, laptop power/sleep behavior, consistent backup/restore and organizer supervision. Concurrency tests are not a capacity benchmark.
- Test HTTPS deployment if chosen. Cloud configuration saving does not establish publication or restoration into a future task.

The real event was not started, its accounts were not reset, and host firewall/network settings were not changed. Existing local data received only the additive, backed-up schema migration during setup.
