# Verification record

The application was implemented and exercised in the actual Linux cloud workspace. These results describe this instance and the disposable test events, not a future laptop, a published cloud snapshot or a physical event LAN.

## Automated application checks

`python -m pytest -q`: **32 tests passed**, with no skipped or expected-failure tests.

Coverage includes:

- All eight unlock transitions, canonical routes, case-insensitive/trimmed puzzle credentials, compatibility redirects and correct Linux asset capitalization.
- Wrong inputs keep progress and show the specified message, homepage error background, retry and current-level return.
- Every asset's authorization at every progress stage; guessed future pages, helper, GIF/audio and final image stay protected. Anonymous media requests, forged cookies and arbitrary paths cannot access protected files.
- Earlier audio remains available at level 6. The real original GIF bytes, its 16 frames, PNG/GIF substitution, both relative music path spellings, and unchanged original checksums are checked.
- The level 4 bits decode exactly to the required ASCII phrase. The helper binary is exact and its keyboard shift decodes to the intended phrase. Explicit source hints occur only in that page's CSS; other credentials and speech transcripts are absent from page source.
- Before-start restrictions, server-authoritative expiry, once-only start and completion, required asset/hotspot preflight, and detection of modified originals.
- Twelve concurrent AI-use submissions accept exactly three increments; corrections require reasons and retain attributed audit records. Concurrent final submissions produce one unlock/completion record.
- Independent participants, organizer/player separation, recovery preserving progress while revoking old sessions, explicit block/unblock, CSV exports, CSRF (including forged Unicode tokens), temporary rate limiting, no-store headers and persistent sessions/state across app restarts.
- Public responses use local resource references. No project-root or directory-listing route exists.

The SQLite backup command was exercised against the instance database; `PRAGMA integrity_check` on its backup returned `ok`. Repeated initialization preserved data. `pip check` reported no broken requirements. Asset import was repeated against the preserved archive and retained original bytes.

## Real browser checks and visual inspection

The optional `tests/browser_check.py` was run against a real Waitress process using a **disposable database** for each engine. Both engines completed participant creation, event start, participant sign-in, the home door, a wrong credential attempt, all seven levels, the helper and completion, then displayed organizer results.

- **Chromium:** passed. Desktop viewport sizes 800×600, 1024×768, 1366×768 and 1920×1080. Audio context entered running state following a real click and could be muted. No JavaScript page errors or external page requests were observed.
- **Firefox ESR:** passed using Mozilla geckodriver 0.37.1. The same viewport sizes and walkthrough were checked. Its cloud audio backend could not start playback; the button correctly retained “Enable sound” and `aria-pressed=false`. Firefox's console is not collected by this checker; DOM behavior and resource entries were checked directly.
- Both hotspots stayed inside and aligned with their images at the four sizes. A browser test initially found drift at large viewport sizes; the container now derives its aspect ratio from the imported image dimensions, which fixes that drift.
- The real level 2 clue started below the viewport; Ctrl+A selected its selectable black-on-black text and the selection highlight revealed it. Other puzzle-page images fit within the tested viewport bounds without document scrolling.
- The original homepage, level 1 hover, selected level 2 clue, level 4 binary cells, entry, wrong-input panel, helper, final page and organizer interface were reviewed through screenshots. No filters, cropping, recompression or image overlays were applied to the delivered clue images. Hotspots are transparent, limited regions; the rest of the image remains available for normal inspection and saving.
- The Firefox browser could not initialize its rendering processes inside the command sandbox. The successful run used the approved unsandboxed test command, with browser requests outside loopback blocked by its test proxy settings. This did not change the live event, browser policies on participant PCs, or host network/firewall configuration. Firefox was obtained through a signed Debian repository; artifact/TLS checks remained enabled.

Machine-readable results and screenshots are generated in ignored `test-results/chromium/` and `test-results/firefox/`. They are private organizer material and contain delivered clues. Re-running the checker removes stale pass/failure markers before starting.

## Original asset inspection

All 16 filenames, formats and SHA-256 checksums match their originals. Images were opened at full resolution; all GIF frames were inspected. The homepage's faint Taurus wording and level 3's faint embedded footer were verified visually, using diagnostic inversion/contrast views without changing the delivered image. The actual GIF's parent-relative music link is documented in the organizer guide.

FFmpeg decoded all six MP3 files successfully. A thresholded amplitude envelope of `music1.mp3` separated dots (~.08 s), dashes (~.21–.22 s), intra-letter gaps (~.05–.06 s), character gaps (~.42–.43 s) and word gaps (~1.17 s). International Morse decoding produced `THE EYE OF THE BULL IN THE SKY`.

The four accelerated voice clips and the spoken hint were **not independently transcribed or listened to by ear**. Their specified transcript is organizer documentation only; codec validation does not establish their actual spoken words. This is an event-day listening requirement.

## Checks still required on the event setup

- Actual Windows startup execution; Windows scripts were reviewed, while Linux setup/startup was executed.
- Participant-to-laptop LAN reachability, firewall rules, network allowlists, managed-profile policies, certificate trust if HTTPS is used, personal-device controls and the supervised AI station.
- Audible playback on physical headphones/speakers and confirmation of the hint/four slowed voice recordings against the organizer guide.
- A rehearsal under expected participant load, laptop power/sleep behavior, backup/restore practice and operational supervision. The concurrent ledger test is not a server capacity benchmark.
- HTTPS reverse-proxy deployment and fresh-task/cloud snapshot restoration. Saving environment instructions is separate from publishing or restoring the environment.

No event was started in the real instance, no production participant/organizer credentials were invented, and no host firewall settings were changed. The source and original assets are now available in the Through_The_Void GitHub repository. Keep that repository private during the event because it includes all puzzle solutions.
