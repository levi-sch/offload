"""Offload: SD-kaart -> LaCie -> NAS, elk bestand geverifieerd met SHA-256, met een lokaal dashboard."""
import collections
import concurrent.futures
import csv
import ctypes
import datetime
import hashlib
import http.server
import json
import logging
import os
import re
import shutil
import string
import struct
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / 'config.json').read_text(encoding='utf-8'))
EXTS = {e.lower() for e in CFG['extensions']}
URL = f"http://127.0.0.1:{CFG['port']}"
MANIFEST = '.offload.json'
CHUNK = 8 * 1024 * 1024
SKIP_DIRS = {'System Volume Information', '$RECYCLE.BIN', 'THMBNL'}  # THMBNL: Sony-miniaturen, enkel voor het dashboard
LOG_COLS = ['tijd', 'actie', 'kaart', 'bestand', 'doel', 'grootte_bytes', 'sha256', 'melding']

logging.basicConfig(filename=HERE / 'offload.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')
log = logging.getLogger('offload')

STATE = {'lacie': None, 'lacie_index': None, 'cards': {}, 'log_error': '',
         'nas': {'reachable': None, 'checked': None, 'current': ''}}


def now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def replace_retry(src, dst):
    # Windows weigert vervangen zolang iemand het bestand open heeft (dashboard, virusscanner, indexer, NAS)
    for attempt in range(30):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(0.2)


# ---------- logboek (CSV op de LaCie, opent in Excel) ----------

LOG_PENDING = []
LOG_LOCK = threading.Lock()


def logbook_path(lacie_root):
    return lacie_root.parent / CFG['logbook']


def logbook(lacie_root, actie, kaart='', bestand='', doel='', grootte='', sha='', melding=''):
    with LOG_LOCK:
        LOG_PENDING.append([now(), actie, kaart, bestand, doel, grootte, sha, melding])
    flush_logbook(lacie_root)


def flush_logbook(lacie_root):
    """Schrijf wachtende regels weg. Lukt dat niet (bv. open in Excel), dan blijven ze bewaard voor later."""
    with LOG_LOCK:
        if not lacie_root or not LOG_PENDING:
            return
        p = logbook_path(lacie_root)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            new = not p.exists()
            with open(p, 'a', newline='', encoding='utf-8-sig' if new else 'utf-8') as f:
                w = csv.writer(f, delimiter=';')  # ; zodat Excel met Belgische instellingen kolommen toont
                if new:
                    w.writerow(LOG_COLS)
                w.writerows(LOG_PENDING)
            LOG_PENDING.clear()
            STATE['log_error'] = ''
        except OSError as e:
            STATE['log_error'] = f'Logboek kon niet bijgewerkt worden ({e.strerror}). Staat het open in Excel? ' \
                                 f'{len(LOG_PENDING)} regels worden later toegevoegd.'


def read_logbook(lacie_root, n=1000):
    rows = []
    p = logbook_path(lacie_root) if lacie_root else None
    if p and p.exists():
        try:
            with open(p, newline='', encoding='utf-8-sig') as f:
                rows = list(csv.reader(f, delimiter=';'))[1:]
        except OSError:
            pass
    with LOG_LOCK:
        rows += LOG_PENDING
    return rows[-n:][::-1]


# ---------- bestanden ----------

def hash_file(path, progress=None):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while b := f.read(CHUNK):
            h.update(b)
            if progress:
                progress(len(b))
    return h.hexdigest()


