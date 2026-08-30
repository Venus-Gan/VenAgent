import { createRouter, createWebHistory } from 'vue-router'

import ChatWorkspace from '../modules/chat/ChatWorkspace.vue'
import ControlPanel from '../modules/control/ControlPanel.vue'
import DocumentsPage from '../modules/documents/DocumentsPage.vue'
import SettingsPage from '../modules/settings/SettingsPage.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: ChatWorkspace },
    { path: '/documents', component: DocumentsPage },
    { path: '/control', component: ControlPanel },
    { path: '/settings', component: SettingsPage },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
