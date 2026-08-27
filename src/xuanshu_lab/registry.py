"""Workspace discovery and registration."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from .contracts import WorkspaceKind, WorkspaceSpec, WorkspaceStatus


class WorkspaceRegistry:
    def __init__(self, workspaces: Iterable[WorkspaceSpec] = ()) -> None:
        self._workspaces: dict[str, WorkspaceSpec] = {}
        for workspace in workspaces:
            self.register(workspace)

    def register(self, workspace: WorkspaceSpec) -> None:
        if workspace.workspace_id in self._workspaces:
            raise ValueError(f"duplicate workspace id: {workspace.workspace_id}")
        self._workspaces[workspace.workspace_id] = workspace

    def get(self, workspace_id: str) -> WorkspaceSpec:
        try:
            return self._workspaces[workspace_id]
        except KeyError as error:
            raise KeyError(f"unknown workspace: {workspace_id}") from error

    def __iter__(self) -> Iterator[WorkspaceSpec]:
        return iter(self._workspaces.values())

    def __len__(self) -> int:
        return len(self._workspaces)


def create_default_registry() -> WorkspaceRegistry:
    return WorkspaceRegistry(
        (
            WorkspaceSpec(
                workspace_id="moment",
                name="经纬",
                english_name="Jingwei Moment",
                category="VISION INTELLIGENCE",
                description="本地视觉理解与图像分析工作空间。",
                kind=WorkspaceKind.WEB,
                status=WorkspaceStatus.READY,
                accent="#1677E8",
                icon_relative_path="frontend/apps/portal/assets/jingwei-card-icon.png",
                route="/apps/moment/index.html?desktop=1",
                capabilities=("图像输入", "视觉分析", "本地运行"),
            ),
            WorkspaceSpec(
                workspace_id="gongshu",
                name="公输",
                english_name="Gongshu Vision2Grasp",
                category="ROBOTICS WORKSPACE",
                description="真实场景优先、仿真验证的机器人抓取研究工作空间。",
                kind=WorkspaceKind.WEB,
                status=WorkspaceStatus.READY,
                accent="#10A98E",
                icon_relative_path="frontend/apps/portal/assets/gongshu-card-icon.png",
                route="/apps/gongshu/index.html?desktop=1",
                capabilities=("真实场景", "抓取感知", "MuJoCo 验证"),
            ),
            WorkspaceSpec(
                workspace_id="hetu",
                name="河图",
                english_name="Hetu Preview",
                category="WORLD MODEL · PREVIEW",
                description="面向空间状态、时序预测与仿真桥接的世界模型预告版。",
                kind=WorkspaceKind.PREVIEW,
                status=WorkspaceStatus.PREVIEW,
                accent="#9367E8",
                icon_relative_path="frontend/apps/portal/assets/hetu-card-icon.png",
                capabilities=("空间表征", "时序预测", "仿真桥接"),
            ),
        )
    )
