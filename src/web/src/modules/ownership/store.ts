import { defineStore } from 'pinia'

export type Actor = {
  kind: 'guest' | 'user' | 'temporary_guest'
  owner_id: string
  username?: string | null
}

type IdentityResponse = {
  actor: Actor
  access_token: string
  access_expires_at: string
  mode: 'durable' | 'temporary'
}

export type OwnershipDialog = 'login' | 'register' | 'password' | 'delete' | 'unavailable' | null

let refreshPromise: Promise<boolean> | null = null
let channel: BroadcastChannel | null = null

export const useOwnershipStore = defineStore('ownership', {
  state: () => ({
    actor: null as Actor | null,
    accessToken: '',
    accessExpiresAt: '',
    mode: 'temporary' as 'durable' | 'temporary',
    bootstrapped: false,
    loading: false,
    dialog: null as OwnershipDialog,
    error: '',
  }),
  getters: {
    isUser: (state) => state.actor?.kind === 'user',
    accountAvailable: (state) => state.mode === 'durable',
    modeLabel: (state) => state.mode === 'durable' ? '持久模式' : '临时匿名',
  },
  actions: {
    async bootstrap() {
      if (this.loading) return
      this.loading = true
      this.error = ''
      this.setupChannel()
      try {
        if (!await this.refresh()) await this.createGuest()
      } catch {
        this.error = '无法连接 VenAgent 服务，请确认后端正在运行。'
      } finally {
        this.bootstrapped = true
        this.loading = false
      }
    },
    async refresh(broadcast = true): Promise<boolean> {
      if (refreshPromise) return refreshPromise
      refreshPromise = (async () => {
        try {
          const response = await fetch('/api/auth/refresh', {
            method: 'POST',
            credentials: 'include',
          })
          if (!response.ok) return false
          this.acceptIdentity(await response.json(), broadcast)
          return true
        } catch {
          return false
        } finally {
          refreshPromise = null
        }
      })()
      return refreshPromise
    },
    async createGuest(broadcast = true) {
      const response = await fetch('/api/auth/guest', {
        method: 'POST',
        credentials: 'include',
      })
      if (!response.ok) throw new Error('guest unavailable')
      this.acceptIdentity(await response.json(), broadcast)
    },
    async revalidateIdentity() {
      this.actor = null
      this.accessToken = ''
      this.accessExpiresAt = ''
      if (!await this.refresh(false)) await this.createGuest(false)
    },
    async apiFetch(path: string, options: RequestInit = {}, retry = true): Promise<Response> {
      const headers = new Headers(options.headers)
      if (this.accessToken) headers.set('Authorization', `Bearer ${this.accessToken}`)
      const response = await fetch(path, { ...options, headers, credentials: 'include' })
      if (response.status !== 401 || !retry) return response
      if (await this.refresh()) return this.apiFetch(path, options, false)
      this.actor = null
      this.accessToken = ''
      await this.createGuest()
      window.dispatchEvent(new CustomEvent('venagent:identity-fallback'))
      return response
    },
    openDialog(dialog: Exclude<OwnershipDialog, null>) {
      this.error = ''
      if (!this.accountAvailable) {
        this.dialog = 'unavailable'
        return
      }
      this.dialog = dialog
    },
    closeDialog() {
      this.dialog = null
      this.error = ''
    },
    async authenticate(mode: 'login' | 'register', username: string, password: string) {
      this.loading = true
      this.error = ''
      try {
        const response = await this.apiFetch(`/api/auth/${mode}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        }, false)
        const data = await response.json().catch(() => ({}))
        if (!response.ok) {
          this.error = data.error?.message || '账号操作失败，请稍后重试。'
          return false
        }
        this.acceptIdentity(data)
        this.closeDialog()
        return true
      } catch {
        this.error = '无法连接账号服务，请稍后重试。'
        return false
      } finally {
        this.loading = false
      }
    },
    async logout(): Promise<boolean> {
      this.loading = true
      this.error = ''
      try {
        const response = await this.apiFetch('/api/auth/logout', { method: 'POST' }, false)
        const data = await response.json().catch(() => ({}))
        if (!response.ok) {
          this.error = data.error?.message || '退出失败，请稍后重试。'
          return false
        }
        this.acceptIdentity(data)
        return true
      } catch {
        this.error = '无法连接账号服务，当前账号仍保持登录。'
        return false
      } finally {
        this.loading = false
      }
    },
    async changePassword(currentPassword: string, newPassword: string) {
      this.loading = true
      this.error = ''
      try {
        const response = await this.apiFetch('/api/auth/password', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
        }, false)
        const data = await response.json().catch(() => ({}))
        if (!response.ok) {
          this.error = data.error?.message || '密码修改失败。'
          return false
        }
        this.acceptIdentity(data)
        this.closeDialog()
        return true
      } catch {
        this.error = '无法连接账号服务，密码没有修改。'
        return false
      } finally {
        this.loading = false
      }
    },
    async deleteAccount(currentPassword: string) {
      this.loading = true
      this.error = ''
      try {
        const response = await this.apiFetch('/api/auth/account', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ current_password: currentPassword, confirmed: true }),
        }, false)
        const data = await response.json().catch(() => ({}))
        if (!response.ok) {
          this.error = data.error?.message || '账号注销失败。'
          return false
        }
        this.actor = null
        this.accessToken = ''
        await this.createGuest()
        this.closeDialog()
        return true
      } catch {
        this.error = '无法连接账号服务，注销状态尚未确认。'
        return false
      } finally {
        this.loading = false
      }
    },
    acceptIdentity(data: IdentityResponse, broadcast = true) {
      this.actor = data.actor
      this.accessToken = data.access_token
      this.accessExpiresAt = data.access_expires_at
      this.mode = data.mode
      if (broadcast) channel?.postMessage({ type: 'identity-invalidated' })
    },
    setupChannel() {
      if (channel || typeof BroadcastChannel === 'undefined') return
      channel = new BroadcastChannel('venagent-identity')
      channel.onmessage = (event) => {
        if (event.data?.type !== 'identity-invalidated') return
        this.actor = null
        this.accessToken = ''
        this.accessExpiresAt = ''
        window.dispatchEvent(new CustomEvent('venagent:identity-invalidated'))
      }
      window.addEventListener('pagehide', () => {
        channel?.close()
        channel = null
      }, { once: true })
    },
  },
})
