"""Interfaces implemented by pretrained segmentation backends."""

from typing import Protocol, Sequence

from vision2grasp.contracts import Detection2D, RGBDFrame


class InstanceSegmenter(Protocol):
    @property
    def model_name(self) -> str: ...

    def predict(self, frame: RGBDFrame) -> Sequence[Detection2D]: ...
