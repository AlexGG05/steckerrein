# steckerrein.de — IT, 3D-Druck & Community

Responsive Community mit Forum, Blog und SQLite. Python 3.12+ und die in `requirements.txt` fest versionierte Bildbibliothek Pillow werden benötigt. Keine npm-Abhängigkeiten. Impressum und Datenschutz bleiben bytegenau erhalten.

## Aufbau und Berechtigungen

- **Besucher:** Themenbereiche, Beiträge, Blogartikel und Antworten öffentlich lesen und durchsuchen. Keine Schreib- oder Bearbeitungsfunktionen.
- **Verifizierte Mitglieder:** In freigegebenen Themenbereichen Beiträge veröffentlichen und antworten. Eigenes öffentliches Profil mit Anzeigename, Profilbild, Bio und Website bearbeiten. Eigene Beiträge und Antworten bearbeiten; eigene Beiträge samt Antworten löschen.
- **Administratorgruppe:** Zusätzlich Ober- und Unterthemen anlegen, bearbeiten, umhängen und löschen sowie Blogartikel veröffentlichen und alle Beiträge/Antworten bearbeiten oder löschen. Neue Bereiche erscheinen automatisch in der Navigation und in der Beitragsauswahl.

Vier Themenbereiche (Allgemein, IT & Homelab, 3D-Druck, Projekte & Builds) und drei Einstiegsartikel werden einmalig angelegt. Es gibt keine Standardkonten oder Standardpasswörter. `/forum`, `/forum/<bereich>`, `/blog`, `/users/<nutzername>` und `/posts/<id>` sind direkt aufrufbar und funktionieren auch nach Neuladen. Alle Schreibrechte werden im Backend geprüft.

## Oberthemen, Unterthemen und Schreibfreigabe

In der Forum-Übersicht können Administratoren über „Bearbeiten“ und „Löschen“ die Bereiche verwalten. Innerhalb eines Bereichs stehen „Bereich bearbeiten“, „Bereich löschen“ und „＋ Unterthema“ bereit. Der übergeordnete Bereich lässt sich sowohl beim Erstellen als auch beim Bearbeiten auswählen. Eigene Unterbereiche können nicht als Eltern ausgewählt werden; das Backend verhindert auch direkte oder indirekte Hierarchieschleifen.

Die Einstellung **„Beiträge und Antworten in diesem Bereich erlauben“** gilt jeweils für den ausgewählten Bereich, unabhängig von der Freigabe seiner Unterthemen. Beispiel:

- **Hardware**: Beiträge nicht erlaubt, dient als Übersicht.
- **Hardware / 3D-Druck**: Beiträge erlaubt, Mitglieder erstellen hier ihre Beiträge.
- **Hardware / Homelab**: Beiträge erlaubt.

Neue Oberthemen sind standardmäßig für neue Beiträge gesperrt, neue Unterthemen standardmäßig freigegeben. Bereits vorhandene Bereiche bleiben beim Update in ihrer bisherigen Schreibfreigabe erhalten; diese lässt sich anschließend gezielt ändern. Vorhandene Beiträge bleiben beim Sperren lesbar und durch ihre Autoren oder Administratoren bearbeitbar; neue Beiträge und Antworten werden auch bei direkten API-Aufrufen abgelehnt. Blogartikel sind unabhängig von der Forum-Schreibfreigabe redaktionell verwaltbar.

Name und Beschreibung eines Bereichs können geändert werden, ohne vorhandene Links zu ändern. Ein leerer Bereich kann nach Bestätigung gelöscht werden. Enthält er Beiträge oder Blogartikel, muss ein anderer, für Beiträge freigegebener Zielbereich ausgewählt werden: Die Inhalte einschließlich Antworten und Autoren werden in einer Transaktion erhalten und verschoben. Bereiche mit Unterthemen können erst nach dem Umhängen oder Entfernen ihrer Unterthemen gelöscht werden. Ein gelöschter Standardbereich wird bei einem Neustart nicht wieder angelegt.

## Öffentliche Nutzerprofile

Über den Nutzernamen bzw. Avatar in der Kopfzeile und an Beiträgen/Antworten ist das öffentliche Profil erreichbar. „Profil bearbeiten“ ist nur im eigenen, angemeldeten und verifizierten Konto verfügbar. Der Nutzername bleibt unverändert; Anzeigename, Bio (bis 1.000 Zeichen) und eine HTTP-/HTTPS-Website sind optional. E-Mail, Passworthash und Sitzungsdaten werden niemals im öffentlichen Profil ausgegeben.

Profilbilder können als PNG, JPEG oder WebP mit höchstens 1 MB und 4 Megapixeln hochgeladen und wieder entfernt werden. Das Backend decodiert das Bild, schneidet es quadratisch auf 256 × 256 Pixel zu und speichert neue PNG-Pixeldaten ohne Metadaten direkt in SQLite. SVG, HTML und ungültige Bilder werden abgelehnt. Datenbank-Backups enthalten damit auch die Profilbilder; ein zusätzliches Upload-Volume ist nicht nötig.

## Adminbereich und Tags

