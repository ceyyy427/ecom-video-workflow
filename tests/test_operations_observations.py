import pytest


def source(records, raw=b"content_id,metric_date,views,likes\nclip-1,2026-10-01,0,\n"):
    from ecom_video.connectors.xhs_import import add_account, freeze_source

    account = add_account(records, "xiaohongshu", "工程账户", "owner")
    return freeze_source(
        records, account["id"], raw, "data.csv", "AUTOMATED FIXTURE authorized export"
    )


def contract(**updates):
    return {
        "counting": "daily",
        "timezone": "Asia/Shanghai",
        "observed_at": "2026-10-02T08:00:00+08:00",
        "metric_definitions": {"views": "平台报表播放次数", "likes": "平台报表点赞次数"},
        **updates,
    }


def test_zero_missing_and_frozen_source_survive_external_changes(tmp_path):
    from ecom_video.db import Store
    from ecom_video.operations.observations import freeze_observations, import_csv
    from ecom_video.operations.records import Records

    r = Records(tmp_path, Store(tmp_path / "workflow.db"))
    s = source(r)
    b = import_csv(r, s["id"], contract())
    assert b["payload"]["rows"][0]["values"]["views"] == "0"
    assert b["payload"]["rows"][0]["values"]["likes"] is None
    f = freeze_observations(r, [b["id"]])
    assert f["payload"]["totals"]["views"] == "0"
    assert f["payload"]["totals"]["likes"] is None
    assert f["payload"]["causal_inference"] is False
    assert f["payload"]["rows"][0]["binding_status"] == "unlinked"
    # Original external report is never consulted again; managed-source tampering is detected.
    assert r.get(f["id"])["basis"] == f["basis"]
    (tmp_path / s["files"][0]["path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        r.get(f["id"])


def test_cumulative_and_mixed_contracts_are_never_summed_as_daily(tmp_path):
    from ecom_video.db import Store
    from ecom_video.operations.observations import freeze_observations, import_csv
    from ecom_video.operations.records import Records

    r = Records(tmp_path, Store(tmp_path / "workflow.db"))
    s = source(r)
    a = import_csv(r, s["id"], contract())
    b = import_csv(r, s["id"], contract(counting="cumulative"))
    f = freeze_observations(r, [b["id"]])
    assert f["payload"]["totals"] is None and f["payload"]["aggregation_allowed"] is False
    for ids in ([a["id"], b["id"]], [a["id"], a["id"]]):
        with pytest.raises(ValueError):
            freeze_observations(r, ids)
    with pytest.raises(ValueError):
        import_csv(r, s["id"], contract(timezone="UTC"))
    with pytest.raises(ValueError):
        import_csv(r, s["id"], contract(currency="CNY"))


@pytest.mark.parametrize("value", ["-1", "1e4", "NaN", "1.2", "=HYPERLINK(x)"])
def test_bad_counts_rejected_without_partial_batch(tmp_path, value):
    from ecom_video.db import Store
    from ecom_video.operations.observations import import_csv
    from ecom_video.operations.records import Records

    r = Records(tmp_path, Store(tmp_path / "workflow.db"))
    s = source(r, f"content_id,metric_date,views\nclip-1,2026-10-01,{value}\n".encode())
    with pytest.raises(ValueError):
        import_csv(r, s["id"], contract())
    assert r.listing("observation_batch") == []
