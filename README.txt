HH - HamHub Log (client per Decodium, QARTest, N1MM+ e altri programmi di log)
=================================================

HH riceve in UDP i QSO registrati dal tuo programma di log (Decodium, QARTest, N1MM+, DXLog, Log4OM...) e li invia al tuo log su hamhub.cloud.
Vive nell'area di notifica (vicino all'orologio): se non vedi l'icona, apri
le icone nascoste con la freccia ^.

Prima configurazione
  1. Accedi su https://hamhub.cloud/log/ e genera la chiave di invio.
  2. HH apre da solo la finestra di configurazione al primo avvio:
     incolla la chiave e premi "Prova la connessione", poi "Salva".
     La porta predefinita e' 12060.
  3. In DECODIUM (non in DecoDXLog), nelle impostazioni, sezione "UDP SERVER":
       - spunta "Secondary UDP"
       - Secondary Server: 127.0.0.1
       - Secondary Port:   12060
       - Secondary traffic: lascia solo "QSO logged"
     Cosi' Decodium invia a HH ogni QSO appena registrato.
  3b. QARTest, N1MM+, DXLog, Log4OM e simili: nelle impostazioni di rete/broadcast abilita
     l'invio dei contatti (Contacts / ContactInfo) all'indirizzo 127.0.0.1, porta 12060.
     HH riconosce da solo il formato: WSJT-X (Decodium), XML N1MM/QARTest, ADIF in UDP.
     (DecoDXLog continua a ricevere i QSO dalla destinazione primaria, porta 2237.)
  4. Fai un QSO di prova: l'icona mostra "Ultimo QSO: ..." e compare una notifica
     "QSO inviato al tuo log". I QSO si vedono su https://hamhub.cloud/log/#qso

Uso quotidiano
  Doppio clic sull'icona: apre il tuo log su hamhub.cloud.
  Clic destro: stato, Configura, Come collegare Decodium, registro,
  "Avvia HH con Windows", notifiche, Esci.
  Se la rete manca, i QSO restano in coda e vengono rispediti da soli.
  Se la chiave non e' valida, i QSO restano in coda: correggi la chiave in
  Configura e partono subito.

File di HH (in %APPDATA%\HamHub\HH):
  HH.ini        configurazione (chiave di invio, porta, indirizzo)
  HH_queue.adi  QSO in attesa di invio
  HH.log        registro delle operazioni (utile se i QSO non arrivano:
                indica quali pacchetti arrivano da Decodium)

Se i QSO non compaiono
  - Nel registro (menu -> "Apri il registro di HH") cerca la riga
    "primo pacchetto di tipo 5 / 12 ...": se manca, Decodium non sta inviando a HH.
    Controlla la porta nelle impostazioni di Decodium.
  - Se la porta risulta occupata, cambia porta in Configura e in Decodium.

Versione 1.2.0
