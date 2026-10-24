# HH — ponte tra il tuo programma di log e HamHub Log

HH riceve in locale (UDP) i QSO dal tuo programma di log e li invia al tuo log su [hamhub.cloud](https://hamhub.cloud/log/#qso).
Se la rete manca i QSO restano in coda e vengono rispediti. Funziona su **Windows, Linux e macOS**.

*HH receives QSOs from your logging program over local UDP and sends them to your HamHub Log (hamhub.cloud). Offline QSOs are queued and retried. Windows, Linux and macOS.*

## Programmi supportati

| Programma | Come collegarlo |
|---|---|
| Decodium, WSJT-X (protocollo WSJT-X: «QSO Logged» e «Logged ADIF») | Impostazioni → UDP Server: `127.0.0.1`, porta `12060` |
| QARTest, N1MM+, DXLog, Log4OM (XML `contactinfo`/`contactreplace`) | Rete/Broadcast: invio contatti verso `127.0.0.1`, porta `12060` |
| Qualunque programma che invia un record ADIF per pacchetto UDP | stessa destinazione |

HH riconosce da solo il formato. Gli altri pacchetti (heartbeat, status, cancellazioni) vengono ignorati.

## Uso

1. Su hamhub.cloud: **Log → Chiave** → genera la chiave di invio.
2. Avvia HH e incolla la chiave in *Configura* (si apre da sola al primo avvio).
3. Nel programma di log imposta l'invio UDP a `127.0.0.1:12060`.

```text
HH              avvia HH (icona nell'area di notifica, una sola istanza)
HH --setup      finestra di configurazione (chiave di invio, porta)
HH --configure CHIAVE [PORTA]   salva la configurazione senza finestre (server, SSH, schermi assenti)
HH --console    solo ricevitore in un terminale, per le prove
HH --version
```

Configurazione, coda (`HH_queue.adi`) e registro (`HH.log`) stanno in:

| Sistema | Cartella |
|---|---|
| Windows | `%APPDATA%\HamHub\HH` |
| macOS | `~/Library/Application Support/HamHub/HH` |
| Linux | `~/.config/HamHub/HH` (o `$XDG_CONFIG_HOME`) |

Il file `HH.ini` contiene la chiave di invio: su Linux e macOS è leggibile solo dall'utente (`0600`). **Non va condiviso né committato.**

## Windows

Installatore e `HH.exe` si scaricano da [hamhub.cloud](https://hamhub.cloud/downloads/HH-Setup.exe). L'icona è quella nativa di Windows, senza librerie esterne.

## Linux

```bash
# eseguibile già compilato (vedi "Compilare") oppure direttamente dal sorgente:
sudo apt install python3 python3-tk          # tk serve solo per la finestra di configurazione
pip install pystray pillow                   # facoltativo: icona nell'area di notifica
python3 HH.py
```

- **Con icona**: `pystray` + `pillow`. Su GNOME serve l'estensione *AppIndicator* (pacchetto `gnome-shell-extension-appindicator`); KDE, XFCE, MATE, Cinnamon la mostrano già.
- **Senza icona** HH lavora in background e usa `notify-send` per le notifiche (pacchetto `libnotify-bin`).
- L'avvio all'accesso crea `~/.config/autostart/hamhub-hh.desktop` (voce di menu *Avvia HH all'accesso*).

## macOS

```bash
brew install python-tk                       # per la finestra di configurazione (se manca)
pip3 install pystray pillow
python3 HH.py
```

L'app `HH.app` vive nella barra dei menu (nessuna icona nel Dock). L'avvio all'accesso crea `~/Library/LaunchAgents/cloud.hamhub.hh.plist`. Le notifiche usano il Centro notifiche di macOS.
Per l'app compilata non firmata: *clic destro → Apri* la prima volta (Gatekeeper).

## Compilare

Serve Python 3.9+ e `pip install -r requirements-build.txt`.

```bash
python build.py      # -> dist/HH.exe (Windows), dist/HH (Linux), dist/HH.app (macOS)
```

`HH.spec` è il file di PyInstaller, valido per tutti e tre i sistemi (su macOS crea anche l'icona `hh.icns` da `hh.ico`).

**Senza compilare in locale**: ogni push su GitHub avvia l'azione *build* (`.github/workflows/build.yml`) che prova HH e produce i tre eseguibili, scaricabili dagli *Artifacts* della corsa. Con un tag `vX.Y.Z` li allega anche a una *Release*.

## Prove

```bash
python tests/test_hh.py
```

Prova il protocollo (Decodium/WSJT-X, XML N1MM/QARTest, ADIF), la coda e i ritentativi contro un server finto, le cartelle, l'avvio automatico e l'istanza unica. Su Windows prova anche l'icona nell'area di notifica.

## Sicurezza e privacy

HH ascolta solo su `127.0.0.1` (non è raggiungibile dalla rete) e invia i QSO a `https://hamhub.cloud/log-api/adif` con la tua chiave di invio, che puoi revocare in ogni momento dalla pagina *Chiave*. [Informativa privacy](https://hamhub.cloud/privacy/).

## Licenza

[MIT](LICENSE): puoi usare, modificare e ridistribuire HH liberamente, mantenendo l'avviso di copyright.

## Autori

Progetto: IU8LMC Martino Merola · 9H1SR Salvatore Raccampo · Contatti: iu8lmc@gmail.com
