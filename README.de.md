# Astro A50 unter Linux

[English](README.md) | Deutsch

Eine unabhängige, experimentelle Linux-Konfiguration für das **Logitech Astro
A50 Gen 5**. Sie bietet getrennte Game- und Voice-Kanäle, Stummschaltung über
den Mikrofonarm, eine GTK-Desktop-App und eine optionale GNOME-Anzeige.

App und Anzeige bieten Akku- und Mikrofonstatus, Sidetone und
Equalizer-Steuerung. Die App enthält außerdem Mikrofon-EQ, Noise-Gate und
Basisstationseinstellungen. Einige Geräteoptionen verwenden ein unabhängig
untersuchtes USB-Protokoll und verändern Einstellungen auf dem Headset. Nutze
sie vorsichtig und überprüfe das Ergebnis am Gerät.

**Einstieg:** Lies die [getestete Umgebung](#getestete-umgebung) und
[Voraussetzungen](#voraussetzungen) und folge den nummerierten Abschnitten.
Game/Voice, Mikrofonarm, App und Anzeige können wie beschrieben auch einzeln
installiert werden.

## Getestete Umgebung

- Logitech Astro A50 mit USB-ID `046d:0b1c`
- Ubuntu 26.04, GNOME 50.1, PipeWire 1.6.2 und WirePlumber 0.5.13
- Firmware 1.3.24, laut G HUB

Andere A50-Generationen, Firmware-Versionen und Linux-Distributionen wurden
nicht getestet. Insbesondere können sich Gerätenamen und HID-Ereignisse
unterscheiden. Die Stummschaltung erfolgt **in PipeWire**, ausgelöst durch den
Mikrofonarm; sie ist keine unabhängig überprüfte Hardware-Stummschaltung.

**Mikrofon und Privatsphäre:** Prüfe, ob beide Mikrofoneingänge tatsächlich
stummgeschaltet sind; die Armposition allein ist kein verlässlicher
Mute-Indikator. Siehe [Mikrofonarm](#2-mikrofonarm-und-signaltöne-einrichten).

## Voraussetzungen

Die Basisstation muss über ihre **„PC“-USB-Buchse** mit dem Linux-PC verbunden
sein, nicht über die Xbox- oder PlayStation-Buchse. Das Headset darf dabei nicht
an eine virtuelle Maschine durchgereicht sein. PipeWire, WirePlumber 0.5 und
eine PipeWire-Pulse-kompatible Soundausgabe müssen laufen. Die Anleitung
verwendet Python 3.10 oder neuer und `systemd --user`. Für die grafische
Einrichtung wird `pavucontrol`
empfohlen.

Unter Ubuntu lassen sich die benötigten Werkzeuge bei Bedarf installieren:

```bash
sudo apt install wireplumber pipewire-bin pipewire-pulse pulseaudio-utils python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 pavucontrol usbutils
```

Prüfe, ob das unterstützte Gerät erkannt wird:

```bash
lsusb -d 046d:0b1c
wpctl status
```

Die folgenden Installationsbefehle werden **im Projektverzeichnis** ausgeführt.
Sie überschreiben vorhandene Dateien mit denselben Zielnamen. Sichere
gegebenenfalls deine vorhandenen Konfigurationen und Skripte vorher.

## 1. Game und Voice einrichten

### Pro-Audio-Profil auswählen

Öffne `pavucontrol` und wähle unter **Konfiguration** für das A50 das Profil
**Pro Audio**. Alternativ lässt sich das Profil über `pactl` setzen. Prüfe
zuerst den tatsächlichen Kartennamen:

```bash
pactl list short cards
```

Wenn die Karte wie in der getesteten Umgebung `alsa_card.usb-Logitech_A50-00`
heißt:

```bash
pactl set-card-profile alsa_card.usb-Logitech_A50-00 pro-audio
```

Im Pro-Audio-Profil sollten zwei Ausgänge und zwei Eingänge erscheinen. Die
Zuordnung wurde beim getesteten Headset mit dem Game/Voice-Mixregler geprüft:

| Profilgerät | Verwendung |
| --- | --- |
| `pro-output-0` | Voice-Ausgang |
| `pro-output-1` | Game-Ausgang |
| `pro-input-0` | Voice-Mikrofon |
| `pro-input-1` | Game-Mikrofon |

### Namen und Standardprofil einrichten

Die folgende WirePlumber-Konfiguration benennt die Knoten und setzt für Karten
mit dem ALSA-Namen `A50` standardmäßig das Pro-Audio-Profil. Der Neustart von
WirePlumber kann laufende Audiowiedergabe kurz unterbrechen.

```bash
install -Dm644 wireplumber/51-a50-labels.conf \
  "$HOME/.config/wireplumber/wireplumber.conf.d/51-a50-labels.conf"
systemctl --user restart wireplumber
```

Mit `wpctl status` sollten anschließend **A50 Voice**, **A50 Game**,
**A50 Mic (Voice)** und **A50 Mic (Game)** sichtbar sein.

### Anwendungen zuordnen

Starte die gewünschte Anwendung und öffne `pavucontrol`. Unter
**Wiedergabe** kannst du ihren Stream dem passenden Ausgang zuweisen, zum
Beispiel ein Spiel zu **A50 Game** und Discord zu **A50 Voice**. Das
gewünschte Mikrofon lässt sich unter **Aufnahme** auswählen, während die
Anwendung aufnimmt. Je nach Anwendung kann die Auswahl auch direkt in deren
Audioeinstellungen erfolgen.

### Optional: stumme Streams nach PlaySync-Wechsel wiederherstellen

Beim Umschalten des Headsets per PlaySync verschwindet es kurz und kommt
wieder. Manche Anwendungen, zum Beispiel Wine/Proton-Spiele, weisen PipeWire
an, ihren Stream nicht neu zu verbinden, und bleiben danach stumm. Dieser
kleine Benutzerdienst verbindet solche Streams wieder mit dem A50-Ausgang, den
sie anvisieren:

```bash
install -Dm755 scripts/a50_relink_streams.py \
  "$HOME/.local/bin/a50-relink-streams.py"
install -Dm644 systemd/a50-relink-streams.service \
  "$HOME/.config/systemd/user/a50-relink-streams.service"
systemctl --user daemon-reload
systemctl --user enable --now a50-relink-streams.service
```

### Optional: Profilwechsel durch GNOME zurücksetzen

In der getesteten GNOME-Version wurde das Pro-Audio-Profil beim Ändern der
Soundeinstellungen teilweise wieder auf Stereo gesetzt. Der folgende
WirePlumber-Hook stellt bei Profiländerungen für eine ALSA-Karte namens `A50`
das Pro-Audio-Profil wieder her. Dadurch lassen sich andere Profile für diese
Karte nicht dauerhaft auswählen, solange der Hook installiert ist.

```bash
install -Dm644 wireplumber/90-a50-lock-pro-audio.lua \
  "$HOME/.local/share/wireplumber/scripts/90-a50-lock-pro-audio.lua"
install -Dm644 wireplumber/90-a50-lock-pro-audio.conf \
  "$HOME/.config/wireplumber/wireplumber.conf.d/90-a50-lock-pro-audio.conf"
systemctl --user restart wireplumber
```

## 2. Mikrofonarm und Signaltöne einrichten

Beim getesteten Gerät wird das Hoch- und Herunterklappen als HID-Ereignis
gemeldet. Der Dienst liest diese Ereignisse und setzt den Mute-Zustand der
beiden A50-Eingänge:

- Arm hoch: beide A50-Eingänge stumm, absteigender Ton.
- Arm runter: beide A50-Eingänge aktiv, aufsteigender Ton – auch wenn sie
  zuvor manuell stummgeschaltet waren.

**Wichtig:** Beim Start und nach erneutem Verbinden ist die Armposition nicht
bekannt, bis der Arm bewegt wird. Der bestehende Mute-Zustand bleibt bis dahin
unverändert. Eine andere Anwendung oder eine Tastenkombination kann den
Mute-Zustand unabhängig vom Arm wieder ändern. Verlasse dich deshalb nicht
allein auf die Armposition, wenn du sicher stummgeschaltet sein musst.

Die mitgelieferten Signaltöne sind laut. Stelle die Lautstärke vor dem ersten
Test vorsichtig ein.

### HID-Zugriff prüfen

Das Skript verwendet diesen gerätespezifischen Pfad:

```bash
ls -l /dev/input/by-id/usb-Logitech_A50-if08-hidraw
test -r /dev/input/by-id/usb-Logitech_A50-if08-hidraw \
  && echo "HID-Gerät lesbar" || echo "HID-Gerät nicht lesbar oder nicht vorhanden"
```

Falls der Pfad fehlt, prüfe die USB-Verbindung und die Gerätekennung. Falls er
existiert, aber nicht lesbar ist, kann auf Systemen mit `udev` und einer aktiven
grafischen Sitzung eine gerätespezifische Regel den Zugriff freigeben. Prüfe
vorher, dass die folgende Datei noch nicht existiert; dieser Befehl würde sie
sonst überschreiben:

```bash
echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="0b1c", TAG+="uaccess"' \
  | sudo tee /etc/udev/rules.d/70-astro-a50-hidraw.rules
sudo udevadm control --reload-rules
```

Trenne danach das Headset kurz vom USB-Anschluss, verbinde es erneut und
wiederhole den Lesetest. Die Regel gewährt der aktiven lokalen Sitzung Zugriff
auf die HID-Schnittstelle dieses USB-Geräts. Falls der Zugriff weiterhin
fehlschlägt, prüfe die Rechte und die Sitzungsverwaltung deiner Distribution,
statt den Dienst als Root auszuführen.

### Dienst installieren

```bash
install -Dm644 scripts/a50-flip-mute.py \
  "$HOME/.local/bin/a50-flip-mute.py"
install -Dm644 sounds/mute.wav \
  "$HOME/.local/share/toggle-mic-mute-sounds/mute.wav"
install -Dm644 sounds/unmute.wav \
  "$HOME/.local/share/toggle-mic-mute-sounds/unmute.wav"
install -Dm644 systemd/a50-flip-mute.service \
  "$HOME/.config/systemd/user/a50-flip-mute.service"
systemctl --user daemon-reload
systemctl --user enable --now a50-flip-mute.service
```

Der Dienst erwartet die PipeWire-Knotennamen
`alsa_input.usb-Logitech_A50-00.pro-input-0` und
`alsa_input.usb-Logitech_A50-00.pro-input-1`. Falls sie bei deinem System
anders lauten, funktioniert die automatische Stummschaltung mit diesem Skript
nicht ohne Anpassung.

### Funktion prüfen

Klappe den Arm hoch und wieder herunter. Prüfe, ob beide Signaltöne zu hören
sind und sich der Mute-Zustand der A50-Eingänge entsprechend ändert:

```bash
wpctl status
systemctl --user status a50-flip-mute.service
journalctl --user -u a50-flip-mute.service -n 30 --no-pager
```

Die aktuellen IDs stehen in `wpctl status`; sie können sich nach einem
Neustart oder erneuten Verbinden ändern. Mit `wpctl get-volume ID` lässt sich
für jeden Eingang prüfen, ob `[MUTED]` angezeigt wird. Ersetze `ID` durch die
jeweilige aktuelle Zahl.

### Optional: Tastenkombination

Dieses separate Skript schaltet **das aktuelle Standardmikrofon** um und spielt
die gleichen Signaltöne. Anders als der Mikrofonarm-Dienst bearbeitet es nicht
automatisch beide A50-Eingänge.

```bash
install -Dm755 scripts/toggle-mic-mute.sh \
  "$HOME/.local/bin/toggle-mic-mute.sh"
```

Richte in GNOME unter **Einstellungen → Tastatur → Tastenkombinationen →
Eigene Tastenkombinationen** eine neue Kombination ein. Als Befehl trägst du
den vollständigen Pfad zum installierten Skript ein, zum Beispiel
`/home/DEIN_BENUTZER/.local/bin/toggle-mic-mute.sh`. Als Taste wurde
**Numpad-Plus** getestet.

## 3. Akkustand abfragen

Der folgende experimentelle Befehl sendet einmalig eine von G HUB beobachtete
Akku-Abfrage und zeigt ein Ergebnis an; er läuft nicht im Hintergrund.
Dasselbe [Geräteprotokoll wurde auch von HaloBattery dokumentiert](https://github.com/HeyOkay/HaloBattery/blob/main/docs/protocols.md#astro-a50-gen-5-logitech-046d0b1c).

Das Headset meldet zwei Werte. Bei unseren Tests entsprach die G-HUB-Anzeige
ohne Ladestation dem ersten und beim Laden dem zweiten Wert. Der Befehl nutzt
diese Regel als **Schätzung** und zeigt zum Vergleich beide gemeldeten Werte.
Ihre Bedeutung ist noch nicht vollständig geklärt, die Werte können
voneinander abweichen und bei einem getrennten oder ausgeschalteten Headset
veraltet sein. Der angezeigte Prozentwert ist daher nicht als gesichert
anzusehen.

Das HID-Gerät muss für den aktuellen Benutzer sowohl lesbar **als auch
schreibbar** sein. Prüfe die Rechte wie oben im Abschnitt zum HID-Zugriff;
ersetze `test -r` durch `test -w`, um den Schreibzugriff zu prüfen. Das Headset
muss mit Linux verbunden sein und darf nicht an eine virtuelle Maschine durchgereicht
sein.

```bash
install -Dm755 scripts/a50_battery.py "$HOME/.local/bin/a50-battery"
"$HOME/.local/bin/a50-battery"
```

Der Befehl meldet Fehler, wenn das Gerät nicht geöffnet werden kann, nicht
antwortet oder unbekannte Werte zurückgibt. Er sendet nur beim Aufruf eine
Abfrage und verändert den Mikrofonarm-Dienst nicht.

### Experimentelle Sidetone-Steuerung

Die Sidetone-Steuerung ist experimentell und nur mit Firmware 1.3.24 getestet.
Das Headset hat sieben Stufen von 0 bis 6. Die USB-Befehle aller sieben Stufen
wurden in G HUB mitgeschnitten. Der Befehl für Stufe 1 und das Zurücksetzen auf
Stufe 0 wurden auch unter Linux getestet.
Die Desktop-App liest den Pegel beim Öffnen aus, zeigt ihn in Prozent an und
übernimmt Änderungen am Regler automatisch. In der GNOME-Erweiterung wird
Sidetone ebenfalls in Prozent angezeigt und beim Loslassen des Reglers
übernommen; Tastatur- und Mausradänderungen werden nach kurzer Pause gesendet.
Dort wird der aktuelle
Pegel nicht ausgelesen. Die sieben Gerätestufen entsprechen gerundet 0, 17,
33, 50, 67, 83 und 100 %.

Installiere den gemeinsamen Befehl für Erweiterung und App:

```bash
install -Dm755 scripts/a50_sidetone.py "$HOME/.local/bin/a50-sidetone"
```

Zum Ändern von Sidetone ist derselbe HID-Zugriff wie für die Akkuabfrage nötig.
Das Headset muss mit Linux verbunden sein, nicht mit einer VM. Fehler werden in
der App beziehungsweise der GNOME-Anzeige dargestellt und von GNOME Shell
protokolliert.

### Experimenteller Equalizer

Der Headset-Equalizer ist experimentell und mit Firmware 1.3.24 getestet.
Das Profil enthält zehn Bänder von 20 Hz bis 20 kHz. Der Editor unterstützt
−6 bis +6 dB in 0,5-dB-Schritten. Die Desktop-App liest beim Öffnen die
aktuelle EQ-Kurve aus, ohne sie zu verändern. Ein Presetname wird bei genau einer passenden
gespeicherten Kurve angezeigt; der aktive Name selbst wird nicht aus dem
Headset ausgelesen.

**Standard** ist das neutrale Profil; ein separates, identisches „Flat“-Preset
gibt es nicht. **Bass**, **Voice** und **Footsteps** sind eigene
Startpunkte. Benutzerdefinierte Presets lassen sich im Desktop-Editor
speichern und werden unter `~/.config/astro-a50-linux/eq-presets.json`
abgelegt. Das Programm kann auch direkt verwendet werden:

```bash
install -Dm755 scripts/a50_equalizer.py "$HOME/.local/bin/a50-equalizer"
"$HOME/.local/bin/a50-equalizer" list
"$HOME/.local/bin/a50-equalizer" apply "Standard"
```

Das Senden eines Profils verändert den EQ im Headset. Nutze es nur, wenn das
Headset mit Linux verbunden ist und der HID-Schreibzugriff eingerichtet wurde.
Die Antwort bestätigt die Annahme des Profils, liest aber den aktuellen EQ
nicht zurück.

### Separater Mikrofon-Equalizer

Der Mikrofon-EQ ist ein eigener, experimenteller Steuerpfad und nicht mit dem
Wiedergabe-EQ verknüpft. Eigene USB-Mitschnitte bestätigen zehn Bänder bei
80 Hz, 150 Hz, 250 Hz, 400 Hz, 800 Hz, 1,5 kHz, 2,5 kHz, 5 kHz, 10 kHz und
19 kHz. Der bestätigte Bereich ist −6 bis +6 dB in 0,5-dB-Schritten.
**Standard** ist neutral; **Warm** und **Klar** sind eigene Startpunkte,
keine akustisch kalibrierten Profile.

Der vollständige Mikrofon-Editor und eigene Presets in der Desktop-GUI sind
getrennt vom Wiedergabe-EQ; die Konfiguration wird separat in
`~/.config/astro-a50-linux/microphone-eq-presets.json` gespeichert.
Die Desktop-App liest die Mikrofon-EQ-Kurve beim Öffnen aus, ohne sie zu
verändern.

### Mikrofon-Noise-Gate

Ein getrennter Mitschnitt bestätigt die Zuordnung **Aus** (`0`), **Nacht**
(`2`), **Zu Hause** (`1`) und **Turnier** (`4`). Das Noise-Gate und die
Mikrofon-EQ-Kurven verwenden unterschiedliche Befehle. Der Befehl lautet
beispielsweise:

```bash
install -Dm755 scripts/a50_microphone_noise_gate.py \
  "$HOME/.local/bin/a50-microphone-noise-gate"
install -Dm644 scripts/a50_equalizer.py "$HOME/.local/bin/a50_equalizer.py"
"$HOME/.local/bin/a50-microphone-noise-gate" list
"$HOME/.local/bin/a50-microphone-noise-gate" set "Nacht"
```

Die Desktop-GUI hat dafür eigene Bedienelemente. Beim Öffnen
stellt sie keinen Zustand ein. Ein erfolgreicher Befehl erhält eine
Gerätebestätigung, die den aktiven oder gespeicherten Zustand nicht selbst
zurückmeldet. Die Desktop-App liest den Zustand beim Öffnen separat aus;
**Nacht** und **Aus** wurden unter Linux überprüft.

### Basisstation und Geräteoptionen

Eigene Mitschnitte zeigen Basisstationshelligkeit bei 50 und 100 sowie
Ruhezustände **Aus**, 15, 30 und 60 Minuten. Die Sound-Modi **Alle**,
**Minimal** und **Aus** wurden ebenfalls erfasst. Die Bestätigung eines
Schreibbefehls liest den gespeicherten Wert nicht zurück. Die Desktop-App fragt
Helligkeit, Ruhezeit und Sound-Modus beim Öffnen separat ab.

Bluetooth wird nur angezeigt, nicht ein- oder ausgeschaltet. Die Statusabfrage
unterscheidet „Gerät verbunden“ von „Kein Gerät verbunden“ und kann bei einer
Verbindung den vom Headset gelieferten Gerätenamen anzeigen. Installiere für
den direkten Aufruf den Befehl und sein gemeinsames Modul, falls die Desktop-App
sie nicht bereits installiert hat:

```bash
install -Dm755 scripts/a50_base_station.py "$HOME/.local/bin/a50-base-station"
install -Dm644 scripts/a50_equalizer.py "$HOME/.local/bin/a50_equalizer.py"
"$HOME/.local/bin/a50-base-station" brightness 50
"$HOME/.local/bin/a50-base-station" sleep 30
"$HOME/.local/bin/a50-base-station" sound minimal
"$HOME/.local/bin/a50-base-station" bluetooth
```

### Optional: Anzeige in der GNOME-Statusleiste

Die beiliegende Erweiterung ist mit GNOME Shell 50 getestet. Sie verwendet den
oben installierten Befehl `a50-battery` und fragt den Akku beim Aktivieren und
danach alle 60 Sekunden ab. Im Menü lässt sich der Wert auch manuell
aktualisieren. Das Akkusymbol ist beim Laden grün, bei vollem Akku dunkler
grün, bis einschließlich 20 % rot und von 21 % bis 40 % orange; ansonsten
verwendet es die GNOME-Standardfarbe. Der angezeigte Prozentwert ist
experimentell und kann ungenau sein. Ein
Mikrofonsymbol in der Statusleiste zeigt den aktuellen Mute-Zustand; im Menü
schaltet der Mikrofoneintrag beide A50-Eingänge um. Bei unterschiedlichen
Zuständen zeigt das Symbol neutral an; ein Klick schaltet beide stumm. Der
Mikrofonstatus wird alle zwei Sekunden aktualisiert. Bei fehlgeschlagenen
Abfragen erscheint ein Fragezeichen beziehungsweise ein neutrales
Mikrofonsymbol. Ein ausgeschaltetes oder getrenntes Headset kann trotzdem
veraltete Akku-Daten zurückgeben. Im getesteten Aufbau wurden Laden, Nichtladen
und ein getrenntes Headset in der Statusleiste geprüft; die Anzeige verhielt
sich wie erwartet.
Das Menü bietet außerdem Sidetone, die eingebauten Equalizer-Presets als
Schnellwahl und den Bluetooth-Verbindungsstatus. Installiere dafür wie oben
beschrieben `a50-battery`, `a50-sidetone`, `a50-equalizer` und
`a50-base-station`; der Bluetooth-Helfer benötigt zusätzlich das gemeinsame
Modul `a50_equalizer.py`. Alternativ installiere `a50-battery` und danach die
Desktop-App, deren Installationsskript die übrigen Helfer installiert.
Mikrofon-EQ, Noise-Gate, Helligkeit, Ruhezustand und Töne bleiben in der
Desktop-App.

Führe nach der Installation des Akku-Befehls im Projektverzeichnis aus:

```bash
gnome-extensions pack --extra-source=status.js \
  gnome-extension/a50-battery@astro-a50-linux
gnome-extensions install -f a50-battery@astro-a50-linux.shell-extension.zip
gnome-extensions enable a50-battery@astro-a50-linux
```

Der Paketbefehl erstellt eine ZIP-Datei im aktuellen Verzeichnis und
überschreibt standardmäßig kein vorhandenes Paket. Zum Aktualisieren einer
bereits installierten Erweiterung deaktiviere sie vor der Installation und
aktiviere sie danach wieder. Falls GNOME das Update nicht sofort lädt, melde
dich ab und wieder an:

```bash
gnome-extensions disable a50-battery@astro-a50-linux
gnome-extensions install -f a50-battery@astro-a50-linux.shell-extension.zip
gnome-extensions enable a50-battery@astro-a50-linux
```

Status prüfen oder Erweiterung deaktivieren:

```bash
gnome-extensions info a50-battery@astro-a50-linux
gnome-extensions disable a50-battery@astro-a50-linux
```

Der Equalizer-Unterpunkt sendet eines der eingebauten Presets sofort an das
Headset.

## 4. Kleine Desktop-GUI

Die GTK4-/Libadwaita-App verwendet ein neutrales GNOME-Kopfhörersymbol statt
eines Hersteller-Produktbilds. Sie zeigt Akku- und Mikrofonstatus, den
Sidetone-Regler sowie getrennte 10-Band-Editoren für Wiedergabe- und
Mikrofon-EQ. Das Menü links öffnet die Startseite **Einstellungen** mit
Geräteoptionen sowie separate Seiten für **EQ Ausgabe** und **EQ Mikrofon**.
Akku und Mikrofonsteuerung bleiben oben sichtbar. Beide EQs haben eigene
Presets und getrennte Dateien für gespeicherte Nutzer-Presets. Änderungen an
Reglern und Auswahllisten werden nach kurzer Pause automatisch übernommen;
Speichern legt weiterhin ein eigenes Preset an. Beim Öffnen werden Sidetone,
Helligkeit, Ruhezeit, Sound-Modus, Noise-Gate und beide EQ-Kurven vom Headset
abgefragt, aber keine Einstellungen geschrieben. Das Auswahlfeld zeigt ein
Preset, wenn seine Kurve übereinstimmt; der aktive Presetname selbst wird
nicht ausgelesen. Bei mehreren Treffern oder einer eigenen Kurve wird dies
entsprechend angezeigt.
Ein Klick auf die Mikrofonsteuerung schaltet beide Eingänge
gemeinsam stumm oder aktiv. Sind sie unterschiedlich eingestellt, schaltet
ein Klick beide stumm.

Die App prüft den Mikrofonstatus alle zwei Sekunden und den Akku alle 60
Sekunden. Geräteabfragen laufen in Hintergrund-Threads. Installiere bei Bedarf
die GTK4- und Libadwaita-Bindings für das System-Python:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

Installiere die App und ihren Eintrag im Anwendungsmenü aus dem
Projektverzeichnis:

```bash
scripts/install-gui.sh
```

Starte **Astro A50 Control** über die Anwendungsübersicht oder mit
`~/.local/bin/a50-control`. Das Installationsskript installiert auch die
Sidetone-, Equalizer- und weiteren Gerätebefehle. Die App verwendet den bereits
installierten Befehl `~/.local/bin/a50-battery` und die in Abschnitt 2
installierten Mute-/Unmute-Töne. Sie verändert nicht den Mikrofonarm-Dienst.

## Bekannte Grenzen

- Das ist eine erste, auf einem Gerät getestete Konfiguration, keine allgemeine
  Unterstützung für alle A50-Modelle.
- Der Mikrofonarm-Dienst kommuniziert nur lesend mit dem HID-Gerät. Er fragt
  die aktuelle Armposition nicht ab.
- Die Akkuanzeige ist experimentell. PLAYSYNC-Steuerung und Firmware-Updates
  sind hier nicht implementiert. Firmware-Updates wurden bislang über G HUB
  in Windows durchgeführt.

## Aktualisieren und Entfernen

Ersetze zum Aktualisieren die Projektdateien und wiederhole nur die
Installationsschritte für die verwendeten Komponenten. Installationsbefehle
überschreiben ihre Zieldateien; sichere eigene Änderungen vorher. Starte
installierte Benutzerdienste bei Bedarf mit
`systemctl --user restart a50-flip-mute.service` beziehungsweise
`systemctl --user restart a50-relink-streams.service` neu. Aktualisiere die
Erweiterung wie oben beschrieben und melde dich bei Bedarf ab und wieder an.

Zum Entfernen beende und deaktiviere jeden installierten Benutzerdienst mit
`systemctl --user disable --now DIENST`; ersetze `DIENST` durch
`a50-flip-mute.service` beziehungsweise `a50-relink-streams.service`.
Deinstalliere die Erweiterung mit
`gnome-extensions uninstall a50-battery@astro-a50-linux`. Entferne danach
bei Bedarf die in den Installationsbefehlen genannten Dateien, den
Desktop-Eintrag
`~/.local/share/applications/io.github.astro-a50-linux.Control.desktop` und
die Dienstdateien in `~/.config/systemd/user/`. Führe nach dem Entfernen von
Dienstdateien `systemctl --user daemon-reload` aus. Entferne installierte
WirePlumber-Konfiguration und Hook nur, wenn du sie für dieses Projekt
eingerichtet hast, und starte WirePlumber danach neu. Entferne die optionale
udev-Regel nur, wenn sie für dieses Projekt erstellt wurde; lade anschließend
die udev-Regeln neu und verbinde das Gerät erneut. Das GUI-Installationsskript
legt `a50-control`, `a50-sidetone`, `a50-equalizer`, `a50_equalizer.py`,
`a50-microphone-equalizer`, `a50-microphone-noise-gate`, `a50-base-station`
und `a50-device-status` in `~/.local/bin/` ab. Entferne einen Helfer nur,
wenn keine verbleibende Komponente ihn benötigt. Eigene Presets unter
`~/.config/astro-a50-linux/` bleiben dabei erhalten; sichere oder entferne sie
bei Bedarf separat. Bereits an das Headset gesendete Änderungen werden nicht
automatisch zurückgesetzt.

## Tests

Im Projektverzeichnis, mit installierten Python-GTK-/Libadwaita-Bindings und
GJS:

```bash
/usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'
gjs -m tests/test_a50_indicator.js
```

GTK-abhängige Tests können ohne grafische Anzeige übersprungen werden. Die
automatisierten Tests verwenden Mocks und ersetzen keinen Test am Gerät.

## Lizenz und Marken

Der Projektcode steht unter der GNU General Public License, Version 3 oder
einer späteren Version (GPL-3.0-or-later); siehe [LICENSE](LICENSE).

Logitech, Astro, A50 und G HUB sind Namen oder Marken ihrer jeweiligen
Rechteinhaber; sie dienen hier zur Identifikation kompatibler Produkte. Dieses
unabhängige Projekt steht nicht in Verbindung mit Logitech und wird nicht von
Logitech unterstützt.
