import json
from decimal import Decimal

import pytest
from test_experiments import action, finish, selected, style
from test_experiments import env as env
from test_review_snapshots import command, ingest

from ecom_video.db import Conflict
from ecom_video.reporting import Reporting
from ecom_video.review_snapshots import Reviews


def prepared(env):
    service, _, _, _ = env
    e = selected(env)
    e = service.apply(e["id"], action(e, "apply-loop"))
    e = style(service, e)
    finish(service.root, service.store, e["result_job_id"])
    return service.await_data(e["id"], action(e, "wait-loop"))


def next_review(
    service,
    e,
    *,
    known=False,
    day="2026-10-02",
    clicks="20",
    impressions="100",
    bind=True,
    account_id=None,
):
    aid = account_id or e["proposal"]["account_id"]
    reports = Reporting(service.root, service.store)
    if bind:
        reports.bind(aid, "456", e["result_job_id"], "AUTOMATED FIXTURE")
    if known:
        reports.ingest(
            aid,
            day,
            day,
            [
                {
                    "date": day,
                    "material_id": "456",
                    "spend": "10",
                    "impressions": impressions,
                    "clicks": clicks,
                    "orders": "1",
                    "revenue": "30",
                    "video_views": "100",
                    "completed_views": "20",
                }
            ],
            (day + clicks + impressions).encode(),
            "qianchuan_api",
            "fixture",
            {"attribution_window": "7d_click"},
        )
    else:
        ingest(
            reports, aid, f"{day},456,10,{impressions},{clicks},1,30,100,20\n", start=day, end=day
        )
    return Reviews(service.root, service.store).create(
        command(aid, "next-" + clicks + impressions + day, start=day, end=day)
    )


def test_unknown_window_keeps_raw_values_but_no_comparable_delta(env):
    service, _, _, _ = env
    e = prepared(env)
    nxt = next_review(service, e)
    result = service.evaluate(
        e["id"], action(e, "eval-1", next_review_id=nxt["review_id"], new_material_id="456")
    )
    evaluation = result["evaluations"][-1]
    assert evaluation["status"] == "insufficient_evidence"
    assert "attribution_window_unknown" in evaluation["reasons"]
    assert evaluation["baseline"]["value"] == "0.1" and evaluation["next"]["value"] == "0.2"
    assert evaluation["absolute_difference"] is None and evaluation["winner"] is None
    assert result["status"] == "awaiting_data"


def known_baseline(env, clicks="10"):
    service, body, _, _ = env
    reports = Reporting(service.root, service.store)
    aid = (
        body["account_id"]
        if "account_id" in body
        else service.context(body["review_id"], "123")["account_id"]
    )
    reports.ingest(
        aid,
        "2026-10-01",
        "2026-10-01",
        [
            {
                "date": "2026-10-01",
                "material_id": "123",
                "spend": "10",
                "impressions": "100",
                "clicks": clicks,
                "orders": "1",
                "revenue": "20",
                "video_views": "100",
                "completed_views": "10",
            }
        ],
        ("known fixture baseline " + clicks).encode(),
        "qianchuan_api",
        "fixture",
        {"attribution_window": "7d_click"},
    )
    review = Reviews(service.root, service.store).create(
        command(aid, "known-base", end="2026-10-01")
    )
    body["review_id"] = review["review_id"]
    return review


def test_descriptive_difference_has_both_hashes_and_reimport_never_rewrites_old(env):
    baseline = known_baseline(env)
    service, _, _, _ = env
    e = prepared(env)
    nxt = next_review(service, e, known=True)
    cmd = action(e, "eval-1", next_review_id=nxt["review_id"], new_material_id="456")
    first = service.evaluate(e["id"], cmd)
    old = json.dumps(first["evaluations"][0], sort_keys=True)
    ev = first["evaluations"][0]
    assert ev["status"] == "descriptive_available" and ev["absolute_difference"] == "0.100000"
    assert ev["relative_difference"] == "1.000000" and ev["causal_inference"] is False
    assert ev["baseline"]["snapshot_hash"] == baseline["snapshot_hash"]
    assert ev["next"]["snapshot_hash"] == nxt["snapshot_hash"]
    newer = next_review(service, e, known=True, clicks="15")
    assert service.evaluate(e["id"], cmd) == first
    second = service.evaluate(
        e["id"], action(first, "eval-2", next_review_id=newer["review_id"], new_material_id="456")
    )
    assert len(second["evaluations"]) == 2
    assert json.dumps(second["evaluations"][0], sort_keys=True) == old
    assert Decimal(second["evaluations"][1]["absolute_difference"]) == Decimal("0.05")


