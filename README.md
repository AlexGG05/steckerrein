# steckerrein.de — IT, 3D-Druck & Community

Responsive Community mit Forum, Blog und SQLite. Python 3.12+ genügt; keine pip-/npm-Abhängigkeiten. Impressum und Datenschutz bleiben bytegenau erhalten.

## Aufbau und Berechtigungen

- **Besucher:** Themenbereiche, Beiträge, Blogartikel und Antworten öffentlich lesen und durchsuchen. Keine Schreib- oder Bearbeitungsfunktionen.
- **Verifizierte Mitglieder:** Unter vorhandenen Themenbereichen Beiträge veröffentlichen und antworten. Eigene Beiträge und Antworten bearbeiten; eigene Beiträge samt Antworten löschen.
- **Administratorgruppe:** Zusätzlich Themenbereiche anlegen, Blogartikel veröffentlichen und alle Beiträge/Antworten bearbeiten oder löschen. Neue Bereiche erscheinen automatisch in der Navigation und in der Beitragsauswahl.

Vier Themenbereiche (Allgemein, IT & Homelab, 3D-Druck, Projekte & Builds) und drei Einstiegsartikel werden einmalig angelegt. Es gibt keine Standardkonten oder Standardpasswörter. `/forum`, `/forum/<bereich>`, `/blog` und `/posts/<id>` sind direkt aufrufbar und funktionieren auch nach Neuladen. Alle Schreibrechte werden im Backend geprüft.

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
python3 server.py
```

Port 8095, Datenbank `data/community.db` (ignoriert). `PORT`, `BIND` und `DATABASE_PATH` können überschrieben werden. HTML/CSS/JS werden nach Neuladen sichtbar; nach Backend-Änderungen Python neu starten. Für Mailfunktionen die obigen Variablen im Prozess setzen; `server.py` lädt `.env` nicht automatisch. Docker Compose lädt dagegen `.env` für die Variablenersetzung; eine Vorlage liegt in `.env.example`.

```sh
python3 -m unittest discover -s tests -v
node --check script.js
docker compose up -d --build
```

12 Integrationstests prüfen Registrierung, fehlende/abgelaufene/wiederverwendete Bestätigungen, erneuten Versand, SMTP-TLS, Kontenmigration, Sitzungen, Themenbereiche, Rollen, Änderungen, Antworten und CSRF. Die Tests nutzen temporäre Datenbanken und versenden keine echten E-Mails. Zusätzlich wurden die vollständigen Gäste-, Mitglieder- und Administratorabläufe im Desktop- und Mobilbrowser geprüft.

## Daten und Betrieb

`community-data` enthält die dauerhafte Datenbank. Niemals beim normalen Update `docker compose down -v` verwenden. Vor Updates ein Backup außerhalb des Volumes sichern. Beispiel für eine konsistente SQLite-Sicherung:

```sh
docker compose exec steckerrein python -c "import sqlite3; src=sqlite3.connect('/data/community.db'); dst=sqlite3.connect('/data/backup.db'); src.backup(dst); dst.close(); src.close()"
```

Die Datei danach außerhalb des Volumes aufbewahren; Wiederherstellung separat prüfen. Der Python-HTTP-Server ist für eine kleine Community hinter dem Reverse Proxy vorgesehen. Client-IP-Rate-Limits zusätzlich am vertrauenswürdigen Proxy setzen; die Anwendung vertraut keinen frei gesetzten Forwarded-IP-Headern.

Noch nicht enthalten: Passwort-Wiederherstellung, Dateiuploads oder Beitragsbenachrichtigungen. Beiträge verwenden Klartext mit Absätzen, kein HTML. Die unveränderte Datenschutzerklärung muss vor öffentlichem Betrieb auf Benutzerkonten, E-Mail-Verifizierung, Sitzungen und öffentliche Beiträge geprüft werden.
