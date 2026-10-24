"""Test di HH: pacchetti WSJT-X, coda e invio, ritentativi, icona nell'area di notifica, avvio con Windows.
Uso:  python tests\\test_hh.py     (dalla cartella HH; prova anche con decodxlog_udpsend.exe se c'e')"""
import ctypes
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA = tempfile.mkdtemp(prefix='hh-test-')
os.environ['HH_DATA_DIR'] = DATA  # prima dell'import: configurazione, coda e registro di prova
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import HH  # noqa: E402

UDPSEND = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'DecoDXLog', 'decodxlog_udpsend.exe')


def check(label, got, want):
    ok = got == want
    print(('OK   ' if ok else 'FAIL ') + label + f'  (atteso {want!r}, ottenuto {got!r})')
    if not ok:
        sys.exit(1)


# ---------- costruzione di pacchetti come li invia Decodium
def u8(s):
    b = s.encode()
    return struct.pack('>I', len(b)) + b


def qdt(year, month, day, h, mi, s):
    import datetime
    jd = datetime.date(year, month, day).toordinal() + 1721425
    return struct.pack('>QIB', jd, ((h * 60 + mi) * 60 + s) * 1000, 1)


def header(mtype, client='Decodium'):
    return struct.pack('>III', HH.WSJT_MAGIC, 3, mtype) + u8(client)


def pkt_qso_logged(call='JA1ABC', hz=14074000, mode='FT8'):
    return (header(5) + qdt(2026, 10, 22, 11, 37, 41) + u8(call) + u8('PM95') + struct.pack('>Q', hz) + u8(mode) + u8('-10') + u8('-12') + u8('5') + u8('ciao à')
            + u8('Taro') + qdt(2026, 10, 22, 11, 36, 20) + u8('IU8LMC') + u8('IU8LMC') + u8('JN71') + u8('') + u8('') + u8(''))


def pkt_adif(call='JA1ABC', hz=14074000):
    text = f'<call:{len(call)}>{call}<qso_date:8>20261022<time_on:6>113620<band:3>20m<mode:3>FT8<freq:9>14.074000<eor>'
    return header(12) + u8(text)


# ================= lettura dei messaggi
check('locator: banda dalla frequenza', [HH.band_of(14.074), HH.band_of(7.047), HH.band_of(50.313), HH.band_of(99.0)], ['20m', '40m', '6m', ''])
t, cid, adif = HH.parse_message(pkt_qso_logged())
check('QSO Logged: tipo e client', (t, cid), (5, 'Decodium'))
for tag in ('<CALL:6>JA1ABC', '<GRIDSQUARE:4>PM95', '<MODE:3>FT8', '<FREQ:9>14.074000', '<BAND:3>20m', '<QSO_DATE:8>20261022', '<TIME_ON:6>113620',
            '<TIME_OFF:6>113741', '<RST_SENT:3>-10', '<RST_RCVD:3>-12', '<NAME:4>Taro', '<STATION_CALLSIGN:6>IU8LMC', '<MY_GRIDSQUARE:4>JN71', '<EOR>'):
    check(f'QSO Logged -> ADIF contiene {tag}', tag in adif, True)
check('QSO Logged: commento con accenti, lunghezza in byte', '<COMMENT:7>ciao à' in adif, True)
check('Logged ADIF: tipo e testo', HH.parse_message(pkt_adif())[::2][0], 12)
check('Logged ADIF: contenuto', 'JA1ABC' in HH.parse_message(pkt_adif())[2], True)
check('testo ADIF semplice', HH.parse_message(b'<call:5>K1ABC<eor>')[0], 'adif')
XML_QSO = ('<?xml version="1.0" encoding="utf-8"?><contactinfo><app>QARTEST</app><contestname>CQWWSSB</contestname><contestnr>1</contestnr>'
           '<timestamp>2026-10-24 12:34:56</timestamp><mycall>IU8LMC</mycall><band>14</band><rxfreq>1420000</rxfreq><txfreq>1420000</txfreq>'
           '<operator>IU8LMC</operator><mode>USB</mode><call>JA1abc</call><snt>59</snt><sntnr>12</sntnr><rcv>57</rcv><rcvnr>0</rcvnr>'
           '<gridsquare>PM95</gridsquare><name>Taro è</name><comment>ciao</comment><power>100</power><ID>abc</ID></contactinfo>').encode('utf-8')
