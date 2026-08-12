<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import { useOwnershipStore } from './store'

const emit = defineEmits<{ identityChanged: [] }>()
const ownership = useOwnershipStore()
const username = ref('')
const password = ref('')
const currentPassword = ref('')
const newPassword = ref('')
const firstInput = ref<HTMLInputElement | null>(null)

const title = computed(() => ({
  login: '登录账号', register: '创建账号', password: '修改密码',
  delete: '注销账号', unavailable: '账号功能暂不可用',
}[ownership.dialog || 'login']))

watch(() => ownership.dialog, async (value) => {
  if (!value) return
  username.value = ''
  password.value = ''
  currentPassword.value = ''
  newPassword.value = ''
  await nextTick()
  firstInput.value?.focus()
})

async function submit() {
  if (ownership.dialog === 'login' || ownership.dialog === 'register') {
    if (await ownership.authenticate(ownership.dialog, username.value.trim(), password.value)) emit('identityChanged')
  } else if (ownership.dialog === 'password') {
    if (await ownership.changePassword(currentPassword.value, newPassword.value)) emit('identityChanged')
  } else if (ownership.dialog === 'delete') {
    if (await ownership.deleteAccount(currentPassword.value)) emit('identityChanged')
  }
}
</script>

<template>
  <div v-if="ownership.dialog" class="dialog-backdrop" @mousedown.self="ownership.closeDialog()">
    <section class="dialog-card" role="dialog" aria-modal="true" :aria-label="title" @keydown.esc="ownership.closeDialog()">
      <header>
        <div>
          <h2>{{ title }}</h2>
          <p v-if="ownership.dialog === 'login' || ownership.dialog === 'register'">匿名历史不会迁移到账号，登录后账号历史从零开始。</p>
        </div>
        <button type="button" aria-label="关闭" @click="ownership.closeDialog()">×</button>
      </header>

      <div v-if="ownership.dialog === 'unavailable'" class="dialog-copy">
        <p>持久化当前不可用，账号操作没有执行。</p>
        <p>当前只能使用临时匿名对话，服务重启后内容可能丢失。</p>
        <div class="dialog-actions">
          <button type="button" @click="ownership.closeDialog()">继续匿名使用</button>
          <button type="button" @click="ownership.closeDialog(); ownership.bootstrap()">重新检查</button>
        </div>
      </div>

      <form v-else @submit.prevent="submit">
        <label v-if="ownership.dialog === 'login' || ownership.dialog === 'register'">
          用户名
          <input ref="firstInput" v-model="username" autocomplete="username" minlength="3" maxlength="32" required />
        </label>
        <label v-if="ownership.dialog === 'login' || ownership.dialog === 'register'">
          密码
          <input v-model="password" type="password" :autocomplete="ownership.dialog === 'register' ? 'new-password' : 'current-password'" minlength="8" maxlength="128" required />
        </label>
        <label v-if="ownership.dialog === 'password' || ownership.dialog === 'delete'">
          当前密码
          <input ref="firstInput" v-model="currentPassword" type="password" autocomplete="current-password" minlength="8" maxlength="128" required />
        </label>
        <label v-if="ownership.dialog === 'password'">
          新密码
          <input v-model="newPassword" type="password" autocomplete="new-password" minlength="8" maxlength="128" required />
        </label>
        <p v-if="ownership.dialog === 'delete'" class="danger-copy">注销后账号、全部对话和运行状态将立即不可访问并永久删除，无法恢复。</p>
        <p v-if="ownership.error" class="form-error" role="alert">{{ ownership.error }}</p>
        <div class="dialog-actions">
          <button type="button" @click="ownership.closeDialog()">取消</button>
          <button :class="{ danger: ownership.dialog === 'delete' }" type="submit" :disabled="ownership.loading">
            {{ ownership.loading ? '处理中…' : ownership.dialog === 'delete' ? '确认永久注销' : '确认' }}
          </button>
        </div>
      </form>
    </section>
  </div>
</template>
