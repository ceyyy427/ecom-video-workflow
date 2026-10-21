"""Pinned Ocean Watch read-only CLI boundary. No arbitrary command execution."""

import json
import os
import platform
import re
import subprocess
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from ..distribution import encode, identifier
from ..media import digest
from ..reporting import dates, normalize

LOCK = json.loads(Path(__file__).with_name("ocean_watch.lock.json").read_text())
REPOSITORY = Path(__file__).resolve().parents[2] / "references" / "ocean-watch"
FIELDS = {
    "stat_cost": "spend",
    "show_cnt": "impressions",
    "click_cnt": "clicks",
    "pay_order_count": "orders",
    "pay_order_amount": "revenue",
    "total_play": "video_views",
}
ENDPOINT = "/v1.0/qianchuan/report/material/get/"


def binary():
    system = platform.system().lower()
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}.get(
        platform.machine().lower()
    )
    filename = f"ocean-watch_{system}_{arch}" + (".exe" if system == "windows" else "")
    path = REPOSITORY / ".codex-plugin" / "bin" / filename
    if (
        filename not in LOCK["sha256"]
        or not path.is_file()
        or digest(path) != LOCK["sha256"][filename]
    ):
        raise ValueError("Ocean Watch 未安装或版本校验失败；运行 scripts/install_ocean_watch.py")
    return path


class OceanWatch:
    def __init__(self, root):
        self.home = Path(root).resolve() / "integrations" / "ocean-watch"
        self.config = self.home / "config.json"

    def capabilities(self):
        try:
            binary()
            installed = True
        except ValueError:
            installed = False
        return {
            "manual_package": True,
            "platform_write": False,
            "qianchuan_report_adapter": True,
            "runtime_verified": installed,
            "config_present": self.config.is_file(),
            "live_verified": False,
            "version": LOCK["version"],
            "message": "千川原生投放请进入专用页面并完成授权；已存在原生授权时，报表使用原生 API，否则使用独立 Ocean Watch 授权。配置存在不代表授权有效。",
        }

    def _run(self, args):
        executable = binary()
        if not self.config.is_file():
            raise ValueError("请先配置独立 Ocean Watch 授权目录")
        self.home.mkdir(parents=True, exist_ok=True)
        # Do not inherit service keys or global Ocean Watch configuration overrides.
        env = {
            k: v
            for k, v in os.environ.items()
            if k in ("PATH", "HOME", "USER", "TMPDIR", "SYSTEMROOT", "LANG", "LC_ALL")
        }
        env["OCEAN_WATCH_HOME"] = str(self.home)
        with tempfile.TemporaryFile() as stdout:
            process = subprocess.Popen(
                [str(executable), *args, "--config", str(self.config)],
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=subprocess.DEVNULL,
                env=env,
                cwd=self.home,
            )
            deadline = time.monotonic() + 55
            try:
                while process.poll() is None:
                    if (
                        time.monotonic() > deadline
                        or os.fstat(stdout.fileno()).st_size > 5 * 1024**2
                    ):
                        raise ValueError("报表请求超时或响应超过限制")
                    time.sleep(0.1)
                if process.returncode or os.fstat(stdout.fileno()).st_size > 5 * 1024**2:
                    raise ValueError("Ocean Watch 查询失败，请检查本地授权和账户权限")
                stdout.seek(0)
                result = json.loads(stdout.read(), parse_float=Decimal)
                if not isinstance(result, dict):
                    raise ValueError("无效平台响应")
                return result
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise ValueError("平台响应格式无效") from None
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()

    def fetch_day(self, account, day):
        dates(day, day)
        advertiser = identifier(account["advertiser_id"])
        if account["platform"] != "qianchuan":
            raise ValueError("此适配器仅支持巨量千川")
        args = [
            "qc-reports",
            "materials",
            "--advertiser-id",
            advertiser,
            "--start-date",
            day,
            "--end-date",
            day,
            "--top",
            "0",
            "--page-size",
            "100",
            "--max-pages",
            "50",
            "--field",
            ",".join(FIELDS),
        ]
        if account["auth_account_id"]:
            args.extend(["--auth-account-id", account["auth_account_id"]])
        response = self._run(args)
        rows = response.get("rows")
        if (
            response.get("mode") != "qianchuan_material_report"
            or response.get("endpoint") != ENDPOINT
            or response.get("advertiser_id") != advertiser
            or response.get("date_range") != {"start_date": day, "end_date": day}
            or response.get("truncated") is not False
            or not isinstance(rows, list)
            or response.get("row_count") != len(rows)
            or response.get("displayed_count") != len(rows)
            or set(response.get("fields", [])) != set(FIELDS)
        ):
            raise ValueError("平台响应范围或完整性校验失败")
        # Preserve only scoped, numeric evidence, never arbitrary upstream strings or credentials.
        normalized = normalize(
            [
                {
                    "date": day,
                    "material_id": r.get("material_id"),
                    **{v: r.get(k) for k, v in FIELDS.items()},
                }
                for r in rows
            ],
            day,
            day,
        )
        request_ids = response.get("request_ids", [])
        if (
            not isinstance(request_ids, list)
            or len(request_ids) > 500
            or any(
                not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", x)
                for x in request_ids
            )
        ):
            raise ValueError("平台请求标识无效")
        return {
            "date": day,
            "endpoint": ENDPOINT,
            "advertiser_id": advertiser,
            "request_ids": request_ids,
            "rows": normalized,
            "source_format": "whitelisted_normalized_provider_response",
            "runtime_commit": LOCK["commit"],
        }

    def sync(self, reports, task):
        account = reports.distribution.account(task["account_id"])
        responses = [
            self.fetch_day(account, day) for day in dates(task["start_date"], task["end_date"], 7)
        ]
        rows = [r for result in responses for r in result["rows"]]
        return reports.ingest(
            task["account_id"],
            task["start_date"],
            task["end_date"],
            rows,
            encode(responses).encode(),
            "ocean_watch_api",
            task["actor"],
            {
                "runtime_commit": LOCK["commit"],
                "scope": "complete_account_material_daily_snapshot",
                "request_ids": [rid for response in responses for rid in response["request_ids"]],
            },
            sync=task,
        )
