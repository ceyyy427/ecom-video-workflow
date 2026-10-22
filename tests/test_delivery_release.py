import tomllib
from pathlib import Path

from ecom_video.customer_setup import release_info


def test_release_identifies_all_delivery_upgrades_and_ships_existing_guide():
    root = Path(__file__).resolve().parents[1]
    assert release_info(root)["version"] == "0.16.0"
    lock = tomllib.loads((root / "uv.lock").read_text())
    assert (
        next(p for p in lock["package"] if p["name"] == "ecom-video-workflow")["version"]
        == "0.16.0"
    )
    assert "逐镜审核" in (root / "docs/CUSTOMER_HANDOFF.md").read_text()
    assert "恢复历史版" in (root / "docs/CUSTOMER_HANDOFF.md").read_text()


def test_release_contains_editor_and_current_customer_guides(tmp_path):
    import zipfile

    from ecom_video.customer_setup import build_package

    root = Path(__file__).resolve().parents[1]
    package = tmp_path / "new.zip"
    build_package(root, package)
    with zipfile.ZipFile(package) as z:
        for name in (
            "ecom_video/editor_timeline.py",
            "ecom_video/narrato_subtitle_text.py",
            "ecom_video/web/customer-editor.js",
            "ecom_video/web/customer-editor.css",
            "docs/third-party/NarratoAI-LICENSE",
        ):
            assert name in z.namelist()
        assert "精细调整" in z.read("docs/CUSTOMER_INSTALL.md").decode()
        assert "只改不满意的一镜" in z.read("docs/CUSTOMER_HANDOFF.md").decode()
        assert not any(
            n.startswith(("var/", "client-projects/", "output/", ".env/")) for n in z.namelist()
        )
