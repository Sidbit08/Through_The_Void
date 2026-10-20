"""Optional private QA: FFmpeg plus PocketSphinx (--recognize only).

Speech recognition chooses among ALL ten digits. It checks the encoded,
delivered MP3 tails after slowing, rather than the source synthesis WAVs.
Physical headphone/speaker listening remains an organizer check.
"""
import argparse
import json

from update_clue_audio import CLIPS, ROOT, packet_hashes, run, samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--recognize', action='store_true')
    args = parser.parse_args()
    outcomes = []
    for name, (word, rate) in CLIPS.items():
        original = ROOT / 'instance/originals/audio-before-seals' / name
        updated = ROOT / 'instance/assets' / name
        original_packets = packet_hashes(original)
        updated_packets = packet_hashes(updated)
        assert updated_packets[:len(original_packets)] == original_packets, name
        duration = float(run('ffprobe', '-v', 'error', '-show_entries',
                             'format=duration', '-of', 'csv=p=0', str(original)))
        peak = max(abs(v) for v in samples(updated))
        assert peak < .99, (name, peak)
        info = {'file': name, 'original_packets_preserved': len(original_packets),
                'appended_packets': len(updated_packets)-len(original_packets), 'decoded_peak': peak}
        if args.recognize:
            from pocketsphinx import Decoder
            raw = run('ffmpeg', '-v', 'error', '-i', str(updated), '-af',
                      f'atrim=start={duration},asetpts=PTS-STARTPTS,asetrate={24000//rate},aresample=16000',
                      '-ar', '16000', '-ac', '1', '-f', 's16le', '-')
            decoder = Decoder(lm=None, samprate=16000, loglevel='ERROR')
            decoder.add_jsgf_string('digits', '#JSGF V1.0; grammar digits; public <digit> = zero | one | two | three | four | five | six | seven | eight | nine;')
            decoder.activate_search('digits')
            decoder.start_utt()
            decoder.process_raw(raw, False, True)
            decoder.end_utt()
            recognized = decoder.hyp().hypstr if decoder.hyp() else None
            info.update(recognized=recognized, slowed_tail_seconds=len(raw)/32000)
            assert recognized == word, (name, recognized, word)
        outcomes.append(info)
        print(json.dumps(info))
    output = ROOT / 'test-results/audio.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(outcomes, indent=2) + '\n')


if __name__ == '__main__':
    main()
