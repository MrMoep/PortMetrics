from portmetrics.settings.overview import (
    DEFAULT_KPI_IDS,
    empty_overview_settings,
    normalize_overview_settings,
)


def test_normalize_defaults_and_filters_unknown() -> None:
    assert normalize_overview_settings(None) == empty_overview_settings()
    assert normalize_overview_settings({"kpi_ids": []})["kpi_ids"] == list(DEFAULT_KPI_IDS)

    saved = normalize_overview_settings(
        {
            "kpi_ids": ["tax_allowance_remaining", "bogus", "nav", "nav"],
            "hero_id": "tax_allowance_remaining",
        }
    )
    assert saved["kpi_ids"] == ["tax_allowance_remaining", "nav"]
    assert saved["hero_id"] == "tax_allowance_remaining"


def test_normalize_hero_fallback() -> None:
    saved = normalize_overview_settings({"kpi_ids": ["invested", "cagr"], "hero_id": "nav"})
    assert saved["hero_id"] == "invested"
