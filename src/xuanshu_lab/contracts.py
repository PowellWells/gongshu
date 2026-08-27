"""Framework-neutral contracts for XUANSHU LAB workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath


class WorkspaceKind(StrEnum):
    WEB = "web"
    PREVIEW = "preview"


class WorkspaceStatus(StrEnum):
    READY = "ready"
    PREVIEW = "preview"


@dataclass(frozen=True, slots=True)
class WorkspaceSpec:
    workspace_id: str
    name: str
    english_name: str
    category: str
    description: str
    kind: WorkspaceKind
    status: WorkspaceStatus
    accent: str
    icon_relative_path: str
    route: str | None = None
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.workspace_id or not self.workspace_id.replace("-", "").isalnum():
            raise ValueError("workspace_id must contain letters, digits, or hyphens")
        if not all((self.name, self.english_name, self.category, self.description)):
            raise ValueError("workspace display metadata cannot be empty")
        if not self.accent.startswith("#") or len(self.accent) != 7:
            raise ValueError("accent must be a six-digit hex color")
        icon_path = PurePosixPath(self.icon_relative_path)
        if icon_path.is_absolute() or ".." in icon_path.parts:
            raise ValueError("icon_relative_path must stay inside the project")
        if self.kind is WorkspaceKind.WEB:
            if not self.route or not self.route.startswith("/"):
                raise ValueError("web workspaces require a root-relative route")
        elif self.route is not None:
            raise ValueError("preview workspaces cannot publish a route")
