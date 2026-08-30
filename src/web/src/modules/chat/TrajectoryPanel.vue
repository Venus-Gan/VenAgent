<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import {
  isFailedOperation,
  operationFailureLabel,
  useChatStore,
  type ProcessingEvent,
  type TrajectoryEvent,
} from './store'
import DshIcon from './DshIcon.vue'

const chat = useChatStore()
const operationExpandedById = ref<Record<string, boolean>>({})

const runs = computed(() => chat.active?.runs || [])

function trajectoryEvents(runId: string): TrajectoryEvent[] {
  return chat.trajectoryByRun[runId] || []
}

function processingEvents(runId: string): ProcessingEvent[] {
  return chat.processingByRun[runId] || []
}

function visibleTrajectoryEvents(runId: string): TrajectoryEvent[] {
  return trajectoryEvents(runId).filter(
    event => event.type !== 'run.started' && event.type !== 'run.completed',
  )
}

function toolIconName(event: ProcessingEvent): 'bash' | 'code' | 'search' | 'edit' | 'sparkle' | 'skill' {
  const toolId = String(event.toolId || '')
  if (toolId === 'exec_command' || toolId === 'bash' || toolId === 'terminal') return 'bash'
  if (toolId.includes('skill')) return 'skill'
  if (toolId.includes('search') || toolId.includes('fetch') || toolId.includes('web')) return 'search'
  if (toolId.includes('write') || toolId.includes('edit') || toolId.includes('patch') || toolId.includes('str_replace')) return 'edit'
  if (toolId.includes('code') || toolId.includes('python') || toolId.includes('node')) return 'code'
  return 'sparkle'
}

function statusClass(status: string): string {
  if (status === 'completed' || status === 'succeeded' || status === 'approved') return 'is-success'
  if (status === 'failed' || status === 'cancelled' || status === 'rejected' || status === 'error' || status === 'incompatible') return 'is-error'
  if (status === 'awaiting_approval' || status === 'pending' || status === 'waiting_approval') return 'is-pending'
  return 'is-running'
}

function operationExpanded(event: ProcessingEvent): boolean {
  return operationExpandedById.value[event.operationId] ?? isFailedOperation(event.status)
}

function toggleOperation(event: ProcessingEvent) {
  operationExpandedById.value[event.operationId] = !operationExpanded(event)
}

async function decideApproval(runId: string, event: ProcessingEvent, approved: boolean) {
  if (!event.approvalId) return
  try {
    await chat.decideApproval(runId, event.approvalId, approved)
  } catch (error: any) {
    chat.notice = error?.message || '审批操作失败'
  }
}

watch(() => chat.activeId, () => {
  operationExpandedById.value = {}
  const active = chat.active
  if (!active) return
  for (const run of active.runs) void chat.loadProcessing(run.runId)
}, { immediate: true })
</script>

<template>
  <section class="trajectory-panel" aria-label="执行轨迹">
    <div v-if="!chat.active" class="trajectory-empty">暂无对话</div>
    <div v-else-if="!runs.length" class="trajectory-empty">当前对话暂无处理过程。</div>
    <div v-for="run in runs" :key="run.runId" class="trajectory-run">
      <header class="trajectory-run-header">
        <div class="trajectory-run-identity">
          <strong>Run {{ run.runId.slice(0, 8) }}</strong>
          <span v-if="run.phase" class="trajectory-phase">{{ run.phase }}</span>
        </div>
        <span class="trajectory-run-status" :class="statusClass(run.status)">{{ run.status }}</span>
      </header>

      <div v-if="chat.skillByRun[run.runId]" class="trajectory-skill">
        <DshIcon name="skill" :size="14" class="trajectory-skill-icon" />
        <span class="trajectory-skill-label">Skill</span>
        <span class="trajectory-skill-name">{{ chat.skillByRun[run.runId] }}</span>
      </div>

      <div v-if="visibleTrajectoryEvents(run.runId).length" class="trajectory-events">
        <div v-for="event in visibleTrajectoryEvents(run.runId)" :key="event.sequence" class="trajectory-event">
          <span class="trajectory-seq">{{ event.sequence }}</span>
          <span class="trajectory-event-label">{{ event.label }}</span>
          <span v-if="event.kind" class="trajectory-event-kind">{{ event.kind }}</span>
          <span class="trajectory-event-status" :class="statusClass(event.status)">{{ event.status }}</span>
          <span v-if="event.toolId" class="trajectory-event-tool">{{ event.toolId }}</span>
          <span v-if="event.errorCode" class="error-code-badge">{{ event.errorCode }}</span>
        </div>
      </div>

      <div v-if="processingEvents(run.runId).length" class="trajectory-operations">
        <div v-for="event in processingEvents(run.runId)" :key="event.operationId" class="trajectory-operation" :class="{ 'is-failure': isFailedOperation(event.status) }">
          <button
            type="button"
            class="trajectory-operation-head"
            :aria-expanded="operationExpanded(event)"
            :aria-controls="`operation-details-${event.operationId}`"
            @click="toggleOperation(event)"
          >
            <DshIcon :name="toolIconName(event)" :size="14" class="trajectory-tool-icon" />
            <span class="trajectory-tool">{{ event.source === 'mcp' ? `MCP/${event.serverId || 'server'}` : 'Native' }} · {{ event.toolId }}</span>
            <span v-if="isFailedOperation(event.status)" class="trajectory-failure-label">{{ operationFailureLabel(event) }}</span>
            <span v-if="event.errorCode" class="error-code-badge">{{ event.errorCode }}</span>
            <span class="trajectory-operation-status" :class="statusClass(event.status)">{{ event.status }}</span>
            <span v-if="event.timingMs !== null" class="trajectory-time">{{ event.timingMs }} ms</span>
            <span class="trajectory-operation-toggle" aria-hidden="true">{{ operationExpanded(event) ? '−' : '+' }}</span>
          </button>
          <div v-if="isFailedOperation(event.status) && event.resultSummary" class="trajectory-failure-summary">{{ event.resultSummary }}</div>
          <div v-if="operationExpanded(event)" :id="`operation-details-${event.operationId}`" class="trajectory-operation-details">
            <div v-if="event.errorCode" class="trajectory-detail"><strong>错误码：</strong>{{ event.errorCode }}</div>
            <div v-if="event.resultSummary" class="trajectory-detail"><strong>完整摘要：</strong>{{ event.resultSummary }}</div>
            <div v-if="event.argumentsSummary" class="trajectory-detail"><strong>参数：</strong>{{ event.argumentsSummary }}</div>
            <div v-if="event.riskReason" class="trajectory-detail"><strong>风险：</strong>{{ event.riskReason }}</div>
            <div v-if="event.artifacts.length" class="trajectory-detail"><strong>Artifact：</strong>{{ event.artifacts.length }} 项 {{ event.artifacts.join(', ') }}</div>
            <div v-if="event.approvalId && event.status === 'awaiting_approval'" class="trajectory-approval" @click.stop>
              待审批
              <button type="button" @click="decideApproval(run.runId, event, true)">批准</button>
              <button type="button" @click="decideApproval(run.runId, event, false)">拒绝</button>
            </div>
          </div>
        </div>
      </div>
      <div v-if="!visibleTrajectoryEvents(run.runId).length && !processingEvents(run.runId).length" class="trajectory-empty trajectory-run-empty">暂无处理事件。</div>
    </div>
  </section>
</template>
