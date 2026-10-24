"""HH - ponte tra i programmi di log (Decodium, QARTest, N1MM...) e HamHub Log.

Decodium (protocollo WSJT-X: "Logged ADIF" e "QSO Logged"), QARTest e gli altri programmi di log (XML N1MM, ADIF) inviano i QSO via UDP. HH li riceve in locale e li
invia a hamhub.cloud con la chiave di invio dell'utente. Senza rete i QSO restano in coda (HH_queue.adi) e vengono
rispediti. HH vive nell'area di notifica (vicino all'orologio): doppio clic per aprire il log, clic destro per il menu.

Funziona su Windows (icona nativa), Linux e macOS (icona con pystray + Pillow, se installati; altrimenti in background con notifiche del sistema).

Uso:
  HH.exe              avvia HH nell'area di notifica (una sola istanza)   [Linux/macOS: python3 HH.py]
  HH.exe --setup      finestra di configurazione (chiave di invio, porta)
  HH.exe --configure CHIAVE [PORTA]   salva la configurazione senza finestre (server e terminali senza schermo)
  HH.exe --console    solo ricevitore, in una finestra di testo (per le prove)
  HH.exe --version    stampa la versione
"""
import ctypes
import datetime
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from collections import deque

VERSION = '1.2.0'
FROZEN = bool(getattr(sys, 'frozen', False))
PROGRAM_DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
RES_DIR = getattr(sys, '_MEIPASS', PROGRAM_DIR)  # risorse (icona) dentro il pacchetto
IS_WIN = os.name == 'nt'
IS_MAC = sys.platform == 'darwin'


def data_dir():
    """Configurazione, coda e registro: %APPDATA%\\HamHub\\HH (Windows), ~/Library/Application Support/HamHub/HH (macOS),
    ~/.config/HamHub/HH (Linux). La cartella del programma puo' essere protetta, per questo non si usa."""
    if os.environ.get('HH_DATA_DIR'):
        return os.environ['HH_DATA_DIR']
    if IS_WIN:
        return os.path.join(os.environ.get('APPDATA') or PROGRAM_DIR, 'HamHub', 'HH')
    if IS_MAC:
        return os.path.join(os.path.expanduser('~/Library/Application Support'), 'HamHub', 'HH')
    return os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'HamHub', 'HH')


HERE = data_dir()
os.makedirs(HERE, exist_ok=True)
CFG = os.path.join(HERE, 'HH.ini')
QUEUE = os.path.join(HERE, 'HH_queue.adi')
LOG = os.path.join(HERE, 'HH.log')
DEFAULT_URL = 'https://hamhub.cloud/log-api/adif'
LOG_PAGE = 'https://hamhub.cloud/log/#qso'
DEFAULT_PORT = 12060
MUTEX_NAME = 'HamHubHH_SingleInstance'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_VALUE = 'HamHubHH'
WSJT_MAGIC = 0xADBCCBDA
MSG_HEARTBEAT, MSG_STATUS, MSG_QSO_LOGGED, MSG_LOGGED_ADIF = 0, 1, 5, 12
lock = threading.Lock()

BANDS = ((1.8, 2.0, '160m'), (3.5, 4.0, '80m'), (5.25, 5.45, '60m'), (7.0, 7.3, '40m'), (10.1, 10.15, '30m'), (14.0, 14.35, '20m'),
         (18.068, 18.168, '17m'), (21.0, 21.45, '15m'), (24.89, 24.99, '12m'), (28.0, 29.7, '10m'), (50.0, 54.0, '6m'), (144.0, 148.0, '2m'))


# ---------------------------------------------------------------- registro e configurazione
def log(msg):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + msg
    try:
        if sys.stdout:
            print(line, flush=True)
    except (OSError, ValueError):
        pass
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def read_cfg():
    cfg = {'token': '', 'port': str(DEFAULT_PORT), 'url': DEFAULT_URL, 'notify': '1'}
    if os.path.exists(CFG):
        with open(CFG, encoding='utf-8') as f:
            for raw in f:
                if '=' in raw and not raw.strip().startswith('#'):
                    k, v = raw.split('=', 1)
                    cfg[k.strip().lower()] = v.strip()
    return cfg


def write_cfg(cfg):
    tmp = CFG + '.new'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('# HH - configurazione\n')
        for k in ('token', 'port', 'url', 'notify'):
            f.write(f'{k}={cfg.get(k, "")}\n')
    if not IS_WIN:
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
    os.replace(tmp, CFG)


def valid_port(text):
    return text.isdigit() and 1024 <= int(text) <= 65535


# ---------------------------------------------------------------- lettura dei pacchetti
def _utf8(data, pos):
    n = struct.unpack('>I', data[pos:pos + 4])[0]
    pos += 4
    if n == 0xFFFFFFFF:
        return '', pos
    return data[pos:pos + n].decode('utf-8', 'replace'), pos + n


def _qdatetime(data, pos):
    """QDateTime di Qt: giorno giuliano, millisecondi dalla mezzanotte, tipo di fuso (e scarto se 2)."""
    jd, ms, spec = struct.unpack('>QIB', data[pos:pos + 13])
    pos += 13
    if spec == 2:
        pos += 4
    day = datetime.date.fromordinal(jd - 1721425)
    return datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(milliseconds=ms), pos