def copy_verified(src, dst, expected=None, progress=None):
    """Kopieer via een .part-bestand, hash onderweg, lees de kopie terug en vergelijk. Geeft de sha256."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + '.part')
    h = hashlib.sha256()
    try:
        with open(src, 'rb') as fi, open(tmp, 'wb') as fo:
            while b := fi.read(CHUNK):
                h.update(b)
                fo.write(b)
                if progress:
                    progress(len(b))
            fo.flush()
            os.fsync(fo.fileno())
        if expected and h.hexdigest() != expected:
            raise OSError('bron wijkt af van de hash in het manifest')
        # ponytail: terugleest kan uit de Windows-cache komen; de echte schijfcheck is de NAS-stap, die opnieuw hasht
        if hash_file(tmp, progress) != h.hexdigest():
            raise OSError('verificatie mislukt: kopie verschilt van bron')
        shutil.copystat(src, tmp)
        replace_retry(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return h.hexdigest()


def media_files(root):
    """[(relatief pad, grootte, mtime)] van alle foto/video/audio onder root."""
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for name in files:
            if Path(name).suffix.lower() in EXTS and not name.startswith('._'):
                p = Path(dirpath, name)
                try:
                    st = p.stat()
                except OSError:
                    continue
                out.append((p.relative_to(root).as_posix(), st.st_size, st.st_mtime))
    return sorted(out)


def free_dest(dst, src):
    """Eerste vrije doelnaam (naam_2, naam_3, ...). Staat er al een identiek bestand: (pad, hash)."""
    n = 1
    while True:
        cand = dst if n == 1 else dst.with_stem(f'{dst.stem}_{n}')
        if not cand.exists():
            return cand, None
        if cand.stat().st_size == src.stat().st_size and (h := hash_file(cand)) == hash_file(src):
            return cand, h
        n += 1


def clean_name(s):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', str(s)).strip(' .')


def clean_path(s, max_parts):
    """'02_Cleanpoint\\01_Eke' -> Path; geen '..', lege delen of te diepe paden."""
    parts = [clean_name(p) for p in re.split(r'[\\/]+', str(s)) if p.strip()]
    if not parts or not all(parts) or len(parts) > max_parts:
        raise ValueError(f'Ongeldige mapnaam: {s}')
    return Path(*parts)


SHOOT_RE = re.compile(r'^\d{2}-(\d{2}|xx)-(\d{2}|xx)_', re.I)  # shootmappen zoals 26-09-11_teambuilding


def client_dirs(lacie_root):
    """Klantmappen voor de keuzelijst: het bovenste niveau plus tussenniveaus zoals 02_Cleanpoint\\01_Eke."""
    out = []
    for d in sorted(lacie_root.iterdir()):
        if d.is_dir() and not d.name.startswith(('.', '$')):
            out.append(d.name)
            out += [f'{d.name}\\{s.name}' for s in sorted(d.iterdir())
                    if s.is_dir() and not SHOOT_RE.match(s.name) and not s.name.startswith('.')]
    return out


def thumbnail(card_root, rel):
    """Klein voorbeeldbeeld: de EXIF-miniatuur van een JPG, of de Sony-miniatuur van een clip."""
    p = card_root / rel
    if p.suffix.lower() in ('.mp4', '.mov', '.mxf'):
        t = p.parent.parent / 'THMBNL' / f'{p.stem}T01.JPG'
        return t.read_bytes() if t.exists() else None
    if p.suffix.lower() not in ('.jpg', '.jpeg'):
        return None
    with open(p, 'rb') as f:
        head = f.read(256 * 1024)
    return exif_thumbnail(head) or p.read_bytes()


def exif_thumbnail(head):
    """De miniatuur die de camera in de EXIF-data (IFD1) van een JPG zet; None als die er niet is."""
    if head[2:4] != b'\xff\xe1' or head[6:12] != b'Exif\0\0':
        return None
    base = 12
    order = '<' if head[base:base + 2] == b'II' else '>'
    try:
        u16 = lambda o: struct.unpack_from(order + 'H', head, base + o)[0]
        u32 = lambda o: struct.unpack_from(order + 'I', head, base + o)[0]
        ifd0 = u32(4)
        ifd1 = u32(ifd0 + 2 + 12 * u16(ifd0))
        if not ifd1:
            return None
        tags = {u16(e): u32(e + 8) for e in range(ifd1 + 2, ifd1 + 2 + 12 * u16(ifd1), 12)}
        off, length = tags[0x0201], tags[0x0202]
    except (struct.error, KeyError):
        return None
    data = head[base + off:base + off + length]
    return data if data[:2] == b'\xff\xd8' and len(data) == length else None


# ---------- manifests (.offload.json per shootmap) ----------

MLOCK = threading.Lock()


def load_json(p):
    return json.loads(p.read_text(encoding='utf-8'))


def save_json(p, data):
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    replace_retry(tmp, p)


def update_manifest(mpath, fn):
    with MLOCK:
        m = load_json(mpath)
        fn(m)
        save_json(mpath, m)


def ensure_manifest(mpath, client, shoot):
    with MLOCK:
        if not mpath.exists():
            save_json(mpath, {'client': client, 'shoot': shoot, 'created': now(), 'cards': [], 'files': []})


def read_manifests(lacie_root):
    # tot 3 niveaus diep: klant / tussenniveau / shoot (bv. 02_Cleanpoint\01_Eke\25-08-12_Bert)
    paths = [lacie_root / MANIFEST, *lacie_root.glob(f'*/{MANIFEST}'), *lacie_root.glob(f'*/*/{MANIFEST}'),
             *lacie_root.glob(f'*/*/*/{MANIFEST}')]
    out = []
    for p in sorted(p for p in paths if p.exists()):
        try:
            with MLOCK:  # niet lezen terwijl een andere thread hem vervangt
                out.append((p, load_json(p)))
        except (OSError, ValueError):
            log.exception('manifest onleesbaar: %s', p)
    return out


def manifest_dir(lacie_root, lacie_rel):
    """Map waar het manifest van een LaCie-bestand hoort en het pad daarbinnen.

    Dat is de diepste shootmap (JJ-MM-DD_naam) boven het bestand, zodat Camera/Drone/bewerkt
    erbinnen vallen; zonder shootmap de eerste twee niveaus.
    """
    parts = Path(lacie_rel).parts
    shoots = [i for i, p in enumerate(parts[:-1]) if SHOOT_RE.match(p)]
    n = shoots[-1] + 1 if shoots else min(2, len(parts) - 1)
    return lacie_root.joinpath(*parts[:n]), '/'.join(parts[n:])


def key(rel, size):
    return Path(rel).name.lower(), size


def registry(ms, lacie_root):
    """{(naam, grootte): [op LaCie, ook op NAS, map, pad]} van alles wat Offload al geverifieerd heeft.

    Het pad is bij voorkeur dat van een kopie die ook op de NAS staat (nodig om veilig van de kaart te wissen).
    """
    # ponytail: herkenning op naam+grootte zoals het oude script; botsing vraagt exact dezelfde naam én bytes
    reg = {}
    for p, m in ms:
        for f in m['files']:
            if f['lacie_ok']:
                v = reg.setdefault(key(f['src'], f['size']), [True, False, '', ''])
                path = (p.parent / f['rel']).relative_to(lacie_root)
                if not v[3] or (f['nas_ok'] and not v[1]):
                    v[2], v[3] = str(path.parent), path.as_posix()
                v[1] |= f['nas_ok']
    return reg


def build_lacie_index(lacie_root):
    """{(naam, grootte): [pad, ...]} van alle media op de LaCie, ook mappen die met de hand gekopieerd zijn."""
    idx = {}
    for rel, size, _ in media_files(lacie_root):
        idx.setdefault(key(rel, size), []).append(rel)
    return idx


def file_states(card, reg, lidx):
    """Per kaartbestand [pad, grootte, mtime, status, waar]; status = new | dup | lacie | safe | scan."""
    out = []
    for rel, size, mtime in card['files']:
        k = key(rel, size)
        r = reg.get(k)
        if r:
            st, where = ('safe' if r[1] else 'lacie'), r[2]
        elif lidx is None:
            st, where = 'scan', ''
        elif k in lidx and rel not in card['mismatch']:
            st, where = 'dup', str(Path(lidx[k][0]).parent)
        else:
            st, where = 'new', ''
        out.append([rel, size, mtime, st, where])
    return out


# ---------- taken ----------

def open_manifest(lacie_root, mdir, card_label):
    """Manifest van een shootmap, aangemaakt als het nog niet bestaat, met deze kaart erin vermeld."""
    parts = mdir.relative_to(lacie_root).parts
    mpath = mdir / MANIFEST
    ensure_manifest(mpath, '\\'.join(parts[:-1]), parts[-1] if parts else '')
    if card_label:
        update_manifest(mpath, lambda m: m['cards'].append(card_label) if card_label not in m['cards'] else None)
    return mpath


def unregister(lacie_root, lacie_rel):
    """Haal een bestand uit zijn manifest; geeft de verwijderde regel terug. Leeg manifest -> weg."""
    mdir, rel = manifest_dir(lacie_root, lacie_rel)
    mpath = mdir / MANIFEST
    if not mpath.exists():
        return None
    removed = []

    def drop(m):
        removed.extend(f for f in m['files'] if f['rel'] == rel)
        m['files'] = [f for f in m['files'] if f['rel'] != rel]
    update_manifest(mpath, drop)
    with MLOCK:
        if not load_json(mpath)['files']:
            mpath.unlink()
    return removed[0] if removed else None


def import_card(card_root, card_label, files, lacie_root, folder, job, lidx=None):
    """Kopieer plat naar <LaCie>/<folder>/<bestandsnaam>, zonder de mappen van de camera.

    folder is een nieuwe shootmap (<klant>/JJ-MM-DD_<shoot>[/submap]) of een bestaande map waar
    ontbrekende bestanden aan toegevoegd worden. Het manifest komt in de shootmap erboven.
    """
    target = lacie_root / folder
    shoot, _ = manifest_dir(lacie_root, (Path(folder) / '_').as_posix())
    target.mkdir(parents=True, exist_ok=True)
    mpath = open_manifest(lacie_root, shoot, card_label)

    def progress(n):
        job['work_done'] += n

    for rel, size, _ in files:
        job['current'] = rel
        base = job['work_done']
        src = card_root / rel
        entry = {'src': rel, 'rel': rel, 'size': size, 'sha256': '', 'lacie_ok': False, 'nas_ok': False, 'error': ''}
        try:
            dst, h = free_dest(target / src.name, src)
            if h is None:
                h = copy_verified(src, dst, progress=progress)
            entry.update(rel=dst.relative_to(shoot).as_posix(), sha256=h, lacie_ok=True)
            if lidx is not None:
                lidx.setdefault(key(rel, size), []).append(dst.relative_to(lacie_root).as_posix())
            logbook(lacie_root, 'gekopieerd', card_label, rel, str(dst.relative_to(lacie_root)), size, h)
        except OSError as e:
            entry['error'] = str(e)
            logbook(lacie_root, 'fout bij kopiëren', card_label, rel, str(folder), size, '', str(e))

        def add(m):
            # een eerdere mislukte poging van hetzelfde kaartbestand vervangen
            m['files'] = [f for f in m['files'] if f['lacie_ok'] or f['src'] != rel]
            m['files'].append(entry)
        update_manifest(mpath, add)
        job['work_done'] = base + 2 * size
        job['done_files'] += 1


def register(lacie_root, lacie_rel, src_rel, size, sha, card_label):
    """Een bestand dat al op de LaCie stond (en dezelfde hash heeft) opnemen, zodat het ook naar de NAS gaat."""
    mdir, rel = manifest_dir(lacie_root, lacie_rel)
    mpath = open_manifest(lacie_root, mdir, card_label)

    def add(m):
        if not any(f['rel'] == rel and f['lacie_ok'] for f in m['files']):
            m['files'].append({'src': src_rel, 'rel': rel, 'size': size, 'sha256': sha, 'lacie_ok': True,
                               'nas_ok': False, 'error': '', 'adopted': True})
    update_manifest(mpath, add)


def adopt_files(card_root, card_label, files, lacie_root, lidx, job, mismatch):
    """Kaartbestanden die al op de LaCie staan: hash vergelijken in plaats van opnieuw kopiëren.

    De kaartlezer is de bottleneck (gemeten ~19 MB/s tegen ~110 MB/s voor de LaCie). Daarom leest een
    tweede thread intussen alle LaCie-kandidaten, één voor één zodat de harde schijf niet moet zoeken.
    Zo duurt de controle even lang als het lezen van de kaart alleen. De voortgang telt de kaart.
    """
    def progress(n):
        job['work_done'] += n

    def lacie_hash(c):
        try:
            return hash_file(lacie_root / c)
        except OSError as e:
            return e

    lacie_pool = concurrent.futures.ThreadPoolExecutor(1)
    lacie = {c: lacie_pool.submit(lacie_hash, c)
             for rel, size, _ in files for c in lidx.get(key(rel, size), [])}
    try:
        for rel, size, _ in files:
            check_one(card_root, card_label, rel, size, lacie_root, lidx, lacie, mismatch, job, progress)
    finally:
        lacie_pool.shutdown(cancel_futures=True)


def check_one(card_root, card_label, rel, size, lacie_root, lidx, lacie, mismatch, job, progress):
    job['current'] = rel
    base = job['work_done']
    try:
        h = hash_file(card_root / rel, progress)
        cands = lidx.get(key(rel, size), [])
        results = {c: lacie[c].result() for c in cands}
        match = next((c for c, r in results.items() if r == h), None)
        errors = [r for r in results.values() if isinstance(r, OSError)]
        if match:
            register(lacie_root, match, rel, size, h, card_label)
            logbook(lacie_root, 'al aanwezig, gecontroleerd', card_label, rel, str(Path(match)), size, h)
        elif errors:  # LaCie-bestand onleesbaar: niet als "andere inhoud" behandelen
            raise errors[0]
        else:
            mismatch.add(rel)
            logbook(lacie_root, 'zelfde naam, andere inhoud', card_label, rel, ', '.join(cands), size, h,
                    'wordt als nieuw bestand behandeld')
    except OSError as e:
        logbook(lacie_root, 'fout bij controle', card_label, rel, '', size, '', str(e))
    job['work_done'] = base + size
    job['done_files'] += 1


def nas_pass(lacie_root, nas_root, status, stop=lambda: False):
    """Kopieer alles wat op de LaCie geverifieerd is maar nog niet op de NAS staat."""
    for mpath, m in read_manifests(lacie_root):
        shoot = mpath.parent
        target = nas_root / shoot.relative_to(lacie_root)
        for f in m['files']:
            if not f['lacie_ok'] or f['nas_ok'] or f.get('nas_conflict'):
                continue
            if stop():
                status['current'] = ''
                return
            status['current'] = f['rel']
            dst = target / f['rel']
            name = str((shoot / f['rel']).relative_to(lacie_root))
            fields = {'nas_ok': True, 'nas_error': ''}
            try:
                if not dst.exists():
                    copy_verified(shoot / f['rel'], dst, expected=f['sha256'])
                    logbook(lacie_root, 'NAS gekopieerd', '', name, str(dst), f['size'], f['sha256'])
                elif hash_file(dst) == f['sha256']:
                    logbook(lacie_root, 'NAS al aanwezig, gecontroleerd', '', name, str(dst), f['size'], f['sha256'])
                else:
                    fields = {'nas_conflict': True, 'nas_error': 'staat al op de NAS met andere inhoud, niet overschreven'}
                    logbook(lacie_root, 'NAS conflict', '', name, str(dst), f['size'], f['sha256'], fields['nas_error'])
            except OSError as e:
                fields = {'nas_error': str(e)}
                logbook(lacie_root, 'NAS fout', '', name, str(dst), f['size'], f['sha256'], str(e))

            def setf(m, rel=f['rel'], fields=fields):
                for x in m['files']:
                    if x['rel'] == rel:
                        x.update(fields)
            update_manifest(mpath, setf)
    status['current'] = ''


# ---------- veilig verwijderen ----------

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [('hwnd', ctypes.c_void_p), ('wFunc', ctypes.c_uint), ('pFrom', ctypes.c_void_p),
                ('pTo', ctypes.c_void_p), ('fFlags', ctypes.c_ushort), ('fAnyOperationsAborted', ctypes.c_int),
                ('hNameMappings', ctypes.c_void_p), ('lpszProgressTitle', ctypes.c_void_p)]


def recycle(path):
    """Naar de Windows-Prullenbak (FOF_ALLOWUNDO). Past het er niet in, dan vraagt Windows het eerst
    (FOF_WANTNUKEWARNING) in plaats van stil definitief te wissen."""
    s = str(path) + '\0\0'
    buf = (ctypes.c_wchar * len(s))(*s)
    op = SHFILEOPSTRUCTW(None, 3, ctypes.cast(buf, ctypes.c_void_p), None, 0x40 | 0x10 | 0x4 | 0x400 | 0x4000)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc or op.fAnyOperationsAborted or Path(path).exists():
        raise OSError(f'Prullenbak weigerde ({rc:#x})')


def wipe_card(card_root, card, files, lacie_root, nas_root, reg, job):
    """Wis kaartbestanden die geverifieerd op LaCie én NAS staan. Een kaart heeft geen Prullenbak,
    dus vlak ervoor nog eens nakijken dat beide kopieën bestaan met de juiste grootte."""
    wiped = set()
    for rel, size, _ in files:
        job['current'] = rel
        r = reg.get(key(rel, size))
        try:
            if not (r and r[1]):
                raise OSError('staat niet geverifieerd op LaCie én NAS')
            copies = (lacie_root / r[3], nas_root / r[3])
            for c in copies:
                if c.stat().st_size != size:
                    raise OSError(f'kopie {c} heeft een andere grootte')
            if (card_root / rel).stat().st_size != size:
                raise OSError('kaartbestand is veranderd')
            (card_root / rel).unlink()
            wiped.add(rel)
            logbook(lacie_root, 'gewist van kaart', card['label'], rel, str(copies[0]), size, '', f'NAS: {copies[1]}')
        except OSError as e:
            logbook(lacie_root, 'niet gewist van kaart', card['label'], rel, '', size, '', str(e))
        job['work_done'] += size
        job['done_files'] += 1
    card['files'] = [f for f in card['files'] if f[0] not in wiped]
    card['relset'] -= wiped
    return wiped


def folder_of(rel):
    return str(Path(rel).parent)


def scan_dups(lacie_root, lidx, job):
    """Bestanden met dezelfde naam en grootte in verschillende mappen: hash vergelijken (alleen LaCie)."""
    found = []
    for paths in [p for p in lidx.values() if len({folder_of(x) for x in p}) > 1]:
        by_hash = {}
        for p in paths:
            job['current'] = p
            try:
                st = (lacie_root / p).stat()
                by_hash.setdefault(hash_file(lacie_root / p, lambda n: job.__setitem__('work_done', job['work_done'] + n)),
                                   []).append([p, st.st_mtime])
            except OSError as e:
                logbook(lacie_root, 'fout bij dubbels zoeken', '', p, '', '', '', str(e))
            job['done_files'] += 1
        for h, items in by_hash.items():
            if len({folder_of(p) for p, _ in items}) > 1:
                found.append({'sha256': h, 'size': (lacie_root / items[0][0]).stat().st_size, 'files': items})
    return found


def dup_folders(g):
    return tuple(sorted({folder_of(p) for p, _ in g['files']}))


def dedupe(lacie_root, nas_root, groups, remove, job, lidx):
    """Verwijder de kopieën in map `remove` naar de Prullenbak; elders blijft telkens een identieke kopie."""
    for g in groups:
        keep = [f for f in g['files'] if folder_of(f[0]) != remove]
        for p, mtime in [f for f in g['files'] if folder_of(f[0]) == remove]:
            job['current'] = p
            try:
                kp, kmtime = keep[0]
                for path, mt in ((kp, kmtime), (p, mtime)):  # niets veranderd sinds het zoeken?
                    st = (lacie_root / path).stat()
                    if st.st_size != g['size'] or st.st_mtime != mt:
                        raise OSError(f'{path} is veranderd sinds het zoeken naar dubbels')
                recycle(lacie_root / p)
                g['files'] = [f for f in g['files'] if f[0] != p]
                k = key(p, g['size'])
                if lidx is not None and p in lidx.get(k, []):
                    lidx[k].remove(p)
                logbook(lacie_root, 'dubbel naar Prullenbak', '', p, '', g['size'], g['sha256'], f'bewaard: {kp}')
                entry = unregister(lacie_root, p)
                if entry:  # de bewaarde kopie neemt de plaats in, zodat die ook naar de NAS gaat
                    register(lacie_root, kp, entry['src'], g['size'], g['sha256'], '')
                    nas_copy = nas_root / p
                    if entry.get('nas_ok') and nas_copy.exists():
                        nas_copy.unlink()  # de NAS (#recycle) bewaart het nog
                        logbook(lacie_root, 'NAS-kopie naar #recycle', '', str(nas_copy), '', g['size'], g['sha256'],
                                f'bewaard: {kp}')
                    elif entry.get('nas_ok'):
                        logbook(lacie_root, 'NAS-kopie niet verwijderd', '', str(nas_copy), '', g['size'], g['sha256'],
                                'NAS niet bereikbaar of bestand al weg; ruim het later zelf op')
            except OSError as e:
                logbook(lacie_root, 'dubbel niet verwijderd', '', p, '', g['size'], g['sha256'], str(e))
            job['work_done'] += g['size']
            job['done_files'] += 1


# ---------- schijven (Windows) ----------

k32 = ctypes.windll.kernel32
DRIVE_REMOVABLE = 2


def drives():
    mask = k32.GetLogicalDrives()
    return [f'{c}:\\' for i, c in enumerate(string.ascii_uppercase) if mask >> i & 1]


def volume(root):
    name, serial = ctypes.create_unicode_buffer(261), ctypes.c_ulong()
    if not k32.GetVolumeInformationW(root, name, 261, ctypes.byref(serial), None, None, None, 0):
        return None
    return name.value, serial.value


def find_lacie():
    for d in drives():
        v = volume(d)
        if v and v[0].lower() == CFG['lacie_label'].lower() and (p := Path(d, CFG['lacie_subdir'])).is_dir():
            return p
    return None


def find_cards():
    for d in drives():
        if k32.GetDriveTypeW(d) == DRIVE_REMOVABLE and (v := volume(d)) \
                and any(Path(d, x).is_dir() for x in ('DCIM', 'PRIVATE')):
            yield d, v


# ---------- achtergrond ----------

JOB = {'running': False}
JOB_LOCK = threading.Lock()
NAS_KICK = threading.Event()


def detect_loop():
    first = True
    while True:
        try:
            lacie = find_lacie()
            if lacie != STATE['lacie']:
                STATE['lacie'], STATE['lacie_index'] = lacie, None
            cards, new = {}, []
            for d, (label, serial) in find_cards():
                old = STATE['cards'].get(d)
                if old and old['serial'] == serial:
                    cards[d] = old
                else:
                    files = media_files(Path(d))
                    cards[d] = {'label': label or 'SD-kaart', 'serial': serial, 'files': files,
                                'relset': {f[0] for f in files}, 'mismatch': set()}
                    new.append(d)
            STATE['cards'] = cards
            if new or (first and '--open' in sys.argv):
                webbrowser.open(URL)
            first = False
            if lacie:
                for d in new:
                    c = cards[d]
                    logbook(lacie, 'kaart ingestoken', c['label'], d, '', sum(f[1] for f in c['files']), '',
                            f"{len(c['files'])} bestanden")
                # opnieuw doorzoeken bij een nieuwe kaart, en elke 5 min voor wat je intussen met de hand verplaatst
                stale = time.time() - STATE.get('index_time', 0) > 300 and not JOB['running']
                if cards and (new or STATE['lacie_index'] is None or stale):
                    if new:
                        STATE['lacie_index'] = None
                    STATE['lacie_index'] = build_lacie_index(lacie)
                    STATE['index_time'] = time.time()
        except Exception:
            log.exception('detectie')
        time.sleep(3)


def nas_loop():
    while True:
        try:
            flush_logbook(STATE['lacie'])
            nas = Path(CFG['nas_root'])
            reachable = Path(nas.anchor).is_dir()  # kan even hangen als de NAS weg is; daarom in deze thread
            STATE['nas'].update(reachable=reachable, checked=now())
            if reachable and STATE['lacie'] and not JOB['running']:
                nas_pass(STATE['lacie'], nas, STATE['nas'], stop=lambda: JOB['running'])
        except Exception:
            log.exception('nas')
        NAS_KICK.wait(60)
        NAS_KICK.clear()


def start_job(kind, dest, todo, fn, passes=2):
    """passes: hoe vaak elke byte van de kaart meetelt in de voortgang (kopiëren + terugleest = 2)."""
    with JOB_LOCK:
        if JOB['running']:
            raise ValueError('Er loopt al een taak.')
        JOB.clear()
        JOB.update(running=True, kind=kind, dest=dest, total_files=len(todo), done_files=0,
                   work_total=passes * sum(f[1] for f in todo), work_done=0, started=time.time(), current='', error='')

    def run():
        try:
            fn()
        except Exception as e:
            JOB['error'] = str(e)
            log.exception(kind)
        finally:
            JOB.update(running=False, finished=time.time(), current='')
            NAS_KICK.set()
    threading.Thread(target=run, daemon=True).start()


def card_context(body):
    lacie, lidx = STATE['lacie'], STATE['lacie_index']
    if not lacie:
        raise ValueError('LaCie niet gevonden.')
    drive = body.get('drive')
    card = STATE['cards'].get(drive)
    if not card:
        raise ValueError('Kaart niet (meer) gevonden.')
    if lidx is None:
        raise ValueError('De LaCie wordt nog doorzocht op dubbels, even geduld.')
    return lacie, lidx, drive, card, file_states(card, registry(read_manifests(lacie), lacie), lidx)


def start_import(body):
    lacie, lidx, drive, card, states = card_context(body)
    wanted = set(body.get('files') or [])
    todo = [tuple(f[:3]) for f in states if f[0] in wanted and f[3] == 'new']
    if not todo:
        raise ValueError('Geen nieuwe bestanden geselecteerd.')
    if body.get('folder'):  # ontbrekende bestanden toevoegen aan een map die al bestaat
        folder = clean_path(body['folder'], 5)
        if not (lacie / folder).is_dir():
            raise ValueError(f'Map bestaat niet (meer): {folder}')
    else:
        shoot, date = clean_name(body.get('shoot', '')), body.get('date', '')
        if not body.get('client') or not shoot:
            raise ValueError('Vul een klant en een shootnaam in.')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
            raise ValueError('Ongeldige datum.')
        subdir = clean_path(body['subdir'], 1) if str(body.get('subdir') or '').strip() else Path()
        folder = clean_path(body['client'], 2) / f'{date[2:]}_{shoot}' / subdir  # 26-09-11_teambuilding
    start_job('import', str(folder), todo,
              lambda: import_card(Path(drive), card['label'], todo, lacie, folder, JOB, lidx))


def start_adopt(body):
    lacie, lidx, drive, card, states = card_context(body)
    todo = [tuple(f[:3]) for f in states if f[3] == 'dup']
    if not todo:
        raise ValueError('Er zijn geen bestaande bestanden om te controleren.')
    start_job('adopt', 'bestaande bestanden', todo,
              lambda: adopt_files(Path(drive), card['label'], todo, lacie, lidx, JOB, card['mismatch']), passes=1)


def start_wipe(body):
    lacie, lidx, drive, card, states = card_context(body)
    wanted = set(body.get('files') or [])
    todo = [tuple(f[:3]) for f in states if f[0] in wanted and f[3] == 'safe']
    if not todo:
        raise ValueError('Geen bestanden die geverifieerd op LaCie én NAS staan.')
    reg = registry(read_manifests(lacie), lacie)
    start_job('wipe', f'kaart {drive}', todo,
              lambda: wipe_card(Path(drive), card, todo, lacie, Path(CFG['nas_root']), reg, JOB), passes=1)


def start_dupscan(body):
    lacie, lidx = STATE['lacie'], STATE['lacie_index']
    if not lacie or lidx is None:
        raise ValueError('De LaCie is niet aangesloten of wordt nog doorzocht.')
    todo = [(p, size, 0) for (_, size), paths in lidx.items() if len({folder_of(x) for x in paths}) > 1 for p in paths]

    def run():
        STATE['dups'] = scan_dups(lacie, lidx, JOB)
        STATE['dups_time'] = now()
        logbook(lacie, 'dubbels gezocht', '', '', '', '', '', f"{len(STATE['dups'])} identieke bestanden in meerdere mappen")
    start_job('dupscan', 'LaCie', todo, run, passes=1)


def start_dedupe(body):
    lacie = STATE['lacie']
    folders, remove = tuple(body.get('folders') or ()), body.get('remove')
    groups = [g for g in STATE.get('dups') or [] if dup_folders(g) == folders]
    if not lacie or not groups or remove not in folders:
        raise ValueError('Deze dubbels zijn niet (meer) gevonden. Zoek opnieuw naar dubbels.')
    todo = [(p, g['size'], 0) for g in groups for p, _ in g['files'] if folder_of(p) == remove]

    def run():
        dedupe(lacie, Path(CFG['nas_root']), groups, remove, JOB, STATE['lacie_index'])
        STATE['dups'] = [g for g in STATE['dups'] if len(dup_folders(g)) > 1]
    start_job('dedupe', remove, todo, run, passes=1)


PICK_LOCK = threading.Lock()


def lacie_relative(lacie_root, chosen):
    """Gekozen map -> pad binnen 00_Bronbestanden; een map erbuiten wordt geweigerd."""
    p, root = Path(chosen).resolve(), lacie_root.resolve()
    if p == root or not p.is_relative_to(root):
        raise ValueError(f'Kies een map binnen {lacie_root}, niet {p}.')
    return str(p.relative_to(root))


def pick_folder(body):
    """Het gewone Windows-venster 'Map kiezen' (zoals bij Opslaan als), met de knop Nieuwe map."""
    lacie = STATE['lacie']
    if not lacie:
        raise ValueError('LaCie niet gevonden.')
    start = lacie
    try:
        if body.get('start') and (lacie / clean_path(body['start'], 5)).is_dir():
            start = lacie / clean_path(body['start'], 5)
    except ValueError:
        pass
    if not PICK_LOCK.acquire(blocking=False):
        raise ValueError('Er staat al een venster "Map kiezen" open.')
    try:
        import tkinter.filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes('-topmost', True)  # boven de browser, ook al draait Offload op de achtergrond
        chosen = tkinter.filedialog.askdirectory(parent=root, initialdir=str(start),
                                                 title='Kies de map voor deze bestanden (op de LaCie)')
        root.destroy()
    finally:
        PICK_LOCK.release()
    return {'folder': lacie_relative(lacie, chosen) if chosen else ''}


def dup_summary():
    pairs = {}
    for g in STATE.get('dups') or []:
        v = pairs.setdefault(dup_folders(g), {'folders': list(dup_folders(g)), 'count': 0, 'bytes': 0, 'names': []})
        v['count'] += 1
        v['bytes'] += g['size']
        if len(v['names']) < 40:
            v['names'].append(Path(g['files'][0][0]).name)
    return sorted(pairs.values(), key=lambda v: -v['bytes'])


def card_summary(drive, card, reg, lidx):
    st = file_states(card, reg, lidx)
    return {'drive': drive, 'label': card['label'], 'serial': card['serial'], 'files': st,
            'counts': dict(collections.Counter(f[3] for f in st)),
            'safe': bool(st) and all(f[3] == 'safe' for f in st)}


def import_summary(mpath, m, lacie_root):
    fs = m['files']
    problems = [{'file': f['rel'], 'error': f['error'] or f.get('nas_error')}
                for f in fs if f['error'] or f.get('nas_error')]
    return {'path': str(mpath.parent.relative_to(lacie_root)), 'created': m['created'], 'cards': m['cards'],
            'count': len(fs), 'bytes': sum(f['size'] for f in fs), 'adopted': sum(bool(f.get('adopted')) for f in fs),
            'lacie_ok': sum(f['lacie_ok'] for f in fs), 'nas_ok': sum(f['nas_ok'] for f in fs),
            'lacie_errors': sum(bool(f['error']) for f in fs), 'nas_errors': sum(bool(f.get('nas_error')) for f in fs),
            'problems': problems[:50]}


def status():
    lr = STATE['lacie']
    ms = read_manifests(lr) if lr else []
    reg = registry(ms, lr) if lr else {}
    return {
        'lacie': str(lr) if lr else None,
        'nas': {**STATE['nas'], 'root': CFG['nas_root']},
        'log_error': STATE['log_error'],
        'gap_minutes': CFG['session_gap_minutes'],
        'clients': client_dirs(lr) if lr else [],
        'cards': [card_summary(d, c, reg, STATE['lacie_index']) for d, c in sorted(STATE['cards'].items())],
        'job': JOB,
        'imports': sorted((import_summary(p, m, lr) for p, m in ms), key=lambda x: x['created'], reverse=True),
        'dups': dup_summary(), 'dups_time': STATE.get('dups_time'),
    }


# ---------- web ----------

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype='application/json', cache='no-store'):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', f'{ctype}; charset=utf-8' if not ctype.startswith('image/') else ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', cache)
        self.end_headers()
        self.wfile.write(data)

    def local(self):  # weert DNS-rebinding van andere websites
        return self.headers.get('Host') in (f"127.0.0.1:{CFG['port']}", f"localhost:{CFG['port']}")

    def do_GET(self):
        if not self.local():
            return self.send(403, {'error': 'verboden'})
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        if url.path == '/':
            return self.send(200, (HERE / 'index.html').read_bytes(), 'text/html')
        if url.path == '/api/status':
            return self.send(200, status())
        if url.path == '/api/log':
            lr = STATE['lacie']
            return self.send(200, {'cols': LOG_COLS, 'rows': read_logbook(lr),
                                   'path': str(logbook_path(lr)) if lr else ''})
        if url.path == '/api/thumb':
            card = STATE['cards'].get(q.get('drive'))
            if card and q.get('rel') in card['relset']:  # alleen bestanden van de kaart, geen willekeurige paden
                try:
                    data = thumbnail(Path(q['drive']), q['rel'])
                except OSError:
                    data = None
                if data:
                    return self.send(200, data, 'image/jpeg', 'max-age=3600')
        self.send(404, {'error': 'niet gevonden'})

    def do_POST(self):
        # application/json kan een andere website niet zonder CORS-preflight sturen, en die beantwoorden we niet
        actions = {'/api/import': start_import, '/api/adopt': start_adopt, '/api/wipe': start_wipe,
                   '/api/dupscan': start_dupscan, '/api/dedupe': start_dedupe, '/api/pickfolder': pick_folder}
        if not self.local() or self.path not in actions or self.headers.get('Content-Type') != 'application/json':
            return self.send(400, {'error': 'ongeldig verzoek'})
        try:
            result = actions[self.path](json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0)))))
            self.send(200, result or {'ok': True})
        except ValueError as e:
            self.send(400, {'error': str(e)})


class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = False  # op Windows zou reuse een tweede instantie op dezelfde poort toelaten


def main():
    k32.SetErrorMode(0x8001)  # geen "plaats een schijf"-popups voor lege kaartlezers
    try:
        server = Server(('127.0.0.1', CFG['port']), Handler)
    except OSError:
        webbrowser.open(URL)  # draait al: alleen het dashboard openen
        return
    log.info('gestart op %s', URL)
    for fn in (detect_loop, nas_loop):
        threading.Thread(target=fn, daemon=True).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
