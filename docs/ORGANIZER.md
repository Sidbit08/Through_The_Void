# Private organizer guide — contains solutions

Keep this document and the project source away from participant PCs. The application does not serve this directory.

## Progression

Participant accounts are separate from the following puzzle credentials. Credential matching trims surrounding whitespace and ignores letter case. The gate belongs to the **destination** page.

| Discovered at | Destination | Username | Password |
| --- | --- | --- | --- |
| Home door | `/level1.htm` | Door click | — |
| Level 1 | `/level2.htm` | TheLesser | Procyon |
| Level 2 | `/TheBrightest.htm` | TheBrightest | Sirius |
| Level 3 | `/Orion.htm` | Orion | Rigel |
| Level 4 | `/Hunted.htm` | Orion | Betelgeuse |
| Level 5 | `/vivid.htm` | Taurus | Aldebaran |
| Level 6 | `/brightside.htm` | Taurus | Hyades |
| Level 7 | `/thevoid.htm` | Taurus | Pleiades |

`/Level2.htm` and `/Brightest.htm` redirect to canonical paths with the same server authorization. `/scrambled.htm` is a helper requiring level 7 access. It is not an eighth level. Internal progress 0 is home, 1–7 are levels, and 8 means completed. Direct image/audio requests check the same participant record. Earlier assets remain available throughout later stages.

## Puzzle walkthrough

1. Inspect homepage CSS source for the image hint. Click within the galaxy door. The faint word **Taurus**, below the large title near original image coordinates (290,642), supplies the later username. It is present at full resolution; originals are served unchanged for new-tab inspection.
2. On level 1, hover the interior bright white star centered near (902,331) in the 1536×1024 JPEG. The username is revealed through CSS. Read the CSS hints and edit the route to `/level2.htm`. The lesser hound's preceding star is Procyon. The first sped-up audio link is a CSS comment.
3. On level 2, scroll below the first viewport and select all text. Black-on-black real text reveals `TheBrightest.htm`. Sirius is the brightest night-sky star. The second sped-up audio is in CSS.
4. Open level 3's original image, invert its colors in an external tool, and inspect at full size. The footer reads “THE HUNTER'S BLUE FOOT IN THE SKY” and “ORION”. Use Orion/Rigel at `/Orion.htm`. The third sped-up audio is in CSS.
5. Read the black/white byte groups left to right, top row to bottom row: **1 is black; 0 is white**. Every group contains eight cells. ASCII decodes to `The Hunter's Red Shoulder` (straight apostrophe, no leading/trailing spaces). The poem's initials spell ASCII; the username is still Orion and the password is Betelgeuse. CSS supplies the next route and fourth audio.
6. On level 5, open `/Level5.png` and replace its extension with `.gif`. Watch the original 16-frame animation, which fades a music link into view. Follow it to the Morse audio, decode its message, and use Taurus/Aldebaran at `/vivid.htm`. Taurus comes from the homepage.
7. On level 6, the hint audio is intended to say “You always had the audio”. Download and slow down the four earlier clips, maintaining the original web-served files. Their specified collective text is:

   > The Bull's bright eye is not alone,  
   > His face is traced by stars unknown.  
   > A V-shaped cluster marks his brow,  
   > Seek the stellar herd that gathers now.

   This identifies the Hyades. The website does not expose this transcript.
8. On level 7, select the camouflaged text. Replace `scrambled.png` with `scrambled.htm` at the root. Decode the binary into `rgw awcwb vwtibs rgw vykka wtw`. Move each letter one QWERTY key right: `the seven beyond the bulls eye`. The answer is Pleiades; the username is still Taurus. Completing the final gate records server time and elapsed event time exactly once and unlocks the winter-sky image.

## Resolved ambiguities and actual asset observations

