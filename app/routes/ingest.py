"""Document ingest endpoint — Phase 1 stub, real implementation in Phase 2."""

from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter()


@router.post("/ingest")
async def ingest_document(file: UploadFile = File(...), doc_type: str = "auto"):
    """Upload and ingest a document for RAG search.

    Phase 1: Returns a stub response. Real chunking + embedding in Phase 2.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Phase 1: accept the upload but don't process it yet
    content = await file.read()
    size_bytes = len(content)

    return {
        "status": "accepted",
        "filename": file.filename,
        "doc_type": doc_type,
        "file_size_bytes": size_bytes,
        "message": "Document upload accepted. RAG ingestion will be available in Phase 2.",
        "chunks_created": 0,
    }
