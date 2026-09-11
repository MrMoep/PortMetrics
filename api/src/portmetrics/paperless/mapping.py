"""Semantic Paperless custom-field roles and persisted settings."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from portmetrics.config import settings
from portmetrics.db.models import AppSetting
from portmetrics.paperless.client import PaperlessClient, PaperlessError

PAPERLESS_SETTINGS_KEY = "paperless"

# PortMetrics roles → legacy Paperless field names (backward compatible default).
DEFAULT_ROLE_TO_NAME: dict[str, str] = {
    "type": "wp_typ",
    "isin": "isin",
    "wkn": "wkn",
    "quantity": "stueckzahl",
    "unit_price": "kurs",
    "fee": "gebuehr",
}

# Legacy-only names still accepted when no UI mapping is stored / in raw payloads.
LEGACY_EXTRA_NAMES: dict[str, str] = {
    "symbol": "symbol",
    "trade_date": "handelsdatum",
    "currency": "waehrung",
    "import_status": "gf_import_status",
    "activity_id": "gf_activity_id",
}

FIELD_ROLE_META: tuple[dict[str, Any], ...] = (
    {
        "role": "type",
        "required": True,
        "label": "Typ (BUY/SELL/DIVIDEND/FEE/INTEREST/OTHER)",
        "hint": "OTHER landet im Staging, ist aber nicht importierbar.",
    },
    {
        "role": "isin",
        "required": True,
        "label": "ISIN",
        "hint": "Primärer Wertpapier-Schlüssel; Ghostfolio-Symbol = ISIN.",
    },
    {
        "role": "wkn",
        "required": False,
        "label": "WKN (optional)",
        "hint": "Nur Audit/Anzeige; nicht für Ghostfolio-Import nötig.",
    },
    {
        "role": "quantity",
        "required": True,
        "label": "Stückzahl / Nennwert",
        "hint": "Bei FEE/INTEREST ohne Stück → intern 1.",
    },
    {
        "role": "unit_price",
        "required": True,
        "label": "Kurs (Stückkurs)",
        "hint": "Monetary-Feld; Währung wird aus dem Wert gelesen (z.B. EUR152.34).",
    },
    {
        "role": "fee",
        "required": False,
        "label": "Entgelte / Gebühr (optional)",
        "hint": "Bei BUY/SELL Kosten; bei DIVIDEND/INTEREST Steuerabzüge. Default 0.",
    },
)

FIELD_ROLES: tuple[str, ...] = tuple(item["role"] for item in FIELD_ROLE_META)
REQUIRED_ROLES: tuple[str, ...] = tuple(
    item["role"] for item in FIELD_ROLE_META if item["required"]
)


def _normalize_public_url(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().rstrip("/")
    return text or None


def _normalize_id_name_list(value: Any) -> list[dict[str, Any]]:
    """Persist [{id, name}, ...] for tags / document types (ID is source of truth)."""
    if not value:
        return []
    if not isinstance(value, list):
        raise ValueError("expected a list of {id, name} objects")
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each filter entry must be an object with id and name")
        raw_id = item.get("id")
        if raw_id is None or str(raw_id).strip() == "":
            continue
        entry_id = int(raw_id)
        if entry_id in seen:
            continue
        seen.add(entry_id)
        name = str(item.get("name") or "").strip() or f"#{entry_id}"
        out.append({"id": entry_id, "name": name})
    return out


def empty_paperless_settings() -> dict[str, Any]:
    return {
        "field_map": {},  # role → paperless field id
        "tag": settings.paperless_tag,  # legacy name-only filter (fallback)
        "sync_tags": [],  # [{id, name}, ...] — OR within, AND with types
        "sync_document_types": [],  # [{id, name}, ...]
        "ghostfolio_default_account_id": settings.ghostfolio_default_account_id,
        "ghostfolio_data_source": settings.ghostfolio_data_source,
        # Browser-reachable Paperless UI base (npm/local); API URL often stays Docker-internal.
        "public_url": None,
    }


def get_paperless_settings(session: Session) -> dict[str, Any]:
    row = session.get(AppSetting, PAPERLESS_SETTINGS_KEY)
    base = empty_paperless_settings()
    if row is None or not isinstance(row.value, dict):
        return base
    merged = dict(base)
    merged.update(row.value)
    field_map = merged.get("field_map") or {}
    if not isinstance(field_map, dict):
        field_map = {}
    # Normalize ids to int; drop removed/unknown roles (symbol, currency, …).
    merged["field_map"] = {
        str(role): int(field_id)
        for role, field_id in field_map.items()
        if role in FIELD_ROLES and field_id is not None and str(field_id).strip() != ""
    }
    tag = merged.get("tag")
    merged["tag"] = (str(tag).strip() or None) if tag is not None else None
    try:
        merged["sync_tags"] = _normalize_id_name_list(merged.get("sync_tags"))
        merged["sync_document_types"] = _normalize_id_name_list(
            merged.get("sync_document_types")
        )
    except ValueError:
        merged["sync_tags"] = []
        merged["sync_document_types"] = []
    account = merged.get("ghostfolio_default_account_id")
    merged["ghostfolio_default_account_id"] = (
        str(account).strip() or None if account is not None else None
    )
    source = merged.get("ghostfolio_data_source") or settings.ghostfolio_data_source
    merged["ghostfolio_data_source"] = str(source).strip() or settings.ghostfolio_data_source
    merged["public_url"] = _normalize_public_url(merged.get("public_url"))
    return merged


def save_paperless_settings(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_paperless_settings(session)
    field_map_in = payload.get("field_map", current["field_map"])
    if not isinstance(field_map_in, dict):
        raise ValueError("field_map must be an object")

    field_map: dict[str, int] = {}
    for role, field_id in field_map_in.items():
        role_key = str(role)
        if role_key not in FIELD_ROLES:
            raise ValueError(f"Unknown field role: {role_key}")
        if field_id is None or field_id == "":
            continue
        field_map[role_key] = int(field_id)

    tag = payload.get("tag", current["tag"])
    sync_tags = _normalize_id_name_list(payload.get("sync_tags", current["sync_tags"]))
    sync_document_types = _normalize_id_name_list(
        payload.get("sync_document_types", current["sync_document_types"])
    )
    # Prefer ID-based tag filter; clear legacy name when sync_tags are set.
    if sync_tags:
        tag = None
    account = payload.get(
        "ghostfolio_default_account_id",
        current["ghostfolio_default_account_id"],
    )
    data_source = payload.get("ghostfolio_data_source", current["ghostfolio_data_source"])
    public_url = payload.get("public_url", current["public_url"])

    value = {
        "field_map": field_map,
        "tag": (str(tag).strip() or None) if tag is not None else None,
        "sync_tags": sync_tags,
        "sync_document_types": sync_document_types,
        "ghostfolio_default_account_id": (
            str(account).strip() or None if account is not None else None
        ),
        "ghostfolio_data_source": (
            str(data_source).strip() or settings.ghostfolio_data_source
            if data_source is not None
            else settings.ghostfolio_data_source
        ),
        "public_url": _normalize_public_url(public_url),
    }
    row = session.get(AppSetting, PAPERLESS_SETTINGS_KEY)
    if row is None:
        row = AppSetting(key=PAPERLESS_SETTINGS_KEY, value=value)
        session.add(row)
    else:
        row.value = value
    session.flush()
    return get_paperless_settings(session)


def sync_filter_ids(cfg: dict[str, Any]) -> tuple[list[int], list[int]]:
    """Return (tag_ids, document_type_ids) from settings."""
    tag_ids = [int(item["id"]) for item in (cfg.get("sync_tags") or []) if item.get("id")]
    type_ids = [
        int(item["id"]) for item in (cfg.get("sync_document_types") or []) if item.get("id")
    ]
    return tag_ids, type_ids


def has_sync_filters(cfg: dict[str, Any]) -> bool:
    tag_ids, type_ids = sync_filter_ids(cfg)
    if tag_ids or type_ids:
        return True
    return bool(cfg.get("tag"))


def resolve_role_field_map(
    session: Session,
    client: PaperlessClient,
) -> dict[str, int]:
    """Return role → Paperless field id; fall back to legacy names if unset."""
    stored = get_paperless_settings(session)["field_map"]
    if stored:
        return dict(stored)

    name_to_id = client.custom_field_map()
    resolved: dict[str, int] = {}
    for role, name in DEFAULT_ROLE_TO_NAME.items():
        field_id = name_to_id.get(name)
        if field_id is not None:
            resolved[role] = field_id
    return resolved


def select_option_map(field: dict[str, Any]) -> dict[str, str]:
    """Build option-id → label for a Paperless select custom field."""
    if str(field.get("data_type") or "").lower() != "select":
        return {}
    extra = field.get("extra_data") if isinstance(field.get("extra_data"), dict) else {}
    options = (
        (extra or {}).get("select_options")
        or field.get("select_options")
        or []
    )
    out: dict[str, str] = {}
    if not isinstance(options, list):
        return out
    for opt in options:
        if isinstance(opt, str):
            label = opt.strip()
            if label:
                out[label] = label
            continue
        if not isinstance(opt, dict):
            continue
        label_raw = opt.get("label") or opt.get("name") or opt.get("value")
        if label_raw is None or str(label_raw).strip() == "":
            continue
        label = str(label_raw).strip()
        oid = opt.get("id")
        if oid is not None and str(oid).strip() != "":
            out[str(oid).strip()] = label
        out[label] = label
    return out


def select_option_maps_by_field_id(fields: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    """field_id → {option_id_or_label: label} for all select custom fields."""
    maps: dict[int, dict[str, str]] = {}
    for field in fields:
        field_id = field.get("id")
        if field_id is None:
            continue
        option_map = select_option_map(field)
        if option_map:
            maps[int(field_id)] = option_map
    return maps


def resolve_select_value(value: Any, id_to_label: dict[str, str] | None) -> Any:
    """Replace select option ids with labels when a map is available."""
    if not id_to_label:
        return value
    if isinstance(value, dict):
        for key in ("label", "value", "name"):
            raw = value.get(key)
            if raw is not None and str(raw).strip():
                text = str(raw).strip()
                return id_to_label.get(text, text)
        oid = value.get("id")
        if oid is not None and str(oid).strip() != "":
            key = str(oid).strip()
            return id_to_label.get(key, key)
        return value
    if value is None or value == "":
        return value
    key = str(value).strip()
    return id_to_label.get(key, value)


def extract_fields_by_roles(
    document: dict[str, Any],
    role_to_field_id: dict[str, int],
    *,
    select_maps: dict[int, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Map document custom_fields → {role: value}."""
    id_to_role = {field_id: role for role, field_id in role_to_field_id.items()}
    result: dict[str, Any] = {}
    for item in document.get("custom_fields") or []:
        field_id = item.get("field")
        if field_id is None:
            continue
        fid = int(field_id)
        role = id_to_role.get(fid)
        if role:
            value = item.get("value")
            if select_maps:
                value = resolve_select_value(value, select_maps.get(fid))
            result[role] = value
    return result


def ensure_required_roles(role_to_field_id: dict[str, int]) -> None:
    missing = [role for role in REQUIRED_ROLES if role not in role_to_field_id]
    if missing:
        raise PaperlessError(
            "Paperless field mapping incomplete (roles): " + ", ".join(missing)
        )


def list_settings_rows(session: Session) -> list[AppSetting]:
    return list(session.scalars(select(AppSetting)).all())
