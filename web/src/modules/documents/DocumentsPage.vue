<script setup lang="ts">
import { onMounted, ref } from 'vue'

import OwnershipDialog from '../ownership/OwnershipDialog.vue'
import { useOwnershipStore } from '../ownership/store'
import { useDocumentsStore } from './store'

const documents = useDocumentsStore()
const ownership = useOwnershipStore()
const fileInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)

const statusLabels: Record<string, string> = {
  uploaded: '已上传',
  parsing: '解析中',
  chunking: '分块中',
  indexing: '索引中',
  ready: '就绪',
  failed: '失败',
  deleted: '已删除',
}

const failureLabels: Record<string, string> = {
  needs_ocr: '扫描件/图片型 PDF，需要 OCR 支持',
  pdf_too_large: 'PDF 超过页数上限',
  parse_error: '解析失败',
  empty: '文档内容为空',
}

async function pickFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  for (const file of files) await documents.upload(file)
  await documents.load()
}

async function onDrop(event: DragEvent) {
  dragging.value = false
  const files = Array.from(event.dataTransfer?.files || [])
  for (const file of files) await documents.upload(file)
  await documents.load()
}

onMounted(async () => {
  await ownership.bootstrap()
  await documents.load()
})
</script>

<template>
  <main class="control-shell">
    <header class="control-header">
      <div>
        <div class="control-title">文档库</div>
        <div class="control-meta">上传文档构建知识库（txt / md / PDF，单文件 ≤ 64MB），聊天中可用 /rag 检索</div>
      </div>
      <div class="control-actions">
        <span v-if="ownership.isUser" class="settings-actor" title="已登录账号">{{ ownership.actor?.username || '' }}</span>
        <button v-else type="button" class="settings-login" @click="ownership.openDialog('register')">注册 / 登录</button>
        <RouterLink class="back-link" to="/">← 返回对话</RouterLink>
        <button type="button" title="刷新文档列表" aria-label="刷新文档列表" @click="documents.load()">↻ 刷新</button>
      </div>
    </header>

    <div v-if="documents.notice" class="control-notice" role="status">{{ documents.notice }}</div>

    <section class="control-section">
      <div class="control-section-head"><h2>上传文档</h2></div>
      <div
        class="upload-zone"
        :class="{ dragging }"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
        @click="fileInput?.click()"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf"
          multiple
          hidden
          @change="pickFiles"
        />
        <div v-if="documents.uploading" class="upload-hint">上传中…</div>
        <div v-else class="upload-hint">点击选择或拖拽文件到此处上传</div>
        <small class="upload-note">PDF 每页少于 80 个字符会被判定为扫描件（需 OCR，暂不支持）</small>
      </div>
    </section>

    <section class="control-section">
      <div class="control-section-head"><h2>文档列表</h2></div>
      <div v-if="documents.loading" class="control-empty">加载中…</div>
      <div v-else-if="!documents.documents.length" class="control-empty">知识库为空，请先上传文档。</div>
      <ul v-else class="document-list">
        <li v-for="record in documents.documents" :key="record.documentId" class="document-item">
          <div class="document-main">
            <div class="document-title">{{ record.title }}</div>
            <div class="document-meta">
              <span class="document-status" :class="record.status">{{ statusLabels[record.status] || record.status }}</span>
              <span v-if="record.failureReason" class="document-failure" :title="failureLabels[record.failureReason] || record.failureReason">
                {{ failureLabels[record.failureReason] || record.failureReason }}
              </span>
              <span v-else>{{ record.chunkCount }} 块</span>
              <span>{{ new Date(record.updatedAt).toLocaleString() }}</span>
            </div>
            <div v-if="record.status === 'indexing' || record.status === 'parsing' || record.status === 'chunking' || record.status === 'uploaded'" class="document-progress">
              <div class="progress-track"><div class="progress-fill" :style="{ width: documents.progressOf(record.documentId) + '%' }"></div></div>
              <span>{{ record.indexedCount }}/{{ record.chunkCount }}</span>
            </div>
          </div>
          <button type="button" class="document-delete" :disabled="record.status === 'deleted'" @click="documents.remove(record)">删除</button>
        </li>
      </ul>
    </section>
  </main>
  <OwnershipDialog @identity-changed="documents.load()" />
</template>

<style scoped>
.upload-zone {
  border: 2px dashed #c3cdda;
  border-radius: 10px;
  padding: 28px 16px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.upload-zone.dragging {
  border-color: #276ef1;
  background: #eef4ff;
}
.upload-hint {
  color: #42536a;
  font-size: 14px;
}
.upload-note {
  display: block;
  margin-top: 8px;
  color: #8a97a8;
  font-size: 12px;
}
.document-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.document-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid #e5e9f0;
  border-radius: 8px;
}
.document-main {
  flex: 1;
  min-width: 0;
}
.document-title {
  color: #23344a;
  font-size: 14px;
  font-weight: 600;
  word-break: break-all;
}
.document-meta {
  margin-top: 4px;
  display: flex;
  gap: 10px;
  align-items: center;
  color: #66758a;
  font-size: 12px;
}
.document-status {
  padding: 2px 8px;
  border-radius: 10px;
  background: #eef2f7;
  color: #42536a;
}
.document-status.ready {
  background: #e6f6ec;
  color: #1e7a45;
}
.document-status.failed {
  background: #fdecee;
  color: #a43a4e;
}
.document-failure {
  color: #a43a4e;
}
.document-progress {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #66758a;
  font-size: 12px;
}
.progress-track {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: #e5e9f0;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  border-radius: 3px;
  background: #276ef1;
  transition: width 0.3s;
}
.document-delete {
  border: 1px solid #e5b4bd;
  border-radius: 7px;
  background: #fff5f6;
  color: #a43a4e;
  padding: 7px 12px;
  font-size: 13px;
}
.document-delete:hover:not(:disabled) {
  background: #fdecee;
}
.document-delete:disabled {
  opacity: 0.5;
}
</style>
