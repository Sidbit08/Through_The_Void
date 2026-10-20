"""Private, optional audio build tool. Requires FFmpeg with its flite filter.

Only newly synthesized tails are encoded. The original poem MP3 packets are
copied, in order, without re-encoding. This is not an application dependency.
"""
import array
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIPS = {
    'elodie_clue_4x.mp3': ('seven', 4),
    'elodie_line2_4x.mp3': ('two', 4),
    'elodie_line3_3x.mp3': ('nine', 3),
    'elodie_line4_3x.mp3': ('four', 3),
}


def run(*args):
    return subprocess.check_output(args, stderr=subprocess.PIPE)


def packet_hashes(path):
    info = json.loads(run('ffprobe', '-v', 'error', '-select_streams', 'a:0',
                          '-show_packets', '-show_data_hash', 'sha256',
                          '-of', 'json', str(path)))
    return [p['data_hash'] for p in info['packets']]


def samples(path):
    result = array.array('f')
    result.frombytes(run('ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1',
                        '-f', 'f32le', '-'))
    return result


def main():
    originals = ROOT / 'instance/originals/audio-before-seals'
    originals.mkdir(parents=True, exist_ok=True)
    report_path = ROOT / 'instance/asset-report.json'
    report = json.loads(report_path.read_text())
    with tempfile.TemporaryDirectory(prefix='void-audio-') as temporary:
        work = Path(temporary)
        for name, (word, rate) in CLIPS.items():
            target = ROOT / 'instance/assets' / name
            original = originals / name
            if not original.exists():
                shutil.copyfile(target, original)
            spoken = work / 'spoken.wav'
            run('ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                f'flite=text={word}:voice=rms', '-y', str(spoken))
            old, new = samples(original), samples(spoken)
            rms = lambda values: (sum(v*v for v in values)/len(values))**.5
            gain = min(rms(old)/rms(new), .80/max(abs(v) for v in new))
            tail = work / 'tail.mp3'
            # Silence is expressed at normal speed before matching acceleration.
            filters = (f'volume={gain},afade=t=in:d=0.01,adelay=350:all=1,'
                       f'apad=pad_dur=0.20,asetrate={16000*rate},aresample=24000')
            run('ffmpeg', '-v', 'error', '-i', str(spoken), '-af', filters,
                '-ac', '2', '-ar', '24000', '-b:a', '96k', '-map_metadata', '-1',
                '-id3v2_version', '0', '-y', str(tail))
            # Temporary filenames contain no shell/concat syntax from user input.
            shutil.copyfile(original, work / 'original.mp3')
            listing = work / 'concat.txt'
            listing.write_text("file 'original.mp3'\nfile 'tail.mp3'\n")
            output = work / 'updated.mp3'
            run('ffmpeg', '-v', 'error', '-f', 'concat', '-safe', '1', '-i', str(listing),
                '-c:a', 'copy', '-map_metadata', '-1', '-id3v2_version', '0',
                '-y', str(output))
            hashes = packet_hashes(original)
            assert packet_hashes(output)[:len(hashes)] == hashes, name
            peak = max(abs(v) for v in samples(output))
            assert peak < .99, (name, peak)
            shutil.copyfile(output, target)
            payload = target.read_bytes()
            report[name] = {'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
            print(f'{name}: preserved {len(hashes)} original packets; peak {peak:.3f}')
    report_path.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