def band_of(mhz):
    for lo, hi, name in BANDS:
        if lo <= mhz <= hi:
            return name
    return ''


def _tag(name, value):
    value = str(value or '')
    return f'<{name}:{len(value.encode("utf-8"))}>{value}' if value else ''


def qso_logged_to_adif(data, pos):
    """Corpo del messaggio "QSO Logged" (tipo 5) -> un record ADIF."""
    off, pos = _qdatetime(data, pos)
    call, pos = _utf8(data, pos)
    grid, pos = _utf8(data, pos)
    freq = struct.unpack('>Q', data[pos:pos + 8])[0]
    pos += 8
    mode, pos = _utf8(data, pos)
    rst_s, pos = _utf8(data, pos)
    rst_r, pos = _utf8(data, pos)
    power, pos = _utf8(data, pos)
    comments, pos = _utf8(data, pos)
    name, pos = _utf8(data, pos)
    on, pos = _qdatetime(data, pos)
    operator, pos = _utf8(data, pos)
    my_call, pos = _utf8(data, pos)
    my_grid, pos = _utf8(data, pos)
    ex_s, pos = _utf8(data, pos)
    ex_r, pos = _utf8(data, pos)
    prop, pos = _utf8(data, pos)
    mhz = freq / 1e6
    parts = [_tag('CALL', call), _tag('GRIDSQUARE', grid), _tag('MODE', mode), _tag('FREQ', f'{mhz:.6f}'), _tag('BAND', band_of(mhz)),
             _tag('QSO_DATE', on.strftime('%Y%m%d')), _tag('TIME_ON', on.strftime('%H%M%S')),
             _tag('QSO_DATE_OFF', off.strftime('%Y%m%d')), _tag('TIME_OFF', off.strftime('%H%M%S')),
             _tag('RST_SENT', rst_s), _tag('RST_RCVD', rst_r), _tag('TX_PWR', power), _tag('COMMENT', comments), _tag('NAME', name),
             _tag('OPERATOR', operator), _tag('STATION_CALLSIGN', my_call), _tag('MY_GRIDSQUARE', my_grid),
             _tag('STX_STRING', ex_s), _tag('SRX_STRING', ex_r), _tag('PROP_MODE', prop)]
    return ''.join(p for p in parts if p) + '<EOR>'


def contact_xml_to_adif(data):
    """Messaggio XML dei programmi di contest (formato N1MM+, usato anche da QARTest, DXLog, Log4OM...) -> (tipo, record ADIF).
    <contactinfo> e <contactreplace> sono QSO; <contactdelete>, <RadioInfo>, <AppInfo>, <lookupinfo>, <spot>... si ignorano."""
    try:
        root = ET.fromstring(data.lstrip(b'\xef\xbb\xbf').strip())
    except ET.ParseError:
        return None, None
    kind = root.tag.lower()
    if kind not in ('contactinfo', 'contactreplace'):
        return kind, None
    f = {(c.tag or '').lower(): (c.text or '').strip() for c in root}
    call = f.get('call', '').upper()
    if not call:
        return kind, None
    try:
        when = datetime.datetime.strptime(f.get('timestamp', ''), '%Y-%m-%d %H:%M:%S')
    except ValueError:
        when = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    mhz = 0.0
    for name in ('txfreq', 'rxfreq'):  # le frequenze N1MM sono in unita' di 10 Hz
        try:
            mhz = float(f.get(name, '')) / 100000.0
        except ValueError:
            continue
        if mhz > 0:
            break
    band = band_of(mhz) if mhz > 0 else ''
    if not band and f.get('band'):
        try:
            band = band_of(float(f['band']))
        except ValueError:
            pass
    mode = f.get('mode', '').upper()
    submode = ''
    if mode in ('USB', 'LSB'):
        mode, submode = 'SSB', f.get('mode', '').upper()
    parts = [_tag('CALL', call), _tag('QSO_DATE', when.strftime('%Y%m%d')), _tag('TIME_ON', when.strftime('%H%M%S')),
             _tag('BAND', band), _tag('FREQ', f'{mhz:.6f}' if mhz > 0 else ''), _tag('MODE', mode), _tag('SUBMODE', submode),
             _tag('RST_SENT', f.get('snt')), _tag('RST_RCVD', f.get('rcv')),
             _tag('STX', f.get('sntnr') if f.get('sntnr', '0') != '0' else ''), _tag('SRX', f.get('rcvnr') if f.get('rcvnr', '0') != '0' else ''),
             _tag('GRIDSQUARE', f.get('gridsquare')), _tag('NAME', f.get('name')), _tag('QTH', f.get('qth')), _tag('COMMENT', f.get('comment')),
             _tag('CONTEST_ID', f.get('contestname').upper() if f.get('contestname') else ''),
             _tag('STATION_CALLSIGN', f.get('mycall', '').upper()), _tag('OPERATOR', f.get('operator', '').upper()),
             _tag('TX_PWR', f.get('power')), _tag('CQZ', f.get('zone')), _tag('CONT', f.get('continent'))]
    return kind, ''.join(p for p in parts if p) + '<EOR>'