- The original text is supporting material. The detailed build request supersedes its placeholder instruction, browser-extension detection request, contradictory wrong-input behavior and inconsistent filenames. No automatic AI detection is implemented.
- The supplied level 1 is **`Level1.jpeg`**, encoded as JPEG; there is no `Level1.png`. No disguised file conversion or renaming was used. The supplied level 6 is **`Level6.png`**, not `level6.png`. The animation is **`Level5.gif`**, not `level5.gif`.
- The source text does not identify the white spot by coordinates. The chosen target is the prominent **interior** white star near (902,331), away from the star cut by the top edge. Its normalized hitbox is x=.578, y=.308, width=.019, height=.031. The door hitbox is an inscribed rectangle x=.56, y=.45, width=.26, height=.32, within the visible galaxy doorway. Both were checked at multiple desktop sizes. Change these with `manage.py hotspot NAME X Y WIDTH HEIGHT` only after inspecting the original.
- Level 3's footer includes ORION but does **not** literally specify `.htm` or an entire URL. The minimal assumption is to replace the complete root image basename and extension: `/Level3.png` → `/Orion.htm`, following the `.htm` convention established by earlier pages. The footer remains faint even when inverted; zoom/full-resolution inspection may be needed. No supplemental visible hint has been invented.
- The actual GIF reads **`../music1.mp3`**, while the detailed request says `./music1.mp3`. Both resolve to `/music1.mp3` from `/Level5.gif`, because all three assets are served at the root. The original GIF is unaltered. Frame durations are 900 ms, fourteen 60 ms frames, then 5060 ms; it loops indefinitely.
- The Morse signal was decoded programmatically to **THE EYE OF THE BULL IN THE SKY**. The terminal full stop in the written specification is not encoded. This does not change the solution.
- All MP3s decode without errors. Durations are approximately 1.176 s, 1.272 s, 1.320 s and 1.656 s for the four accelerated clips, 3.936 s for the hint, and 24.451 s for Morse. The voice clips and hint have **not been independently transcribed by ear** here. An organizer must listen to the hint and slowed speech before event launch and confirm that their wording matches the intended puzzle. Do not treat a successful codec check as proof of the spoken content.
- No separate static track was supplied. A very quiet local Web Audio noise loop is offered through an explicit “Enable sound” gesture. Each navigation may require re-enabling; the control reflects the actual audio-context state. It does not autoplay the clue recordings.
- The reference site could not be fetched in this environment (HTTP 403). The supplied interaction requirements were implemented directly, without copying artwork or puzzles from that site.

Original dimensions, frame counts and SHA-256 values are in `instance/asset-report.json`. All 16 assets were extracted through an allowlist after ZIP path/symlink/size validation. Original bytes and the source archive are preserved. No required files are missing.

## Event and ledger operations

Create participants before launch in organizer control. Generated codes are shown only once and stored as password hashes. Recovery rotates the access code, revokes that participant's existing sessions, and retains all progress and timestamps. Puzzle credentials never authenticate a participant account.

Start is explicit and cannot be repeated to extend the deadline. It requires every asset to match the saved original checksum and both hotspot boxes to be calibrated. Before start, participants may sign in but cannot see puzzles. After expiry, participants may revisit unlocked material; new unlocks and completions are refused by server time.

Record an AI use immediately before a supervised prompt. A database transaction increments the count only if fewer than three uses exist. Corrections subtract one use, require an audit reason, and append an immutable-through-UI ledger entry attributed to the organizer. A correction can be made after expiry to fix results. The UI has no unaudited allowance reset. This ledger does not enforce another site's account or API limits.

Use an explicit block with a reason for a policy violation. The affected player sees `ERROR: A.I. will cook your Brain. Don't try this.` over the homepage artwork. Their progress is retained; an unblock also requires a reason. No extension fingerprinting or speculative detection is used.

Export results and the complete audit ledger separately. The result CSV contains stage, allowance use, policy status, completion/elapsed time and each successful unlock time. The full audit CSV includes participant, organizer, action, reason, server timestamp and allowance delta. CSV formula-like user strings are neutralized. Neither export contains access codes, session tokens or puzzle passwords.

## Operational security boundary

CSS, images and audio **are meant to be inspected and saved**. A participant can share a discovered clue, URL or puzzle answer with someone else; the site cannot prevent that. Progress enforcement prevents skipping server gates, not answer sharing. Downloaded media and browser history cannot be remotely erased after the fact. Use the sign-out control and clear downloads/history when reassigning a shared PC.

Only allowlisted public CSS/JS and authorized original assets are served. Expected answers stay in the server module. There are no debug/source endpoints or public filesystem directory mounts. CSRF checks cover state-changing forms; session IDs rotate on login/logout. Organizer and player cookies are independent. Wrong credentials give the same message regardless of which field failed. Gate attempts are limited to 15 per minute per participant/IP, entry to 15 per minute/IP and organizer login to 8 per minute/IP; retrying after the window works normally.

Restrict OS access to `instance/`, backups, logs and this guide. SQLite hashes and sessions are private even though no service route exposes them. Protect the laptop's clock, suspend settings and disk. The owner of the server account and filesystem is a trusted operator. HTTP/HTTPS tradeoffs and backup/restore procedures are in the README.
