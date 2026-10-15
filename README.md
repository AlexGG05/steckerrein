# steckerrein.de – Domainverkauf

Deutschsprachige Verkaufswebsite mit Kontaktformular (E-Mail, Telefonnummer, Preisvorschlag und Nachricht).

## Docker Compose über Arcane

Das Projekt enthält einen Dockerfile und eine fertige `compose.yaml`.

**Wichtig:** Die Compose-Datei nutzt `build: .`. In Arcane muss deshalb der komplette GitHub-Repository-Inhalt als Projektquelle bzw. Build-Kontext verfügbar sein. Nur YAML in ein leeres Compose-Projekt einzufügen reicht nicht, da sonst Dockerfile und Website-Dateien fehlen.

### Inhalt für docker-compose.yaml

```yaml
services:
  steckerrein:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: steckerrein
    restart: unless-stopped
    ports:
      - "8095:80"
    security_opt:
      - no-new-privileges:true
```

### Bereitstellen

Auf dem Docker-Host:

```bash
git clone https://github.com/AlexGG05/steckerrein.git
cd steckerrein
docker compose up -d --build
```

Danach erreichbar über `http://SERVER-IP:8095`.

**Arcane:** Wenn deine Arcane-Version Git-basierte Projekte mit Build-Kontext unterstützt, das Repository `https://github.com/AlexGG05/steckerrein.git` als Projektquelle einrichten und die mitgelieferte Compose-Datei verwenden. Alternativ das Repository auf dem Docker-Host klonen, mit Docker Compose starten und in Arcane verwalten.

Für Updates: `git pull && docker compose up -d --build`.

### Domain

Im Cloudflare Tunnel oder Reverse Proxy `steckerrein.de` auf `http://DOCKER-HOST:8095` weiterleiten und HTTPS aktivieren. Port 8095 bei Bedarf ändern.

## Kontaktformular

Das Formular übermittelt die Eingaben an den externen Dienst **FormSubmit**, der eine E-Mail an `info@agrosskopf.de` sendet. Bei der ersten Einsendung muss die Empfängeradresse per E-Mail bestätigt werden. Anschließend eine echte Testanfrage durchführen. Es ist kein SMTP im Docker-Container erforderlich. Bei FormSubmit-Störungen kann die Zustellung fehlschlagen.

## Vor Veröffentlichung

- `impressum.html`: Betreibername, ladungsfähige Anschrift und gesetzlich erforderliche Angaben ergänzen.
- `datenschutz.html`: Vollständige Datenschutzhinweise einschließlich Hosting und FormSubmit ergänzen.
- FormSubmit aktivieren und E-Mail-Zustellung prüfen.
- HTTPS und DNS korrekt einrichten.

## Projektdateien

`index.html`, `style.css`, `script.js`, `impressum.html`, `datenschutz.html`, `Dockerfile`, `nginx.conf`, `compose.yaml`.
