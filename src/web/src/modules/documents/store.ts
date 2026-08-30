import { defineStore } from 'pinia'

import { useOwnershipStore } from '../ownership/store'

export type DocumentRecord = {
  documentId: string
  title: string
  docType: string
  source: string
  status: string
  failureReason: string | null
  chunkCount: number
  indexedCount: number
  createdAt: number
  updatedAt: number
}

async function readJson(response: Response): Promise<any> {
  const body = await response.text()
  if (!body) return {}
  try {
    return JSON.parse(body)
  } catch {
    return { error: { message: response.ok ? '服务响应格式无效。' : '服务暂时不可用，请稍后重试。' } }
  }
}

function mapDocument(item: any): DocumentRecord {
  return {
    documentId: item.document_id,
    title: item.title,
    docType: item.doc_type,
    source: item.source,
    status: item.status,
    failureReason: item.failure_reason ?? null,
    chunkCount: item.chunk_count ?? 0,
    indexedCount: item.indexed_count ?? 0,
    createdAt: Date.parse(item.created_at ?? item.updated_at),
    updatedAt: Date.parse(item.updated_at),
  }
}

export const useDocumentsStore = defineStore('documents', {
  state: () => ({
    documents: [] as DocumentRecord[],
    loading: false,
    uploading: false,
    notice: '',
  }),
  getters: {
    progressOf(state) {
      return (documentId: string) => {
        const record = state.documents.find(item => item.documentId === documentId)
        if (!record || record.chunkCount === 0) return 0
        return Math.min(100, Math.round((record.indexedCount / record.chunkCount) * 100))
      }
    },
  },
  actions: {
    async load() {
      const ownership = useOwnershipStore()
      this.loading = true
      this.notice = ''
      try {
        const response = await ownership.apiFetch('/api/documents?limit=200')
        if (!response.ok) throw new Error()
        const data = await readJson(response)
        this.documents = (data.documents || []).map(mapDocument)
      } catch {
        this.notice = '文档列表暂时无法读取，请稍后重试。'
      } finally {
        this.loading = false
      }
    },
    async upload(file: File) {
      const ownership = useOwnershipStore()
      this.uploading = true
      this.notice = ''
      try {
        const form = new FormData()
        form.append('file', file)
        const response = await ownership.apiFetch('/api/documents', {
          method: 'POST',
          body: form,
        })
        const data = await readJson(response)
        if (!response.ok) {
          this.notice = data.error?.message || '上传失败，请稍后重试。'
          return
        }
        const record = mapDocument(data)
        const index = this.documents.findIndex(item => item.documentId === record.documentId)
        if (index >= 0) this.documents[index] = record
        else this.documents.unshift(record)
        if (record.status === 'failed') {
          this.notice = `文档处理失败：${record.failureReason || '未知原因'}，可删除后重新上传。`
        }
      } catch (error: any) {
        this.notice = error?.message || '上传失败，请稍后重试。'
      } finally {
        this.uploading = false
      }
    },
    async remove(record: DocumentRecord) {
      if (!confirm(`删除“${record.title}”？此操作无法撤销。`)) return
      const ownership = useOwnershipStore()
      try {
        const response = await ownership.apiFetch(
          '/api/documents/' + encodeURIComponent(record.documentId),
          { method: 'DELETE' },
        )
        if (!response.ok && response.status !== 404) throw new Error()
        this.documents = this.documents.filter(item => item.documentId !== record.documentId)
      } catch {
        this.notice = '删除失败，文档仍保留。'
      }
    },
  },
})
