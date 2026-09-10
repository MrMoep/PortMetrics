"""Paperless NGX REST client (documents + custom fields)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

# Legacy custom field names (used when no UI mapping is stored).
CUSTOM_FIELD_NAMES = (
    "wp_typ",
    "isin",
    "wkn",
    "stueckzahl",
    "kurs",
    "gebuehr",
)

ProgressCallback = Callable[[dict[str, Any]], None]


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

    def _client(self, *, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=timeout if timeout is not None else self._timeout,
            transport=self._transport,
            headers={"Authorization": f"Token {self.token}"},
        )

    def list_custom_fields(self) -> list[dict[str, Any]]:
        return self._list_named_collection("/api/custom_fields/")

    def list_tags(self) -> list[dict[str, Any]]:
        return self._list_named_collection("/api/tags/")

    def list_document_types(self) -> list[dict[str, Any]]:
        return self._list_named_collection("/api/document_types/")

    def _list_named_collection(self, path: str) -> list[dict[str, Any]]:
        with self._client() as client:
            response = client.get(path, params={"page_size": 100})
            if response.status_code >= 400:
                raise PaperlessError(
                    f"Paperless {path} failed ({response.status_code}): {response.text}"
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
        tag_ids: list[int] | None = None,
        document_type_ids: list[int] | None = None,
        paginate: bool = False,
        request_timeout: float | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> list[dict[str, Any]]:
        """List documents newest-first.

        Filter logic (applied server-side where possible, then merged):
        - multiple tag_ids → OR
        - multiple document_type_ids → OR
        - tags AND document types → intersection of both dimensions

        ``paginate=False`` returns at most one page (``page_size``, default 100).
        ``paginate=True`` follows ``next`` until exhausted.
        """
        type_ids = list(document_type_ids or [])
        # One pass without type filter when none selected.
        type_passes: list[int | None] = type_ids if type_ids else [None]

        by_id: dict[int, dict[str, Any]] = {}
        pages_scanned = 0
        for type_id in type_passes:
            for page_docs in self._iter_document_pages(
                page_size=page_size,
                tag=tag,
                tag_ids=tag_ids,
                document_type_id=type_id,
                paginate=paginate,
                request_timeout=request_timeout,
            ):
                pages_scanned += 1
                for doc in page_docs:
                    doc_id = doc.get("id")
                    if doc_id is None:
                        continue
                    by_id[int(doc_id)] = doc
                if on_progress:
                    on_progress(
                        {
                            "event": "page",
                            "pages_scanned": pages_scanned,
                            "docs_seen": len(by_id),
                            "document_type_id": type_id,
                        }
                    )
                if not paginate:
                    break

        docs = sorted(
            by_id.values(),
            key=lambda d: str(d.get("created") or ""),
            reverse=True,
        )
        if not paginate:
            return docs[:page_size]
        return docs

    def _iter_document_pages(
        self,
        *,
        page_size: int,
        tag: str | None,
        tag_ids: list[int] | None,
        document_type_id: int | None,
        paginate: bool,
        request_timeout: float | None,
    ) -> Iterator[list[dict[str, Any]]]:
        params: list[tuple[str, str | int]] = [
            ("page_size", page_size),
            ("ordering", "-created"),
        ]
        if tag_ids:
            for tid in tag_ids:
                params.append(("tags__id", int(tid)))
        elif tag:
            params.append(("tags__name__iexact", tag))
        if document_type_id is not None:
            params.append(("document_type__id", int(document_type_id)))

        with self._client(timeout=request_timeout) as client:
            path: str | None = "/api/documents/"
            query: list[tuple[str, str | int]] | None = params
            while path:
                response = client.get(path, params=query)
                if response.status_code >= 400:
                    raise PaperlessError(
                        f"Paperless documents failed ({response.status_code}): {response.text}"
                    )
                payload = response.json()
                if isinstance(payload, list):
                    yield payload
                    break
                yield payload.get("results") or []
                if not paginate:
                    break
                next_url = payload.get("next")
                if not next_url:
                    break
                path, query = self._split_next(next_url)

    def _split_next(self, next_url: str) -> tuple[str, list[tuple[str, str]]]:
        parsed = urlparse(next_url)
        if parsed.scheme and parsed.netloc:
            # Absolute URL from Paperless — use path + query relative to base_url host.
            path = parsed.path or "/api/documents/"
            query = [(k, v) for k, values in parse_qs(parsed.query).items() for v in values]
            return path, query
        # Relative next link
        if "?" in next_url:
            path, qs = next_url.split("?", 1)
            query = [(k, v) for k, values in parse_qs(qs).items() for v in values]
            return path, query
        return next_url, []

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
