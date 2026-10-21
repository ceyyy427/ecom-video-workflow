"""Machine-readable P13 adapter. Help and admission errors never initialize a database."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .agent_contracts import MAX_EVENT_SEQ, Problem, parse_command, rejection
from .agent_runtime_contracts import Control, StyleChoice, execution_enabled
from .agent_service import MAX_COMMAND_BYTES, AgentService, capabilities, enabled, validate_id


class InputError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal diagnostic may echo a credential pasted as an argument.
        raise InputError


def parser():
    p = Parser(description="本机 Agent 提案与有界制作；人工确认保留，不写投放平台")
    p.add_argument("--data", help="明确的数据目录；run/get/events 必填")
    commands = p.add_subparsers(dest="action", required=True)
    commands.add_parser("capabilities", help="读取工具契约，不打开数据目录")
    run = commands.add_parser("run", help="读取 JSON 命令并保存只读提案记录")
    run.add_argument("--input", required=True, help="UTF-8 JSON 文件，或 - 表示标准输入")
    get = commands.add_parser("get", help="读取已保存运行记录")
    get.add_argument("run_id")
    events = commands.add_parser("events", help="按递增 seq 读取事件")
    events.add_argument("run_id")
    events.add_argument("--after-seq", type=int, default=0)
    events.add_argument("--limit", type=int, default=100)
    inspect = commands.add_parser("inspect", help="查询 P14 执行进度与预算")
    inspect.add_argument("run_id")
    for action in ("execute", "pause", "resume", "cancel", "style"):
        item = commands.add_parser(action, help="P14 显式控制或人工风格选择")
        item.add_argument("run_id")
        item.add_argument(
            "--input", required=True, help="绑定计划哈希、版本和策略的 JSON 文件，或 -"
        )
    return p


def load_json(path):
    if path == "-":
        raw = sys.stdin.buffer.read(MAX_COMMAND_BYTES + 1)
    else:
        if not Path(path).is_file():
            raise InputError
        with Path(path).open("rb") as source:
            raw = source.read(MAX_COMMAND_BYTES + 1)
    if len(raw) > MAX_COMMAND_BYTES:
        raise InputError
    return json.loads(raw)


def execute(args):
    if args.action == "capabilities":
        return capabilities()
    if not args.data:
        raise InputError
    if args.action == "run":
        command = parse_command(load_json(args.input)).model_dump()
    else:
        validate_id(args.run_id)
        if args.action == "events" and (
            not 0 <= args.after_seq <= MAX_EVENT_SEQ or not 1 <= args.limit <= 100
        ):
            raise InputError
    if not enabled():
        raise Problem("AGENT_DISABLED")
    if args.action in ("execute", "pause", "resume", "cancel", "style"):
        command = (
            (StyleChoice if args.action == "style" else Control)
            .model_validate(load_json(args.input))
            .model_dump()
        )
    if (
        args.action in ("execute", "resume", "style", "inspect")
        or (args.action == "run" and command["operation"] == "project.produce")
    ) and not execution_enabled():
        raise Problem("AGENT_DISABLED")
    root = Path(args.data).expanduser().resolve()
    if args.action != "run" and not (root / "workflow.db").is_file():
        raise Problem("NOT_FOUND")
    # Import/initialize only after syntax, command validation and feature checks.
    from .db import Store

    service = AgentService(root, Store(root / "workflow.db"))
    if args.action in ("execute", "pause", "resume", "cancel", "style", "inspect"):
        from .agent_runtime import Runtime

        runtime = Runtime(root, service.store)
        if args.action == "inspect":
            return runtime.get(args.run_id)
        if args.action == "style":
            return runtime.choose(args.run_id, command)
        return runtime.control(args.run_id, args.action, command)
    if args.action == "run":
        return service.create(command)
    if args.action == "get":
        return service.get(args.run_id)
    return service.events(args.run_id, args.after_seq, args.limit)


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        result = execute(args)
    except (InputError, ValidationError, ValueError, UnicodeError, OSError):
        result = rejection("INVALID_INPUT")
    except Problem as exc:
        result = rejection(exc.code)
    except Exception:
        result = rejection("INTERNAL_ERROR")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    error = result.get("error")
    if error:
        print(f"{error['code']}: {error['safe_message']}", file=sys.stderr)
        return 2 if error["code"] == "INVALID_INPUT" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
