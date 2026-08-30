"""已选择 Skill 的程序性上下文投影。"""

from __future__ import annotations

from ..skills.catalog import SkillSnapshot
from .context import ContextBlock, conservative_token_count


def skill_context_block(snapshot: SkillSnapshot | None) -> ContextBlock:
    if snapshot is None:
        content = "当前没有可用 Skill，且本次任务未选择 Skill。"
    else:
        catalog_lines = [
            f"- {item.manifest.name}: {item.manifest.description}"
            for item in snapshot.catalog
        ]
        lines = [
            "可按需选择的 Skill：",
            *(catalog_lines or ["- 无"]),
        ]
        if not snapshot.selected:
            lines.append("本次任务未选择 Skill。")
        else:
            lines.append("本次任务选择以下 Skill，按其完整指令执行：")
        for item in snapshot.selected:
            lines.append(
                f"- {item.manifest.name}（{item.manifest.version}）: "
                f"{item.manifest.description}"
            )
            if item.content:
                lines.append(f"  指令：\n{item.content}")
            if item.manifest.files:
                package_root = (
                    "/workspace/.venagent/skills/"
                    f"{item.skill_id}/{item.package_digest}"
                )
                lines.append(f"  只读包目录：{package_root}")
                lines.extend(
                    f"  - {package_root}/{reference.path}"
                    for reference in item.manifest.files
                )
        content = "\n".join(lines)
    return ContextBlock(
        block_id="skill-context",
        category="skill_context",
        source="m06-skills",
        content=content,
        priority=70,
        mandatory=False,
        token_count=conservative_token_count(content),
    )
