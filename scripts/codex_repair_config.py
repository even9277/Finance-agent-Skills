#!/usr/bin/env python3
"""
Repair ~/.codex/config.toml: remove incomplete [model_providers.*] tables that
lack required `name` (Codex error: missing field `name` at line …).

Safe to re-run. Backs up the original file first.

Usage:
  python3 scripts/codex_repair_config.py
  python3 scripts/codex_repair_config.py --codex-home /path/to/.codex
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


def strip_incomplete_model_provider_sections(text: str) -> tuple[str, list[str]]:
    """Remove [model_providers.X] ... blocks that have no `name =` line in the block body."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    removed: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^\[model_providers\.([^\]]+)\]\s*$", line)
        if not m:
            out.append(line)
            i += 1
            continue

        header = line
        section_id = m.group(1)
        block = [header]
        i += 1
        while i < len(lines) and not re.match(r"^\[", lines[i]):
            block.append(lines[i])
            i += 1
        body = "".join(block[1:])
        if re.search(r"^\s*name\s*=", body, re.MULTILINE):
            out.extend(block)
        else:
            removed.append(f"[model_providers.{section_id}] (no name = …)")
    return "".join(out), removed


def validate_toml(text: str) -> None:
    try:
        import tomllib  # py3.11+
    except ImportError as e:  # pragma: no cover
        raise SystemExit("Python 3.11+ required for tomllib validation") from e
    tomllib.loads(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair Codex config.toml")
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path.home() / ".codex",
        help="Directory containing config.toml (default: ~/.codex)",
    )
    args = parser.parse_args()
    codex_home: Path = args.codex_home
    cfg = codex_home / "config.toml"

    if not cfg.is_file():
        print(f"No file at {cfg}; nothing to repair.", file=sys.stderr)
        return 0

    raw = cfg.read_text(encoding="utf-8")
    fixed, removed = strip_incomplete_model_provider_sections(raw)
    if removed:
        bak = cfg.with_name(f"config.toml.bak.repair.{datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(cfg, bak)
        print(f"Backup: {bak}")
        for r in removed:
            print(f"Removed incomplete section: {r}")
        cfg.write_text(fixed, encoding="utf-8")
        print(f"Wrote: {cfg}")
    else:
        print("No incomplete [model_providers.*] sections found (missing name).")

    try:
        validate_toml(cfg.read_text(encoding="utf-8"))
        print("tomllib parse: OK")
    except Exception as exc:
        print(f"tomllib parse FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
