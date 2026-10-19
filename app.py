"""Offload: SD-kaart -> LaCie -> NAS, elk bestand geverifieerd met SHA-256, met een lokaal dashboard."""
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
import sys
import threading
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / 'config.json').read_text(encoding='utf-8'))
EXTS = {e.lower() for e in CFG['extensions']}
URL = f"http://127.0.0.1:{CFG['port']}"
MANIFEST = '.offload.json'
CHUNK = 8 * 1024 * 1024
SKIP_DIRS = {'System Volume Information', '$RECYCLE.BIN'}

logging.basicConfig(filename=HERE / 'offload.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')
log = logging.getLogger('offload')


def now():
    return datetime.datetime.now().isoformat(timespec='seconds')


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
        os.replace(tmp, dst)
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


# ---------- manifests (.offload.json per shootmap) ----------

MLOCK = threading.Lock()


def load_json(p):
    return json.loads(p.read_text(encoding='utf-8'))


def save_json(p, data):
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, p)


def update_manifest(mpath, fn):
    with MLOCK:
        m = load_json(mpath)
        fn(m)
        save_json(mpath, m)


def read_manifests(lacie_root):
    out = []
    for p in sorted(lacie_root.glob(f'*/*/{MANIFEST}')):
        try:
            out.append((p, load_json(p)))
        except (OSError, ValueError):
            log.exception('manifest onleesbaar: %s', p)
    return out


def key(src_rel, size):
    return Path(src_rel).name.lower(), size


def index(ms):
    """{(naam, grootte): [op LaCie, op LaCie én NAS]} over alle imports."""
    # ponytail: herkenning op naam+grootte zoals het oude script; botsing vraagt exact dezelfde naam én bytes
    idx = {}
    for m in ms:
        for f in m['files']:
            v = idx.setdefault(key(f['src'], f['size']), [False, False])
            v[0] |= f['lacie_ok']
            v[1] |= f['lacie_ok'] and f['nas_ok']
    return idx


def import_card(card_root, card_label, files, lacie_root, client, shoot_name, job):
    shoot = lacie_root / client / shoot_name
    mpath = shoot / MANIFEST
    shoot.mkdir(parents=True, exist_ok=True)
    with MLOCK:
        if not mpath.exists():
            save_json(mpath, {'client': client, 'shoot': shoot_name, 'created': now(), 'cards': [], 'files': []})
    update_manifest(mpath, lambda m: m['cards'].append(card_label) if card_label not in m['cards'] else None)

    def progress(n):
        job['work_done'] += n

    for rel, size, _ in files:
        job['current'] = rel
        base = job['work_done']
        src = card_root / rel
        entry = {'src': rel, 'rel': rel, 'size': size, 'sha256': '', 'lacie_ok': False, 'nas_ok': False, 'error': ''}
        try:
            dst, h = free_dest(shoot / rel, src)
            if h is None:
                h = copy_verified(src, dst, progress=progress)
            entry.update(rel=dst.relative_to(shoot).as_posix(), sha256=h, lacie_ok=True)
        except OSError as e:
            entry['error'] = str(e)
            log.warning('import %s: %s', rel, e)

        def add(m):
            # een eerdere mislukte poging van hetzelfde kaartbestand vervangen
            m['files'] = [f for f in m['files'] if f['lacie_ok'] or f['src'] != rel]
            m['files'].append(entry)
        update_manifest(mpath, add)
        job['work_done'] = base + 2 * size
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
                return
            status['current'] = f['rel']
            dst = target / f['rel']
            fields = {'nas_ok': True, 'nas_error': ''}
            try:
                if not dst.exists():
                    copy_verified(shoot / f['rel'], dst, expected=f['sha256'])
                elif hash_file(dst) != f['sha256']:
                    fields = {'nas_conflict': True, 'nas_error': 'staat al op de NAS met andere inhoud, niet overschreven'}
            except OSError as e:
                fields = {'nas_error': str(e)}
                log.warning('nas %s: %s', dst, e)

            def setf(m, rel=f['rel'], fields=fields):
                for x in m['files']:
                    if x['rel'] == rel:
                        x.update(fields)
            update_manifest(mpath, setf)
    status['current'] = ''


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

STATE = {'lacie': None, 'cards': {}, 'nas': {'reachable': None, 'checked': None, 'current': ''}}
JOB = {'running': False}
JOB_LOCK = threading.Lock()
NAS_KICK = threading.Event()


def detect_loop():
    first = True
    while True:
        try:
            STATE['lacie'] = find_lacie()
            cards, new = {}, False
            for d, (label, serial) in find_cards():
                old = STATE['cards'].get(d)
                if old and old['serial'] == serial:
                    cards[d] = old
                else:
                    cards[d] = {'label': label or 'SD-kaart', 'serial': serial, 'files': media_files(Path(d))}
                    new = True
                    log.info('kaart %s (%s): %d bestanden', d, label, len(cards[d]['files']))
            STATE['cards'] = cards
            if new or (first and '--open' in sys.argv):
                webbrowser.open(URL)
            first = False
        except Exception:
            log.exception('detectie')
        time.sleep(3)


