"""Allow-listed deterministic operation registry.

Public surface:
    REGISTRY, OperationKind, OperationSpec,
    list_operations(), is_allowed(name), get_operation(name)
"""

from backend.recon_engine.operations.registry import (
    REGISTRY,
    OperationKind,
    OperationSpec,
    get_operation,
    is_allowed,
    list_operations,
)

__all__ = [
    "REGISTRY",
    "OperationKind",
    "OperationSpec",
    "get_operation",
    "is_allowed",
    "list_operations",
]
