"""Zelfcontrole: python test_app.py"""
import tempfile
from pathlib import Path

import app


def main():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        card, lacie, nas = t / 'card', t / 'lacie', t / 'nas'
        (card / 'DCIM/100MSDCF').mkdir(parents=True)
        (card / 'DCIM/100MSDCF/DSC00001.JPG').write_bytes(b'foto' * 1000)
        (card / 'DCIM/100MSDCF/DSC00001.XML').write_text('sidecar')  # geen media: wordt overgeslagen
        (card / 'C0001.MP4').write_bytes(b'video' * 100000)
        lacie.mkdir()

        files = app.media_files(card)
        assert [f[0] for f in files] == ['C0001.MP4', 'DCIM/100MSDCF/DSC00001.JPG'], files

        # SD -> LaCie
        job = {'work_done': 0, 'done_files': 0}
        app.import_card(card, 'KAART1', files, lacie, 'Klant', '2026-10-19_Test', job)
        shoot = lacie / 'Klant/2026-10-19_Test'
        assert (shoot / 'C0001.MP4').read_bytes() == (card / 'C0001.MP4').read_bytes()
        m = app.load_json(shoot / app.MANIFEST)
        assert all(f['lacie_ok'] and len(f['sha256']) == 64 for f in m['files']), m
        assert job['work_done'] == 2 * sum(f[1] for f in files)

        idx = app.index(m for _, m in app.read_manifests(lacie))
        card_state = app.card_summary('X:\\', {'label': 'KAART1', 'files': files}, idx)
        assert card_state['new_count'] == 0 and not card_state['safe']

        # identiek bestand opnieuw: geen _2; ander bestand met dezelfde naam: _2, origineel blijft
        assert app.free_dest(shoot / 'C0001.MP4', card / 'C0001.MP4')[1] is not None
        (t / 'other.MP4').write_bytes(b'anders')
        assert app.free_dest(shoot / 'C0001.MP4', t / 'other.MP4') == (shoot / 'C0001_2.MP4', None)

        # beschadigde bron t.o.v. manifest wordt niet naar de NAS gezet
        good = (shoot / 'C0001.MP4').read_bytes()
        (shoot / 'C0001.MP4').write_bytes(b'kapot')
        status = {}
        app.nas_pass(lacie, nas, status)
        m = app.load_json(shoot / app.MANIFEST)
        bad = next(f for f in m['files'] if f['rel'] == 'C0001.MP4')
        assert not bad['nas_ok'] and 'hash' in bad['nas_error'], bad
        assert not (nas / 'Klant/2026-10-19_Test/C0001.MP4').exists()

        # hersteld -> volgende ronde lukt alles en is de kaart veilig
        (shoot / 'C0001.MP4').write_bytes(good)
        app.nas_pass(lacie, nas, status)
        m = app.load_json(shoot / app.MANIFEST)
        assert all(f['nas_ok'] for f in m['files']), m
        assert (nas / 'Klant/2026-10-19_Test/DCIM/100MSDCF/DSC00001.JPG').exists()
        idx = app.index(m for _, m in app.read_manifests(lacie))
        assert app.card_summary('X:\\', {'label': 'KAART1', 'files': files}, idx)['safe']

        # manifest vervangen terwijl iemand anders hem kort open heeft (bug WinError 5)
        mpath = shoot / app.MANIFEST
        fh = open(mpath, 'rb')
        app.threading.Timer(0.5, fh.close).start()
        app.save_json(mpath, app.load_json(mpath))
        assert fh.closed

        # nieuw bestand op dezelfde kaart -> alleen dat is nieuw
        (card / 'C0002.MP4').write_bytes(b'nog een clip')
        files = app.media_files(card)
        assert app.card_summary('X:\\', {'label': 'KAART1', 'files': files}, idx)['new_count'] == 1

    print('OK')


if __name__ == '__main__':
    main()
