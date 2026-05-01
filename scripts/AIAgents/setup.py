#!/usr/bin/env python3
"""
scripts/AIAgents/setup.py
Creates links from the AI-agent tool-expected locations to the source-of-truth
files in scripts/AIAgents/.

Run once after cloning:
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


def repo_root() -> Path:
    """Return the repository root (three levels up from this file:
    setup.py → AIAgents/ → scripts/ → repo root)."""
    return Path(__file__).resolve().parent.parent.parent


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

    errors = 0
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

    print("Done. All AI agent files are linked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
