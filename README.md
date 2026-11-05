# steckerrein.de — IT, 3D-Druck & Community

Responsive Community mit Forum, redaktionellem Blog und SQLite-Speicherung. Python 3.12+ genügt; es gibt keine externen Python- oder Frontend-Abhängigkeiten. Alle Gestaltungselemente und Assets werden lokal ausgeliefert.

## Lokal entwickeln

```sh
cd /workspace/steckerrein
python3 server.py
```

Der Server lauscht auf Port 8095. Änderungen an HTML/CSS/JS werden nach Neuladen sichtbar; nach Python-Änderungen den Prozess neu starten. Standarddatenbank: `data/community.db` (ignoriert). `PORT`, `BIND` und `DATABASE_PATH` können über Umgebungsvariablen gesetzt werden. Drei einführende Blogartikel werden einmalig angelegt. Mitglieds- und Diskussionszahlen stammen aus der Datenbank; es gibt keine erfundenen Benutzerkonten.

## Funktionen

- Registrierung mit öffentlichem Nutzernamen, Anmeldung, Abmeldung und siebentägige Sitzungen.
- Forum mit Themenwelten, Suche, Seitennavigation und Antworten.
- Blogartikel und Kommentare; Veröffentlichungsrechte nur für freigeschaltete Redaktionskonten.
- Eigene Beiträge sowie als Redaktion sämtliche Beiträge inklusive Antworten löschen.
- Passwörter mit scrypt und individuellem Salt, gehashte Sitzungstokens, HttpOnly-/SameSite-Cookies, CSRF-Schutz, serverseitige Eingabevalidierung und lokale Begrenzung von Anmeldeversuchen.

Es gibt derzeit keine E-Mail-Verifikation, Passwort-zurücksetzen-Funktion, Dateiuploads oder Mailbenachrichtigungen. Nutzer müssen ihre Zugangsdaten aufbewahren. Der Blog nutzt Klartext mit Absätzen, kein HTML. Antworten und Themen sind öffentlich.

## Redaktion freischalten

Zuerst über die Website ein persönliches Konto registrieren, anschließend auf dem Server gezielt freischalten:

```sh
python3 server.py --promote DEIN_NUTZERNAME
```

Bei Docker Compose:

```sh
docker compose exec steckerrein python server.py --promote DEIN_NUTZERNAME
```

Danach erscheint unter „Neues Thema“ die Auswahl für einen Blogartikel. Niemand erhält automatisch durch die erste Registrierung Administratorrechte. Keine Standardpasswörter.

## Docker

```sh
docker compose up -d --build
```

Die Website wird auf Port 8095 bereitgestellt. Das benannte Volume `community-data` enthält Benutzerkonten, Beiträge und Sitzungen und muss bei Updates erhalten bleiben. `docker compose down -v` würde diese Daten löschen. Zum Sichern möglichst die SQLite-Backup-API verwenden, beispielsweise im Container:

```sh
docker compose exec steckerrein python -c "import sqlite3; src=sqlite3.connect('/data/community.db'); dst=sqlite3.connect('/data/backup.db'); src.backup(dst); dst.close(); src.close()"
```

Die Sicherungsdatei anschließend außerhalb des Volumes aufbewahren und Wiederherstellung separat testen.

GitHub Actions baut und veröffentlicht weiterhin `ghcr.io/alexgg05/steckerrein:latest`. Für Arcane kann ohne Checkout folgende Compose-Konfiguration verwendet werden, nachdem das neue Image veröffentlicht wurde:

```yaml
services:
  steckerrein:
    image: ghcr.io/alexgg05/steckerrein:latest
    restart: unless-stopped
    ports:
      - "8095:8095"
    environment:
      COOKIE_SECURE: "1"
    volumes:
      - community-data:/data
    security_opt:
      - no-new-privileges:true
volumes:
  community-data:
```

Für den öffentlichen Betrieb HTTPS über einen Reverse Proxy bzw. Cloudflare Tunnel verwenden, den Host-Header beibehalten und `COOKIE_SECURE=1` setzen. Das Beispiel für Arcane setzt HTTPS voraus. Der Proxy verweist wie bisher auf Port 8095 des Docker-Hosts; der interne Containerport ist nun ebenfalls 8095. Der eingebaute HTTP-Server ist für eine kleine Community hinter dem Proxy vorgesehen. Dort zusätzlich Request-Limits und Rate-Limiting konfigurieren. Der Server benötigt keinen externen Formulardienst und keine Zugangsschlüssel.

## Prüfungen

```sh
python3 -m unittest discover -s tests -v
node --check script.js
```

Die Integrationstests verwenden eine temporäre Datenbank und prüfen HTTP-Auslieferung, Registrierung, Sitzungen, Rollen, Beiträge, Antworten, Suche, Löschung, Eingaben und CSRF-Schutz. Keine Produktionsdaten werden verändert.

## Rechtstexte

`impressum.html` und `datenschutz.html` sind aus dem bisherigen Repository bytegenau erhalten. Das frühere Verkaufsformular und die FormSubmit-Anbindung wurden entfernt. Die vorhandene Datenschutzerklärung wurde auf ausdrücklichen Wunsch nicht angepasst; vor öffentlichem Betrieb muss geprüft werden, ob sie die neue Verarbeitung von Benutzerkonten, Sitzungen und öffentlichen Beiträgen abdeckt.
