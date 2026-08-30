import { defineStore } from 'pinia'

import { useOwnershipStore } from '../ownership/store'

export type McpToolManifest = {
  name: string
  description: string
  input_schema: Record<string, any>
  read_only_hint: boolean
  destructive_hint: boolean
}

export type McpServer = {
  server_id: string
  name: string
  transport: 'stdio' | 'streamable_http'
  enabled: boolean
  command: string | null
  args: string[]
  url: string | null
  credential_ref: string | null
  allow: string[]
  deny: string[]
  declared_tools: McpToolManifest[]
}

export type ToolItem = {
  tool_id: string
  public_name: string
  source: string
  risk: string
  exposed: boolean
  unavailable_reason: string | null
}

export type SkillItem = {
  skill_id: string
  name: string
  version: string
  description: string
  enabled: boolean
}

export type HubCandidate = {
  skill_id: string
  name: string
  source: 'official' | 'github'
  repo_full_name: string
  description: string
  topics: string[]
  stars: number
  source_url: string
  updated_at: string | null
}

async function readJson(response: Response): Promise<any> {
  const body = await response.text()
  if (!body) return {}
  try {
    return JSON.parse(body)
  } catch {
    return {}
  }
}

export const useControlStore = defineStore('control', {
  state: () => ({
    servers: [] as McpServer[],
    tools: [] as ToolItem[],
    catalogRevision: 0,
    skills: [] as SkillItem[],
    featuredSkills: [] as HubCandidate[],
    hubItems: [] as HubCandidate[],
    hubDegraded: false,
    hubReason: '',
    loading: false,
    notice: '',
  }),
  actions: {
    async loadAll() {
      this.loading = true
      this.notice = ''
      try {
        await Promise.all([
          this.loadServers(),
          this.loadCatalog(),
          this.loadSkills(),
          this.searchHub(''),
        ])
      } catch {
        this.notice = '控制面数据加载失败，请稍后重试。'
      } finally {
        this.loading = false
      }
    },
    async loadServers() {
      const ownership = useOwnershipStore()
      const response = await ownership.apiFetch('/api/mcp/servers')
      if (!response.ok) throw new Error()
      this.servers = await readJson(response)
    },
    async loadCatalog() {
      const ownership = useOwnershipStore()
      const response = await ownership.apiFetch('/api/tools/catalog')
      if (!response.ok) throw new Error()
      const data = await readJson(response)
      this.tools = data.tools || []
      this.catalogRevision = data.catalog_revision || 0
    },
    async loadSkills() {
      const ownership = useOwnershipStore()
      const response = await ownership.apiFetch('/api/skills')
      if (!response.ok) throw new Error()
      this.skills = await readJson(response)
    },
    async saveServer(payload: Record<string, unknown>) {
      const ownership = useOwnershipStore()
      const url = payload.server_id
        ? '/api/mcp/servers/' + encodeURIComponent(String(payload.server_id))
        : '/api/mcp/servers'
      const response = await ownership.apiFetch(url, {
        method: payload.server_id ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await readJson(response)
      if (!response.ok) throw new Error(data.error?.message || '保存失败')
      await this.loadAll()
    },
    async removeServer(server: McpServer) {
      if (!confirm(`删除 MCP Server “${server.name}”？`)) return
      const ownership = useOwnershipStore()
      const response = await ownership.apiFetch(
        '/api/mcp/servers/' + encodeURIComponent(server.server_id),
        { method: 'DELETE' },
      )
      if (!response.ok && response.status !== 404) throw new Error()
      await this.loadAll()
    },
    async discoverServer(server: McpServer) {
      const ownership = useOwnershipStore()
      const response = await ownership.apiFetch(
        '/api/mcp/servers/' + encodeURIComponent(server.server_id) + '/discover',
      )
      const data = await readJson(response)
      if (!response.ok) throw new Error(data.error?.message || '连接检测失败')
      await this.loadAll()
      this.notice = `已发现 ${data.tools?.length || 0} 个 MCP 工具。`
    },
    async searchHub(query: string) {
      const ownership = useOwnershipStore()
      const response = await ownership.apiFetch(
        '/api/skills/hub?query=' + encodeURIComponent(query),
      )
      const data = await readJson(response)
      if (!response.ok) throw new Error()
      this.hubItems = data.items || []
      this.featuredSkills = data.featured || []
      this.hubDegraded = data.degraded === true
      this.hubReason = data.reason || ''
    },
    async installSkill(skillId: string) {
      const ownership = useOwnershipStore()
      const response = await ownership.apiFetch('/api/skills/hub/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_id: skillId }),
      })
      const data = await readJson(response)
      if (!response.ok) throw new Error(data.error?.message || '安装失败')
      await this.loadSkills()
      this.notice = `已安装 Skill：${data.name}`
    },
    async uninstallSkill(skill: SkillItem) {
      const ownership = useOwnershipStore()
      const response = await ownership.apiFetch(
        '/api/skills/' + encodeURIComponent(skill.skill_id),
        { method: 'DELETE' },
      )
      if (!response.ok) throw new Error('卸载失败')
      this.skills = this.skills.filter(item => item.skill_id !== skill.skill_id)
      this.notice = `已卸载 Skill：${skill.name}`
    },
    async setSkillEnabled(skill: SkillItem, enabled: boolean) {
      const ownership = useOwnershipStore()
      const response = await ownership.apiFetch(
        '/api/skills/' + encodeURIComponent(skill.skill_id),
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled }),
        },
      )
      const data = await readJson(response)
      if (!response.ok) throw new Error(data.error?.message || '操作失败')
      skill.enabled = data.enabled
    },
  },
})
