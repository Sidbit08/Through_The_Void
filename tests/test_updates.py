import hashlib
import json
import shutil
import sqlite3
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from conftest import ROOT, admin_login, csrf, login
from test_hunt import progress, set_progress
from void_app import create_app
from void_app.assets import CLUE_AUDIO, sync_clue_audio
from void_app.db import SCHEMA, connect, initialize
from void_app.puzzles import ANSWERS, HELPER_BITS, KEY_LEFT, KEY_RIGHT, STAGES, keyboard_encode


def submit(client, token, gate=2, username='bad', password='private-attempt-marker'):
    return client.post(STAGES[gate][0], data={'csrf': token, 'username': username, 'password': password})


def counter(app, gate=2, identity='p1'):
    with connect(app.config['DATABASE']) as db:
        row = db.execute('SELECT * FROM gate_attempts WHERE participant=? AND gate=?', (identity, gate)).fetchone()
        return dict(row) if row else None


@pytest.mark.parametrize('gate,username,password,old', [
    (5, 'Orion', 'Betelgeuse-5831', 'Betelgeuse'),
    (7, 'Taurus', 'Hyades-7294', 'Hyades'),
    (8, 'Taurus', 'Pleiades-crypt', 'Pleiades'),
])
def test_new_credentials_replace_old_and_clear_failures(app, player, gate, username, password, old):
    client, token = player
    set_progress(app, gate-1)
    assert submit(client, token, gate, username, old).status_code == 401
    assert progress(app)['progress'] == gate-1
    assert counter(app, gate)['failures'] == 1
    assert submit(client, token, gate, f' {username.upper()} ', f'\t{password.upper()}\n').status_code == 302
    assert progress(app)['progress'] == gate
    assert counter(app, gate) is None


def test_exact_keyboard_mapping_without_wrap():
    assert KEY_LEFT['w'] == 'q' and KEY_LEFT['p'] == 'o'
    assert KEY_LEFT['s'] == 'a' and KEY_LEFT['m'] == 'n'
    assert KEY_RIGHT['q'] == 'w' and KEY_RIGHT['j'] == 'k'
    for edge in 'qaz':
        with pytest.raises(KeyError):
            keyboard_encode(edge)
    cipher = ''.join(chr(int(byte, 2)) for byte in HELPER_BITS.split())
    assert all(len(byte) == 8 for byte in HELPER_BITS.split())
    assert ''.join(KEY_RIGHT.get(c, c) for c in cipher) == 'the seven beyond the bulls eye - key crypt'
    assert keyboard_encode(' - ') == ' - '


def test_fragment_only_after_authorized_level_two_and_not_initial_sources(app, player):
    client, _ = player
    assert app.test_client().get('/fragment').status_code == 302
    for stage in (0, 1):
        set_progress(app, stage)
        assert client.get('/fragment').status_code == 404
    set_progress(app, 2)
    page = client.get('/level2.htm')
    sources = [page.text] + [client.get('/static/' + name).text for name in ('site.css', 'sound.js', 'fragment.js')]
    assert all('TheBrightest.htm' not in source for source in sources)
    assert '<p id="fragment" class="buried-text"></p>' in page.text
    script = sources[-1]
    assert 'textContent = text' in script and "addEventListener('load'" in script
    clue = client.get('/fragment')
    assert clue.status_code == 200 and clue.text == 'TheBrightest.htm'
    assert clue.mimetype == 'text/plain' and 'no-store' in clue.headers['Cache-Control']
    with connect(app.config['DATABASE']) as db:
        db.execute("UPDATE participants SET blocked=1 WHERE id='p1'")
    assert client.get('/fragment').status_code == 403
    with connect(app.config['DATABASE']) as db:
        db.execute("UPDATE participants SET blocked=0 WHERE id='p1'")
        db.execute('UPDATE event SET start=NULL,deadline=NULL')
    assert client.get('/fragment').status_code == 403


def test_fifth_failure_blocks_without_validation_or_extension_then_expires(app, player, monkeypatch):
    client, token = player
    set_progress(app, 1)
    for attempt in range(1, 6):
        result = submit(client, token)
        assert result.status_code == 401
        assert 'ERROR 404: Wrong input provided.' in result.text
        assert counter(app)['failures'] == attempt
    assert result.headers['Retry-After'] == '60'
    until = counter(app)['cooldown_until']
    # Fail loudly if puzzle comparison is attempted during cooldown. CSRF still runs.
    import hmac
    original_compare = hmac.compare_digest
    def guarded(a, b):
        assert b not in (b'thelesser', b'procyon'), 'credentials validated during cooldown'
        return original_compare(a, b)
    with monkeypatch.context() as patch:
        patch.setattr(hmac, 'compare_digest', guarded)
        app.clock[0] += 17.2
        for _ in range(3):
            result = submit(client, token, username='TheLesser', password='Procyon')
            assert result.status_code == 429 and result.headers['Retry-After'] == '43'
        assert client.get('/level2.htm').status_code == 429
    assert counter(app)['cooldown_until'] == until
    assert client.get('/level1.htm').status_code == 200
    assert client.get('/Level1.jpeg').status_code == 200
    assert progress(app)['progress'] == 1
    app.clock[0] = until
    assert submit(client, token).status_code == 401
    assert counter(app)['failures'] == 1 and counter(app)['cooldown_until'] is None
    assert submit(client, token, username='TheLesser', password='Procyon').status_code == 302
    assert counter(app) is None
    with connect(app.config['DATABASE']) as db:
        events = [dict(row) for row in db.execute('SELECT * FROM gate_events')]
    assert [e['failures'] for e in events if e['event'] == 'failure'] == [1, 2, 3, 4, 5, 1]
    assert sum(e['event'] == 'cooldown-start' for e in events) == 1
    assert sum(e['event'] == 'cooldown-expired' for e in events) == 1
    assert 'private-attempt-marker' not in json.dumps(events)