def parse_message(data):
    """Pacchetto UDP -> (tipo, id del client, testo ADIF o None). tipo e' il numero WSJT-X, 'adif' per testo ADIF semplice,
    'contactinfo'/'contactreplace' per l'XML dei programmi di contest, None se sconosciuto."""
    if data.lstrip(b'\xef\xbb\xbf \r\n\t')[:1] == b'<' and b'<eor>' not in data.lower():
        kind, adif = contact_xml_to_adif(data)
        if kind:
            return kind, '', adif
    if len(data) >= 12 and struct.unpack('>I', data[:4])[0] == WSJT_MAGIC:
        try:
            _schema, mtype = struct.unpack('>II', data[4:12])
            client, pos = _utf8(data, 12)
            if mtype == MSG_LOGGED_ADIF:
                n = struct.unpack('>I', data[pos:pos + 4])[0]
                return mtype, client, data[pos + 4:pos + 4 + n].decode('utf-8', 'replace')
            if mtype == MSG_QSO_LOGGED:
                return mtype, client, qso_logged_to_adif(data, pos)
            return mtype, client, None
        except (struct.error, ValueError, OverflowError):
            return None, '', None
    text = data.decode('utf-8', 'replace')
    if '<eor>' in text.lower():
        return 'adif', '', text
    return None, '', None


def parse_packet(data):
    """Compatibilita': solo il testo ADIF contenuto nel pacchetto, o None."""
    return parse_message(data)[2]


def adif_key(text):
    """Chiave per riconoscere lo stesso QSO arrivato come "QSO Logged" e come "Logged ADIF": nominativo, data, ora (HHMM)."""
    def f(name):
        m = re.search(r'<' + name + r':(\d+)(?::[^>]*)?>', text, re.I)
        return text[m.end():m.end() + int(m.group(1))].upper() if m else ''
    return f('CALL'), f('QSO_DATE'), f('TIME_ON')[:4]


def first_call(text):
    return adif_key(text)[0] or '?'


# ---------------------------------------------------------------- coda e invio
def queue_add(text):
    with lock:
        with open(QUEUE, 'a', encoding='utf-8') as f:
            f.write(text.strip() + '\n<EOR>\n' if '<eor>' not in text.lower() else text.strip() + '\n')


def queue_take():
    with lock:
        if not os.path.exists(QUEUE):
            return ''
        with open(QUEUE, encoding='utf-8') as f:
            return f.read()


def queue_len():
    return queue_take().lower().count('<eor>')


def queue_clear(sent):
    with lock:
        if not os.path.exists(QUEUE):
            return
        with open(QUEUE, encoding='utf-8') as f:
            now = f.read()
        rest = now[len(sent):] if now.startswith(sent) else now
        if rest.strip():
            with open(QUEUE, 'w', encoding='utf-8') as f:
                f.write(rest)
        else:
            os.remove(QUEUE)


