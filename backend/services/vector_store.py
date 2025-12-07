"""
Vector Store Service - Manages Chroma DB operations for semantic search
"""

import asyncio
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings
import structlog

from backend.config.settings import get_settings

settings = get_settings()
logger = structlog.get_logger(__name__)


class VectorStoreService:
    """Service for managing vector database operations"""
    
    def __init__(self):
        self.client = None
        self.collection = None
        
    async def initialize(self):
        """Initialize Chroma DB connection"""
        try:
            logger.info("Initializing vector store", path=settings.chroma_db_path)
            
            # Ensure the directory exists
            import os
            os.makedirs(settings.chroma_db_path, exist_ok=True)
            
            self.client = chromadb.PersistentClient(
                path=settings.chroma_db_path,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            
            # Get or create collection
            self.collection = self.client.get_or_create_collection(
                name=settings.chroma_collection_name,
                metadata={"description": "FinOps cost intelligence knowledge base"}
            )
            
            # Initialize with sample data if empty
            if self.collection.count() == 0:
                await self._populate_initial_data()
            
            logger.info(
                "Vector store initialized successfully",
                collection_name=settings.chroma_collection_name,
                document_count=self.collection.count()
            )
            
        except Exception as e:
            logger.error(f"Vector store initialization failed: {e}", exc_info=True)
            raise
    
    async def _populate_initial_data(self):
        """Populate vector store with initial cost intelligence knowledge"""
        
        sample_documents = [
            {
                "id": "ec2-optimization-1",
                "content": "EC2 Reserved Instances provide up to 75% savings compared to On-Demand pricing for predictable workloads. Consider 1-year or 3-year terms for maximum savings.",
                "metadata": {"category": "compute", "service": "ec2", "type": "optimization"}
            },
            {
                "id": "s3-storage-classes-1", 
                "content": "S3 Intelligent Tiering automatically moves objects between storage classes based on access patterns, providing cost savings without performance impact.",
                "metadata": {"category": "storage", "service": "s3", "type": "optimization"}
            },
            {
                "id": "cloudfront-caching-1",
                "content": "Optimizing CloudFront cache behaviors and TTL settings can reduce origin requests by up to 90%, significantly lowering data transfer costs.",
                "metadata": {"category": "cdn", "service": "cloudfront", "type": "optimization"}
            }
        ]
        
        documents = [doc["content"] for doc in sample_documents]
        ids = [doc["id"] for doc in sample_documents] 
        metadatas = [doc["metadata"] for doc in sample_documents]
        
        self.collection.add(
            documents=documents,
            ids=ids,
            metadatas=metadatas
        )
        
        logger.info(f"Added {len(sample_documents)} initial documents to vector store")
    
    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for similar documents"""
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=limit
            )
            
            # Format results
            formatted_results = []
            if results["documents"] and results["documents"][0]:
                for i in range(len(results["documents"][0])):
                    formatted_results.append({
                        "id": results["ids"][0][i],
                        "content": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i] if results["metadatas"][0] else {},
                        "distance": results["distances"][0][i] if results["distances"] and results["distances"][0] else 0.0
                    })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []
    
    async def add_document(
        self, 
        doc_id: str, 
        content: str, 
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Add a document to the vector store"""
        try:
            self.collection.add(
                documents=[content],
                ids=[doc_id],
                metadatas=[metadata or {}]
            )
            
        except Exception as e:
            logger.error(f"Failed to add document: {e}")
            raise
    
    async def close(self):
        """Close vector store connection"""
        # Chroma doesn't require explicit closing
        pass