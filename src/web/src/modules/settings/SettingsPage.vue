<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import OwnershipDialog from '../ownership/OwnershipDialog.vue'
import { useOwnershipStore } from '../ownership/store'
import { useSettingsStore, type ThinkingLevel } from './store'

const settings = useSettingsStore()
const ownership = useOwnershipStore()

type Protocol = 'anthropic' | 'responses' | 'completions'

const form = ref({
  protocol: 'responses' as Protocol,
  apiKey: '',
  model: '',
  baseUrl: '',
  thinkingLevel: 'none' as ThinkingLevel,
})

const protocolOptions: { value: Protocol; label: string }[] = [
  { value: 'anthropic', label: 'Anthropic 原生 API' },
  { value: 'responses', label: 'OpenAI Responses API' },
  { value: 'completions', label: 'OpenAI Chat Completions' },
]

const thinkingOptions: { value: ThinkingLevel; label: string }[] = [
  { value: 'none', label: '无思考（快速）' },
  { value: 'low', label: '低（4096 budget / minimal）' },
  { value: 'medium', label: '中（16384 budget / medium）' },
  { value: 'high', label: '高（32768 budget / high）' },
]

const thinkingDisabled = computed(() => form.value.protocol === 'completions')

const isOwner = computed(() => ownership.isUser)
const actorLabel = computed(() => ownership.actor?.username || '')

function snapshotToForm() {
  const llm = settings.snapshot?.llm
  if (!llm) return
  form.value.protocol =
    llm.provider === 'anthropic'
      ? 'anthropic'
      : llm.api_mode === 'responses'
        ? 'responses'
        : 'completions'
  form.value.model = llm.model
  form.value.baseUrl = llm.base_url || ''
  form.value.thinkingLevel = llm.thinking_level || 'none'
}

async function save() {
  const protocol = form.value.protocol
  const baseUrl = form.value.baseUrl.trim()
  const provider =
    protocol === 'anthropic'
      ? 'anthropic'
      : baseUrl
        ? 'openai_compatible'
        : 'openai'
  const apiMode = protocol === 'anthropic' ? null : protocol
  const ok = await settings.save({
    provider,
    api_key: form.value.apiKey.trim(),
    model: form.value.model.trim(),
    base_url: baseUrl,
    api_mode: apiMode,
    thinking_level:
      thinkingDisabled.value ? 'none' : form.value.thinkingLevel,
  })
  if (ok) {
    form.value.apiKey = ''
    snapshotToForm()
  }
}

onMounted(async () => {
  await ownership.bootstrap()
  await settings.load()
  snapshotToForm()
})
</script>

<template>
  <main class="control-shell">
    <header class="control-header">
      <div>
        <div class="control-title">设置</div>
        <div class="control-meta">LLM 连接配置（写入 config.yaml，重启后端后生效）</div>
      </div>
      <div class="control-actions">
        <span v-if="isOwner" class="settings-actor" title="已登录账号">{{ actorLabel }}</span>
        <button v-else type="button" class="settings-login" @click="ownership.openDialog('register')">注册 / 登录</button>
        <RouterLink class="back-link" to="/control">控制面</RouterLink>
        <RouterLink class="back-link" to="/">← 返回对话</RouterLink>
        <button type="button" title="刷新设置" aria-label="刷新设置" @click="settings.load().then(snapshotToForm)">↻ 刷新</button>
      </div>
    </header>

    <div v-if="settings.notice" class="control-notice" role="status">{{ settings.notice }}</div>
    <div v-if="settings.error" class="settings-error" role="alert">{{ settings.error }}</div>

    <section class="control-section">
      <div class="control-section-head"><h2>LLM 连接</h2></div>
      <form class="server-form" @submit.prevent="save">
        <label>API 协议
          <select v-model="form.protocol">
            <option v-for="option in protocolOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
        <label>API Key
          <input
            v-model="form.apiKey"
            type="password"
            autocomplete="off"
            :placeholder="settings.snapshot?.llm.api_key_configured ? '已保存（留空保持不变）' : 'sk-...'"
          />
        </label>
        <label>模型
          <input v-model="form.model" required placeholder="如 gpt-4o / claude-sonnet-4-5" />
        </label>
        <label v-if="form.protocol !== 'anthropic'">Base URL
          <input v-model="form.baseUrl" placeholder="留空使用官方端点；填第三方兼容服务地址" />
        </label>
        <label>思考强度
          <select v-model="form.thinkingLevel" :disabled="thinkingDisabled">
            <option v-for="option in thinkingOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <small v-if="thinkingDisabled" class="settings-hint">Chat Completions 协议不支持思考强度，已按无思考保存。</small>
        </label>
        <div class="form-actions">
          <button type="submit" :disabled="settings.saving">{{ settings.saving ? '保存中…' : '保存' }}</button>
        </div>
      </form>
    </section>

    <section class="control-section">
      <div class="control-section-head"><h2>当前生效配置</h2></div>
      <div v-if="!settings.snapshot" class="control-empty">加载中…</div>
      <dl v-else class="settings-overview">
        <div><dt>Provider</dt><dd>{{ settings.snapshot.llm.provider || '（未配置）' }}</dd></div>
        <div><dt>模型</dt><dd>{{ settings.snapshot.llm.model || '（未配置）' }}</dd></div>
        <div><dt>Base URL</dt><dd>{{ settings.snapshot.llm.base_url || '（默认端点）' }}</dd></div>
        <div><dt>API 协议</dt><dd>{{ settings.snapshot.llm.provider === 'anthropic' ? '（原生）' : (settings.snapshot.llm.api_mode || '（原生）') }}</dd></div>
        <div><dt>API Key</dt><dd>{{ settings.snapshot.llm.api_key_configured ? '已配置' : '未配置' }}</dd></div>
        <div><dt>思考强度</dt><dd>{{ settings.snapshot.llm.thinking_level || 'none' }}</dd></div>
      </dl>
    </section>
  </main>
  <OwnershipDialog @identity-changed="settings.load().then(snapshotToForm)" />
</template>

<style scoped>
.settings-error {
  margin-top: 16px;
  padding: 10px 14px;
  border-radius: 6px;
  background: #fdecee;
  color: #a43a4e;
  font-size: 13px;
}
.settings-actor {
  padding: 7px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  background: #ffffff;
  color: #42536a;
  font-size: 13px;
}
.settings-login {
  border: 1px solid #276ef1;
  border-radius: 7px;
  background: #276ef1;
  color: #ffffff;
  padding: 7px 10px;
  font-size: 13px;
}
.settings-login:hover {
  background: #1d63d8;
}
.settings-hint {
  color: #8a97a8;
  font-size: 12px;
}
.settings-overview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px 24px;
  margin: 0;
}
.settings-overview div {
  padding: 10px 12px;
  border: 1px solid #e5e9f0;
  border-radius: 8px;
}
.settings-overview dt {
  color: #66758a;
  font-size: 12px;
}
.settings-overview dd {
  margin: 4px 0 0;
  color: #23344a;
  font-size: 14px;
  word-break: break-all;
}
</style>
