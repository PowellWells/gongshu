"""XUANSHU LAB desktop platform."""

from .contracts import WorkspaceKind, WorkspaceSpec, WorkspaceStatus
from .registry import WorkspaceRegistry, create_default_registry

__all__ = [
    "WorkspaceKind",
    "WorkspaceRegistry",
    "WorkspaceSpec",
    "WorkspaceStatus",
    "create_default_registry",
]
