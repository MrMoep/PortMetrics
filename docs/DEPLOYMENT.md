# Deployment (Unraid / Docker)

## Image

Nach Release auf `main`:

| Tag | Bedeutung |
|-----|-----------|
| `ghcr.io/mrmoep/portmetrics:latest` | aktueller `main` |
| `ghcr.io/mrmoep/portmetrics:0.2.0` | Release 0.2.0 |
| `ghcr.io/mrmoep/portmetrics:0.1.0` | Release 0.1.0 |
| `ghcr.io/mrmoep/portmetrics:<sha>` | kurzer Git-SHA |

## Compose (Beispiel)

```yaml
services:
  portmetrics:
    image: ghcr.io/mrmoep/portmetrics:0.2.0
    ports:
      - "8080:8080"
    env_file: .env
    volumes:
      - /mnt/user/appdata/portmetrics/logs:/app/logs
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped
```

Lokal bauen (ohne Registry): `docker compose up --build` im Repo-Root.

## Voraussetzung

1. PostgreSQL 18 mit DBs `portmetrics` (+ optional `portmetrics_test`)
2. Schema-Migrationen:

```powershell
cd api
$env:APP_ENV="production"
$env:DATABASE_URL="postgresql+psycopg://user:pass@HOST:5432/portmetrics"
alembic upgrade head
```

(Stand 0.2.0: inkl. `0002_app_settings`.)

3. `.env` aus [`.env.example`](../.env.example) — mind. `DATABASE_URL`, optional Ghostfolio/Paperless.
4. Optional Reverse Proxy (z. B. Nginx Proxy Manager): Host auf Container-Port `8080` zeigen.
   Für Cross-Origin-Zugriff die Browser-Origin setzen, z. B.
   `CORS_ORIGINS=https://portmetric.mrcarott.de` (mehrere Origins komma-getrennt).

### Wichtige Env-Variablen (Unraid)

| Variable | Pflicht | Hinweis |
|----------|---------|---------|
| `APP_ENV` | ja | `production` |
| `DATABASE_URL` | ja | Postgres auf dem Host |
| `GHOSTFOLIO_URL` / `GHOSTFOLIO_ACCESS_TOKEN` | für Sync | |
| `PAPERLESS_URL` / `PAPERLESS_TOKEN` | optional | Belege |
| `PAPERLESS_WEBHOOK_SECRET` | für Auto-Ingest | Header `X-PortMetrics-Secret` |
| `PAPERLESS_SYNC_INTERVAL_MINUTES` | nein | `0` = aus; z. B. `15` Catch-up |
| `PAPERLESS_TAG` | nein | oder in UI unter Einstellungen |
| `CORS_ORIGINS` | bei Reverse Proxy | Browser-Origin |

Field-Mapping und Ghostfolio-Defaults: nach Start unter **Einstellungen** (nicht nur Env).

## Erststart

1. Container starten, `/health` prüfen (`version` sollte `0.2.0` sein)
2. Dashboard öffnen (`http://host:8080/` oder die NPM-URL)
3. **Sync Ghostfolio** → FIFO/Metrics laufen mit
4. Optional Paperless: Felder unter **Einstellungen** zuordnen, Webhook laut [PAPERLESS.md](PAPERLESS.md)

## Absicherung

Nicht öffentlich exponieren. Reverse Proxy + Auth (Authentik / Basic Auth) vor Port 8080.
