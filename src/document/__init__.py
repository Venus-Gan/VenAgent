"""M08 文档库领域包。"""

from .ports import (
    DocumentRecord,
    DocumentStore,
    DocumentStoreError,
    DocumentVersion,
    RagChunk,
)
from .service import DocumentService, DocumentUploadError

__all__ = [
    "DocumentRecord",
    "DocumentService",
    "DocumentStore",
    "DocumentStoreError",
    "DocumentUploadError",
    "DocumentVersion",
    "RagChunk",
]
