# Entwicklung

## Branch-Strategie

```
feature/*  ──PR──►  dev  ──PR──►  main
                      │              │
                   CI: Tests      CI: Tests
                   kein Image     + Image-Build (GHCR)
```

| Branch | Zweck |
|--------|-------|
| `main` | Produktiv / Release. Jeder Push baut und publiziert das Docker-Image. |
| `dev` | Entwicklungssammler. Integration aller Features. **Kein** Image-Build. |
| `feature/…` | Kurze Feature-Branches. PR **nur** gegen `dev`. |

### Regeln

1. Nie direkt auf `main` committen (außer Hotfix nach Absprache).
2. Jedes Feature: eigener Branch → PR nach `dev`.
3. PR nach `dev` braucht grüne CI (Tests + Lint).
4. Release: PR `dev` → `main`; danach baut CI das Image.
5. **Testabdeckung:** Neue Logik inkl. Tests; bestehende Tests bei Änderungen anpassen.

## Lokal testen — ja

Die App ist klein genug, um **ohne Image-Build** lokal zu laufen:

```powershell
cd api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
uvicorn portmetrics.main:app --reload --port 8080
```

Optional mit Compose (baut lokal, publiziert nichts):

```powershell
docker compose up --build
```

### Zwei Datenbanken (empfohlen)

Auf deiner PostgreSQL-18-Instanz (Unraid):

| DB | Verwendung | Env |
|----|------------|-----|
| `portmetrics` | Produktiv | `DATABASE_URL` |
| `portmetrics_test` | Tests / lokale Dev | `TEST_DATABASE_URL` bzw. lokal `DATABASE_URL` |

`.env` (nie committen) für lokale Dev → **Test-DB**:

```env
APP_ENV=development
DATABASE_URL=postgresql://user:pass@HOST:5432/portmetrics_test
TEST_DATABASE_URL=postgresql://user:pass@HOST:5432/portmetrics_test
```

Produktiv (Unraid Container / `.env` auf dem Server) → **Prod-DB**:

```env
APP_ENV=production
DATABASE_URL=postgresql://user:pass@HOST:5432/portmetrics
```

Pytest nutzt bevorzugt `TEST_DATABASE_URL`, sonst `DATABASE_URL`. So kann die Produktiv-DB nicht versehentlich von Unit-/Integrationstests beschrieben werden.

## CI-Workflows

| Workflow | Trigger | Tut |
|----------|---------|-----|
| **CI** (`.github/workflows/ci.yml`) | PR nach `dev`/`main`, Push auf `dev` | Lint + Pytest (+ Coverage) |
| **Release Image** (`.github/workflows/release-image.yml`) | Push auf `main` | Docker-Image → `ghcr.io/<owner>/portmetrics` |

## Image-Tags (nach Merge auf `main`)

- `ghcr.io/<owner>/portmetrics:latest`
- `ghcr.io/<owner>/portmetrics:<git-sha>`
- `ghcr.io/<owner>/portmetrics:<semver>` — wenn ein Tag `v*` gepusht wird
