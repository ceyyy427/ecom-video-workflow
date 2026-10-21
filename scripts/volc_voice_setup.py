#!/usr/bin/env python3
"""Set a local Volcengine speech API Key without arguments, stdout or network access."""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecom_video.voice_config import save_config  # noqa: E402,F401
from ecom_video.volc_voice import DEFAULT_SPEAKER, SPEAKERS, config_path  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="本机保存火山语音 API Key（不发起调用）")
    parser.add_argument("--speaker", choices=list(SPEAKERS), default=DEFAULT_SPEAKER)
    parser.add_argument("--replace", action="store_true", help="明确替换已有配置")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        print("请在本机交互终端运行；不接受命令参数或管道中的密钥。", file=sys.stderr)
        return 1
    if config_path().exists() and not args.replace:
        print("已有配置，未修改。需要替换时请加 --replace。", file=sys.stderr)
        return 1
    try:
        key = getpass.getpass("火山语音新版控制台 API Key（输入不显示）：")
        save_config(config_path(), key.strip(), args.speaker, args.replace)
    except (OSError, ValueError):
        print("配置未保存：请检查输入、文件权限或已有配置。", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n已取消，未发起调用。", file=sys.stderr)
        return 1
    print("已保存本机私有配置。尚未调用或验证账户权限；回到页面刷新配音状态。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
