"""M08 文档库 HTTP routes：上传/列表/详情/删除/重传（per-owner，写操作需 Origin）。"""

from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict

from ....config import AppConfig
from ....document import (
    DocumentRecord,
    DocumentService,
    DocumentStoreError,
    DocumentUploadError,
)
from ....ownership.errors import AccountRequired
from ....ownership.service import OwnershipService
from ..auth import current_actor, require_origin
from ..errors import ApiError, ownership_api_error, persistence_api_error


class DocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str
    doc_type: str
    source: str
    status: str
    failure_reason: str | None = None
    chunk_count: int = 0
    indexed_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[DocumentResponse]


class DocumentDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: bool
    chunk_ids: list[int]


def _document_response(record: DocumentRecord) -> DocumentResponse:
    return DocumentResponse(
        document_id=record.document_id,
        title=record.title,
        doc_type=record.doc_type,
        source=record.source,
        status=record.status,
        failure_reason=record.failure_reason,
        chunk_count=record.chunk_count,
        indexed_count=record.indexed_count,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def register_document_routes(
    app: FastAPI,
    service: DocumentService | None,
    ownership: OwnershipService,
    config: AppConfig,
) -> None:
    def _require_service(request: Request) -> DocumentService:
        if service is None:
            raise persistence_api_error()
        return service

    @app.post("/api/documents", response_model=DocumentResponse, status_code=201)
    async def upload_document(
        request: Request,
        file: UploadFile = File(...),
        title: str | None = Form(default=None),
    ) -> DocumentResponse:
        require_origin(request, config)
        actor = current_actor(request, ownership)
        if actor.kind != "user":
            raise ownership_api_error(AccountRequired())
        doc_service = _require_service(request)
        content = await file.read()
        filename = file.filename or "document.txt"
        try:
            record = doc_service.upload(
                actor.owner_id, filename=filename, content=content, title=title
            )
        except DocumentUploadError as exc:
            raise ApiError(
                413 if exc.code == "document_too_large" else 422,
                exc.code,
                str(exc),
            ) from exc
        except DocumentStoreError:
            raise persistence_api_error() from None
        return _document_response(record)

    @app.put("/api/documents/{document_id}", response_model=DocumentResponse)
    async def reingest_document(
        document_id: str,
        request: Request,
        file: UploadFile = File(...),
    ) -> DocumentResponse:
        require_origin(request, config)
        actor = current_actor(request, ownership)
        if actor.kind != "user":
            raise ownership_api_error(AccountRequired())
        doc_service = _require_service(request)
        content = await file.read()
        filename = file.filename or "document.txt"
        try:
            record = doc_service.reingest(
                actor.owner_id, document_id, filename=filename, content=content
            )
        except DocumentUploadError as exc:
            raise ApiError(
                413 if exc.code == "document_too_large" else 422,
                exc.code,
                str(exc),
            ) from exc
        except DocumentStoreError as exc:
            if "not found" in str(exc):
                raise ApiError(404, "document_not_found", "文档不存在") from exc
            raise persistence_api_error() from None
        return _document_response(record)

    @app.get("/api/documents", response_model=DocumentListResponse)
    def list_documents(
        request: Request,
        status: str | None = Query(default=None),
        before: datetime | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> DocumentListResponse:
        actor = current_actor(request, ownership)
        doc_service = _require_service(request)
        try:
            items = doc_service.list(
                actor.owner_id, status=status, before=before, limit=limit
            )
        except DocumentStoreError:
            raise persistence_api_error() from None
        return DocumentListResponse(
            documents=[_document_response(item) for item in items]
        )

    @app.get("/api/documents/{document_id}", response_model=DocumentResponse)
    def document_detail(document_id: str, request: Request) -> DocumentResponse:
        actor = current_actor(request, ownership)
        doc_service = _require_service(request)
        try:
            record = doc_service.get(actor.owner_id, document_id)
        except DocumentStoreError:
            raise persistence_api_error() from None
        if record is None:
            raise ApiError(404, "document_not_found", "文档不存在")
        return _document_response(record)

    @app.delete(
        "/api/documents/{document_id}", response_model=DocumentDeleteResponse
    )
    def delete_document(document_id: str, request: Request) -> DocumentDeleteResponse:
        require_origin(request, config)
        actor = current_actor(request, ownership)
        if actor.kind != "user":
            raise ownership_api_error(AccountRequired())
        doc_service = _require_service(request)
        try:
            chunk_ids = doc_service.delete(actor.owner_id, document_id)
        except DocumentStoreError as exc:
            if "not found" in str(exc):
                raise ApiError(404, "document_not_found", "文档不存在") from exc
            raise persistence_api_error() from None
        return DocumentDeleteResponse(
            deleted=True, chunk_ids=list(chunk_ids)
        )
