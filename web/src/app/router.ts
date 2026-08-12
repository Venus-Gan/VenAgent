import { createRouter, createWebHistory } from 'vue-router'

import ChatWorkspace from '../modules/chat/ChatWorkspace.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: ChatWorkspace },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