@pytest.mark.parametrize(
    "change,reason",
    [
        ("missing", "target_metric_missing_or_zero_denominator"),
        ("overlap", "next_window_not_after_baseline"),
        ("small", "next_impressions_unknown_or_below_policy"),
        ("unbound", "variant_binding_missing_or_mismatched"),
    ],
)
def test_insufficient_evidence_reasons_are_explicit(env, change, reason):
    known_baseline(env)
    service, _, _, _ = env
    e = prepared(env)
    nxt = next_review(
        service,
        e,
        known=True,
        clicks="" if change == "missing" else "20",
        day="2026-10-01" if change == "overlap" else "2026-10-02",
        impressions="10" if change == "small" else "100",
        bind=change != "unbound",
    )
    result = service.evaluate(
        e["id"], action(e, "eval-fault", next_review_id=nxt["review_id"], new_material_id="456")
    )
    assert reason in result["evaluations"][0]["reasons"]
    assert result["evaluations"][0]["absolute_difference"] is None


def test_cross_account_and_unreviewed_output_cannot_be_evaluated(env):
    from ecom_video.distribution import Distribution

    service, _, _, _ = env
    e = selected(env)
    e = service.apply(e["id"], action(e, "apply-pending"))
    with pytest.raises(Conflict, match="审核"):
        service.await_data(e["id"], action(e, "wait-bad"))
    e = style(service, e)
    finish(service.root, service.store, e["result_job_id"])
    other = Distribution(service.root, service.store).add_account(
        "fixture other", "qianchuan", "999"
    )["id"]
    nxt = next_review(service, e, account_id=other)
    with pytest.raises(Conflict, match="账户"):
        service.evaluate(
            e["id"],
            action(e, "cross-account", next_review_id=nxt["review_id"], new_material_id="456"),
        )


def test_unverified_variant_values_are_not_used_as_new_product_performance(env):
    known_baseline(env)
    service, _, _, _ = env
    e = prepared(env)
    nxt = next_review(service, e, known=True, bind=False)
    result = service.evaluate(
        e["id"],
        action(e, "unrelated-values", next_review_id=nxt["review_id"], new_material_id="456"),
    )
    ev = result["evaluations"][0]
    assert ev["next"]["value"] is None
    assert "variant_binding_missing_or_mismatched" in ev["reasons"]


def test_zero_baseline_preserves_absolute_delta_without_relative_ratio(env):
    known_baseline(env, clicks="0")
    service, _, _, _ = env
    e = prepared(env)
    nxt = next_review(service, e, known=True)
    result = service.evaluate(
        e["id"], action(e, "zero-base", next_review_id=nxt["review_id"], new_material_id="456")
    )
    ev = result["evaluations"][0]
    assert ev["status"] == "descriptive_available" and ev["absolute_difference"] == "0.200000"
    assert (
        ev["relative_difference"] is None
        and ev["relative_difference_status"] == "unknown_zero_baseline"
    )


@pytest.mark.parametrize(
    "context,reason",
    [
        ({"currency": "USD", "attribution_window": "7d_click"}, "incompatible_source_context"),
        ({"attribution_window": "1d_view"}, "attribution_window_mismatch"),
    ],
)
def test_known_incompatible_source_context_never_computes_delta(env, context, reason):
    known_baseline(env)
    service, _, _, _ = env
    e = prepared(env)
    next_review(service, e, known=True)
    aid = e["proposal"]["account_id"]
    Reporting(service.root, service.store).ingest(
        aid,
        "2026-10-02",
        "2026-10-02",
        [
            {
                "date": "2026-10-02",
                "material_id": "456",
                "spend": "10",
                "impressions": "100",
                "clicks": "20",
                "orders": "1",
                "revenue": "20",
                "video_views": "100",
                "completed_views": "20",
            }
        ],
        b"fixture incompatible context",
        "qianchuan_api",
        "fixture",
        context,
    )
    nxt = Reviews(service.root, service.store).create(
        command(aid, "context-conflict", start="2026-10-02", end="2026-10-02")
    )
    result = service.evaluate(
        e["id"], action(e, "context-eval", next_review_id=nxt["review_id"], new_material_id="456")
    )
    ev = result["evaluations"][0]
    assert ev["status"] == "insufficient_evidence" and reason in ev["reasons"]
    assert ev["absolute_difference"] is None
