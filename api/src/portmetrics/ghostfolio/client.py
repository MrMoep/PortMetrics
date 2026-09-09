from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field


class GhostfolioError(RuntimeError):
    pass


class GhostfolioActivity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    # Ghostfolio API: accountId is optional (Prisma Order.accountId String?)
    account_id: str | None = Field(default=None, alias="accountId")
    currency: str
    date: datetime
    fee: Decimal = Decimal("0")
    quantity: Decimal
    type: str
    unit_price: Decimal = Field(alias="unitPrice")
    comment: str | None = None
    symbol: str
    isin: str | None = None
    data_source: str | None = Field(default=None, alias="dataSource")

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> GhostfolioActivity:
        profile = raw.get("SymbolProfile") or raw.get("symbolProfile") or {}
        payload = {
            **raw,
            "symbol": profile.get("symbol") or raw.get("symbol"),
            "isin": profile.get("isin") or raw.get("isin"),
            "dataSource": profile.get("dataSource") or raw.get("dataSource"),
        }
        if not payload.get("symbol"):
            raise GhostfolioError(f"Activity {raw.get('id')} missing symbol")
        return cls.model_validate(payload)


class GhostfolioSymbolData(BaseModel):
    """Symbol quote + optional daily history from GET /api/v1/symbol/:ds/:symbol."""

    model_config = ConfigDict(extra="ignore")

    data_source: str
    symbol: str
    currency: str
    market_price: Decimal | None = None
    historical: list[tuple[date, Decimal]] = Field(default_factory=list)


class GhostfolioClient:
    """Thin Ghostfolio REST client (JWT via security access token)."""

    def __init__(
        self,
        base_url: str,
        access_token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self._timeout = timeout
        self._transport = transport
        self._jwt: str | None = None

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self._timeout,
            transport=self._transport,
        )

    def authenticate(self) -> str:
        with self._client() as client:
            response = client.post(
                "/api/v1/auth/anonymous",
                json={"accessToken": self.access_token},
            )
            if response.status_code >= 400:
                raise GhostfolioError(
                    f"Ghostfolio auth failed ({response.status_code}): {response.text}"
                )
            data = response.json()
            token = data.get("authToken") or data.get("token")
            if not token:
                raise GhostfolioError("Ghostfolio auth response missing authToken")
            self._jwt = token
            return token

    def _auth_headers(self) -> dict[str, str]:
        if not self._jwt:
            self.authenticate()
        assert self._jwt is not None
        return {"Authorization": f"Bearer {self._jwt}"}

    def list_activities(self) -> list[GhostfolioActivity]:
        with self._client() as client:
            headers = self._auth_headers()
            # Prefer /activities; fall back to deprecated /order.
            response = client.get("/api/v1/activities", headers=headers)
            if response.status_code == 404:
                response = client.get("/api/v1/order", headers=headers)
            if response.status_code >= 400:
                raise GhostfolioError(
                    f"Ghostfolio activities failed ({response.status_code}): {response.text}"
                )
            payload = response.json()
            raw_activities = payload.get("activities") or payload.get("orders") or []
            if isinstance(payload, list):
                raw_activities = payload
            return [GhostfolioActivity.from_api(item) for item in raw_activities]

    def import_activities(self, activities: list[dict[str, Any]]) -> dict[str, Any]:
        with self._client() as client:
            headers = self._auth_headers()
            response = client.post(
                "/api/v1/import",
                headers=headers,
                json={"activities": activities},
            )
            if response.status_code >= 400:
                raise GhostfolioError(
                    f"Ghostfolio import failed ({response.status_code}): {response.text}"
                )
            if not response.content:
                return {"activities": []}
            return response.json()

    def get_symbol(
        self,
        data_source: str,
        symbol: str,
        *,
        include_historical_data: int | None = None,
    ) -> GhostfolioSymbolData:
        """Fetch quote (+ optional daily history) for one Ghostfolio asset profile."""
        params: dict[str, int] = {}
        if include_historical_data is not None and include_historical_data > 0:
            params["includeHistoricalData"] = include_historical_data
        with self._client() as client:
            headers = self._auth_headers()
            response = client.get(
                f"/api/v1/symbol/{data_source}/{symbol}",
                headers=headers,
                params=params or None,
            )
            if response.status_code >= 400:
                raise GhostfolioError(
                    f"Ghostfolio symbol {data_source}/{symbol} failed "
                    f"({response.status_code}): {response.text}"
                )
            payload = response.json()
            historical: list[tuple[date, Decimal]] = []
            for point in payload.get("historicalData") or []:
                raw_date = point.get("date")
                raw_value = point.get("value")
                if raw_date is None or raw_value is None:
                    continue
                if isinstance(raw_date, str):
                    day = date.fromisoformat(raw_date[:10])
                elif isinstance(raw_date, datetime):
                    day = raw_date.date()
                else:
                    continue
                historical.append((day, Decimal(str(raw_value))))
            market_raw = payload.get("marketPrice")
            return GhostfolioSymbolData(
                data_source=payload.get("dataSource") or data_source,
                symbol=payload.get("symbol") or symbol,
                currency=(payload.get("currency") or "EUR").upper()[:3],
                market_price=Decimal(str(market_raw)) if market_raw is not None else None,
                historical=historical,
            )


def trade_date_of(activity: GhostfolioActivity) -> date:
    return activity.date.date()