def test_cooldown_survives_new_session_ip_logout_and_app_restart(app, player):
    client, token = player
    set_progress(app, 1)
    for _ in range(5):
        submit(client, token)
    original = counter(app)
    assert client.post('/logout', data={'csrf': token}).status_code == 302
    fresh_token = login(client)
    assert submit(client, fresh_token).status_code == 429
    second = app.test_client()
    second.environ_base['REMOTE_ADDR'] = '192.168.1.200'
    second_token = login(second)
    assert submit(second, second_token).status_code == 429
    restarted = create_app({'TESTING': True, 'DATA_DIR': app.config['DATA_DIR'], 'CLOCK': lambda: app.clock[0]})
    restored = restarted.test_client()
    restored.set_cookie('void_player', second.get_cookie('void_player').value)
    assert submit(restored, second_token).status_code == 429
    other = app.test_client()
    other_token = login(other, 'p2')
    with connect(app.config['DATABASE']) as db:
        db.execute("UPDATE participants SET progress=1 WHERE id='p2'")
    assert submit(other, other_token).status_code == 401
    assert counter(app) == original
    # A destination's counter does not affect other destinations for the same ID.
    set_progress(app, 2)
    assert submit(client, fresh_token, gate=3).status_code == 401
    assert counter(app, 3)['failures'] == 1
    assert client.get('/level2.htm').status_code == 200


def test_concurrent_failed_guesses_cannot_exceed_five(app, player):
    client, token = player
    set_progress(app, 1)
    cookie = client.get_cookie('void_player').value
    def attempt(_):
        other = app.test_client()
        other.set_cookie('void_player', cookie)
        return submit(other, token).status_code
    with ThreadPoolExecutor(max_workers=12) as pool:
        statuses = list(pool.map(attempt, range(20)))
    assert statuses.count(401) == 5 and statuses.count(429) == 15
    assert counter(app)['failures'] == 5
    assert counter(app)['cooldown_until'] == app.clock[0] + 60
    with connect(app.config['DATABASE']) as db:
        failures = db.execute("SELECT failures FROM gate_events WHERE event='failure' ORDER BY id").fetchall()
    assert [row[0] for row in failures] == [1, 2, 3, 4, 5]


def test_organizer_reset_requires_auth_csrf_reason_and_is_scoped_and_audited(app, player):
    client, token = player
    set_progress(app, 1)
    for _ in range(5):
        submit(client, token)
    before = dict(progress(app))
    with connect(app.config['DATABASE']) as db:
        db.execute("INSERT INTO gate_attempts VALUES('p1',3,2,NULL)")
    unauth = app.test_client()
    guest_token = csrf(unauth.get('/organizer/login'))
    reset = {'csrf': guest_token, 'action': 'reset-cooldown', 'participant': 'p1', 'gate': '2', 'reason': 'Supervised retry'}
    assert unauth.post('/organizer', data=reset).status_code == 302
    admin = app.test_client()
    admin_token = admin_login(admin)
    assert admin.post('/organizer', data=reset).status_code == 400
    reset['csrf'] = admin_token
    assert admin.post('/organizer', data={**reset, 'reason': ''}).status_code == 400
    assert admin.post('/organizer', data={**reset, 'gate': '9'}).status_code == 400
    assert counter(app)['failures'] == 5
    assert admin.post('/organizer', data=reset).status_code == 302
    assert counter(app) is None and counter(app, 3)['failures'] == 2
    assert dict(progress(app)) == before
    assert submit(client, token).status_code == 401
    with connect(app.config['DATABASE']) as db:
        log = db.execute("SELECT * FROM audit WHERE action='reset-cooldown'").fetchone()
    assert log['organizer'] == 'astronomer' and log['participant'] == 'p1'
    detail = json.loads(log['detail'])
    assert detail['gate'] == '/level2.htm' and detail['previous']['failures'] == 5
    assert detail['reason'] == 'Supervised retry'
    assert 'private-attempt-marker' not in admin.get('/organizer/audit.csv').text


