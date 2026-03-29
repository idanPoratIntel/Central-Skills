#!/usr/bin/env python3
"""
Bump major-only versions in skills.json / mcp.json when files under each entry's path change.
Version is a single integer string (e.g. "1", "2"); minor/patch are not used.

Usage:
  python scripts/bump_versions.py --staged          # pre-commit: staged files
  python scripts/bump_versions.py --git-range HEAD~1..HEAD   # CI: last commit
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_JSON = REPO_ROOT / "skills.json"
MCP_JSON = REPO_ROOT / "mcp.json"


def parse_major(version: str) -> int:
    """Accept "N" or legacy "N.x.y" — only the major segment is used."""
    s = version.strip()
    if not s:
        raise ValueError("empty version")
    head = s.split(".", 1)[0].strip()
    if not head.isdigit():
        raise ValueError(f"major must be a non-negative integer, got: {version!r}")
    return int(head)


def bump_major(version: str) -> str:
    return str(parse_major(version) + 1)


def git_changed_files(git_range: str | None, staged: bool) -> list[str]:
    if staged:
        cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT"]
    elif git_range:
        cmd = ["git", "diff", "--name-only", "--diff-filter=ACMRT", git_range]
    else:
        raise ValueError("Need --staged or --git-range")
    r = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(r.returncode)
    lines = [ln.strip().replace("\\", "/") for ln in r.stdout.splitlines() if ln.strip()]
    return lines


def path_matches_prefix(changed: list[str], prefix: str) -> bool:
    p = prefix.strip().strip("/").replace("\\", "/")
    if not p:
        return False
    for f in changed:
        fn = f.replace("\\", "/")
        if fn == p or fn.startswith(p + "/"):
            return True
    return False


def bump_file(
    json_path: Path,
    changed: list[str],
    label: str,
) -> bool:
    if not json_path.is_file():
        return False
    raw = json_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        print(f"{label}: expected a JSON array in {json_path}", file=sys.stderr)
        sys.exit(1)

    modified = False
    for entry in data:
        if not isinstance(entry, dict):
            continue
        path_str = entry.get("path")
        ver = entry.get("version")
        if not path_str or not ver:
            continue
        if not path_matches_prefix(changed, path_str):
            continue
        try:
            new_ver = bump_major(str(ver))
        except ValueError as e:
            print(f"{label} entry {entry.get('id')!r}: {e}", file=sys.stderr)
            sys.exit(1)
        if new_ver != ver:
            entry["version"] = new_ver
            modified = True
            print(f"{label}: {entry.get('id')} {ver} -> {new_ver}")

    if modified:
        json_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return modified


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--staged",
        action="store_true",
        help="Use staged files (git diff --cached)",
    )
    ap.add_argument(
        "--git-range",
        metavar="RANGE",
        help="e.g. HEAD~1..HEAD for files changed in that range",
    )
    args = ap.parse_args()

    if args.staged and args.git_range:
        ap.error("Use only one of --staged or --git-range")
    if not args.staged and not args.git_range:
        ap.error("Provide --staged or --git-range")

    try:
        changed = git_changed_files(args.git_range, args.staged)
    except ValueError as e:
        ap.error(str(e))

    any_change = False
    any_change |= bump_file(SKILLS_JSON, changed, "skills")
    any_change |= bump_file(MCP_JSON, changed, "mcp")

    if not any_change:
        print("No matching path changes; skills.json / mcp.json unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