t, cid, xadif = HH.parse_message(XML_QSO)
check('XML N1MM/QARTest: tipo', t, 'contactinfo')
check('XML N1MM/QARTest: nominativo, data, ora', HH.adif_key(xadif), ('JA1ABC', '20261024', '1234'))
check('XML N1MM/QARTest: frequenza e banda dalle unita\' di 10 Hz', ('<FREQ:9>14.200000' in xadif, '<BAND:3>20m' in xadif), (True, True))
check('XML N1MM/QARTest: USB diventa SSB + sottomodo', ('<MODE:3>SSB' in xadif, '<SUBMODE:3>USB' in xadif), (True, True))
check('XML N1MM/QARTest: rapporti, numero progressivo, nome con accento in byte', ('<RST_SENT:2>59' in xadif, '<STX:2>12' in xadif, '<SRX:' in xadif, '<NAME:7>Taro è' in xadif), (True, True, False, True))
check('XML N1MM/QARTest: nominativo proprio e contest', ('<STATION_CALLSIGN:6>IU8LMC' in xadif, '<CONTEST_ID:7>CQWWSSB' in xadif), (True, True))
check('XML contactreplace e\' un QSO', HH.parse_message(XML_QSO.replace(b'contactinfo', b'contactreplace'))[::2], ('contactreplace', xadif))
check('XML contactdelete, RadioInfo, AppInfo: nessun QSO', [HH.parse_message(b'<%s><call>K1ABC</call></%s>' % (x, x))[2] for x in (b'contactdelete', b'RadioInfo', b'AppInfo')], [None] * 3)
check('XML senza nominativo o rotto: scartato', [HH.parse_message(x)[2] for x in (b'<contactinfo><mode>CW</mode></contactinfo>', b'<contactinfo><call>K1')], [None] * 2)
check('ADIF con tag e <eor> resta ADIF, non XML', HH.parse_message(b'<call:5>K1ABC<eor>')[0], 'adif')
check('Heartbeat e Status: nessun QSO', (HH.parse_message(header(0))[2], HH.parse_message(header(1))[2]), (None, None))
check('pacchetti malformati scartati senza errori', [HH.parse_message(x)[2] for x in (b'', b'ciao', header(5) + b'\x00\x01', pkt_qso_logged()[:40])], [None] * 4)
check('stessa chiave per "QSO Logged" e "Logged ADIF" dello stesso QSO', HH.adif_key(adif), HH.adif_key(HH.parse_message(pkt_adif())[2]))
check('chiave diversa per un altro nominativo', HH.adif_key(adif) != HH.adif_key(HH.parse_message(pkt_adif('DL1XYZ'))[2]), True)

# con lo strumento di DecoDXLog che imita Decodium
if os.path.exists(UDPSEND):
    rs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rs.bind(('127.0.0.1', 0))
    rs.settimeout(2)
    port = rs.getsockname()[1]
    subprocess.run([UDPSEND, '--host', '127.0.0.1', '--port', str(port), '--call', 'TEST1X', '--mycall', 'IU8LMC', '--mode', 'FT8', '--freq', '14074000'],
                   capture_output=True, timeout=20)
    got = {}
    try:
        while True:
            m = HH.parse_message(rs.recvfrom(65535)[0])
            got[m[0]] = m[2]
    except socket.timeout:
        pass
    check('strumento DecoDXLog: arrivano Heartbeat, Status, QSO Logged e Logged ADIF', sorted(got), [0, 1, 5, 12])
    a5, a12 = got[5], got[12]
    check('strumento DecoDXLog: i due messaggi descrivono lo stesso QSO', HH.adif_key(a5), HH.adif_key(a12))
    check('strumento DecoDXLog: nominativo, banda e modo concordano', (HH.adif_key(a5)[0], 'BAND:3>20M' in a5.upper(), 'FT8' in a5.upper()), ('TEST1X', True, True))
    only = subprocess.run([UDPSEND, '--host', '127.0.0.1', '--port', str(port), '--call', 'TEST2X', '--only-qsologged'], capture_output=True, timeout=20)
    kinds = []
    try:
        while True:
            kinds.append(HH.parse_message(rs.recvfrom(65535)[0])[0])
    except socket.timeout:
        pass
    check('strumento DecoDXLog: con solo "QSO Logged" HH riceve comunque il QSO', 5 in kinds and 12 not in kinds, True)
    rs.close()
else:
    print('--   decodxlog_udpsend.exe non trovato: prova con lo strumento saltata')