def nas_loop():
    while True:
        try:
            nas = Path(CFG['nas_root'])
            reachable = Path(nas.anchor).is_dir()  # kan even hangen als de NAS weg is; daarom in deze thread
            STATE['nas'].update(reachable=reachable, checked=now())
            if reachable and STATE['lacie'] and not JOB['running']:
                nas_pass(STATE['lacie'], nas, STATE['nas'], stop=lambda: JOB['running'])
        except Exception:
            log.exception('nas')
        NAS_KICK.wait(60)
        NAS_KICK.clear()


def start_import(body):
    lacie = STATE['lacie']
    if not lacie:
        raise ValueError('LaCie niet gevonden.')
    drive = body.get('drive')
    card = STATE['cards'].get(drive)
    if not card:
        raise ValueError('Kaart niet (meer) gevonden.')
    client, shoot, date = clean_name(body.get('client', '')), clean_name(body.get('shoot', '')), body.get('date', '')
    if not client or not shoot:
        raise ValueError('Vul een klant en een shootnaam in.')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
        raise ValueError('Ongeldige datum.')
    shoot_name = f'{date}_{shoot}'
    with JOB_LOCK:
        if JOB['running']:
            raise ValueError('Er loopt al een import.')
        idx = index(m for _, m in read_manifests(lacie))
        todo = [f for f in card['files'] if not idx.get(key(f[0], f[1]), [False])[0]]
        if not todo:
            raise ValueError('Alles van deze kaart staat al op de LaCie.')
        JOB.clear()
        JOB.update(running=True, drive=drive, label=card['label'], dest=f'{client}\\{shoot_name}',
                   total_files=len(todo), done_files=0, work_total=2 * sum(f[1] for f in todo), work_done=0,
                   started=time.time(), current='', error='')

    def run():
        try:
            import_card(Path(drive), card['label'], todo, lacie, client, shoot_name, JOB)
        except Exception as e:
            JOB['error'] = str(e)
            log.exception('import')
        finally:
            JOB.update(running=False, finished=time.time(), current='')
            NAS_KICK.set()
    threading.Thread(target=run, daemon=True).start()


def card_summary(drive, card, idx):
    files = card['files']
    st = [idx.get(key(r, s), [False, False]) for r, s, _ in files]
    new = [f for f, x in zip(files, st) if not x[0]]
    first = min((f[2] for f in (new or files)), default=time.time())
    return {'drive': drive, 'label': card['label'], 'count': len(files), 'bytes': sum(f[1] for f in files),
            'new_count': len(new), 'new_bytes': sum(f[1] for f in new),
            'on_lacie': sum(x[0] for x in st), 'on_nas': sum(x[1] for x in st),
            'safe': bool(files) and all(x[1] for x in st),
            'date': datetime.date.fromtimestamp(first).isoformat()}


def import_summary(mpath, m, lacie_root):
    fs = m['files']
    problems = [{'file': f['rel'], 'error': f['error'] or f.get('nas_error')}
                for f in fs if f['error'] or f.get('nas_error')]
    return {'path': str(mpath.parent.relative_to(lacie_root)), 'created': m['created'], 'cards': m['cards'],
            'count': len(fs), 'bytes': sum(f['size'] for f in fs),
            'lacie_ok': sum(f['lacie_ok'] for f in fs), 'nas_ok': sum(f['nas_ok'] for f in fs),
            'lacie_errors': sum(bool(f['error']) for f in fs), 'nas_errors': sum(bool(f.get('nas_error')) for f in fs),
            'problems': problems[:50]}


def status():
    lr = STATE['lacie']
    ms = read_manifests(lr) if lr else []
    idx = index(m for _, m in ms)
    return {
        'lacie': str(lr) if lr else None,
        'nas': {**STATE['nas'], 'root': CFG['nas_root']},
        'clients': sorted(d.name for d in lr.iterdir() if d.is_dir() and not d.name.startswith('.')) if lr else [],
        'cards': [card_summary(d, c, idx) for d, c in sorted(STATE['cards'].items())],
        'job': JOB,
        'imports': sorted((import_summary(p, m, lr) for p, m in ms), key=lambda x: x['created'], reverse=True),
    }


# ---------- web ----------

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype='application/json'):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', f'{ctype}; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def local(self):  # weert DNS-rebinding van andere websites
        return self.headers.get('Host') in (f"127.0.0.1:{CFG['port']}", f"localhost:{CFG['port']}")

    def do_GET(self):
        if not self.local():
            return self.send(403, {'error': 'verboden'})
        if self.path == '/':
            return self.send(200, (HERE / 'index.html').read_bytes(), 'text/html')
        if self.path == '/api/status':
            return self.send(200, status())
        self.send(404, {'error': 'niet gevonden'})

    def do_POST(self):
        # application/json kan een andere website niet zonder CORS-preflight sturen, en die beantwoorden we niet
        if not self.local() or self.path != '/api/import' or self.headers.get('Content-Type') != 'application/json':
            return self.send(400, {'error': 'ongeldig verzoek'})
        try:
            start_import(json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0)))))
            self.send(200, {'ok': True})
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
