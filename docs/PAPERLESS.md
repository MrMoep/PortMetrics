# Paperless-Integration



Paperless NGX ist **Belegarchiv + Staging**, nicht das Ledger. Extrahierte Felder landen in `staging_imports`, werden gepr?ft und erst dann nach Ghostfolio importiert.



Teil von **PortMetrics 0.2.0**. Verwandt: [API.md](API.md), [DATA_MODEL.md](DATA_MODEL.md).



## Custom Fields



Felder werden **in Paperless** angelegt (beliebige Namen). In PortMetrics unter **Einstellungen** den Rollen zuordnen (gespeicherte Feld-**IDs**). Pflicht/Optional ist in der UI gekennzeichnet.



| Rolle | Pflicht | Beschreibung |

|-------|---------|--------------|

| `type` | ja | `BUY`, `SELL`, `DIVIDEND`, `FEE`, `INTEREST`, `OTHER` |

| `isin` | ja | ISIN ? zugleich Ghostfolio-Symbol |

| `wkn` | nein | WKN ? wird bei ISIN+WKN in `asset_identifiers` persistiert |

| `quantity` | ja* | St?ckzahl / Nennwert |

| `unit_price` | ja | St?ckkurs (Monetary, z.?B. `EUR152.34`) |

| `fee` | nein | Entgelte bzw. Steuerabz?ge (Default 0) |



\* Bei `FEE` / `INTEREST` / `OTHER` ohne St?ckzahl setzt PortMetrics intern `quantity=1`.



**Nicht mehr als Custom-Field-Rollen:**



| Thema | Verhalten |

|-------|-----------|

| Handelsdatum | Paperless-**Dokumentdatum** (`created`) |

| W?hrung | aus Monetary-Wert von Kurs/Entgelte |

| Symbol / Ticker | Confirm nutzt `preferred_symbol` aus Kennungs-Tabelle (`asset_identifiers`) |

| Import-Status / Activity-ID | lokal in Staging / `document_links` (kein Paperless-Write-back) |



`OTHER` erscheint in der Staging-Queue, Confirm ist gesperrt, bis der Typ in Paperless korrigiert und erneut gesynct wurde.



Ohne gespeichertes Mapping f?llt PortMetrics auf Legacy-Namen zur?ck (`wp_typ`, `isin`, `wkn`, `stueckzahl`, `kurs`, `gebuehr`).



Optional: Sync-Filter in den Einstellungen ? Tags und/oder Dokumententypen (ID + Name). Legacy: Env `PAPERLESS_TAG` als Fallback, bis ID-Filter gesetzt sind.

**Filterlogik:** mehrere Tags = ODER, mehrere Dokumententypen = ODER; Tags und Typen zusammen = UND.

**Teilsync** (Scheduler + UI): neueste ?100 Docs, Filter optional. **Full Sync** (UI): alle Seiten; ohne Filter Warnung. Webhook filtert nicht nach Tag/Typ, pr?ft aber Pflichtfelder.



## Workflow



```

PDF ? P-GPT / Felder

  ? Webhook (document updated) oder Sync/Scheduler

  ? staging_imports

  ? Review (Confirm/Reject) im Dashboard

  ? Ghostfolio Import ? document_links

  ? automatischer Mirror (Activities/Preise/FIFO/Metrics; best-effort)

```



### Webhook (empfohlen)



1. `PAPERLESS_WEBHOOK_SECRET` in PortMetrics setzen.

2. In Paperless einen Workflow anlegen:

   - Trigger: **Document updated** (nicht nur added ? Custom Fields oft erst sp?ter)

   - Filter: optional Tag (z.?B. `wertpapier`)

   - Action: Webhook `POST` auf `https://<portmetrics>/api/webhooks/paperless`

   - Header: `X-PortMetrics-Secret: <secret>` (oder Query `?secret=`)

   - Body JSON z.?B. `{ "doc_url": "{doc_url}" }` oder `{ "document_id": "<id>" }`

3. Confirm/Reject weiterhin nur im Staging-Tab.



Unvollst?ndige Felder werden ?bersprungen (`action=skipped`); manueller Sync bleibt als Fallback.



### Scheduler (optional Catch-up)



`PAPERLESS_SYNC_INTERVAL_MINUTES>0` aktiviert einen periodischen **Teilsync** (Hybrid zu Webhook). `0` = aus.



## API



| Methode | Pfad | Zweck |

|---------|------|-------|

| `GET` | `/api/staging` | Offene Review-Queue (`pending` + `error`) |

| `GET` | `/api/staging?status=pending` | Nur pending |

| `GET` | `/api/staging?status=all` | Alle inkl. imported/rejected |

| `POST` | `/api/staging/sync?mode=partial` | Teilsync <=100 (JSON) |

| `POST` | `/api/staging/sync?mode=full` | Full Sync, NDJSON-Progress |

| `POST` | `/api/staging/match-activities` | Manuell: Staging an bestehende Activities |

| `POST` | `/api/webhooks/paperless` | Auto-Ingest eines Docs |

| `POST` | `/api/staging/{id}/confirm` | Import nach Ghostfolio + stiller Mirror (`OTHER` -> 400) |

| `POST` | `/api/staging/{id}/reject` | Ablehnen |

| `GET` | `/api/settings/paperless` | Mapping + Filter + GF-Defaults |

| `PUT` | `/api/settings/paperless` | Mapping / sync_tags / sync_document_types |

| `GET` | `/api/settings/paperless/custom-fields` | Felder aus Paperless |

| `GET` | `/api/settings/paperless/tags` | Tags (id, name) |

| `GET` | `/api/settings/paperless/document-types` | Dokumententypen (id, name) |

| `POST` | `/api/settings/paperless/test` | Verbindungstest |



## Env



```env

PAPERLESS_URL=http://paperless:8000

PAPERLESS_TOKEN=

PAPERLESS_TAG=

PAPERLESS_WEBHOOK_SECRET=

PAPERLESS_SYNC_INTERVAL_MINUTES=0

GHOSTFOLIO_DEFAULT_ACCOUNT_ID=

GHOSTFOLIO_DATA_SOURCE=YAHOO

```



`PAPERLESS_URL` / `PAPERLESS_TOKEN` / `PAPERLESS_WEBHOOK_SECRET` bleiben Env. Tag, Field-Map, öffentliche Web-URL (`public_url` für Doc-Links; Fallback `PAPERLESS_URL`) und Ghostfolio-Defaults können in der UI überschrieben und in `app_settings` persistiert werden. Dokumente mit ISIN+WKN füllen `asset_identifiers` (WKN nur wenn Tabellen-Zelle leer); preferred Symbol wird manuell bzw. per Staging-Vorschlag gesetzt.