# ================= configurazione
cfg = HH.read_cfg()
check('configurazione di partenza', (cfg['token'], cfg['port'], cfg['notify']), ('', '12060', '1'))
HH.write_cfg(dict(cfg, token='abc DEF=1#', port='12099', notify='0'))
cfg = HH.read_cfg()
check('configurazione: scrittura e lettura (chiave con spazi, = e #)', (cfg['token'], cfg['port'], cfg['notify']), ('abc DEF=1#', '12099', '0'))
check('porte valide', [HH.valid_port(x) for x in ('12060', '80', '65536', 'abc', '')], [True, False, False, False, False])


# ================= invio e ritentativi contro un server finto
class Stub(BaseHTTPRequestHandler):
    keys = {'good'}
    down = False
    got = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode()
        if Stub.down:
            self.send_response(503)
            self.end_headers()
            return
        if self.headers.get('X-Ingest-Key') not in Stub.keys:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"no"}')
            return
        n = body.lower().count('<eor>')
        Stub.got.append(body)
        data = json.dumps({'inserted': n, 'skipped': 0}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


srv = ThreadingHTTPServer(('127.0.0.1', 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{srv.server_address[1]}/adif'
free = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
free.bind(('127.0.0.1', 0))
uport = free.getsockname()[1]
free.close()
check('prova della chiave: valida', HH.test_key({'token': 'good', 'url': url})[0], True)
check('prova della chiave: non valida', HH.test_key({'token': 'sbagliata', 'url': url}), (False, 'Chiave di invio non valida: generane una nuova su hamhub.cloud/log/.'))
check('prova della chiave: manca', HH.test_key({'token': '', 'url': url})[0], False)
check('prova della chiave: server irraggiungibile', HH.test_key({'token': 'good', 'url': 'http://127.0.0.1:9/adif'})[1], 'Nessuna connessione a hamhub.cloud: controlla la rete.')

Stub.got.clear()  # le prove della chiave hanno gia' passato qualche richiesta
HH.write_cfg({'token': 'good', 'port': str(uport), 'url': url, 'notify': '1'})
notes = []
core = HH.Core(notify=lambda a, b: notes.append((a, b)))
core.start()
time.sleep(0.5)
tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
send = lambda data: tx.sendto(data, ('127.0.0.1', uport))
wait = lambda cond, secs=8: any(cond() or time.sleep(0.1) for _ in range(int(secs * 10)))
check('ascolto avviato', core.bound_port, uport)
check('stato iniziale', core.status_lines(), [f'In ascolto su 127.0.0.1:{uport}', 'Nessun QSO ricevuto ancora'])
send(header(0))
wait(lambda: core.connected())
check('dopo un Heartbeat: Decodium collegato, nessun QSO', core.status_lines()[-1], 'Programma di log collegato: in attesa del primo QSO')
send(pkt_qso_logged('JA1ABC'))
send(pkt_adif('JA1ABC'))
wait(lambda: len(Stub.got) >= 1)
time.sleep(3)  # il QSO Logged duplicato non deve partire dopo la finestra di attesa
check('"QSO Logged" + "Logged ADIF" dello stesso QSO: un solo invio', (len(Stub.got), sum(b.lower().count('<eor>') for b in Stub.got)), (1, 1))
check('stato dopo il QSO', (core.last_qso, core.sent_total, core.net), ('JA1ABC', 1, 'ok'))
check('notifica di invio', notes[-1], ('HamHub Log', 'QSO inviato al tuo log: JA1ABC'))
send(pkt_qso_logged('DL1XYZ'))
wait(lambda: len(Stub.got) >= 2, 10)
check('solo "QSO Logged": parte dopo la breve attesa', (len(Stub.got), 'DL1XYZ' in Stub.got[-1]), (2, True))
send(XML_QSO.replace(b'JA1abc', b'QARTEST1'))  # un QSO di QARTest (XML N1MM) in UDP
wait(lambda: len(Stub.got) >= 3, 10)
check('QARTest (XML N1MM) in UDP: il QSO arriva al cloud', (len(Stub.got), 'QARTEST1' in Stub.got[-1], core.last_qso), (3, True, 'QARTEST1'))
send(b'<contactdelete><call>QARTEST1</call><timestamp>2026-10-24 12:34:56</timestamp></contactdelete>')
send(b'<RadioInfo><app>QARTEST</app><freq>1420000</freq></RadioInfo>')
time.sleep(1)
check('XML di cancellazione e info radio: nessun invio', len(Stub.got), 3)
# rete assente: il QSO resta in coda
Stub.down = True
send(pkt_adif('K1ABC'))
wait(lambda: core.net == 'offline', 10)
check('rete assente: stato e QSO in coda', (core.net, HH.queue_len()), ('offline', 1))
Stub.down = False
core.wake.set()
wait(lambda: HH.queue_len() == 0, 40)
check('rete tornata: la coda si svuota', (HH.queue_len(), core.net, 'K1ABC' in Stub.got[-1]), (0, 'ok', True))
# chiave non valida: i QSO NON si perdono
HH.write_cfg({'token': 'scaduta', 'port': str(uport), 'url': url, 'notify': '1'})
core.reload_if_changed()
send(pkt_adif('F5XYZ'))
wait(lambda: core.net == 'key_invalid', 10)
check('chiave non valida: stato, QSO ancora in coda, avviso', (core.net, HH.queue_len(), any('non valida' in n[1] for n in notes)), ('key_invalid', 1, True))
HH.write_cfg({'token': 'good', 'port': str(uport), 'url': url, 'notify': '1'})
core.wake.set()
core.reload_if_changed()
wait(lambda: HH.queue_len() == 0, 15)
check('chiave corretta dopo l\'errore: il QSO in coda parte', (HH.queue_len(), 'F5XYZ' in Stub.got[-1]), (0, True))
# cambio di porta senza riavviare
free = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
free.bind(('127.0.0.1', 0))
p2 = free.getsockname()[1]
free.close()
HH.write_cfg({'token': 'good', 'port': str(p2), 'url': url, 'notify': '0'})
core.reload_if_changed()
wait(lambda: core.bound_port == p2, 8)
check('cambio di porta a caldo', core.bound_port, p2)
# porta occupata
occ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):  # Windows: blocca davvero la porta; su Linux e macOS basta non condividerla
    occ.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
occ.bind(('127.0.0.1', 0))
busy = occ.getsockname()[1]
HH.write_cfg({'token': 'good', 'port': str(busy), 'url': url, 'notify': '0'})
core.reload_if_changed()
wait(lambda: 'non disponibile' in core.port_error, 8)
check('porta occupata: messaggio chiaro', 'non disponibile' in core.status_lines()[0], True)
core.shutdown()
occ.close()
srv.shutdown()

# ================= avvio con Windows (con un nome di prova, senza toccare quello vero)
if os.name == 'nt':
    HH.RUN_VALUE = 'HamHubHH_test'
    HH.set_autostart(False)
    check('avvio con Windows: spento', HH.autostart_enabled(), False)
    HH.set_autostart(True)
    check('avvio con Windows: acceso', HH.autostart_enabled(), True)
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, HH.RUN_KEY) as k:
        val = winreg.QueryValueEx(k, HH.RUN_VALUE)[0]
    check('avvio con Windows: comando tra virgolette', val.startswith('"') and 'HH.py' in val, True)
    HH.set_autostart(False)
    check('avvio con Windows: di nuovo spento', HH.autostart_enabled(), False)
    HH.MUTEX_NAME = 'HamHubHH_test_mutex'  # non confliggere con un HH vero in esecuzione
    check('una sola istanza: la prima passa, la seconda no', (HH.single_instance(), HH.single_instance()), (True, False))

    # ================= icona nell'area di notifica
    from ctypes import wintypes as wt
    HH.write_cfg({'token': 'good', 'port': str(p2), 'url': url, 'notify': '1'})
    tcore = HH.Core()
    th = threading.Thread(target=lambda: HH.run_tray(tcore), daemon=True)
    th.start()
    wait(lambda: getattr(HH.run_tray, 'state', None) and HH.run_tray.state.get('hwnd'), 8)
    st = HH.run_tray.state
    shell32 = ctypes.WinDLL('shell32')

    class NID(ctypes.Structure):
        _fields_ = [('cbSize', wt.DWORD), ('hWnd', wt.HWND), ('uID', wt.UINT), ('guidItem', ctypes.c_byte * 16)]

    shell32.Shell_NotifyIconGetRect.argtypes = [ctypes.POINTER(NID), ctypes.POINTER(wt.RECT)]
    shell32.Shell_NotifyIconGetRect.restype = ctypes.c_long

    def icon_rect():
        ident = NID(ctypes.sizeof(NID), st['hwnd'], 1)
        rc = wt.RECT()
        return shell32.Shell_NotifyIconGetRect(ctypes.byref(ident), ctypes.byref(rc)), rc

    hr, rc = icon_rect()
    check('icona nell\'area di notifica: registrata da Windows', (hr, rc.right > rc.left and rc.bottom > rc.top), (0, True))
    st['balloons'].append(('HamHub Log', 'Prova di notifica'))
    st['user32'].PostMessageW(st['hwnd'], st['WM_NOTIFY_Q'], 0, 0)
    time.sleep(0.5)
    check('notifica a fumetto: coda svuotata dal ciclo dei messaggi', len(st['balloons']), 0)
    check('tooltip aggiornato con lo stato', st['tip'].startswith('HH - HamHub Log\nIn ascolto su 127.0.0.1:'), True)
    st['user32'].PostMessageW(st['hwnd'], 0x111, 107, 0)  # voce "Esci"
    th.join(5)
    check('voce Esci: il ciclo termina e l\'icona sparisce', (not th.is_alive(), icon_rect()[0] != 0), (True, True))
    tcore.shutdown()

    # finestra di configurazione: si apre e resta viva
    env = dict(os.environ, HH_DATA_DIR=DATA)
    pr = subprocess.Popen([sys.executable, os.path.join(HERE, '..', 'HH.py'), '--setup'], env=env)
    time.sleep(3)
    alive = pr.poll() is None
    pr.kill()
    check('finestra di configurazione: si apre', alive, True)

# ================= Linux e macOS: cartelle, avvio automatico, istanza unica, configurazione da riga di comando (le prove girano anche su Windows)
home = tempfile.mkdtemp(prefix='hh-home-')
saved = (HH.IS_WIN, HH.IS_MAC, dict(os.environ))
os.environ.update(HOME=home, USERPROFILE=home)
os.environ.pop('XDG_CONFIG_HOME', None)
os.environ.pop('HH_DATA_DIR', None)
HH.IS_WIN, HH.IS_MAC = False, False
check('Linux: cartella dei dati', os.path.normpath(HH.data_dir()), os.path.join(home, '.config', 'HamHub', 'HH'))
os.environ['XDG_CONFIG_HOME'] = os.path.join(home, 'xdg')
check('Linux: XDG_CONFIG_HOME rispettata', os.path.normpath(HH.data_dir()), os.path.join(home, 'xdg', 'HamHub', 'HH'))
HH.set_autostart(True)
desk = HH.autostart_file()
txt = open(desk, encoding='utf-8').read()
check('Linux: avvio all accesso con file .desktop', (HH.autostart_enabled(), os.path.normpath(desk).endswith('autostart' + os.sep + 'hamhub-hh.desktop'), '[Desktop Entry]' in txt, 'Exec="' in txt), (True, True, True, True))
HH.set_autostart(False)
check('Linux: avvio all accesso tolto', HH.autostart_enabled(), False)
HH.IS_MAC = True
check('macOS: cartella dei dati', os.path.normpath(HH.data_dir()), os.path.join(home, 'Library', 'Application Support', 'HamHub', 'HH'))
HH.set_autostart(True)
plist = open(HH.autostart_file(), encoding='utf-8').read()
check('macOS: avvio all accesso con LaunchAgent', (HH.autostart_enabled(), 'cloud.hamhub.hh' in plist, '<key>RunAtLoad</key><true/>' in plist, '<string>' in plist), (True, True, True, True))
HH.set_autostart(False)
check('macOS: avvio all accesso tolto', HH.autostart_enabled(), False)
HH.IS_WIN, HH.IS_MAC = saved[0], saved[1]
os.environ.clear()
os.environ.update(saved[2])
if os.name != 'nt':
    first = HH.single_instance()
    h1 = HH.single_instance.handle
    second = HH.single_instance()   # un secondo file di blocco sullo stesso percorso: non deve passare
    check('Linux/macOS: una sola istanza', (first, second), (True, False))
    check('Linux/macOS: il file della chiave è privato', oct(os.stat(HH.CFG).st_mode & 0o777), '0o600')
# HH --configure CHIAVE [PORTA]
old_argv = sys.argv
sys.argv = ['HH.py', '--configure', 'chiave-prova', '12077']
HH.main()
cfg = HH.read_cfg()
check('--configure: chiave e porta salvate', (cfg['token'], cfg['port']), ('chiave-prova', '12077'))
sys.argv = old_argv
check('porta non valida in --configure: uscita con errore', subprocess.run([sys.executable, os.path.join(HERE, '..', 'HH.py'), '--configure', 'x', '80'], capture_output=True, env=dict(os.environ, HH_DATA_DIR=DATA)).returncode != 0, True)
check('--version', subprocess.run([sys.executable, os.path.join(HERE, '..', 'HH.py'), '--version'], capture_output=True, env=dict(os.environ, HH_DATA_DIR=DATA)).stdout.decode().strip(), f'HH {HH.VERSION}')
print('TUTTI I TEST HH OK')
