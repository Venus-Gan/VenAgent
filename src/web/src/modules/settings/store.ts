import { defineStore } from 'pinia'

import { useOwnershipStore } from '../ownership/store'

export type ThinkingLevel = 'none' | 'low' | 'medium' | 'high'

export type SettingsLlm = {
  provider: string
  model: string
  base_url: string | null
  api_mode: string | null
  api_key_configured: boolean
  thinking_level: ThinkingLevel
}

export type SettingsSnapshot = {
  llm: SettingsLlm
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

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    snapshot: null as SettingsSnapshot | null,
    loading: false,
    saving: false,
    notice: '',
    error: '',
  }),
  actions: {
    async load() {
      const ownership = useOwnershipStore()
      this.loading = true
      this.error = ''
      try {
        const response = await ownership.apiFetch('/api/settings')
        const data = await readJson(response)
        if (!response.ok) throw new Error(data.error?.message || '设置读取失败')
        this.snapshot = data
      } catch (error: any) {
        this.error = error?.message || '无法连接设置服务。'
      } finally {
        this.loading = false
      }
    },
    async save(payload: {
      provider: string
      api_key: string
      model: string
      base_url: string
      api_mode: string | null
      thinking_level: ThinkingLevel
    }) {
      const ownership = useOwnershipStore()
      this.saving = true
      this.notice = ''
      this.error = ''
      try {
        const response = await ownership.apiFetch('/api/settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        const data = await readJson(response)
        if (!response.ok) {
          this.error = data.error?.message || '设置保存失败，请检查输入。'
          return false
        }
        this.snapshot = data
        this.notice = '已保存。重启后端后生效。'
        return true
      } catch (error: any) {
        this.error = error?.message || '无法连接设置服务，配置没有保存。'
        return false
      } finally {
        this.saving = false
      }
    },
  },
})