def test_legacy_migration_preserves_every_existing_table_and_creates_backup(tmp_path):
    path = tmp_path / 'void.sqlite3'
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.execute('UPDATE event SET start=100,deadline=21700')
    db.execute("INSERT INTO participants VALUES('team','hash',8,2,0,150,50)")
    db.execute("INSERT INTO organizers VALUES(1,'operator','organizer-hash')")
    db.execute("INSERT INTO sessions VALUES('token','participant','team','csrf',9999999999)")
    db.execute("INSERT INTO unlocks VALUES('team',8,150)")
    db.execute("INSERT INTO audit VALUES(1,'team','operator',140,'use-ai','existing',1)")
    db.execute("INSERT INTO attempts VALUES('login',120,2)")
    db.commit()
    tables = ['event', 'participants', 'organizers', 'sessions', 'unlocks', 'audit', 'attempts']
    expected = {name: db.execute(f'SELECT * FROM {name}').fetchall() for name in tables}
    db.close()
    initialize(path)
    initialize(path)
    with sqlite3.connect(path) as migrated:
        assert migrated.execute('PRAGMA user_version').fetchone()[0] == 1
        assert migrated.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        for name, rows in expected.items():
            assert migrated.execute(f'SELECT * FROM {name}').fetchall() == rows
    backups = list((tmp_path / 'backups').glob('before-gate-migration-*.sqlite3'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        for name, rows in expected.items():
            assert backup.execute(f'SELECT * FROM {name}').fetchall() == rows


def test_safe_audio_sync_is_idempotent_and_preserves_database_and_other_assets(app):
    data = Path(app.config['DATA_DIR'])
    for name in CLUE_AUDIO:
        shutil.copyfile(ROOT / 'instance/originals/audio-before-seals' / name, data / 'assets' / name)
    before = dict(progress(app))
    unrelated = (data / 'assets/hint.mp3').read_bytes()
    for _ in range(2):
        assert sync_clue_audio(ROOT / 'instance', data) == list(CLUE_AUDIO)
    assert dict(progress(app)) == before
    assert (data / 'assets/hint.mp3').read_bytes() == unrelated
    for name in CLUE_AUDIO:
        assert (data / 'assets' / name).read_bytes() == (ROOT / 'instance/assets' / name).read_bytes()
        assert (data / 'backups/audio-before-seals' / name).read_bytes() == (ROOT / 'instance/originals/audio-before-seals' / name).read_bytes()
    (data / 'assets' / CLUE_AUDIO[-1]).write_bytes(b'custom-recording')
    (data / 'assets' / CLUE_AUDIO[0]).write_bytes((ROOT / 'instance/originals/audio-before-seals' / CLUE_AUDIO[0]).read_bytes())
    with pytest.raises(ValueError, match='unrecognized'):
        sync_clue_audio(ROOT / 'instance', data)
    assert (data / 'assets' / CLUE_AUDIO[0]).read_bytes() == (ROOT / 'instance/originals/audio-before-seals' / CLUE_AUDIO[0]).read_bytes()


def test_unaffected_assets_match_original_archive():
    archive = next((ROOT / 'instance/originals').glob('*.zip'))
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            basename = Path(name).name
            path = ROOT / 'instance/assets' / basename
            if path.is_file():
                original = ROOT / 'instance/originals/audio-before-seals' / basename
                assert source.read(name) == (original if basename in CLUE_AUDIO else path).read_bytes()


def test_organizer_cli_uses_selected_database_trims_username_and_reports_no_secrets(app, monkeypatch, capsys):
    import manage
    data = str(app.config['DATA_DIR'])
    password = 'temporary-private-test-passphrase'
    monkeypatch.setattr('sys.argv', ['manage.py', '--data-dir', data, 'organizer', '  recovered-admin  '])
    monkeypatch.setattr(manage.getpass, 'getpass', lambda _prompt: password)
    manage.main()
    output = capsys.readouterr().out
    assert str(app.config['DATABASE']) in output and password not in output
    admin = app.test_client()
    token = csrf(admin.get('/organizer/login'))
    assert admin.post('/organizer/login', data={'csrf': token, 'identity': 'recovered-admin', 'password': password}).status_code == 302
    monkeypatch.setattr('sys.argv', ['manage.py', '--data-dir', data, 'status'])
    manage.main()
    output = capsys.readouterr().out
    assert 'recovered-admin' in output and str(app.config['DATABASE']) in output
    assert password not in output and 'password_hash' not in output


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='optional audio QA requires FFmpeg')
def test_audio_retains_original_packets_has_appended_speech_and_no_digit_metadata():
    from scripts.update_clue_audio import packet_hashes, run, samples
    for name in CLUE_AUDIO:
        original = ROOT / 'instance/originals/audio-before-seals' / name
        updated = ROOT / 'instance/assets' / name
        old = packet_hashes(original)
        new = packet_hashes(updated)
        assert new[:len(old)] == old and len(new) > len(old)
        assert max(abs(v) for v in samples(updated)) < .99
        tags = json.loads(run('ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(updated)))
        public_tags = json.dumps(tags['format'].get('tags', {})) + json.dumps([s.get('tags', {}) for s in tags['streams']])
        assert all(word not in public_tags.casefold() for word in ('seven', 'two', 'nine', 'four', '7294'))
