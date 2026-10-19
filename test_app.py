"""Zelfcontrole: python test_app.py"""
import csv
import struct
import tempfile
from pathlib import Path

import app


def states(card, lacie, lidx):
    return {f[0]: f[3] for f in app.file_states(card, app.registry(app.read_manifests(lacie), lacie), lidx)}


def main():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        card_root, lacie, nas = t / 'card', t / 'drive/00_Bronbestanden', t / 'nas'
        (card_root / 'DCIM/100MSDCF').mkdir(parents=True)
        (card_root / 'PRIVATE/M4ROOT/THMBNL').mkdir(parents=True)
        mini = b'\xff\xd8mini\xff\xd9'  # EXIF met een miniatuur in IFD1, zoals camera's die schrijven
        tiff = (b'II' + struct.pack('<HI', 42, 8) + struct.pack('<HI', 0, 14) + struct.pack('<H', 2)
                + struct.pack('<HHII', 0x201, 4, 1, 44) + struct.pack('<HHII', 0x202, 4, 1, len(mini))
                + struct.pack('<I', 0) + mini)
        (card_root / 'DCIM/100MSDCF/DSC00001.JPG').write_bytes(
            b'\xff\xd8\xff\xe1' + struct.pack('>H', len(tiff) + 8) + b'Exif\0\0' + tiff + b'\xff\xd8foto' * 1000)
        (card_root / 'DCIM/100MSDCF/DSC00002.JPG').write_bytes(b'andere klant' * 100)
        (card_root / 'DCIM/100MSDCF/DSC00001.XML').write_text('sidecar')  # geen media: overgeslagen
        (card_root / 'PRIVATE/M4ROOT/THMBNL/C0001T01.JPG').write_bytes(b'clipminiatuur')  # niet kopiëren
        (card_root / 'C0001.MP4').write_bytes(b'video' * 100000)
        lacie.mkdir(parents=True)

        files = app.media_files(card_root)
        assert [f[0] for f in files] == ['C0001.MP4', 'DCIM/100MSDCF/DSC00001.JPG', 'DCIM/100MSDCF/DSC00002.JPG'], files
        card = {'label': 'KAART1', 'files': files, 'mismatch': set()}

        # miniaturen: EXIF-miniatuur uit de JPG, Sony-miniatuur voor de clip
        assert app.thumbnail(card_root, 'DCIM/100MSDCF/DSC00001.JPG') == b'\xff\xd8mini\xff\xd9'
        (card_root / 'PRIVATE/M4ROOT/CLIP').mkdir()
        (card_root / 'PRIVATE/M4ROOT/CLIP/C0001.MP4').write_bytes(b'')
        assert app.thumbnail(card_root, 'PRIVATE/M4ROOT/CLIP/C0001.MP4') == b'clipminiatuur'

        # foto 1 en de clip staan al met de hand op de LaCie (oude map); foto 1 identiek, clip niet
        old = lacie / '01_Klant/oude_map'
        old.mkdir(parents=True)
        (old / 'DSC00001.JPG').write_bytes((card_root / 'DCIM/100MSDCF/DSC00001.JPG').read_bytes())
        (old / 'C0001.MP4').write_bytes(b'VIDEO' * 100000)  # zelfde naam en grootte, andere inhoud
        lidx = app.build_lacie_index(lacie)
        assert states(card, lacie, None) == dict.fromkeys(states(card, lacie, None), 'scan')
        s = states(card, lacie, lidx)
        assert s == {'C0001.MP4': 'dup', 'DCIM/100MSDCF/DSC00001.JPG': 'dup', 'DCIM/100MSDCF/DSC00002.JPG': 'new'}, s

        # dubbels controleren: foto 1 wordt geregistreerd, de clip blijkt anders en wordt "nieuw"
        job = {'work_done': 0, 'done_files': 0}
        dups = [f for f in files if s[f[0]] == 'dup']
        app.adopt_files(card_root, 'KAART1', dups, lacie, lidx, job, card['mismatch'])
        assert card['mismatch'] == {'C0001.MP4'}
        s = states(card, lacie, lidx)
        assert s == {'C0001.MP4': 'new', 'DCIM/100MSDCF/DSC00001.JPG': 'lacie', 'DCIM/100MSDCF/DSC00002.JPG': 'new'}, s
        assert not list(lacie.rglob('DSC00001_2.JPG'))  # geen dubbel gemaakt

        # selectie: alleen de clip naar klant A, foto 2 later naar klant B
        clip = [f for f in files if f[0] == 'C0001.MP4']
        app.import_card(card_root, 'KAART1', clip, lacie, '01_Klant', '26-10-19_Shoot', job, lidx)
        shoot = lacie / '01_Klant/26-10-19_Shoot'
        assert (shoot / 'C0001.MP4').read_bytes() == (card_root / 'C0001.MP4').read_bytes()
        assert (old / 'C0001.MP4').read_bytes() == b'VIDEO' * 100000  # oude map onaangeroerd
        assert states(card, lacie, lidx)['DCIM/100MSDCF/DSC00002.JPG'] == 'new'
        foto2 = [f for f in files if f[0] == 'DCIM/100MSDCF/DSC00002.JPG']
        client = app.clean_path(r'02_Andere\01_Locatie', 2)
        app.import_card(card_root, 'KAART1', foto2, lacie, client, '26-10-19_Event', job, lidx, Path('Camera'))
        event = lacie / '02_Andere/01_Locatie/26-10-19_Event'
        assert (event / 'Camera/DSC00002.JPG').exists()  # plat: geen DCIM/100MSDCF
        assert app.load_json(event / app.MANIFEST)['files'][0]['rel'] == 'Camera/DSC00002.JPG'
        assert r'02_Andere\01_Locatie' in app.client_dirs(lacie)
        assert r'02_Andere\01_Locatie\26-10-19_Event' not in app.client_dirs(lacie)

        # zelfde bestandsnaam uit twee cameramappen in één platte map: tweede wordt naam_2, niets overschreven
        (card_root / 'DCIM/101MSDCF').mkdir()
        (card_root / 'DCIM/101MSDCF/DSC00002.JPG').write_bytes(b'na de teller-reset')
        app.import_card(card_root, 'KAART1', [('DCIM/101MSDCF/DSC00002.JPG', 18, 0)], lacie, client, '26-10-19_Event', job, lidx, Path('Camera'))
        assert (event / 'Camera/DSC00002_2.JPG').read_bytes() == b'na de teller-reset'
        assert (event / 'Camera/DSC00002.JPG').read_bytes() == b'andere klant' * 100

        # mappen: geen '..' of te diepe paden; manifest hoort bij de shootmap (JJ-MM-DD_naam)
        for bad in ('..', r'01_Klant\..\..', r'a\b\c'):
            try:
                app.clean_path(bad, 2)
                raise AssertionError(bad)
            except ValueError:
                pass
        assert app.manifest_dir(lacie, '02_X/01_Eke/25-08-12_Bert/Camera/A.JPG') == (lacie / '02_X/01_Eke/25-08-12_Bert', 'Camera/A.JPG')
        assert app.manifest_dir(lacie, '01_VMRE/25-xx-xx_old/Gebouw/B.JPG') == (lacie / '01_VMRE/25-xx-xx_old', 'Gebouw/B.JPG')
        assert app.manifest_dir(lacie, '01_Klant/oude_map/C.JPG') == (lacie / '01_Klant/oude_map', 'C.JPG')

        # identiek bestand opnieuw: geen _2; ander bestand met dezelfde naam: _2, origineel blijft
        assert app.free_dest(shoot / 'C0001.MP4', card_root / 'C0001.MP4')[1] is not None
        (t / 'other.MP4').write_bytes(b'anders')
        assert app.free_dest(shoot / 'C0001.MP4', t / 'other.MP4') == (shoot / 'C0001_2.MP4', None)

        # beschadigd bestand op de LaCie t.o.v. manifest gaat niet naar de NAS
        good = (shoot / 'C0001.MP4').read_bytes()
        (shoot / 'C0001.MP4').write_bytes(b'kapot')
        app.nas_pass(lacie, nas, {})
        bad = next(f for f in app.load_json(shoot / app.MANIFEST)['files'] if f['rel'] == 'C0001.MP4')
        assert not bad['nas_ok'] and 'hash' in bad['nas_error'], bad
        assert not (nas / '01_Klant/26-10-19_Shoot/C0001.MP4').exists()

        # hersteld -> alles op de NAS (ook het geregistreerde oude bestand) en de kaart is veilig
        (shoot / 'C0001.MP4').write_bytes(good)
        app.nas_pass(lacie, nas, {})
        assert (nas / '01_Klant/oude_map/DSC00001.JPG').exists()
        assert set(states(card, lacie, lidx).values()) == {'safe'}

        # manifest vervangen terwijl iemand anders hem kort open heeft (bug WinError 5)
        mpath = shoot / app.MANIFEST
        fh = open(mpath, 'rb')
        app.threading.Timer(0.5, fh.close).start()
        app.save_json(mpath, app.load_json(mpath))
        assert fh.closed

        # logboek: CSV naast 00_Bronbestanden, bij een vergrendeld bestand blijft alles bewaard
        with open(app.logbook_path(lacie), newline='', encoding='utf-8-sig') as f:
            rows = list(csv.reader(f, delimiter=';'))
        acties = [r[1] for r in rows[1:]]
        assert rows[0] == app.LOG_COLS
        for a in ('al aanwezig, gecontroleerd', 'zelfde naam, andere inhoud', 'gekopieerd', 'NAS fout', 'NAS gekopieerd'):
            assert a in acties, (a, acties)
        real = app.logbook_path
        app.logbook_path = lambda root: t  # een map openen faalt, zoals een CSV die open staat in Excel
        app.logbook(lacie, 'tijdens vergrendeling')
        assert app.LOG_PENDING and app.STATE['log_error']
        app.logbook_path = real
        app.flush_logbook(lacie)
        assert not app.LOG_PENDING and app.read_logbook(lacie)[0][1] == 'tijdens vergrendeling'

    print('OK')


if __name__ == '__main__':
    main()
