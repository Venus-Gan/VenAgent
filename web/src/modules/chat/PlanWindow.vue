<script setup lang="ts">
import { computed, ref } from 'vue'

import DshIcon from './DshIcon.vue'
import { derivePlanWindow, type PlanWindowNodeStatus, type TrajectoryEvent } from './store'

const props = defineProps<{
  events: TrajectoryEvent[]
}>()

const open = ref(false)
const expandedRow = ref<string | null>(null)

const plan = computed(() => derivePlanWindow(props.events))

const headLabel = computed(() => {
  const value = plan.value
  if (!value) return ''
  const running = value.counts.running
  const pending = value.counts.pending
  const parts: string[] = []
  if (running > 0) parts.push(`${running} 进行中`)
  if (pending > 0) parts.push(`${pending} 待处理`)
  if (!parts.length) parts.push(`${value.counts.done}/${value.nodes.length} 完成`)
  return parts.join(' · ')
})

const failed = computed(() => plan.value?.gaveUp === true || (plan.value?.counts.failed ?? 0) > 0)

function statusIcon(status: PlanWindowNodeStatus): string {
  if (status === 'succeeded') return '✓'
  if (status === 'failed') return '✕'
  if (status === 'skipped') return '⤼'
  if (status === 'cancelled') return '−'
  return ''
}

function executorLabel(node: { tool: string | null; agent: string | null }): string {
  return node.agent || node.tool || ''
}
</script>

<template>
  <div v-if="plan" class="plan-window" :class="{ 'is-failed': failed }" data-testid="plan-window">
    <button
      type="button"
      class="plan-window-head"
      :aria-expanded="open"
      aria-controls="plan-window-list"
      @click="open = !open"
    >
      <DshIcon name="checklist" :size="14" class="plan-window-icon" />
      <span class="plan-window-title">任务</span>
      <span class="plan-window-summary" :class="{ failed }">{{ headLabel }}</span>
      <span v-if="plan.replansUsed" class="plan-window-rev" :title="`Replanner 修订 ${plan.replansUsed} 次`">rev {{ plan.revision }}</span>
      <span v-if="plan.gaveUp" class="plan-window-gave-up">无法完成</span>
      <span class="plan-window-toggle" :class="{ 'is-open': open }" aria-hidden="true">›</span>
    </button>
    <ol v-if="open" id="plan-window-list" class="plan-window-list">
      <li
        v-for="node in plan.nodes"
        :key="node.id"
        class="plan-window-item"
        :class="`is-${node.status}`"
      >
        <button
          type="button"
          class="plan-window-row"
          :aria-expanded="expandedRow === node.id"
          @click="expandedRow = expandedRow === node.id ? null : node.id"
        >
          <span class="plan-window-dot" aria-hidden="true">
            <span v-if="node.status === 'running'" class="plan-window-spinner" />
            <template v-else>{{ statusIcon(node.status) }}</template>
          </span>
          <span class="plan-window-goal">{{ node.goal }}</span>
          <span v-if="executorLabel(node)" class="plan-window-executor">{{ executorLabel(node) }}</span>
          <span v-if="node.raceGroup" class="plan-window-race" :title="`竞速组 ${node.raceGroup}`">⚡</span>
          <span class="plan-window-row-toggle" aria-hidden="true">›</span>
        </button>
        <div v-if="expandedRow === node.id" class="plan-window-detail">
          <div class="plan-window-detail-line"><strong>节点</strong>{{ node.id }}（revision {{ plan.revision }}）</div>
          <div v-if="node.dependsOn.length" class="plan-window-detail-line"><strong>依赖</strong>{{ node.dependsOn.join('、') }}</div>
          <div v-if="node.summary" class="plan-window-detail-line"><strong>观察</strong>{{ node.summary.slice(0, 200) }}</div>
          <div v-if="node.errorCode" class="plan-window-detail-line is-error"><strong>错误码</strong>{{ node.errorCode }}</div>
        </div>
      </li>
    </ol>
  </div>
</template>
