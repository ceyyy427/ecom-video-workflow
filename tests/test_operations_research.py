import pytest


def test_market_sample_prices_stay_separate_by_currency_and_unknown_is_visible(tmp_path):
    from ecom_video.db import Store
    from ecom_video.operations.records import Records
    from ecom_video.operations.research import analyze_market

    r = Records(tmp_path, Store(tmp_path / "workflow.db"))
    raw = b"sku,product_name,price,currency,sampled_at,source\na,Jacket,100,CNY,2026-10-01,customer-export-row1\nb,Jacket,20,USD,2026-10-01,customer-export-row2\nc,Jacket,,CNY,2026-10-01,customer-export-row3\n"
    result = analyze_market(r, raw, "customer authorized samples; not full market", "douyin")
    p = result["payload"]
    assert (
        p["price_groups"]["CNY"]["median"] == "100" and p["price_groups"]["USD"]["median"] == "20"
    )
    assert p["missing_price_rows"] == 1 and p["sample_quality"] == "limited"
    assert p["market_size"] is None
    with pytest.raises(ValueError):
        analyze_market(r, raw, "", "douyin")


def test_margin_requires_complete_current_currency_qualified_costs():
    from ecom_video.operations.research import gross_margin

    values = {
        "sale_price": "100",
        "cost": "40",
        "shipping": "5",
        "payment_fee": "1",
        "other_cost": "2",
        "platform_rate": "0.05",
        "currency": "CNY",
        "rate_effective_from": "2026-10-01",
        "rate_effective_until": "2026-10-31",
        "as_of": "2026-10-28",
    }
    result = gross_margin(values)
    assert result["profit"] == "47.00" and result["margin_ratio"] == "0.470000"
    for change in (
        {"cost": None},
        {"currency": ""},
        {"as_of": "2026-11-01"},
        {"platform_rate": "5"},
    ):
        assert gross_margin({**values, **change})["available"] is False


def test_strategy_is_invalidated_when_current_confirmed_facts_change(tmp_path):
    from test_customer import approve, client, picture, project

    from ecom_video.operations.records import Records
    from ecom_video.operations.research import create_strategy, strategy_state

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    r = Records(tmp_path, c.app.state.store)
    s = create_strategy(r, p["id"], p["product"]["revision"], "通勤人群", "克制", None)
    assert strategy_state(r, s["id"])["current"] is True
    c.post(
        f"/api/products/{p['id']}/documents",
        data={"revision": p["product"]["revision"]},
        files={"file": ("new.txt", "新资料候选".encode(), "text/plain")},
    )
    assert strategy_state(r, s["id"])["current"] is False
