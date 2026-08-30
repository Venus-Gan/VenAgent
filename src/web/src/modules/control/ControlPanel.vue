<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { useOwnershipStore } from '../ownership/store'
import { useControlStore, type McpServer, type SkillItem } from './store'

const control = useControlStore()
const ownership = useOwnershipStore()
const showForm = ref(false)
const editingId = ref<string | null>(null)
const hubQuery = ref('')
const form = ref({
  server_id: '',
  name: '',
  transport: 'stdio' as 'stdio' | 'streamable_http',
  enabled: true,
  command: '',
  args: '',
  url: '',
  credential_ref: '',
  allow: '',
  deny: '',
  declared_tools: '[]',
})

function openNew() {
  editingId.value = null
  form.value = {
    server_id: '',
    name: '',
    transport: 'stdio',
    enabled: true,
    command: '',
    args: '',
    url: '',
    credential_ref: '',
    allow: '',
    deny: '',
    declared_tools: '[]',
  }
  showForm.value = true
}

function openEdit(server: McpServer) {
  editingId.value = server.server_id
  form.value = {
    server_id: server.server_id,
    name: server.name,
    transport: server.transport,
    enabled: server.enabled,
    command: server.command || '',
    args: server.args.join(' '),
    url: server.url || '',
    credential_ref: server.credential_ref || '',
    allow: server.allow.join(', '),
    deny: server.deny.join(', '),
    declared_tools: JSON.stringify(server.declared_tools, null, 2),
  }
  showForm.value = true
}

function parseTools(raw: string): any[] {
  const value = raw.trim()
  if (!value) return []
  const parsed = JSON.parse(value)
  if (!Array.isArray(parsed)) throw new Error('declared_tools 必须是 JSON 数组')
  return parsed
}

async function save() {
  try {
    const value = form.value
    await control.saveServer({
      server_id: value.server_id,
      name: value.name,
      transport: value.transport,
      enabled: value.enabled,
      command: value.command || null,
      args: value.args.split(/\s+/).filter(Boolean),
      url: value.url || null,
      credential_ref: value.credential_ref || null,
      allow: value.allow.split(',').map(item => item.trim()).filter(Boolean),
      deny: value.deny.split(',').map(item => item.trim()).filter(Boolean),
      declared_tools: parseTools(value.declared_tools),
    })
    showForm.value = false
  } catch (error: any) {
    control.notice = error?.message || '保存失败'
  }
}

async function toggle(server: McpServer) {
  try {
    await control.saveServer({ ...server, enabled: !server.enabled })
  } catch (error: any) {
    control.notice = error?.message || '启停失败'
  }
}

async function remove(server: McpServer) {
  try {
    await control.removeServer(server)
  } catch {
    control.notice = '删除失败'
  }
}

async function discover(server: McpServer) {
  try {
    await control.discoverServer(server)
  } catch (error: any) {
    control.notice = error?.message || '连接检测失败'
  }
}

async function searchHub() {
  try {
    await control.searchHub(hubQuery.value)
  } catch {
    control.notice = 'Skill 广场搜索失败'
  }
}

async function install(skillId: string) {
  try {
    await control.installSkill(skillId)
  } catch (error: any) {
    control.notice = error?.message || '安装失败'
  }
}

async function setSkill(skill: SkillItem, enabled: boolean) {
  try {
    await control.setSkillEnabled(skill, enabled)
  } catch {
    control.notice = 'Skill 启停失败'
  }
}

async function uninstall(skill: SkillItem) {
  if (!window.confirm(`卸载 Skill“${skill.name}”？`)) return
  try {
    await control.uninstallSkill(skill)
  } catch {
    control.notice = 'Skill 卸载失败'
  }
}

onMounted(async () => {
  await ownership.bootstrap()
  await control.loadAll()
})
</script>

