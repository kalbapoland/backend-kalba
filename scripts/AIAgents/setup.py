#!/usr/bin/env python3
"""
scripts/AIAgents/setup.py
Creates links from the AI-agent tool-expected locations to the source-of-truth
files in scripts/AIAgents/.

Run once after cloning:
    set KALBA_BACKEND_DIR=E:\\Projects\\Kalba\\backend
    python scripts/AIAgents/setup.py

Windows: creates hardlinks for files, junction points for directories.
         No Administrator rights or Developer Mode required.
Linux/macOS: creates symlinks for both.

The script is idempotent — already-existing links are skipped.
"""

import filecmp
import os
import platform
import subprocess
import sys
from pathlib import Path


REQUIRED_SKILL_FILES = [
    Path("CoPilot") / "skills" / "ship-code-change" / "SKILL.md",
    Path("CoPilot") / "skills" / "start-local-backend" / "SKILL.md",
    Path("Claude") / "skills" / "ship-code-change" / "SKILL.md",
    Path("Claude") / "skills" / "start-local-backend" / "SKILL.md",
]


def required_env_dir(var_name: str) -> Path:
    """Return a required directory path from environment or raise a clear error."""
    raw_value = os.getenv(var_name, "").strip()
    if not raw_value:
        raise RuntimeError(f"Missing required environment variable: {var_name}")

    path = Path(raw_value).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise RuntimeError(
            f"Environment variable {var_name} must point to an existing directory: {path}"
        )
    return path


def repo_root() -> Path:
    """Return backend repository root from environment configuration."""
    root = required_env_dir("KALBA_BACKEND_DIR")
    expected = (Path(__file__).resolve().parent.parent.parent).resolve()
    if root != expected:
        raise RuntimeError(
            "KALBA_BACKEND_DIR does not match this repository root: "
            f"expected {expected}, got {root}"
        )
    return root


def _is_junction(path: Path) -> bool:
    """Return True if path is a Windows junction point."""
    try:
        return path.is_dir() and os.stat(path, follow_symlinks=False).st_reparse_tag == 0xA0000003
    except (AttributeError, OSError):
        try:
            return path.is_symlink() or (
                platform.system() == "Windows"
                and subprocess.call(
                    ["cmd", "/c", f"fsutil reparsepoint query {path} >nul 2>&1"],
                    shell=False,
                ) == 0
            )
        except Exception:
            return False


def _same_file_contents(src: Path, dst: Path) -> bool:
    """Return True when two regular files have identical contents."""
    try:
        return src.is_file() and dst.is_file() and filecmp.cmp(src, dst, shallow=False)
    except OSError:
        return False


def link_file(src: Path, dst: Path) -> None:
    """Create a hardlink (Windows) or symlink (Unix) from dst → src."""
    if dst.exists() or dst.is_symlink():
        if dst.is_symlink() and dst.resolve() == src.resolve():
            print(f"  [skip]  {dst.relative_to(repo_root())} (symlink already correct)")
            return
        try:
            if os.stat(dst).st_ino == os.stat(src).st_ino:
                print(f"  [skip]  {dst.relative_to(repo_root())} (hardlink already correct)")
                return
        except OSError:
            pass
        if _same_file_contents(src, dst):
            dst.unlink()
            print(f"  [sync]  {dst.relative_to(repo_root())} (replacing identical file with link)")
        else:
            print(f"  [warn]  {dst.relative_to(repo_root())} already exists and is not linked — skipping")
            return

    dst.parent.mkdir(parents=True, exist_ok=True)

    if platform.system() == "Windows":
        os.link(src, dst)
        print(f"  [link]  {dst.relative_to(repo_root())} -> {src.relative_to(repo_root())} (hardlink)")
    else:
        os.symlink(src, dst)
        print(f"  [link]  {dst.relative_to(repo_root())} -> {src.relative_to(repo_root())} (symlink)")


def link_dir(src: Path, dst: Path) -> None:
    """Create a junction (Windows) or symlink (Unix) from dst → src."""
    if dst.exists() or dst.is_symlink():
        if dst.is_symlink() and dst.resolve() == src.resolve():
            print(f"  [skip]  {dst.relative_to(repo_root())} (symlink already correct)")
            return
        if _is_junction(dst):
            print(f"  [skip]  {dst.relative_to(repo_root())} (junction already exists)")
            return
        print(f"  [warn]  {dst.relative_to(repo_root())} already exists and is not a junction — skipping")
        return

    dst.parent.mkdir(parents=True, exist_ok=True)

    if platform.system() == "Windows":
        subprocess.check_call(
            ["powershell", "-Command",
             f"New-Item -ItemType Junction -Path '{dst}' -Target '{src}' -Force"],
            stdout=subprocess.DEVNULL,
        )
        print(f"  [link]  {dst.relative_to(repo_root())} -> {src.relative_to(repo_root())} (junction)")
    else:
        os.symlink(src, dst)
        print(f"  [link]  {dst.relative_to(repo_root())} -> {src.relative_to(repo_root())} (symlink)")


def main() -> int:
    root = repo_root()
    agents = root / "scripts" / "AIAgents"

    print(f"Repository root: {root}")
    print(f"Source of truth: {agents.relative_to(root)}")
    print()

    errors = 0

    for rel_path in REQUIRED_SKILL_FILES:
        skill_path = agents / rel_path
        if not skill_path.is_file():
            print(f"  [error] missing required skill file: {skill_path.relative_to(root)}")
            errors += 1

    if errors:
        print()
        print(f"Aborting setup due to {errors} missing required skill file(s).")
        return 1

    # ── Files (hardlink / symlink) ────────────────────────────────────────────
    files = [
        (agents / "Claude"  / "CLAUDE.md",                root / "CLAUDE.md"),
        (agents / "CoPilot" / "copilot-instructions.md",  root / ".github" / "copilot-instructions.md"),
    ]

    # ── Directories (junction / symlink) ─────────────────────────────────────
    dirs = [
        (agents / "Claude"  / "agents",   root / ".claude"  / "agents"),
        (agents / "Claude"  / "skills",   root / ".claude"  / "skills"),
        (agents / "CoPilot" / "prompts",  root / ".github"  / "prompts"),
        (agents / "CoPilot" / "skills",   root / ".github"  / "skills"),
    ]

    for src, dst in files:
        try:
            link_file(src, dst)
        except Exception as exc:
            print(f"  [error] {dst}: {exc}")
            errors += 1

    for src, dst in dirs:
        try:
            link_dir(src, dst)
        except Exception as exc:
            print(f"  [error] {dst}: {exc}")
            errors += 1

    print()
    if errors:
        print(f"Done with {errors} error(s).")
        return 1

    sync_script = agents / "sync_shared_content.py"
    if not sync_script.exists():
        print(f"  [error] missing sync script: {sync_script.relative_to(root)}")
        return 1

    print("Running shared wrapper sync...")
    sync_result = subprocess.run(
        [sys.executable, str(sync_script)],
        cwd=str(root),
        check=False,
    )
    if sync_result.returncode != 0:
        print(f"  [error] wrapper sync failed with exit code {sync_result.returncode}")
        return sync_result.returncode

    print("Done. All AI agent files are linked and wrappers are synced.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
