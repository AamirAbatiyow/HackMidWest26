"""Vendor directory, resolution (known/new/uncertain) and the fake-vendor ring detector."""

from .directory import VendorDirectory, normalize_address, normalize_name
from .embeddings import MemoryEmbeddingIndex, PgVectorEmbeddingIndex, make_embedding_index
from .resolve import index_vendors, resolve_vendor
from .ring import detect_ring

__all__ = [
    "MemoryEmbeddingIndex",
    "PgVectorEmbeddingIndex",
    "VendorDirectory",
    "detect_ring",
    "index_vendors",
    "make_embedding_index",
    "normalize_address",
    "normalize_name",
    "resolve_vendor",
]
