"""
知识库 + 文件管理 路由

分页参数使用 str 类型接收，避免 FastAPI 对空字符串做 int 解析报错。
"""
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.core.config import settings
from backend.core.database import get_db
from backend.core.utils import parse_page, parse_page_size
from backend.models import Users
from backend.schemas.common import SuccessResponse
from backend.services.document_process import DocumentProcessService
from backend.schemas.knowledge import (
    BatchFileAction,
    BatchKnowledgeBaseAction,
    BatchResult,
    ChunkIdsRequest,
    DocIdsRequest,
    DocumentPreview,
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    PaginatedResponse,
    ProcessDocumentsRequest,
    ProcessResult,
)
from backend.repositories import DocumentRepo
from backend.services import KnowledgeBaseService
from backend.services.knowledge import _get_kb_for_user

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["知识库"])


# ── 分页解析：使用 backend/core/utils.py 公共函数 parse_page / parse_page_size ──


# ── 知识库 CRUD ────────────────────────

@router.get("/processing-tasks", response_model=SuccessResponse[list[dict]], summary="全局处理任务列表", description="处理中/排队中的文档任务（含知识库名与阶段），处理浮窗轮询用；注意：必须注册在 /{kb_id} 动态路由之前")
async def processing_tasks(
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await KnowledgeBaseService.list_processing_tasks(db, user)
    return SuccessResponse(result=result)


@router.get("", response_model=SuccessResponse[PaginatedResponse], summary="获取当前用户的知识库列表", description="自动过滤已删除(status=9)的记录，按创建时间倒序")
async def list_kb(
    page: str = Query("", description="页码，默认 1"),
    page_size: str = Query("", description="每页条数，默认 20"),
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await KnowledgeBaseService.list_by_user(
        db, user, parse_page(page), parse_page_size(page_size)
    )
    return SuccessResponse(result=result)


@router.post("", response_model=SuccessResponse[KnowledgeBaseResponse], summary="创建新知识库", description="支持配置分块参数、Embedding 模型等，不传则使用默认值")
async def create_kb(
    body: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await KnowledgeBaseService.create(db, user, body)
    return SuccessResponse(result=result)


@router.get("/defaults", response_model=SuccessResponse[dict], summary="获取知识库默认配置", description="返回新建知识库的默认处理策略，供创建表单回填")
async def get_kb_defaults(
    user: Users = Depends(get_current_user),
):
    _ = user
    return SuccessResponse(result={
        "cleaning_config": KnowledgeBaseService.get_default_cleaning_config(),
        "auto_process": KnowledgeBaseService.get_default_auto_process(),
        "chunk_size": int(getattr(settings.document, "default_chunk_size", 800)),
        "chunk_overlap": int(getattr(settings.document, "default_chunk_overlap", 150)),
        "chunk_separators": getattr(
            settings.document, "default_chunk_separators", "\n##,\n###,\n,。,., "
        ),
    })


@router.get("/{kb_id}", response_model=SuccessResponse[KnowledgeBaseResponse], summary="获取指定知识库的详细信息", description="包含分块配置、Embedding 配置等完整字段")
async def get_kb(
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await KnowledgeBaseService.get(db, user, kb_id)
    return SuccessResponse(result=result)


@router.put("/{kb_id}", response_model=SuccessResponse[KnowledgeBaseResponse], summary="修改知识库配置", description="可修改名称/描述/上传限制/分块参数/Embedding 模型等，仅更新传入的非空字段")
async def update_kb(
    kb_id: UUID,
    body: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await KnowledgeBaseService.update(db, user, kb_id, body)
    return SuccessResponse(result=result)


@router.delete("/{kb_id}", response_model=SuccessResponse, summary="删除知识库", description="软删除，仅标记状态不删除数据")
async def delete_kb(
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    await KnowledgeBaseService.delete(db, user, kb_id)
    return SuccessResponse(message="已删除")


# ── 文档处理 ────────────────────────────

def _check_result(processed: int, total: int) -> None:
    """有失败就抛异常，不返回 success（commit 已执行，成功的状态已落库）"""
    if processed < total:
        failed = total - processed
        raise HTTPException(status_code=400, detail=f"{failed}/{total} 项处理失败，成功的已保存")


@router.post("/{kb_id}/parse", response_model=SuccessResponse[ProcessResult], summary="触发文档解析", description="解析文档为纯文本，支持 PDF 和 Office 格式")
async def parse_docs(
    kb_id: UUID,
    body: DocIdsRequest,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    kb = await _get_kb_for_user(db, user, kb_id)
    total = len(body.doc_ids)
    processed = await DocumentProcessService.parse_documents(db, kb, body.doc_ids)
    await db.commit()
    _check_result(processed, total)
    return SuccessResponse(result=ProcessResult(processed=processed, total=total))


@router.post("/{kb_id}/clean", response_model=SuccessResponse[ProcessResult], summary="触发文档清洗", description="按知识库当前清洗规则处理已解析文本")
async def clean_docs(
    kb_id: UUID,
    body: DocIdsRequest,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    kb = await _get_kb_for_user(db, user, kb_id)
    total = len(body.doc_ids)
    processed = await DocumentProcessService.clean_documents(db, kb, body.doc_ids)
    await db.commit()
    _check_result(processed, total)
    return SuccessResponse(result=ProcessResult(processed=processed, total=total))


@router.post("/{kb_id}/chunk", response_model=SuccessResponse[ProcessResult], summary="触发文档分块", description="按知识库配置的规则将文本切分为多个片段")
async def chunk_docs(
    kb_id: UUID,
    body: DocIdsRequest,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    kb = await _get_kb_for_user(db, user, kb_id)
    total = len(body.doc_ids)
    processed = await DocumentProcessService.chunk_documents(db, kb, body.doc_ids)
    await db.commit()
    _check_result(processed, total)
    return SuccessResponse(result=ProcessResult(processed=processed, total=total))


@router.post("/{kb_id}/vectorize", response_model=SuccessResponse[ProcessResult], summary="触发块向量化", description="批量调用 Embedding 服务将分块转为向量并存储")
async def vectorize_chunks(
    kb_id: UUID,
    body: ChunkIdsRequest,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    kb = await _get_kb_for_user(db, user, kb_id)
    total = len(body.chunk_ids)
    processed = await DocumentProcessService.vectorize_chunks(db, kb, body.chunk_ids)
    await db.commit()
    _check_result(processed, total)
    return SuccessResponse(result=ProcessResult(processed=processed, total=total))


@router.post("/{kb_id}/vectorize-docs", response_model=SuccessResponse[ProcessResult], summary="按文档批量向量化", description="选中文档后自动查找其所有有效分块并向量化")
async def vectorize_by_docs(
    kb_id: UUID,
    body: DocIdsRequest,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    kb = await _get_kb_for_user(db, user, kb_id)
    total = len(body.doc_ids)
    processed = await DocumentProcessService.vectorize_documents(db, kb, body.doc_ids)
    await db.commit()
    _check_result(processed, total)
    return SuccessResponse(result=ProcessResult(processed=processed, total=total))


# ── 批量操作 ────────────────────────────

@router.post("/batch", response_model=SuccessResponse[BatchResult], summary="批量操作知识库", description="支持批量启用、禁用、删除，仅操作当前用户的知识库")
async def batch_kb(
    body: BatchKnowledgeBaseAction,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await KnowledgeBaseService.batch_kb(db, user, body.ids, body.action)
    return SuccessResponse(result=result)


# ── 文件管理 ────────────────────────────

@router.post(
    "/{kb_id}/files",
    response_model=SuccessResponse,
    summary="上传文件到指定知识库",
    description="自动校验文件类型和大小，防止文件名冲突",
)
async def upload_file(
    kb_id: UUID,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    kb = await _get_kb_for_user(db, user, kb_id)
    result = await KnowledgeBaseService.upload_file(db, user, kb_id, file)
    # 自动处理由知识库自身开关控制；系统设置只影响之后的新建知识库默认值。
    if kb.auto_process:
        # 响应返回前预置"处理中"状态（任务入队标记），前端立即可见进行中标签
        await KnowledgeBaseService.mark_processing_to_stage(db, result.id, "vectorize")
        background_tasks.add_task(
            DocumentProcessService.auto_process_document,
            str(kb_id),
            str(result.id),
        )
    return SuccessResponse(result=result)


@router.get(
    "/{kb_id}/files",
    response_model=SuccessResponse[PaginatedResponse],
    summary="获取知识库下的文件列表",
    description="分页返回，包含解析、分块、向量化状态",
)
async def list_files(
    kb_id: UUID,
    page: str = Query("", description="页码，默认 1"),
    page_size: str = Query("", description="每页条数，默认 20"),
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await KnowledgeBaseService.list_files(
        db, user, kb_id, parse_page(page), parse_page_size(page_size)
    )
    return SuccessResponse(result=result)


@router.post(
    "/{kb_id}/files/process",
    response_model=SuccessResponse[ProcessResult],
    summary="一键处理文件",
    description="将选中文件入队，后台按解析→清洗→分块→向量化完整处理。",
)
async def process_files(
    kb_id: UUID,
    body: ProcessDocumentsRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    kb = await _get_kb_for_user(db, user, kb_id)
    documents = [await DocumentRepo.get_by_id(db, doc_id) for doc_id in body.doc_ids]
    if any(doc is None or doc.status == 9 or doc.knowledge_base_id != kb.id for doc in documents):
        raise HTTPException(status_code=404, detail="文件不存在")
    for doc in documents:
        await KnowledgeBaseService.mark_processing_to_stage(db, doc.id, body.target_stage)
        background_tasks.add_task(
            DocumentProcessService.auto_process_document,
            str(kb_id),
            str(doc.id),
            body.target_stage,
        )
    return SuccessResponse(result=ProcessResult(processed=len(documents), total=len(body.doc_ids)))


@router.post(
    "/{kb_id}/files/{doc_id}/preview",
    response_model=SuccessResponse[DocumentPreview],
    summary="预览文件清洗与切片",
    description="在内存中执行解析、清洗和切片，不写入 documents、chunks 或 embeddings。",
)
async def preview_file(
    kb_id: UUID,
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    kb = await _get_kb_for_user(db, user, kb_id)
    result = await DocumentProcessService.preview_document(db, kb, doc_id)
    return SuccessResponse(result=result)


@router.delete(
    "/{kb_id}/files/{doc_id}",
    response_model=SuccessResponse,
    summary="删除指定文件",
    description="软删除，仅标记状态不删除文件",
)
async def delete_file(
    kb_id: UUID,
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    await KnowledgeBaseService.delete_file(db, user, kb_id, doc_id)
    return SuccessResponse(message="已删除")


@router.post(
    "/{kb_id}/files/batch",
    response_model=SuccessResponse[BatchResult],
    summary="批量删除文件",
    description="仅删除当前知识库下的文件",
)
async def batch_files(
    kb_id: UUID,
    body: BatchFileAction,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await KnowledgeBaseService.batch_files(db, user, kb_id, body.ids, body.action)
    return SuccessResponse(result=result)
