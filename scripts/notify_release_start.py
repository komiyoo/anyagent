#!/usr/bin/env python3
"""Send a Feishu custom bot notification before an SDK release build."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path


MAX_COMMITS = 30
MAX_MARKDOWN_BYTES = 16_000
PACKAGE_PYPROJECT = Path("packages/anyagent/pyproject.toml")


def run_git(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def short_ref(ref: str) -> str:
    try:
        return run_git(["rev-parse", "--short", ref])
    except subprocess.CalledProcessError:
        return ref


def commit_lines(commit_range: str) -> list[str]:
    try:
        output = run_git(["log", "--no-merges", "--format=%h %s", commit_range])
    except subprocess.CalledProcessError:
        output = run_git(["log", "--no-merges", "--format=%h %s", "-n", str(MAX_COMMITS)])
    return [line for line in output.splitlines() if line.strip()]


def package_version() -> str:
    payload = tomllib.loads(PACKAGE_PYPROJECT.read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def escape_markdown(value: str) -> str:
    return value.replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")


def build_markdown(project: str, branch: str, previous_ref: str, target_ref: str, commits: list[str]) -> str:
    previous_sha = short_ref(previous_ref)
    target_sha = short_ref(target_ref)
    commit_count = len(commits)
    shown = commits[:MAX_COMMITS]
    hidden = commit_count - len(shown)

    lines = [
        f"**项目**: {escape_markdown(project)}",
        f"**分支**: `{escape_markdown(branch)}`",
        f"**包**: `anyagent=={escape_markdown(package_version())}`",
        f"**范围**: `{previous_sha}..{target_sha}`",
        f"**新增 commit**: {commit_count}",
        "",
    ]

    if shown:
        lines.append("**本次累计 commit 信息**")
        lines.extend(f"- `{line.split(' ', 1)[0]}` {escape_markdown(line.split(' ', 1)[1] if ' ' in line else '')}" for line in shown)
        if hidden > 0:
            lines.append(f"- ... 还有 {hidden} 条 commit 未展示")
    else:
        lines.append("本次没有新增 commit。")

    markdown = "\n".join(lines)
    while len(markdown.encode("utf-8")) > MAX_MARKDOWN_BYTES and len(shown) > 1:
        shown = shown[:-1]
        hidden = commit_count - len(shown)
        lines = lines[:6] + [
            "**本次累计 commit 信息**",
            *[f"- `{line.split(' ', 1)[0]}` {escape_markdown(line.split(' ', 1)[1] if ' ' in line else '')}" for line in shown],
            f"- ... 还有 {hidden} 条 commit 未展示",
        ]
        markdown = "\n".join(lines)
    return markdown


def build_card(project: str, branch: str, previous_ref: str, target_ref: str, commits: list[str]) -> dict[str, object]:
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"SDK 发布构建开始: {project}"},
            "subtitle": {"tag": "plain_text", "content": f"{branch} -> anyagent=={package_version()}"},
            "template": "blue",
            "padding": "12px 12px 12px 12px",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": [
                {
                    "tag": "markdown",
                    "content": build_markdown(project, branch, previous_ref, target_ref, commits),
                    "text_align": "left",
                    "text_size": "normal_v2",
                    "margin": "0px 0px 0px 0px",
                }
            ],
        },
    }


def sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="anyagent")
    parser.add_argument("--branch", default=os.environ.get("CI_COMMIT_BRANCH") or os.environ.get("BRANCH_NAME") or "main")
    parser.add_argument("--previous-ref", default=os.environ.get("ANYAGENT_RELEASE_PREVIOUS_REF") or "HEAD~1")
    parser.add_argument("--target-ref", default=os.environ.get("ANYAGENT_RELEASE_TARGET_REF") or "HEAD")
    args = parser.parse_args()

    webhook_url = os.environ.get("FEISHU_RELEASE_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("FEISHU_RELEASE_WEBHOOK_URL is not set; skipping release notification.", file=sys.stderr)
        return 0

    commit_range = f"{args.previous_ref}..{args.target_ref}"
    payload: dict[str, object] = {
        "msg_type": "interactive",
        "card": build_card(args.project, args.branch, args.previous_ref, args.target_ref, commit_lines(commit_range)),
    }

    secret = os.environ.get("FEISHU_RELEASE_WEBHOOK_SECRET", "").strip()
    if secret:
        timestamp = int(time.time())
        payload["timestamp"] = str(timestamp)
        payload["sign"] = sign(secret, timestamp)

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        print(f"Failed to send Feishu release notification: {exc}", file=sys.stderr)
        return 1

    try:
        result = json.loads(response_body)
    except json.JSONDecodeError:
        print("Feishu release notification returned a non-JSON response.", file=sys.stderr)
        return 1

    if result.get("code") != 0:
        print(f"Feishu release notification failed: code={result.get('code')} msg={result.get('msg')}", file=sys.stderr)
        return 1

    print("Feishu release notification sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