def send(cfg, text, timeout=30):
    req = urllib.request.Request(cfg['url'], data=text.encode('utf-8'), method='POST',
                                 headers={'X-Ingest-Key': cfg['token'], 'Content-Type': 'text/plain; charset=utf-8', 'User-Agent': f'HH/{VERSION}'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def test_key(cfg):
    """Prova la chiave senza inviare QSO: (ok, messaggio)."""
    if not cfg.get('token'):
        return False, 'Manca la chiave di invio.'
    try:
        send(cfg, '<EOH>\n', timeout=15)
        return True, 'Connessione riuscita: la chiave è valida.'
    except urllib.error.HTTPError as e:
        return False, 'Chiave di invio non valida: generane una nuova su hamhub.cloud/log/.' if e.code == 401 else f'Il server ha risposto con un errore ({e.code}).'
    except (urllib.error.URLError, OSError, ValueError):
        return False, 'Nessuna connessione a hamhub.cloud: controlla la rete.'


# ---------------------------------------------------------------- nucleo: ricezione e invio
class Core:
    """Ricevitore UDP + invio al cloud. Lo stato serve all'icona (tooltip e menu)."""

    def __init__(self, notify=None):
        self.cfg = read_cfg()
        self.notify = notify or (lambda title, text: None)
        self.stop = threading.Event()
        self.sock = None
        self.bound_port = None
        self.port_error = ''
        self.cfg_mtime = os.path.getmtime(CFG) if os.path.exists(CFG) else 0
        self.last_packet = 0.0          # ultimo pacchetto UDP qualunque (Decodium e' collegato)
        self.last_client = ''
        self.last_qso = ''              # "CALL"
        self.last_qso_time = 0.0
        self.sent_total = 0
        self.net = 'ok'                 # ok | offline | key_invalid | no_key
        self.pending5 = {}              # QSO arrivati come "QSO Logged": si attende l'eventuale "Logged ADIF"
        self.wake = threading.Event()

    # --- stato leggibile
    def connected(self):
        return time.time() - self.last_packet < 90

    def status_lines(self):
        c = self.cfg
        lines = []
        if self.port_error:
            lines.append(self.port_error)
        else:
            lines.append(f'In ascolto su 127.0.0.1:{self.bound_port or c["port"]}')
        if self.net == 'no_key':
            lines.append('Manca la chiave di invio: apri Configura')
        elif self.net == 'key_invalid':
            lines.append('Chiave di invio non valida: apri Configura')
        elif self.net == 'offline':
            lines.append(f'Rete o servizio non disponibile: {queue_len()} QSO in coda')
        if self.last_qso:
            lines.append(f'Ultimo QSO: {self.last_qso} alle {time.strftime("%H:%M", time.localtime(self.last_qso_time))}')
        elif self.connected():
            lines.append('Programma di log collegato: in attesa del primo QSO')
        else:
            lines.append('Nessun QSO ricevuto ancora')
        return lines

    # --- configurazione
    def reload_if_changed(self):
        m = os.path.getmtime(CFG) if os.path.exists(CFG) else 0
        if m != self.cfg_mtime:
            self.cfg_mtime = m
            new = read_cfg()
            changed_port = new['port'] != self.cfg['port']
            self.cfg.update(new)
            if changed_port:
                self._close_socket()
            if self.net in ('no_key', 'key_invalid'):
                self.net = 'ok' if self.cfg['token'] else 'no_key'
            self.wake.set()
            log('configurazione aggiornata')

    # --- ricezione
    def _close_socket(self):
        s, self.sock = self.sock, None
        self.bound_port = None
        if s:
            try:
                s.close()
            except OSError:
                pass

    def _bind(self):
        port = int(self.cfg['port'])
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', port))
        except OSError as e:
            s.close()
            self.port_error = f'Porta {port} non disponibile ({e.strerror or e}): un altro programma la usa'
            raise
        s.settimeout(1.0)
        self.sock, self.bound_port, self.port_error = s, port, ''
        log(f'HH in ascolto su 127.0.0.1:{port} -> {self.cfg["url"]}')

    def listen_loop(self):
        seen_types = set()
        while not self.stop.is_set():
            if self.sock is None:
                try:
                    self._bind()
                except (OSError, ValueError):
                    self.stop.wait(10)
                    continue
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                self.sock = None
                continue
            self.last_packet = time.time()
            mtype, client, text = parse_message(data)
            if client:
                self.last_client = client
            if mtype not in seen_types:  # una riga per tipo di messaggio: basta a capire cosa arriva
                seen_types.add(mtype)
                log(f'primo pacchetto di tipo {mtype if mtype is not None else "sconosciuto"} da {addr[0]}:{addr[1]}' + (f' (client {client})' if client else ''))
            if text and text.strip():
                self.on_adif(mtype, text, addr)

    def on_adif(self, mtype, text, addr):
        key = adif_key(text)
        if mtype == MSG_QSO_LOGGED:
            # Decodium invia "QSO Logged" e subito dopo "Logged ADIF" dello stesso QSO: si aspetta il secondo (piu' completo)
            t = threading.Timer(2.0, self._accept, args=(text, addr, key))
            self.pending5[key] = t
            t.start()
            return
        t = self.pending5.pop(key, None)
        if t:
            t.cancel()
        self._accept(text, addr, key)

    def _accept(self, text, addr, key):
        self.pending5.pop(key, None)
        queue_add(text)
        n = text.lower().count('<eor>')
        self.last_qso, self.last_qso_time = first_call(text), time.time()
        log(f'QSO ricevuti da {addr[0]}:{addr[1]} ({n} record): {self.last_qso}')
        self.wake.set()

    # --- invio
    def sender_loop(self):
        while not self.stop.is_set():
            self.wake.wait(5)
            self.wake.clear()
            self.reload_if_changed()
            if not self.cfg['token']:
                self.net = 'no_key'
                continue
            pending = queue_take()
            if not pending.strip():
                continue
            try:
                res = send(self.cfg, pending)
                n = res.get('inserted', 0)
                log(f'inviati al cloud: {n} nuovi, {res.get("skipped", 0)} già presenti')
                queue_clear(pending)
                self.sent_total += n
                if self.net != 'ok':
                    self.net = 'ok'
                if self.cfg.get('notify', '1') != '0':
                    self.notify('HamHub Log', f'QSO inviato al tuo log: {self.last_qso}' if n == 1 else f'{n} QSO inviati al tuo log')
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    if self.net != 'key_invalid':
                        self.notify('HamHub Log', 'Chiave di invio non valida: apri Configura dall\'icona vicino all\'orologio. I QSO restano in coda.')
                    self.net = 'key_invalid'
                    log('chiave di invio non valida: i QSO restano in coda, apri Configura')
                    self.wake.wait(55)
                else:
                    log(f'errore dal cloud ({e.code}): riprovo tra 30 secondi')
                    self.net = 'offline'
                    self.wake.wait(30)
            except (urllib.error.URLError, OSError, ValueError) as e:
                if self.net != 'offline':
                    log(f'rete non disponibile ({e}): QSO in coda, riprovo ogni 30 secondi')
                self.net = 'offline'
                self.wake.wait(30)

    def start(self):
        for fn in (self.listen_loop, self.sender_loop):
            threading.Thread(target=fn, daemon=True).start()
        if queue_len():
            self.wake.set()

    def shutdown(self):
        self.stop.set()
        self._close_socket()


# ---------------------------------------------------------------- avvio automatico (Windows: registro; Linux: .desktop; macOS: LaunchAgent)
def exe_argv():
    return [sys.executable] if FROZEN else [sys.executable, os.path.abspath(__file__)]


def exe_command():
    return ' '.join(f'"{a}"' for a in exe_argv())


def autostart_file():
    if IS_MAC:
        return os.path.join(os.path.expanduser('~/Library/LaunchAgents'), 'cloud.hamhub.hh.plist')
    return os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'autostart', 'hamhub-hh.desktop')


def autostart_enabled():
    if not IS_WIN:
        return os.path.exists(autostart_file())
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
            return True
    except (OSError, ImportError):
        return False


def set_autostart(on):
    if not IS_WIN:
        path = autostart_file()
        if not on:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        argv = exe_argv()
        if IS_MAC:
            items = ''.join(f'    <string>{a}</string>\n' for a in argv)
            text = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>\n  <key>Label</key><string>cloud.hamhub.hh</string>\n  <key>ProgramArguments</key><array>\n' + items +
                    '  </array>\n  <key>RunAtLoad</key><true/>\n</dict></plist>\n')
        else:
            exec_line = ' '.join('"' + a.replace('"', '\\"') + '"' for a in argv)
            text = f'[Desktop Entry]\nType=Application\nName=HH - HamHub Log\nComment=Invia i QSO al tuo log su hamhub.cloud\nExec={exec_line}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n'
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, exe_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except FileNotFoundError:
                pass


