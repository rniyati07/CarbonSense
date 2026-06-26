#!/usr/bin/env python3
"""CI gate: YAML rule version-bump enforcement.

ROADMAP_v2 ENG-3b-1 DoD:
    "A rule change ships via reviewed PR + version bump, independent of any
    model deploy."

This script detects rule YAML files modified in the current PR (compared to the
merge-base on the target branch) and verifies that the ``version`` field has been
incremented relative to the base branch.  It exits non-zero if any modified rule
file does not have an incremented version.

Usage (CI):
    python scripts/ci/validate_rule_versions.py --base-ref origin/main

Usage (local pre-check):
    python scripts/ci/validate_rule_versions.py

The script uses ``git diff`` to detect which files changed and ``git show`` to read
the base version.  No external dependencies beyond the standard library and PyYAML.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

RULES_DIR = Path("services/rules_engine/rules")
RULES_EXTENSIONS = {".yaml", ".yml"}


def run(cmd: list[str]) -> str:
    """Run a shell command and return stdout, stripping trailing whitespace."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()


def get_modified_rule_files(base_ref: str) -> list[Path]:
    """Return repo-relative paths of rule YAML files modified vs *base_ref*."""
    diff_output = run(
        ["git", "diff", "--name-only", base_ref, "--", str(RULES_DIR)]
    )
    if not diff_output:
        return []
    return [
        Path(p)
        for p in diff_output.splitlines()
        if Path(p).suffix in RULES_EXTENSIONS
    ]


def get_base_version(base_ref: str, filepath: Path) -> int | None:
    """Return the ``version`` field in *filepath* at *base_ref*, or None if new."""
    content = run(["git", "show", f"{base_ref}:{filepath}"])
    if not content:
        # File is new — no base version to compare against; allow it.
        return None
    try:
        data = yaml.safe_load(content)
        return int(data.get("version", 0))
    except Exception:
        return None


def get_current_version(filepath: Path) -> int | None:
    """Return the ``version`` field in the working-tree copy of *filepath*."""
    try:
        with open(filepath) as f:
            data = yaml.safe_load(f)
        return int(data.get("version", 0)) if data else None
    except Exception:
        return None


def main(base_ref: str) -> int:
    """Validate all modified rule files.  Returns 0 on success, 1 on failure."""
    modified = get_modified_rule_files(base_ref)

    if not modified:
        print("✅  No rule YAML files modified — version check not required.")
        return 0

    failures: list[str] = []

    for filepath in modified:
        base_ver = get_base_version(base_ref, filepath)
        curr_ver = get_current_version(filepath)

        if curr_ver is None:
            failures.append(
                f"  ❌  {filepath}: Cannot read current version — is the file valid YAML?"
            )
            continue

        if base_ver is None:
            # New file — just ensure a version is set.
            print(f"  ✅  {filepath}: New rule (version={curr_ver}) — OK")
            continue

        if curr_ver <= base_ver:
            failures.append(
                f"  ❌  {filepath}: version NOT incremented "
                f"(base={base_ver}, current={curr_ver}).  "
                f"Bump the 'version' field before merging."
            )
        else:
            print(
                f"  ✅  {filepath}: version incremented "
                f"({base_ver} → {curr_ver}) — OK"
            )

    if failures:
        print("\nRule version-bump validation FAILED:\n")
        for msg in failures:
            print(msg)
        print(
            "\nEvery modified rule YAML must have its 'version' field incremented.\n"
            "This is required by ROADMAP_v2 ENG-3b-1 DoD and TRD_v2 §3.2."
        )
        return 1

    print("\n✅  All modified rule files have incremented versions.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="Git ref to compare against (default: origin/main)",
    )
    args = parser.parse_args()
    sys.exit(main(args.base_ref))
