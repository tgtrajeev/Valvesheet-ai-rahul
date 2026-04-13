CREATE EXTENSION IF NOT EXISTS vector;

-- Conversation sessions
CREATE TABLE sessions (
    id VARCHAR(64) PRIMARY KEY,
    messages JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- RAG document chunks
CREATE TABLE document_chunks (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector(384),
    source_type VARCHAR(50),
    document_name VARCHAR(255),
    section VARCHAR(255),
    piping_class VARCHAR(20),
    valve_type VARCHAR(10),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_chunks_embedding ON document_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_chunks_source ON document_chunks(source_type, document_name);

-- Generated datasheets
CREATE TABLE generated_datasheets (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) REFERENCES sessions(id),
    vds_code VARCHAR(20) NOT NULL,
    datasheet JSONB NOT NULL,
    validation_status VARCHAR(20),
    completion_pct FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_datasheets_session ON generated_datasheets(session_id);
CREATE INDEX idx_datasheets_vds ON generated_datasheets(vds_code);

-- Ingested documents registry
CREATE TABLE ingested_documents (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    doc_type VARCHAR(50),
    chunk_count INTEGER DEFAULT 0,
    file_size_bytes INTEGER,
    ingested_at TIMESTAMP DEFAULT NOW()
);