def open_path(path):
    """Apre un file o un indirizzo con il programma predefinito del sistema."""
    if IS_WIN:
        os.startfile(path)
    else:
        subprocess.Popen(['open' if IS_MAC else 'xdg-open', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def spawn_setup():
    cmd = exe_argv() + ['--setup']
    subprocess.Popen(cmd, creationflags=0x08000000) if IS_WIN else subprocess.Popen(cmd)  # CREATE_NO_WINDOW su Windows


def notify_desktop(title, text):
    """Notifica del sistema su Linux (notify-send) e macOS (osascript); senza strumenti non fa nulla."""
    try:
        if IS_MAC:
            subprocess.Popen(['osascript', '-e', f'display notification {json.dumps(text)} with title {json.dumps(title)}'])
        elif shutil.which('notify-send'):
            subprocess.Popen(['notify-send', '-a', 'HH', title, text])
    except OSError:
        pass


# ---------------------------------------------------------------- finestra di configurazione (Tkinter)
HELP_DECODIUM = ('HH riceve i QSO in UDP da qualunque programma di log, all\'indirizzo 127.0.0.1 porta {port}:\n'
                 '  • Decodium: Impostazioni → «UDP SERVER» → spunta «Secondary UDP», Server 127.0.0.1,\n'
                 '    Port {port}, traffico solo «QSO logged»\n'
                 '  • QARTest, N1MM+, DXLog, Log4OM: nelle impostazioni di rete/«Broadcast» abilita l\'invio\n'
                 '    dei contatti (Contacts / ContactInfo) verso 127.0.0.1, porta {port}\n'
                 '  • Programmi che inviano ADIF in UDP: stessa destinazione, un record per pacchetto\n'
                 'HH capisce da solo il formato (WSJT-X, XML N1MM/QARTest, ADIF).')


def setup_window():
    import tkinter as tk
    from tkinter import ttk
    if IS_WIN:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    cfg = read_cfg()
    root = tk.Tk()
    root.title('HH - Configurazione')
    root.resizable(False, False)
    try:
        root.iconbitmap(os.path.join(RES_DIR, 'hh.ico'))
    except tk.TclError:
        pass
    pad = {'padx': 14, 'pady': 4}
    frm = ttk.Frame(root, padding=10)
    frm.grid()
    ttk.Label(frm, text='Chiave di invio (da hamhub.cloud/log/ → Invio QSO)').grid(sticky='w', **pad)
    token = tk.StringVar(value=cfg['token'])
    ent = ttk.Entry(frm, textvariable=token, width=52)  # chiave sempre in chiaro, così si controlla ciò che si incolla
    ent.grid(sticky='we', **pad)
    ttk.Label(frm, text='Porta UDP di ascolto').grid(sticky='w', **pad)
    port = tk.StringVar(value=cfg['port'])
    ttk.Entry(frm, textvariable=port, width=10).grid(sticky='w', **pad)
    notify = tk.BooleanVar(value=cfg.get('notify', '1') != '0')
    ttk.Checkbutton(frm, text='Mostra una notifica quando un QSO viene inviato', variable=notify).grid(sticky='w', **pad)
    help_lbl = ttk.Label(frm, text=HELP_DECODIUM.format(port=cfg['port']), justify='left', foreground='#444')
    help_lbl.grid(sticky='w', padx=14, pady=(10, 4))
    port.trace_add('write', lambda *_: help_lbl.config(text=HELP_DECODIUM.format(port=port.get() or cfg['port'])))
    msg = ttk.Label(frm, text='', wraplength=420, justify='left')
    msg.grid(sticky='w', **pad)

    def current():
        return dict(cfg, token=token.get().strip(), port=port.get().strip(), notify='1' if notify.get() else '0')

    def check():
        c = current()
        if not valid_port(c['port']):
            msg.config(text='La porta deve essere un numero tra 1024 e 65535.', foreground='#b00020')
            return False
        ok, text = test_key(c)
        msg.config(text=text, foreground='#0a7d33' if ok else '#b00020')
        return ok

    def save():
        c = current()
        if not valid_port(c['port']):
            msg.config(text='La porta deve essere un numero tra 1024 e 65535.', foreground='#b00020')
            return
        write_cfg(c)
        root.destroy()

    row = ttk.Frame(frm)
    row.grid(sticky='e', padx=14, pady=(8, 2))
    ttk.Button(row, text='Prova la connessione', command=check).pack(side='left', padx=4)
    ttk.Button(row, text='Salva', command=save).pack(side='left', padx=4)
    ttk.Button(row, text='Annulla', command=root.destroy).pack(side='left', padx=4)
    ent.focus_set()
    root.mainloop()


# ---------------------------------------------------------------- icona nell'area di notifica (Win32, senza librerie esterne)
def run_tray(core):
    from ctypes import wintypes as wt
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [('style', wt.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                    ('hInstance', wt.HINSTANCE), ('hIcon', wt.HICON), ('hCursor', wt.HANDLE), ('hbrBackground', wt.HBRUSH),
                    ('lpszMenuName', wt.LPCWSTR), ('lpszClassName', wt.LPCWSTR)]

    class NOTIFYICONDATA(ctypes.Structure):
        _fields_ = [('cbSize', wt.DWORD), ('hWnd', wt.HWND), ('uID', wt.UINT), ('uFlags', wt.UINT), ('uCallbackMessage', wt.UINT),
                    ('hIcon', wt.HICON), ('szTip', wt.WCHAR * 128), ('dwState', wt.DWORD), ('dwStateMask', wt.DWORD),
                    ('szInfo', wt.WCHAR * 256), ('uVersion', wt.UINT), ('szInfoTitle', wt.WCHAR * 64), ('dwInfoFlags', wt.DWORD),
                    ('guidItem', ctypes.c_byte * 16), ('hBalloonIcon', wt.HICON)]

    user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
    user32.RegisterClassW.restype = wt.ATOM
    user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
    user32.CreateWindowExW.restype = wt.HWND
    user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.LoadImageW.restype = wt.HANDLE
    user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
    user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID]
    user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, wt.LPVOID]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
    user32.DestroyWindow.argtypes = [wt.HWND]
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.DestroyMenu.argtypes = [wt.HMENU]
    user32.CreatePopupMenu.restype = wt.HMENU
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.LoadIconW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
    user32.LoadIconW.restype = wt.HANDLE
    user32.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
    kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wt.HMODULE
    shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATA)]
    shell32.Shell_NotifyIconW.restype = wt.BOOL

    WM_DESTROY, WM_COMMAND, WM_TIMER, WM_NULL = 0x2, 0x111, 0x113, 0x0
    WM_USER = 0x400
    WM_TRAY, WM_NOTIFY_Q = WM_USER + 1, WM_USER + 2
    WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_CONTEXTMENU = 0x203, 0x205, 0x7B
    NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 1, 2, 4, 0x10
    NIIF_INFO = 1
    MF_STRING, MF_GRAYED, MF_CHECKED, MF_SEPARATOR = 0, 1, 8, 0x800
    TPM_RETURNCMD, TPM_RIGHTBUTTON = 0x100, 0x2
    IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
    ID_OPEN, ID_SETUP, ID_LOG, ID_HELP, ID_AUTOSTART, ID_NOTIFY, ID_EXIT = 101, 102, 103, 104, 105, 106, 107
    balloons = deque()
    state = {'tip': '', 'taskbar_msg': user32.RegisterWindowMessageW('TaskbarCreated'), 'quit': False, 'adds': 0}

    icon_path = os.path.join(RES_DIR, 'hh.ico')
    size = user32.GetSystemMetrics(49) or 16  # SM_CXSMICON
    hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE) if os.path.exists(icon_path) else None
    if not hicon:
        hicon = user32.LoadIconW(None, ctypes.c_void_p(32512))  # icona di sistema predefinita

    nid = NOTIFYICONDATA()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
    nid.uID = 1
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    nid.uCallbackMessage = WM_TRAY
    nid.hIcon = hicon

    def tip_text():
        return ('HH - HamHub Log\n' + '\n'.join(core.status_lines()))[:127]

    def tray(op):
        ok = bool(shell32.Shell_NotifyIconW(op, ctypes.byref(nid)))
        if op == NIM_ADD and ok:
            state['adds'] += 1
        return ok

    def set_tip():
        state['tip'] = nid.szTip = tip_text()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        tray(NIM_MODIFY)

    def balloon(title, text):
        nid.uFlags = NIF_INFO
        nid.szInfoTitle, nid.szInfo, nid.dwInfoFlags = title[:63], text[:255], NIIF_INFO
        tray(NIM_MODIFY)
        nid.szInfo = ''

    def open_setup():
        spawn_setup()

    def show_help():
        text = HELP_DECODIUM.format(port=core.cfg['port']) + '\n\nSe i QSO non compaiono, apri il registro di HH dal menu: indica quali pacchetti arrivano dal programma di log.'
        user32.MessageBoxW(None, text, 'Come collegare il programma di log a HH', 0x40)

    def menu():
        m = user32.CreatePopupMenu()
        user32.AppendMenuW(m, MF_STRING | MF_GRAYED, 0, f'HH {VERSION} - HamHub Log')
        for line in core.status_lines():
            user32.AppendMenuW(m, MF_STRING | MF_GRAYED, 0, line)
        user32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(m, MF_STRING, ID_OPEN, 'Apri il mio log su hamhub.cloud')
        user32.AppendMenuW(m, MF_STRING, ID_SETUP, 'Configura...')
        user32.AppendMenuW(m, MF_STRING, ID_HELP, 'Come collegare il programma di log...')
        user32.AppendMenuW(m, MF_STRING, ID_LOG, 'Apri il registro di HH')
        user32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(m, MF_STRING | (MF_CHECKED if autostart_enabled() else 0), ID_AUTOSTART, 'Avvia HH con Windows')
        user32.AppendMenuW(m, MF_STRING | (MF_CHECKED if core.cfg.get('notify', '1') != '0' else 0), ID_NOTIFY, 'Mostra le notifiche')
        user32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(m, MF_STRING, ID_EXIT, 'Esci')
        return m

    def command(cid, hwnd):
        if cid == ID_OPEN:
            webbrowser.open(LOG_PAGE)
        elif cid == ID_SETUP:
            open_setup()
        elif cid == ID_HELP:
            threading.Thread(target=show_help, daemon=True).start()
        elif cid == ID_LOG:
            open_path(LOG) if os.path.exists(LOG) else None
        elif cid == ID_AUTOSTART:
            set_autostart(not autostart_enabled())
        elif cid == ID_NOTIFY:
            cfg = read_cfg()
            cfg['notify'] = '0' if cfg.get('notify', '1') != '0' else '1'
            write_cfg(cfg)
        elif cid == ID_EXIT:
            state['quit'] = True
            user32.DestroyWindow(hwnd)

    @WNDPROC
    def wndproc(hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                if lparam == WM_LBUTTONDBLCLK:
                    webbrowser.open(LOG_PAGE)
                elif lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    pt = wt.POINT()
                    user32.GetCursorPos(ctypes.byref(pt))
                    user32.SetForegroundWindow(hwnd)
                    m = menu()
                    cid = user32.TrackPopupMenu(m, TPM_RETURNCMD | TPM_RIGHTBUTTON, pt.x, pt.y, 0, hwnd, None)
                    user32.PostMessageW(hwnd, WM_NULL, 0, 0)
                    user32.DestroyMenu(m)
                    if cid:
                        command(cid, hwnd)
                return 0
            if msg == WM_NOTIFY_Q:
                while balloons:
                    balloon(*balloons.popleft())
                return 0
            if msg == WM_TIMER:
                core.reload_if_changed()
                if tip_text() != state['tip']:
                    set_tip()
                return 0
            if msg == state['taskbar_msg']:  # Explorer riavviato: l'icona va rimessa
                nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
                tray(NIM_ADD)
                return 0
            if msg == WM_COMMAND:
                command(wparam & 0xFFFF, hwnd)
                return 0
            if msg == WM_DESTROY:
                tray(NIM_DELETE)
                user32.PostQuitMessage(0)
                return 0
        except Exception as e:  # un errore in una voce di menu non deve mai far sparire l'icona
            log(f'errore nell\'icona: {type(e).__name__}: {e}')
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASS()
    wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = wndproc, hinst, 'HamHubHHTray'
    user32.RegisterClassW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(0, 'HamHubHHTray', 'HH', 0, 0, 0, 0, 0, None, None, hinst, None)  # finestra mai mostrata

    def notify(title, text):
        if core.cfg.get('notify', '1') != '0':
            balloons.append((title, text))
            user32.PostMessageW(hwnd, WM_NOTIFY_Q, 0, 0)

    core.notify = notify
    nid.hWnd = hwnd
    state['tip'] = nid.szTip = tip_text()
    if not tray(NIM_ADD):
        log('impossibile creare l\'icona nell\'area di notifica')
    user32.SetTimer(hwnd, 1, 2000, None)
    log(f'HH {VERSION} avviato nell\'area di notifica')
    state.update(hwnd=hwnd, user32=user32, tray=tray, command=command, balloons=balloons, WM_NOTIFY_Q=WM_NOTIFY_Q)
    run_tray.state = state
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    return 0


def single_instance():
    """True se questa e' l'unica istanza. Windows: mutex; Linux e macOS: file di blocco (flock). Resta valido finche' vive il processo."""
    if not IS_WIN:
        import fcntl
        single_instance.handle = open(os.path.join(HERE, 'HH.lock'), 'w')
        try:
            fcntl.flock(single_instance.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    single_instance.handle = k.CreateMutexW(None, 0, MUTEX_NAME)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def run_portable(core):
    """Linux e macOS: icona nell'area di notifica con pystray + Pillow (se installati), altrimenti HH lavora in background e usa le notifiche del sistema."""
    core.notify = notify_desktop
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        log('pystray/Pillow non installati: HH lavora senza icona (pip install pystray pillow per averla). Esci con Ctrl+C o chiudendo il processo.')
        try:
            while True:
                time.sleep(2)
                core.reload_if_changed()
        except KeyboardInterrupt:
            return 0
    ico = os.path.join(RES_DIR, 'hh.ico')
    try:
        image = Image.open(ico)
        image.load()
    except (OSError, ValueError):
        image = Image.new('RGBA', (64, 64), (38, 132, 255, 255))
        ImageDraw.Draw(image).text((20, 22), 'HH', fill='white')

    def line(n):
        return pystray.MenuItem(lambda item: (core.status_lines() + [''] * 3)[n] or ' ', None, enabled=False)

    def toggle_notify(icon, item):
        cfg = read_cfg()
        cfg['notify'] = '0' if cfg.get('notify', '1') != '0' else '1'
        write_cfg(cfg)

    def toggle_autostart(icon, item):
        set_autostart(not autostart_enabled())

    def quit_app(icon, item):
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(f'HH {VERSION} - HamHub Log', None, enabled=False), line(0), line(1), pystray.Menu.SEPARATOR,
        pystray.MenuItem('Apri il mio log su hamhub.cloud', lambda icon, item: webbrowser.open(LOG_PAGE), default=True),
        pystray.MenuItem('Configura...', lambda icon, item: spawn_setup()),
        pystray.MenuItem('Apri il registro di HH', lambda icon, item: open_path(LOG) if os.path.exists(LOG) else None),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Avvia HH all\'accesso', toggle_autostart, checked=lambda item: autostart_enabled()),
        pystray.MenuItem('Mostra le notifiche', toggle_notify, checked=lambda item: read_cfg().get('notify', '1') != '0'),
        pystray.Menu.SEPARATOR, pystray.MenuItem('Esci', quit_app))
    icon = pystray.Icon('HamHubHH', image, 'HH - HamHub Log', menu)

    def housekeeping():
        while not core.stop.is_set():
            time.sleep(2)
            core.reload_if_changed()
            try:
                icon.title = ('HH - HamHub Log\n' + '\n'.join(core.status_lines()))[:127]
            except Exception:  # noqa: BLE001
                pass
    threading.Thread(target=housekeeping, daemon=True).start()
    log(f'HH {VERSION} avviato con l\'icona (pystray)')
    icon.run()   # su macOS deve girare nel thread principale
    return 0


