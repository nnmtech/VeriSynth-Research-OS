"""
Memory Agent with search and provenance tracking.

Provides semantic search, embedding generation, and full provenance tracking
for audit-ready systems.
"""
import hashlib
import time
from datetime import datetime
from typing import Any

import structlog

from app.core.config import get_settings
from app.models.schemas import MemoryEntry, MemoryQuery, MemorySearchResult

logger = structlog.get_logger(__name__)

# Optional Google Cloud imports
try:
    from google.cloud import firestore
    FIRESTORE_AVAILABLE = True
except ImportError:
    FIRESTORE_AVAILABLE = False
    firestore = None  # type: ignore


class MemoryAgent:
    """
    Memory Agent with semantic search and provenance tracking.

    Integrates with Firestore for persistence and Vertex AI Matching Engine
    for vector search.
    """

    def __init__(self) -> None:
        """Initialize Memory Agent."""
        self.settings = get_settings()
        self.logger = logger.bind(component="memory_agent")

        # Initialize Firestore client if available
        if FIRESTORE_AVAILABLE:
            try:
                self.db = firestore.AsyncClient(
                    project=self.settings.gcp_project_id,
                    database=self.settings.firestore_database,
                )
                self.collection = self.db.collection("memory_entries")
                self.logger.info("firestore_initialized")
            except Exception as e:
                self.logger.warning("firestore_init_failed", error=str(e))
                self.db = None
                self.collection = None
        else:
            self.logger.warning("firestore_not_available")
            self.db = None
            self.collection = None

    async def store(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """
        Store content in memory with provenance.

        Args:
            content: Content to store
            metadata: Additional metadata
            provenance: Provenance information (source, timestamp, author, etc.)

        Returns:
            MemoryEntry with generated ID and embedding
        """
        self.logger.info("storing_memory", content_length=len(content))

        # Generate ID from content hash
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        entry_id = f"mem_{content_hash[:16]}"

        # Generate embedding (placeholder - would use Vertex AI in production)
        embedding = await self._generate_embedding(content)

        # Build provenance
        full_provenance = {
            "stored_at": datetime.utcnow().isoformat(),
            "content_hash": content_hash,
            **(provenance or {}),
        }

        entry = MemoryEntry(
            id=entry_id,
            content=content,
            embedding=embedding,
            metadata=metadata or {},
            provenance=full_provenance,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        # Store in Firestore
        if self.collection and FIRESTORE_AVAILABLE:
            try:
                await self.collection.document(entry_id).set(entry.model_dump())
                self.logger.info("memory_stored", entry_id=entry_id)
            except Exception as e:
                self.logger.error("firestore_store_failed", error=str(e))

        return entry

    async def search(
        self,
        query: MemoryQuery,
    ) -> MemorySearchResult:
        """
        Search memory with semantic similarity.

        Args:
            query: Search query with parameters

        Returns:
            MemorySearchResult with matching entries
        """
        start_time = time.time()
        self.logger.info("searching_memory", query=query.query)

        # Generate query embedding
        query_embedding = await self._generate_embedding(query.query)

        # Search for similar entries
        entries = await self._vector_search(
            query_embedding=query_embedding,
            max_results=query.max_results,
            similarity_threshold=query.similarity_threshold,
            filters=query.filters,
        )

        execution_time = time.time() - start_time

        self.logger.info(
            "search_complete",
            num_results=len(entries),
            execution_time=execution_time,
        )

        return MemorySearchResult(
            entries=entries,
            total=len(entries),
            query=query.query,
            execution_time=execution_time,
        )

    async def get_by_id(self, entry_id: str) -> MemoryEntry | None:
        """
        Get memory entry by ID.

        Args:
            entry_id: Entry ID

        Returns:
            MemoryEntry or None if not found
        """
        if not self.collection:
            return None

        try:
            doc = await self.collection.document(entry_id).get()
            if doc.exists:
                data = doc.to_dict()
                return MemoryEntry(**data)
        except Exception as e:
            self.logger.error("get_by_id_failed", entry_id=entry_id, error=str(e))

        return None

    async def update_provenance(
        self,
        entry_id: str,
        provenance_update: dict[str, Any],
    ) -> bool:
        """
        Update provenance information for an entry.

        Args:
            entry_id: Entry ID
            provenance_update: Provenance fields to update

        Returns:
            True if successful
        """
        if not self.collection or not FIRESTORE_AVAILABLE:
            return False

        try:
            await self.collection.document(entry_id).update({
                "provenance": firestore.firestore.ArrayUnion([provenance_update]),
                "updated_at": datetime.utcnow(),
            })
            self.logger.info("provenance_updated", entry_id=entry_id)
            return True
        except Exception as e:
            self.logger.error("provenance_update_failed", entry_id=entry_id, error=str(e))
            return False

    async def _generate_embedding(self, text: str) -> list[float]:
        """
        Generate embedding for text using Vertex AI.

        In production, this would use Vertex AI Text Embeddings.
        For now, returns a placeholder.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        # Placeholder: In production, use Vertex AI textembedding-gecko
        # from google.cloud import aiplatform
        # model = aiplatform.TextEmbeddingModel.from_pretrained("textembedding-gecko@001")
        # embeddings = model.get_embeddings([text])
        # return embeddings[0].values

        # Return a simple hash-based placeholder
        import hashlib
        hash_obj = hashlib.sha256(text.encode())
        hash_bytes = hash_obj.digest()

        # Convert to 768-dim vector (standard embedding size)
        embedding = []
        for i in range(0, len(hash_bytes), 1):
            embedding.append(float(hash_bytes[i]) / 255.0 - 0.5)

        # Pad to 768 dimensions
        while len(embedding) < 768:
            embedding.append(0.0)

        return embedding[:768]

    async def _vector_search(
        self,
        query_embedding: list[float],
        max_results: int,
        similarity_threshold: float,
        filters: dict[str, Any],
    ) -> list[MemoryEntry]:
        """
        Perform vector similarity search.

        In production, this would use Vertex AI Matching Engine.
        For now, performs simple Firestore query.

        Args:
            query_embedding: Query embedding vector
            max_results: Maximum results to return
            similarity_threshold: Minimum similarity score
            filters: Additional filters

        Returns:
            List of matching MemoryEntry objects
        """
        if not self.collection:
            return []

        try:
            # In production, use Vertex AI Matching Engine for vector search
            # For now, do basic Firestore query
            query = self.collection.limit(max_results)

            # Apply filters
            for key, value in filters.items():
                query = query.where(f"metadata.{key}", "==", value)

            docs = query.stream()

            entries = []
            async for doc in docs:
                data = doc.to_dict()
                entries.append(MemoryEntry(**data))

            return entries
        except Exception as e:
            self.logger.error("vector_search_failed", error=str(e))
            return []
