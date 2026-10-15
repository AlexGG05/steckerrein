# steckerrein.de – Domainverkauf

Deutschsprachige Verkaufswebsite mit Kontaktformular (E-Mail, Telefonnummer, Preisvorschlag und Nachricht).

## Docker Compose über Arcane

Die Website wird automatisch über GitHub Actions als Docker-Image in der GitHub Container Registry (GHCR) gebaut.

### Docker Compose für Arcane

Diesen Inhalt in Arcane als Compose-Projekt verwenden (kein Dockerfile oder Git-Checkout erforderlich):

```yaml
services:
  steckerrein:
    image: ghcr.io/alexgg05/steckerrein:latest
    container_name: steckerrein
    restart: unless-stopped
    ports:
      - "8095:80"
    security_opt:
      - no-new-privileges:true
```

**Vor dem ersten Deployment:** Unter [GitHub Actions](https://github.com/AlexGG05/steckerrein/actions) prüfen, dass der Workflow „Build and publish Docker image“ erfolgreich gelaufen ist. Das Paket unter GitHub Packages gegebenenfalls auf **Public** stellen, damit Arcane es ohne Zugangsdaten herunterladen kann. Bei privaten Paketen ist eine GHCR-Anmeldung auf dem Docker-Host erforderlich.

Nach dem Deployment ist die Website unter `http://SERVER-IP:8095` erreichbar. Für Updates in Arcane das Image erneut pullen und den Container neu erstellen.

Für `steckerrein.de` den Cloudflare Tunnel oder Reverse Proxy auf `http://DOCKER-HOST:8095` weiterleiten und HTTPS aktivieren.

## Kontaktformular

Das Formular übermittelt die Eingaben an den externen Dienst **FormSubmit**, der eine E-Mail an `info@agrosskopf.de` sendet. Bei der ersten Einsendung muss die Empfängeradresse per E-Mail bestätigt werden. Anschließend eine echte Testanfrage durchführen. Es ist kein SMTP im Docker-Container erforderlich. Bei FormSubmit-Störungen kann die Zustellung fehlschlagen.

## Vor Veröffentlichung

- `impressum.html`: Betreibername, ladungsfähige Anschrift und gesetzlich erforderliche Angaben ergänzen.
- `datenschutz.html`: Vollständige Datenschutzhinweise einschließlich Hosting und FormSubmit ergänzen.
- FormSubmit aktivieren und E-Mail-Zustellung prüfen.
- HTTPS und DNS korrekt einrichten.

## Projektdateien

`index.html`, `style.css`, `script.js`, `impressum.html`, `datenschutz.html`, `Dockerfile`, `nginx.conf`, `compose.yaml`.
