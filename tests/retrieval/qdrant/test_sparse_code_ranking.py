"""Index real PDFs and rank each document first by a unique code."""

import re
from collections import defaultdict
from pathlib import Path

from archive.common.chunk_model import Chunk, ChunkKind
from archive.ingest.parse.pdf_parse_gateway import parse_pdf
from archive.retrieval.qdrant.qdrant_gateway import QdrantGateway
from archive.retrieval.qdrant.sparse_encoding_utils import sparse_vector

DOC_COUNT = 30
TOP_K = 3
CODE_REGEX = re.compile(r"\b(?:F|C|BRV)-\d{4}-\d{2,4}\b")


def test_unique_code_ranks_its_document_first(
    kit_corpus_dir: Path, tmp_path: Path
) -> None:
    paths = sorted(kit_corpus_dir.glob("*.pdf"))[:DOC_COUNT]
    codes_to_docs: dict[str, set[str]] = defaultdict(set)
    chunks = []
    for path in paths:
        doc = parse_pdf(path)
        text = "\n".join(doc.pages)
        for code in CODE_REGEX.findall(text):
            codes_to_docs[code].add(doc.doc_id)
        chunks.append(
            Chunk(
                doc_id=doc.doc_id,
                chunk_id=f"{doc.doc_id}#0",
                chunk_kind=ChunkKind.TEXT,
                doc_type="unknown",
                doc_date=None,
                identifiers=[],
                lang="fr",
                text=text,
            )
        )
    unique = {
        code: next(iter(ids))
        for code, ids in codes_to_docs.items()
        if len(ids) == 1
    }
    assert unique
    gateway = QdrantGateway.open(tmp_path)
    try:
        gateway.ensure_collection()
        gateway.upsert(chunks)
        for code, expected_doc in unique.items():
            hits = gateway.query_sparse(sparse_vector(code), None, TOP_K)
            assert hits[0][0].doc_id == expected_doc, code
    finally:
        gateway.close()