# ---------------------------------------------------------------- avvio
def main():
    if '--version' in sys.argv:
        print(f'HH {VERSION}')
        return 0
    if '--configure' in sys.argv:
        args = sys.argv[sys.argv.index('--configure') + 1:]
        if not args or args[0].startswith('--'):
            sys.exit('uso: HH --configure CHIAVE [PORTA]')
        cfg = read_cfg()
        cfg['token'] = args[0].strip()
        if len(args) > 1 and not args[1].startswith('--'):
            if not valid_port(args[1]):
                sys.exit('la porta deve essere un numero tra 1024 e 65535')
            cfg['port'] = args[1]
        write_cfg(cfg)
        print(f'configurazione salvata in {CFG}')
        return 0
    if IS_WIN and '--console' not in sys.argv:
        ctypes.windll.kernel32.FreeConsole()  # se lanciato da python.exe o da un terminale, nessuna finestra di testo resta aperta
    if '--setup' in sys.argv:
        try:
            setup_window()
        except Exception as e:  # noqa: BLE001  (senza schermo o senza Tk)
            sys.exit(f'finestra di configurazione non disponibile ({type(e).__name__}): usa  HH --configure CHIAVE [PORTA]')
        return 0
    if '--console' in sys.argv:
        core = Core()
        if not core.cfg['token']:
            log('chiave di invio mancante: esegui HH --setup oppure HH --configure CHIAVE')
        core.start()
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0
    if not single_instance():
        if IS_WIN:
            ctypes.windll.user32.MessageBoxW(None, 'HH è già in esecuzione: cerca l\'icona vicino all\'orologio (se non la vedi, apri le icone nascoste con la freccia ^).',
                                             'HH - HamHub Log', 0x40)
        else:
            print('HH è già in esecuzione.')
        return 0
    core = Core()
    core.start()
    if not core.cfg['token']:  # primo avvio: si apre subito la configurazione
        if IS_WIN or os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY') or IS_MAC:
            spawn_setup()
        else:
            log('chiave di invio mancante: esegui  HH --configure CHIAVE')
    try:
        return run_tray(core) if IS_WIN else run_portable(core)
    finally:
        core.shutdown()


if __name__ == '__main__':
    sys.exit(main())
