"""Paperless NGX REST client (documents + custom fields)."""

from __future__ import annotations

from typing import Any

import httpx

# Legacy custom field names (used when no UI mapping is stored).
CUSTOM_FIELD_NAMES = (
    "wp_typ",
    "isin",
    "symbol",
    "stueckzahl",
    "kurs",
    "gebuehr",
    "handelsdatum",
    "waehrung",
    "gf_import_status",
    "gf_activity_id",
)


class PaperlessError(RuntimeError):
    pass


class PaperlessClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._timeout = timeout
        self._transport = transport
        self._field_id_by_name: dict[str, int] | None = None

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self._timeout,
            transport=self._transport,
            headers={"Authorization": f"Token {self.token}"},
        )

    def list_custom_fields(self) -> list[dict[str, Any]]:
        with self._client() as client:
            response = client.get("/api/custom_fields/", params={"page_size": 100})
            if response.status_code >= 400:
                raise PaperlessError(
                    f"Paperless custom_fields failed ({response.status_code}): {response.text}"
                )
            payload = response.json()
            if isinstance(payload, list):
                return payload
            return payload.get("results") or []

    def custom_field_map(self) -> dict[str, int]:
        if self._field_id_by_name is not None:
            return self._field_id_by_name
        mapping: dict[str, int] = {}
        for field in self.list_custom_fields():
            name = str(field.get("name") or "")
            field_id = field.get("id")
            if name and field_id is not None:
                mapping[name] = int(field_id)
        self._field_id_by_name = mapping
        return mapping

    def list_documents(
        self,
        *,
        page_size: int = 100,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"page_size": page_size, "ordering": "-created"}
        if tag:
            params["tags__name__iexact"] = tag
        with self._client() as client:
            response = client.get("/api/documents/", params=params)
            if response.status_code >= 400:
                raise PaperlessError(
                    f"Paperless documents failed ({response.status_code}): {response.text}"
                )
            payload = response.json()
            return payload.get("results") or []

    def get_document(self, document_id: int) -> dict[str, Any]:
        with self._client() as client:
            response = client.get(f"/api/documents/{document_id}/")
            if response.status_code >= 400:
                raise PaperlessError(
                    f"Paperless document {document_id} failed "
                    f"({response.status_code}): {response.text}"
                )
            return response.json()

    def patch_document_custom_fields(
        self,
        document_id: int,
        values_by_name: dict[str, Any] | None = None,
        *,
        values_by_field_id: dict[int, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge custom field values onto an existing document (by name and/or id)."""
        document = self.get_document(document_id)
        existing = {
            int(item["field"]): item.get("value")
            for item in (document.get("custom_fields") or [])
            if item.get("field") is not None
        }
        if values_by_field_id:
            for field_id, value in values_by_field_id.items():
                existing[int(field_id)] = value
        if values_by_name:
            field_map = self.custom_field_map()
            for name, value in values_by_name.items():
                field_id = field_map.get(name)
                if field_id is None:
                    raise PaperlessError(f"Paperless custom field '{name}' is not defined")
                existing[field_id] = value
        payload = {
            "custom_fields": [
                {"field": field_id, "value": value} for field_id, value in existing.items()
            ]
        }
        with self._client() as client:
            response = client.patch(f"/api/documents/{document_id}/", json=payload)
            if response.status_code >= 400:
                raise PaperlessError(
                    f"Paperless patch document {document_id} failed "
                    f"({response.status_code}): {response.text}"
                )
            return response.json()


def extract_custom_fields(
    document: dict[str, Any],
    field_id_by_name: dict[str, int],
) -> dict[str, Any]:
    """Map Paperless custom_fields list → {name: value} (legacy helper)."""
    id_to_name = {field_id: name for name, field_id in field_id_by_name.items()}
    result: dict[str, Any] = {}
    for item in document.get("custom_fields") or []:
        field_id = item.get("field")
        name = id_to_name.get(int(field_id)) if field_id is not None else None
        if name:
            result[name] = item.get("value")
    return result