<template>
  <main class="control-shell">
    <header class="control-header">
      <div>
        <div class="control-title">M06 控制面</div>
        <div class="control-meta">工具目录、MCP、Skill 与审批状态</div>
      </div>
      <div class="control-actions">
        <RouterLink class="back-link" to="/">← 返回对话</RouterLink>
        <button type="button" title="刷新控制面" aria-label="刷新控制面" @click="control.loadAll()">↻ 刷新</button>
      </div>
    </header>

    <div v-if="control.notice" class="control-notice" role="status">{{ control.notice }}</div>

    <section class="control-section">
      <div class="control-section-head">
        <h2>MCP Servers</h2>
        <button type="button" @click="openNew">新增 Server</button>
      </div>
      <form v-if="showForm" class="server-form" @submit.prevent="save">
        <label>ID <input v-model="form.server_id" required :disabled="editingId !== null" /></label>
        <label>名称 <input v-model="form.name" required /></label>
        <label>传输
          <select v-model="form.transport">
            <option value="stdio">stdio</option>
            <option value="streamable_http">streamable_http</option>
          </select>
        </label>
        <label>命令 <input v-model="form.command" /></label>
        <label>参数 <input v-model="form.args" placeholder="launcher.js serve" /></label>
        <label>URL <input v-model="form.url" /></label>
        <label>凭据引用 <input v-model="form.credential_ref" placeholder="ENV_VAR_NAME" /></label>
        <label>allow <input v-model="form.allow" placeholder="tool_a, tool_b" /></label>
        <label>deny <input v-model="form.deny" placeholder="tool_c" /></label>
        <label>启用 <input v-model="form.enabled" type="checkbox" /></label>
        <label class="span2">declared_tools JSON
          <textarea v-model="form.declared_tools" rows="6" spellcheck="false" />
        </label>
        <div class="form-actions">
          <button type="submit">保存</button>
          <button type="button" @click="showForm = false">取消</button>
        </div>
      </form>
      <div v-if="!control.servers.length" class="control-empty">还没有 MCP Server。</div>
      <div v-else class="server-list">
        <article v-for="server in control.servers" :key="server.server_id" class="server-card">
          <div>
            <strong>{{ server.name }}</strong>
            <span>{{ server.server_id }} · {{ server.transport }} · {{ server.enabled ? '启用' : '停用' }}</span>
          </div>
          <div class="server-card-actions">
            <button type="button" @click="discover(server)">连接检测</button>
            <button type="button" @click="toggle(server)">{{ server.enabled ? '停用' : '启用' }}</button>
            <button type="button" @click="openEdit(server)">编辑</button>
            <button type="button" class="danger" @click="remove(server)">删除</button>
          </div>
        </article>
      </div>
    </section>

    <section class="control-section">
      <div class="control-section-head"><h2>工具目录</h2></div>
      <div class="tool-grid">
        <div v-for="tool in control.tools" :key="tool.tool_id" class="tool-card" :class="{ blocked: !tool.exposed }">
          <strong>{{ tool.public_name }}</strong>
          <span>{{ tool.source }} · {{ tool.risk }}</span>
          <small>{{ tool.exposed ? 'exposed' : tool.unavailable_reason || 'blocked' }}</small>
        </div>
        <div v-if="!control.tools.length" class="control-empty">工具目录为空。</div>
      </div>
    </section>

    <section class="control-section">
      <div class="control-section-head"><h2>Skill 广场</h2></div>
      <div class="hub-search">
        <input v-model="hubQuery" placeholder="搜索 GitHub Skill" @keydown.enter.prevent="searchHub" />
        <button type="button" @click="searchHub">搜索</button>
      </div>
      <div v-if="control.hubDegraded" class="control-muted">广场暂时不可用：{{ control.hubReason }}</div>
      <h3 class="hub-section-title">官方精选</h3>
      <div v-if="!control.featuredSkills.length" class="control-empty">暂无官方精选 Skill。</div>
      <div v-for="item in control.featuredSkills" :key="item.skill_id" class="hub-item">
        <div>
          <strong>{{ item.name }}</strong>
          <span>{{ item.description }}</span>
        </div>
        <button type="button" @click="install(item.skill_id)">安装</button>
      </div>
      <h3 class="hub-section-title">社区 / GitHub</h3>
      <div v-if="!control.hubItems.length" class="control-empty">暂无社区 Skill，搜索后显示结果。</div>
      <div v-for="item in control.hubItems" :key="item.skill_id" class="hub-item">
        <div>
          <strong>{{ item.name || item.repo_full_name }}</strong>
          <span>{{ item.description }}</span>
        </div>
        <button type="button" @click="install(item.skill_id)">安装</button>
      </div>
    </section>

    <section class="control-section">
      <div class="control-section-head"><h2>已安装 Skill</h2></div>
      <div v-if="!control.skills.length" class="control-empty">尚未安装 Skill。</div>
      <div v-for="skill in control.skills" :key="skill.skill_id" class="skill-row">
        <div>
          <strong>{{ skill.name }}</strong>
          <span>{{ skill.version }} · {{ skill.description }}</span>
        </div>
        <div class="skill-row-actions">
          <button type="button" @click="setSkill(skill, !skill.enabled)">{{ skill.enabled ? '停用' : '启用' }}</button>
          <button type="button" class="danger" @click="uninstall(skill)">卸载</button>
        </div>
      </div>
    </section>
  </main>
</template>
