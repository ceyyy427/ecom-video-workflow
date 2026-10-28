import pytest
from test_operations_media_pack import video_job
from test_operations_observations import contract


def test_manual_hypothesis_creates_one_pending_project_without_inheriting_any_approval(tmp_path):
    from ecom_video.connectors.xhs_import import add_account, freeze_source
    from ecom_video.customer import Customers
    from ecom_video.db import Store
    from ecom_video.operations.iterations import compare_iteration, hypotheses, select_hypothesis
    from ecom_video.operations.media_pack import publication_pack, register_content
    from ecom_video.operations.observations import freeze_observations, import_csv
    from ecom_video.operations.records import Records

    r = Records(tmp_path, Store(tmp_path / "workflow.db"))
    jid, _ = video_job(r)
    a = add_account(r, "xiaohongshu", "工程账户", "owner")
    p = publication_pack(r, jid, "xiaohongshu", "外套", "待核对")
    register_content(r, p["id"], a["id"], "clip-1", "AUTOMATED FIXTURE", True)
    s = freeze_source(
        r,
        a["id"],
        b"content_id,metric_date,views\nclip-1,2026-10-01,100\n",
        "sample.csv",
        "AUTOMATED FIXTURE",
    )
    b = import_csv(r, s["id"], contract())
    snap = freeze_observations(r, [b["id"]])
    h = hypotheses(r, snap["id"], jid)
    with pytest.raises(ValueError):
        select_hypothesis(r, h["id"], "opening", "", False)
    chosen = select_hypothesis(
        r, h["id"], "opening", "AUTOMATED FIXTURE manual-selection simulation", True
    )
    repeated = select_hypothesis(
        r, h["id"], "opening", "AUTOMATED FIXTURE manual-selection simulation", True
    )
    assert chosen == repeated
    new = Customers(tmp_path, r.store).get(chosen["payload"]["project_id"])
    assert new["product"]["status"] == "collecting" and new["job"] is None
    assert new["product"]["script_approvals"] == [] and new["product"]["fact_reviews"] == []
    result = compare_iteration(r, chosen["id"], snap["id"])
    assert not result["payload"]["comparable"] and result["payload"]["causal_inference"] is False
    assert result["payload"]["delta"] is None

    # Separate test fixture for a completed next version; never a real publishing receipt.
    import json

    child, _ = video_job(r)
    with r.store.transaction() as db:
        db.execute(
            "UPDATE jobs SET script=?,snapshot=?,provenance=? WHERE id=?",
            (
                "拉近看细节",
                json.dumps({"script": "拉近看细节"}),
                json.dumps({"product_id": new["id"]}),
                child,
            ),
        )
    next_pack = publication_pack(r, child, "xiaohongshu", "下一版细节", "AUTOMATED FIXTURE")
    register_content(r, next_pack["id"], a["id"], "clip-2", "AUTOMATED FIXTURE", True)
    next_source = freeze_source(
        r,
        a["id"],
        b"content_id,metric_date,views\nclip-2,2026-10-03,140\n",
        "next.csv",
        "AUTOMATED FIXTURE",
    )
    next_batch = import_csv(r, next_source["id"], contract(observed_at="2026-10-04T08:00:00+08:00"))
    later = freeze_observations(r, [next_batch["id"]])
    compared = compare_iteration(r, chosen["id"], later["id"])["payload"]
    assert compared["comparable"] and compared["delta"]["views"] == "40"
    assert compared["actual_changes"]["script_changed"] is True
    assert compared["causal_inference"] is False
    # A parent whose linked product no longer matches cannot create another variant.
    with r.store.transaction() as db:
        db.execute(
            "UPDATE jobs SET provenance=? WHERE id=?",
            (json.dumps({"product_id": new["id"], "fact_review": {"id": "old-review"}}), jid),
        )
    with pytest.raises(ValueError, match="父片"):
        select_hypothesis(r, h["id"], "rhythm", "AUTOMATED FIXTURE", True)
