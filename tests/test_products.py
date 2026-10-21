import json
import sqlite3
from pathlib import Path

import pytest

from ecom_video.db import Conflict, Store
from ecom_video.generation import compose, validate_scenes
from ecom_video.products import Products
from ecom_video.sources import parse_document


def seed(tmp_path):
    store = Store(tmp_path / "workflow.db")
    products = Products(store)
    p = products.create("随行杯")
    source = {
        "id": "source1",
        "kind": "document",
        "file_name": "产品.txt",
        "path": "products/source.txt",
        "sha256": "a" * 64,
        "original_url": None,
        "final_url": None,
        "extracted": parse_document("产品.txt", "名称：随行杯\n容量：500mL\n材质：不锈钢".encode()),
    }
    p = products.add_source(p["id"], p["revision"], source)
    return store, products, p


def confirmed(tmp_path):
    store, products, p = seed(tmp_path)
    p = products.confirm_facts(
        p["id"], p["revision"], [f["id"] for f in p["facts"]], "审核员", "已核对原始资料"
    )
    return store, products, p


def test_v1_migration_preserves_jobs(tmp_path):
    path = tmp_path / "workflow.db"
    c = sqlite3.connect(path)
    c.executescript(Path("ecom_video/migrations/001_initial.sql").read_text())
    c.execute(
        "INSERT INTO jobs(id,title,script,seconds,status,created_at,updated_at) VALUES('old','旧产品','原脚本',3,'draft',1,1)"
    )
    c.execute("PRAGMA user_version=1")
    c.commit()
    c.close()
    store = Store(path)
    assert store.get("old")["script"] == "原脚本"
    assert store.get("old")["provenance"] is None
    Store(path)  # repeat migration is safe


def test_revision_and_new_source_invalidate_confirmation(tmp_path):
    store, products, p = confirmed(tmp_path)
    with pytest.raises(Conflict):
        products.confirm_facts(p["id"], 0, [p["facts"][0]["id"]], "人", "备注")
    old_review = p["current_review_id"]
    source = {**p["sources"][0], "id": "source2", "path": "products/second.txt"}
    p = products.add_source(p["id"], p["revision"], source)
    assert p["status"] == "collecting" and p["current_review_id"] is None
    assert any(r["id"] == old_review for r in p["fact_reviews"])
    with pytest.raises(Conflict):
        products.save_draft(p["id"], p["revision"], [], "extractive")


def test_confirm_script_atomic_idempotent_provenance_and_lock(tmp_path):
    store, products, p = confirmed(tmp_path)
    facts = products.confirmed_facts(p)
    scenes = compose(facts)
    p = products.save_draft(p["id"], p["revision"], scenes, "extractive")
    draft_id = p["current_draft_id"]
    job = products.approve(p["id"], p["revision"], draft_id, "导演", "核对了脚本事实", 3)
    assert job["status"] == "draft"
    assert job["provenance"]["fact_review"]["reviewer"] == "审核员"
    assert job["provenance"]["sources"][0]["sha256"] == "a" * 64
    assert (
        products.approve(p["id"], p["revision"], draft_id, "导演", "重复请求", 3)["id"] == job["id"]
    )
    with pytest.raises(Conflict):
        store.update_draft(job["id"], "随行杯", "无来源：治愈一切", 3)
    assert store.get(job["id"])["script"] == job["script"]
    assert len(products.get(p["id"])["script_approvals"]) == 1


def test_no_unconfirmed_or_unattributed_scenes(tmp_path):
    _, products, p = confirmed(tmp_path)
    facts = products.confirmed_facts(p)
    for scenes in [
        [{"text": "无来源承诺", "fact_ids": []}],
        [{"text": "容量：500mL", "fact_ids": ["invented"]}],
    ]:
        with pytest.raises(ValueError):
            validate_scenes(scenes, facts)
    rewritten = validate_scenes(
        [{"text": "这是500mL的随行杯", "fact_ids": [facts[1]["id"]]}], facts
    )
    assert rewritten[0]["attribution"] == "human_rewrite"
    with pytest.raises(ValueError):
        products.add_quote(p["id"], p["revision"], "source1", "u001", "不存在的引文")


def test_model_invalid_outputs_fail_closed(tmp_path, monkeypatch):
    from ecom_video import generation

    _, products, p = confirmed(tmp_path)
    facts = products.confirmed_facts(p)
    monkeypatch.setenv("ECOM_LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("ECOM_LLM_MODEL", "test-model")
    monkeypatch.setenv("ECOM_LLM_API_KEY", "fixture-secret")
    for output in [
        {"fact_ids": ["invented"], "hook": "intro"},
        {"fact_ids": [facts[0]["id"]], "hook": "intro", "claim": "保证有效"},
    ]:
        monkeypatch.setattr(
            generation,
            "request_once",
            lambda *a, output=output, **kw: (
                200,
                {},
                json.dumps({"choices": [{"message": {"content": json.dumps(output)}}]}).encode(),
            ),
        )
        with pytest.raises(ValueError):
            generation.call_model(facts)


def test_old_draft_cannot_be_confirmed_after_new_evidence(tmp_path):
    _, products, p = confirmed(tmp_path)
    p = products.save_draft(
        p["id"], p["revision"], compose(products.confirmed_facts(p)), "extractive"
    )
    old = p["current_draft_id"]
    p = products.add_source(
        p["id"], p["revision"], {**p["sources"][0], "id": "newsource", "path": "products/new.txt"}
    )
    with pytest.raises(Conflict):
        products.approve(p["id"], p["revision"], old, "人", "已经失效")
    assert not products.get(p["id"])["script_approvals"]


def test_valid_model_returns_only_verbatim_confirmed_facts(tmp_path, monkeypatch):
    from ecom_video import generation

    _, products, p = confirmed(tmp_path)
    facts = products.confirmed_facts(p)
    monkeypatch.setenv("ECOM_LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("ECOM_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("ECOM_LLM_API_KEY", "fixture-secret")

    def response(url, **kwargs):
        assert url == "https://example.com/v1/chat/completions"
        outbound = json.loads(kwargs["body"])
        sent_facts = json.loads(outbound["messages"][1]["content"])
        assert set(sent_facts[0]) == {"id", "text"}
        selection = {"fact_ids": [facts[1]["id"], facts[0]["id"]], "hook": "details"}
        return (
            200,
            {},
            json.dumps({"choices": [{"message": {"content": json.dumps(selection)}}]}).encode(),
        )

    monkeypatch.setattr(generation, "request_once", response)
    generated = generation.call_model(facts)
    assert [s["text"] for s in generated["scenes"][1:-1]] == [facts[1]["text"], facts[0]["text"]]
    assert all(s["attribution"] != "human_rewrite" for s in generated["scenes"])
