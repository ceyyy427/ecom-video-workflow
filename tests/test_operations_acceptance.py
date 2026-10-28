import argparse
import json
import subprocess
import sys

import pytest

from scripts.accept_domestic_suite import PROJECT, validate_inputs


def test_content_cli_is_explicit_and_bad_cases_do_not_create_workspace(tmp_path):
    help_result = subprocess.run(
        [sys.executable, str(PROJECT / "scripts/accept_domestic_suite.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert "{foundation,content}" in help_result.stdout
    backup = tmp_path / "backup"
    backup.mkdir()
    manifest = tmp_path / "cases.json"
    manifest.write_text(json.dumps({"cases": [], "legacy_backup_path": str(backup)}))
    target = tmp_path / "new"
    with pytest.raises(ValueError):
        validate_inputs(argparse.Namespace(stage="content", workspace=target, manifest=manifest))
    assert not target.exists()
