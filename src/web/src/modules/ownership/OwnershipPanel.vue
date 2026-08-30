<script setup lang="ts">
import { useOwnershipStore } from './store'

const emit = defineEmits<{ identityChanged: [] }>()
const ownership = useOwnershipStore()

async function logout() {
  if (await ownership.logout()) emit('identityChanged')
}
</script>

<template>
  <section class="account-panel" aria-label="账号">
    <div class="identity-row">
      <span class="identity-dot" :class="ownership.mode" />
      <div>
        <strong>{{ ownership.isUser ? ownership.actor?.username : '匿名使用' }}</strong>
        <small>{{ ownership.modeLabel }}</small>
      </div>
    </div>
    <div v-if="ownership.isUser" class="account-actions">
      <button type="button" @click="ownership.openDialog('password')">修改密码</button>
      <button type="button" @click="logout">退出</button>
      <button class="danger-link" type="button" @click="ownership.openDialog('delete')">注销账号</button>
    </div>
    <div v-else class="account-actions">
      <button type="button" @click="ownership.openDialog('login')">登录</button>
      <button type="button" @click="ownership.openDialog('register')">注册</button>
    </div>
  </section>
</template>
