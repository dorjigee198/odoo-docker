import logging
import requests
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "https://ai.dcpl.bt/ollama"
EMBED_MODEL = "nomic-embed-text"
VECTOR_DIM = 768


def get_embedding(text):
    """Get vector embedding from Ollama nomic-embed-text."""
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("embedding", [])
    except Exception as e:
        _logger.error("Embedding error: %s", e)
        return []


class KnowledgeChunk(models.Model):
    _name = "dc.knowledge.chunk"
    _description = "Dragon Coders Knowledge Chunk"
    _order = "document_id, sequence"

    document_id = fields.Many2one(
        "dc.knowledge.document",
        string="Document",
        required=True,
        ondelete="cascade",
    )
    content = fields.Text(string="Chunk Content", required=True)
    category = fields.Char(string="Category")
    sequence = fields.Integer(string="Order", default=0)
    has_embedding = fields.Boolean(
        string="Embedded",
        default=False,
        readonly=True,
        help="True when embedding_vec is populated in pgvector",
    )

    def init(self):
        """
        Runs on module install/update.
        Sets up pgvector column and HNSW index.
        """
        self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        self.env.cr.execute(
            f"""
            ALTER TABLE dc_knowledge_chunk
            ADD COLUMN IF NOT EXISTS embedding_vec vector({VECTOR_DIM});
        """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chunk_embedding_hnsw
            ON dc_knowledge_chunk
            USING hnsw (embedding_vec vector_cosine_ops);
        """
        )
        _logger.info("pgvector setup complete for dc_knowledge_chunk")

    def embed_and_store(self):
        """
        Generate embedding for this chunk and store it
        in the pgvector column via raw SQL.
        """
        vector = get_embedding(self.content)
        if not vector:
            _logger.warning("No embedding returned for chunk %s", self.id)
            return False

        self.env.cr.execute(
            """
            UPDATE dc_knowledge_chunk
            SET embedding_vec = %s::vector
            WHERE id = %s
        """,
            [str(vector), self.id],
        )

        self.env.cr.execute(
            """
            UPDATE dc_knowledge_chunk
            SET has_embedding = true
            WHERE id = %s
        """,
            [self.id],
        )

        _logger.info("Embedded chunk %s successfully", self.id)
        return True

    @api.model
    def get_relevant_chunks(self, query, limit=3, threshold=0.20):
        """
        Primary: pgvector cosine similarity search with threshold.
        Fallback: keyword search if embedding fails.
        """
        query_vector = get_embedding(query)

        if query_vector:
            self.env.cr.execute(
                """
                SELECT c.id,
                       1 - (c.embedding_vec <=> %s::vector) AS score
                FROM dc_knowledge_chunk c
                JOIN dc_knowledge_document d ON d.id = c.document_id
                WHERE d.state = 'ready'
                  AND d.active = true
                  AND c.embedding_vec IS NOT NULL
                  AND 1 - (c.embedding_vec <=> %s::vector) >= %s
                ORDER BY c.embedding_vec <=> %s::vector
                LIMIT %s
            """,
                [
                    str(query_vector),
                    str(query_vector),
                    threshold,
                    str(query_vector),
                    limit,
                ],
            )

            rows = self.env.cr.fetchall()
            if rows:
                ids = [row[0] for row in rows]
                scores = {row[0]: row[1] for row in rows}
                _logger.info(
                    "Vector search returned %s chunks (best score: %.3f)",
                    len(ids),
                    max(scores.values()),
                )
                id_index = {id_: i for i, id_ in enumerate(ids)}
                chunks = self.browse(ids)
                return sorted(chunks, key=lambda c: id_index[c.id])

            _logger.info("No chunks above threshold %.2f for query", threshold)
            return []

        # ── Fallback: keyword search ──────────────────────────────────────
        _logger.warning("Embedding failed — falling back to keyword search")

        query_words = set(query.lower().split())
        stop_words = {
            "a",
            "an",
            "the",
            "is",
            "it",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "and",
            "or",
            "are",
            "was",
            "be",
            "do",
            "does",
            "have",
            "has",
            "what",
            "how",
            "when",
            "where",
            "who",
            "which",
            "can",
            "you",
            "we",
            "i",
            "me",
            "my",
            "your",
            "our",
            "this",
            "that",
            "with",
            "from",
            "by",
            "about",
            "will",
            "would",
            "could",
            "should",
        }
        keywords = query_words - stop_words

        if not keywords:
            return self.search(
                [
                    ("document_id.state", "=", "ready"),
                    ("document_id.active", "=", True),
                ],
                limit=limit,
            )

        all_chunks = self.search(
            [
                ("document_id.state", "=", "ready"),
                ("document_id.active", "=", True),
            ]
        )

        scored = []
        for chunk in all_chunks:
            content_lower = chunk.content.lower()
            score = sum(1 for kw in keywords if kw in content_lower)
            if query.lower() in content_lower:
                score += 5
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:limit]]