Verifizierte Administratoren erreichen über **Adminbereich** in der Navigation oder direkt unter `/admin` die Verwaltung:

- **Themenbereiche:** Ober-/Unterthemen, Elternbereiche, Schreibfreigaben, Bearbeiten und sicheres Löschen.
- **Beitragstags:** Tags wie „Offen“, „Gelöst“ oder Druckermodelle anlegen, umbenennen, einfärben und löschen. Die ersten beiden Tags werden einmalig angelegt. Autoren und Administratoren wählen beim Erstellen/Bearbeiten eines Beitrags bis zu zehn Tags aus. Andere Mitglieder dürfen fremde Zuordnungen nicht ändern.
- **Nutzertags:** Öffentliche Kennzeichnungen anlegen, bearbeiten und löschen. Diese Tags sind getrennt von Beitragstags und vergeben **keine** Administrator- oder Schreibrechte.
- **Mitglieder:** Nutzer suchen und bis zu zehn Nutzertags zuweisen oder entfernen. Die Tags erscheinen im öffentlichen Profil sowie beim Autor von Beiträgen und Antworten. E-Mail-Adressen oder Passwörter werden in dieser Liste nicht ausgegeben.

Beim Umbenennen eines Tags aktualisieren sich bestehende Zuordnungen automatisch. Beim Löschen werden nur der Tag und seine Zuordnungen entfernt; Beiträge, Antworten und Konten bleiben bestehen. Die Datenbank prüft alle Zuordnungen, und sämtliche Verwaltungsendpunkte sind auf verifizierte Administratoren beschränkt. Die anfänglichen Tags werden nach einer Löschung nicht bei jedem Neustart neu angelegt.

## E-Mail-Verifizierung per SMTP

Registrierung benötigt Nutzername, private E-Mail-Adresse und ein Passwort mit mindestens 10 Zeichen. Erst nach Bestätigung der Adresse ist eine Anmeldung mit E-Mail oder Nutzername möglich. Der Bestätigungslink ist 24 Stunden gültig, einmalig verwendbar und wird in der Datenbank ausschließlich gehasht gespeichert. Er wird als URL-Fragment ausgeliefert, nicht in HTTP-Zugriffsprotokolle geschrieben. Die Bestätigung erfordert einen bewussten Klick auf der Website.

Unter „E-Mail bestätigen / erneut senden“ kann mit den Zugangsdaten eine neue Mail angefordert werden (mindestens 60 Sekunden Abstand). Bisherige Konten ohne E-Mail ergänzen dort ihre Adresse. Bestehende Beiträge und Administratorrechte bleiben erhalten; alte Sitzungen werden beim Update einmalig widerrufen. Niemand erhält automatisch durch die erste Registrierung Administratorrechte.

**Ohne SMTP-Konfiguration werden keine neuen Konten freigeschaltet.** Es gibt keinen automatischen Verifizierungs-Bypass oder Mail-Token in API-Antworten/Logs. CAPTCHA/Bot-Schutz ist auf Wunsch nicht eingebaut. Begrenzungen für Anmeldeversuche und CSRF-Schutz bleiben bestehen.

## Konfiguration in Arcane

Diese Variablen im privaten Environment des Compose-Projekts eintragen. Das Passwort nicht in Git oder öffentliches YAML schreiben:

| Variable | Wert |
| --- | --- |
| `PUBLIC_URL` | `https://steckerrein.de` oder die tatsächliche öffentliche HTTPS-Adresse, ohne Pfad |
| `COOKIE_SECURE` | `1` für HTTPS |
| `SMTP_HOST` | `smtp.ionos.de` |
| `SMTP_PORT` | `465` (TLS ab Verbindungsbeginn); alternativ `587` (STARTTLS) |
| `SMTP_USER` | `noreply@agrosskopf.de` |
| `SMTP_PASSWORD` | SMTP-Passwort, gegebenenfalls App-Passwort |
| `MAIL_FROM` | `noreply@agrosskopf.de` |

IONOS-Server, Benutzername und Absender sind in der Compose-Datei vorbelegt. Für den Versand muss nur noch das echte Postfachpasswort unter `SMTP_PASSWORD` gesetzt werden. Das Postfach muss bei IONOS existieren und SMTP-Anmeldung erlauben.

TLS-Zertifikate werden immer geprüft; unverschlüsseltes SMTP wird nicht unterstützt. Absender und DNS (SPF/DKIM/DMARC) nach Vorgaben des Mailanbieters einrichten. Der Docker-Host muss den SMTP-Server auf dem gewählten Port erreichen können. Für eine tatsächliche Zustellprüfung ein eigenes Konto registrieren, den Link aus dem Postfach bestätigen und anschließend anmelden. Die Tests verwenden einen abgefangenen SMTP-Transport und belegen keine echte Zustellung.

Für Arcane ohne Git-Checkout:

