#!/usr/bin/env python3
"""
Synchronize shared reviewer/manager content across backend CoPilot prompts and Claude agents.

Source of truth for common text:
    scripts/AIAgents/Shared/prompts/<name>.md
    scripts/AIAgents/Shared/skills/<name>.md

Targets (thin wrappers only):
    scripts/AIAgents/CoPilot/prompts/<name>.prompt.md
    scripts/AIAgents/Claude/agents/<name>.md
    scripts/AIAgents/CoPilot/skills/<name>/SKILL.md
    scripts/AIAgents/Claude/skills/<name>/SKILL.md

Frontmatter in target files is preserved. Body content is replaced with a wrapper
that points to the matching Shared file.

Bootstrap behavior:
    If a shared file does not exist yet, it is created from the current non-wrapper
    body of the first available target.
"""

from __future__ import annotations

from pathlib import Path


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return "", text

    lines = text.splitlines(keepends=True)
    if not lines or not lines[0].startswith("---"):
        return "", text

    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            frontmatter = "".join(lines[: i + 1]).rstrip("\n\r")
            body = "".join(lines[i + 1 :]).lstrip("\n\r")
            return frontmatter, body

    return "", text


def join_frontmatter(frontmatter: str, body: str) -> str:
    body = body.rstrip() + "\n"
    if not frontmatter:
        return body
    return f"{frontmatter}\n\n{body}"


def make_wrapper_body(shared_rel_path: str) -> str:
    return (
        "This file is a thin wrapper.\n\n"
        f"Source of truth: `{shared_rel_path}`\n\n"
        "Before applying any instructions from this file, read and follow the "
        "source-of-truth file above.\n"
        "If this wrapper and the source-of-truth file conflict, the "
        "source-of-truth file wins.\n"
    )


def is_wrapper_body(body: str) -> bool:
    normalized = body.strip()
    return normalized.startswith("This file is a thin wrapper.") and "Source of truth:" in normalized


def sync_named_files(
    *,
    repo_root: Path,
    left_map: dict[str, Path],
    right_map: dict[str, Path],
    shared_dir: Path,
) -> tuple[list[str], list[str], list[str]]:
    changed_left: list[str] = []
    changed_right: list[str] = []
    bootstrapped_shared: list[str] = []

    names = sorted(set(left_map) | set(right_map))
    for name in names:
        left_file = left_map.get(name)
        right_file = right_map.get(name)
        shared_file = shared_dir / f"{name}.md"

        left_text = left_file.read_text(encoding="utf-8") if left_file else ""
        left_front, left_body = split_frontmatter(left_text) if left_file else ("", "")

        right_text = right_file.read_text(encoding="utf-8") if right_file else ""
        right_front, right_body = (
            split_frontmatter(right_text) if right_file else ("", "")
        )

        if not shared_file.exists():
            source_body = left_body if left_file and not is_wrapper_body(left_body) else right_body
            if is_wrapper_body(source_body):
                raise RuntimeError(
                    f"Cannot bootstrap shared file from wrapper content: {shared_file.relative_to(repo_root)}"
                )
            shared_file.write_text(source_body.rstrip() + "\n", encoding="utf-8")
            bootstrapped_shared.append(str(shared_file.relative_to(repo_root)))

        shared_rel = str(shared_file.relative_to(repo_root)).replace("\\", "/")
        wrapper_body = make_wrapper_body(shared_rel)

        if left_file:
            new_left = join_frontmatter(left_front, wrapper_body)
            if new_left != left_text:
                left_file.write_text(new_left, encoding="utf-8")
                changed_left.append(str(left_file.relative_to(repo_root)))

        if right_file:
            new_right = join_frontmatter(right_front, wrapper_body)
            if new_right != right_text:
                right_file.write_text(new_right, encoding="utf-8")
                changed_right.append(str(right_file.relative_to(repo_root)))

    return changed_left, changed_right, bootstrapped_shared


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    ai_root = repo_root / "scripts" / "AIAgents"

    copilot_prompts = ai_root / "CoPilot" / "prompts"
    claude_agents = ai_root / "Claude" / "agents"
    copilot_skills = ai_root / "CoPilot" / "skills"
    claude_skills = ai_root / "Claude" / "skills"

    shared_prompts = ai_root / "Shared" / "prompts"
    shared_skills = ai_root / "Shared" / "skills"
    shared_prompts.mkdir(parents=True, exist_ok=True)
    shared_skills.mkdir(parents=True, exist_ok=True)

    prompt_files = sorted(copilot_prompts.glob("*.prompt.md"))
    claude_files = sorted(claude_agents.glob("*.md"))
    copilot_skill_files = sorted(copilot_skills.glob("*/SKILL.md"))
    claude_skill_files = sorted(claude_skills.glob("*/SKILL.md"))

    if not prompt_files and not claude_files and not copilot_skill_files and not claude_skill_files:
        print("No backend CoPilot/Claude prompt or skill files found.")
        return 0

    cp_map = {f.name.removesuffix(".prompt.md"): f for f in prompt_files}
    cl_map = {f.name.removesuffix(".md"): f for f in claude_files}
    cps_map = {f.parent.name: f for f in copilot_skill_files}
    cls_map = {f.parent.name: f for f in claude_skill_files}

    changed_copilot_prompts, changed_claude_agents, bootstrapped_prompts = sync_named_files(
        repo_root=repo_root,
        left_map=cp_map,
        right_map=cl_map,
        shared_dir=shared_prompts,
    )
    changed_copilot_skills, changed_claude_skills, bootstrapped_skills = sync_named_files(
        repo_root=repo_root,
        left_map=cps_map,
        right_map=cls_map,
        shared_dir=shared_skills,
    )

    print("=== Shared Sync Summary ===")
    print(f"Shared prompts bootstrapped: {len(bootstrapped_prompts)}")
    for path in bootstrapped_prompts:
        print(f"  + {path}")

    print(f"Shared skills bootstrapped: {len(bootstrapped_skills)}")
    for path in bootstrapped_skills:
        print(f"  + {path}")

    print(f"CoPilot prompts updated: {len(changed_copilot_prompts)}")
    for path in changed_copilot_prompts:
        print(f"  * {path}")

    print(f"Claude agents updated: {len(changed_claude_agents)}")
    for path in changed_claude_agents:
        print(f"  * {path}")

    print(f"CoPilot skills updated: {len(changed_copilot_skills)}")
    for path in changed_copilot_skills:
        print(f"  * {path}")

    print(f"Claude skills updated: {len(changed_claude_skills)}")
    for path in changed_claude_skills:
        print(f"  * {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())