"""确定性上下文选择、section 预算与模型 placement。"""

from __future__ import annotations

from .context import BudgetReport, ContextBlock, ModelCallContext
from .errors import ContextOverflow, ProjectionConfigurationError
from .schema import Placement, ProjectionPolicy


class ContextProjectionService:
    """只处理已鉴权、已脱敏 blocks；不查询任何权威模块。"""

    def project(
        self,
        policy: ProjectionPolicy,
        blocks: tuple[ContextBlock, ...],
        *,
        input_budget: int,
    ) -> ModelCallContext:
        if not policy.model_role or not policy.sections:
            raise ProjectionConfigurationError("projection policy is incomplete")
        sections = {item.section_kind: item for item in policy.sections}
        unknown = [block.block_id for block in blocks if block.category not in sections]
        if unknown:
            raise ProjectionConfigurationError(
                f"blocks have no configured section: {','.join(sorted(unknown))}"
            )

        mandatory = [
            block
            for block in blocks
            if block.mandatory or sections[block.category].required
        ]
        mandatory_tokens = sum(item.token_count for item in mandatory)
        if mandatory_tokens > input_budget:
            raise ContextOverflow(
                f"mandatory context requires {mandatory_tokens} tokens, "
                f"budget is {input_budget}"
            )

        # 与输入到达顺序无关，恢复或并行采集后才能得到相同 Prompt。
        ordered = sorted(
            blocks,
            key=lambda block: (
                not (block.mandatory or sections[block.category].required),
                -sections[block.category].priority,
                -block.priority,
                block.block_id,
            ),
        )
        selected: list[ContextBlock] = []
        omitted: list[ContextBlock] = []
        total = 0
        section_totals: dict[str, int] = {}
        for block in ordered:
            section = sections[block.category]
            section_total = section_totals.get(block.category, 0)
            fits = (
                total + block.token_count <= input_budget
                and section_total + block.token_count <= section.token_budget
            )
            required = block.mandatory or section.required
            if not fits and required:
                raise ContextOverflow(
                    f"mandatory block {block.block_id} exceeds budget"
                )
            if not fits:
                omitted.append(block)
                continue
            selected.append(block)
            total += block.token_count
            section_totals[block.category] = section_total + block.token_count

        by_placement: dict[Placement, list[str]] = {
            "system_messages": [],
            "messages": [],
            "tools": [],
        }
        for block in selected:
            by_placement[sections[block.category].placement].append(block.content)
        report = BudgetReport(
            input_budget,
            total,
            tuple(item.block_id for item in selected),
            tuple(item.block_id for item in omitted),
        )
        return ModelCallContext(
            tuple(by_placement["system_messages"]),
            tuple(by_placement["messages"]),
            tuple(by_placement["tools"]),
            report,
            policy.version,
        )
