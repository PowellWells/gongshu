"""Interfaces implemented by pretrained segmentation backends."""

from typing import Protocol, Sequence

from vision2grasp.contracts import Detection2D, RGBDFrame, RGBFrame


class InstanceSegmenter(Protocol):
    @property
    def model_name(self) -> str: ...

    def predict(self, frame: RGBFrame | RGBDFrame) -> Sequence[Detection2D]: ...