```yaml
services:
  steckerrein:
    image: ghcr.io/alexgg05/steckerrein:latest
    restart: unless-stopped
    ports:
      - "8095:8095"
    environment:
      COOKIE_SECURE: "1"
      PUBLIC_URL: ${PUBLIC_URL:-https://steckerrein.de}
      SMTP_HOST: ${SMTP_HOST:-smtp.ionos.de}
      SMTP_PORT: ${SMTP_PORT:-465}
      SMTP_USER: ${SMTP_USER:-noreply@agrosskopf.de}
      SMTP_PASSWORD: ${SMTP_PASSWORD}
      MAIL_FROM: ${MAIL_FROM:-noreply@agrosskopf.de}
    volumes:
      - community-data:/data
    security_opt:
      - no-new-privileges:true
volumes:
  community-data:
```

Nach dem erfolgreichen GitHub-Actions-Build das neue Image pullen und den Container neu erstellen. Das vorhandene Volume beibehalten. HTTPS über Reverse Proxy/Cloudflare Tunnel bereitstellen; **alle Pfade inklusive `/api/`, `/forum`, `/blog` und `/posts/` auf den neuen Container-Port 8095 weiterleiten**, nicht auf einen alten statischen Nginx-Container. Host-Header beibehalten. Bei einer alten Oberfläche zusätzlich einen eventuell aktivierten Cloudflare-HTML/Asset-Cache leeren. Die Anwendung liefert HTML/JS/CSS mit `Cache-Control: no-store`; das Frontend verwendet versionierte Assets.

## Administrator freischalten

Eigenes Konto registrieren und E-Mail bestätigen, dann auf dem Docker-Host:

```sh
docker compose exec steckerrein python server.py --promote DEIN_NUTZERNAME
```

Anschließend neu anmelden. Im Forum erscheint „＋ Themenbereich“, im Blog „＋ Blogartikel“. Ohne Docker denselben Befehl mit `python3 server.py --promote DEIN_NUTZERNAME` und dem richtigen `DATABASE_PATH` verwenden.

## Entwicklung und Tests

```sh
cd /workspace/steckerrein
python3 -m pip install --requirement requirements.txt
python3 server.py
```

Port 8095, Datenbank `data/community.db` (ignoriert). `PORT`, `BIND` und `DATABASE_PATH` können überschrieben werden. HTML/CSS/JS werden nach Neuladen sichtbar; nach Backend-Änderungen Python neu starten. Für Mailfunktionen die obigen Variablen im Prozess setzen; `server.py` lädt `.env` nicht automatisch. Docker Compose lädt dagegen `.env` für die Variablenersetzung; eine Vorlage liegt in `.env.example`.

```sh
python3 -m unittest discover -s tests -v
node --check script.js
docker compose up -d --build
```

18 Integrationstests prüfen Registrierung, fehlende/abgelaufene/wiederverwendete Bestätigungen, erneuten Versand, SMTP-TLS, Kontenmigration, Sitzungen, Themenhierarchie, Schreibfreigaben, sichere Bereichslöschung, Rollen, Änderungen, Antworten, öffentliche Profile, validierte Profilbilder, Beitrags-/Nutzertags, Adminrechte und CSRF. Die Tests nutzen temporäre Datenbanken und versenden keine echten E-Mails. Zusätzlich wurden die vollständigen Gäste-, Mitglieder- und Administratorabläufe im Desktop- und Mobilbrowser geprüft.

## Daten und Betrieb

`community-data` enthält die dauerhafte Datenbank. Niemals beim normalen Update `docker compose down -v` verwenden. Vor Updates ein Backup außerhalb des Volumes sichern. Beispiel für eine konsistente SQLite-Sicherung:

```sh
docker compose exec steckerrein python -c "import sqlite3; src=sqlite3.connect('/data/community.db'); dst=sqlite3.connect('/data/backup.db'); src.backup(dst); dst.close(); src.close()"
```

Die Datei danach außerhalb des Volumes aufbewahren; Wiederherstellung separat prüfen. Der Python-HTTP-Server ist für eine kleine Community hinter dem Reverse Proxy vorgesehen. Client-IP-Rate-Limits zusätzlich am vertrauenswürdigen Proxy setzen; die Anwendung vertraut keinen frei gesetzten Forwarded-IP-Headern.

Noch nicht enthalten: Passwort-Wiederherstellung, Dateianhänge an Beiträgen oder Beitragsbenachrichtigungen. Beiträge verwenden Klartext mit Absätzen, kein HTML. Die unveränderte Datenschutzerklärung muss vor öffentlichem Betrieb auf Benutzerkonten, E-Mail-Verifizierung, Sitzungen, öffentliche Profile/Profilbilder und öffentliche Beiträge geprüft werden.

## Docker-Build in der verwalteten Cloud-Umgebung

Beim netzwerkgestützten Build die bereitgestellte Proxy-CA als BuildKit-Secret übergeben, ohne TLS-Prüfung abzuschalten:

```sh
docker build --secret id=proxy_ca,src="$CODEX_PROXY_CERT" -t ghcr.io/alexgg05/steckerrein:latest .
docker compose up -d --no-build
```

Normale Docker-Hosts und GitHub Actions verwenden ihren regulären CA-Speicher. Die optionale CA wird ausschließlich beim Installationsschritt gemountet und nicht ins Image kopiert.
