"""Camera-intrinsics providers for Phone RGB spatial perception."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
from typing import Mapping, Sequence

from vision2grasp.contracts import CameraIntrinsics, RGBFrame

from .contracts import CalibrationState, IntrinsicsObservation, IntrinsicsSource
from .interfaces import CameraIntrinsicsCandidateProvider


INTRINSICS_SOURCE_PRIORITY = (
    IntrinsicsSource.CALIBRATED,
    IntrinsicsSource.SENSOR_METADATA,
    IntrinsicsSource.MODEL_PREDICTED,
    IntrinsicsSource.NOMINAL_FOV,
)
CAMERA_INTRINSICS_ENV = "VISION2GRASP_CAMERA_INTRINSICS"
CAMERA_INTRINSICS_SCHEMA_VERSION = "vision2grasp.camera-intrinsics/v1"


class IntrinsicsUnavailableError(RuntimeError):
    """No configured source can produce projection geometry for this frame."""


@dataclass(frozen=True, slots=True)
class NominalFOVIntrinsicsConfig:
    nominal_diagonal_fov_deg: float = 75.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.nominal_diagonal_fov_deg):
            raise ValueError("nominal diagonal FOV must be finite")
        if not 1.0 < self.nominal_diagonal_fov_deg < 179.0:
            raise ValueError("nominal diagonal FOV must be in (1, 179) degrees")


class NominalFOVCameraIntrinsicsProvider:
    """Construct uncalibrated pinhole intrinsics from frame size and diagonal FOV."""

    source = IntrinsicsSource.NOMINAL_FOV

    def __init__(self, config: NominalFOVIntrinsicsConfig | None = None) -> None:
        self._config = config or NominalFOVIntrinsicsConfig()

    def resolve(self, frame: RGBFrame) -> IntrinsicsObservation:
        height, width = frame.rgb.shape[:2]
        diagonal_px = math.hypot(width, height)
        focal_px = diagonal_px / (
            2.0 * math.tan(math.radians(self._config.nominal_diagonal_fov_deg) / 2.0)
        )
        intrinsics = CameraIntrinsics(
            width=width,
            height=height,
            fx=focal_px,
            fy=focal_px,
            cx=(width - 1.0) / 2.0,
            cy=(height - 1.0) / 2.0,
        )
        return IntrinsicsObservation(
            intrinsics=intrinsics,
            source=IntrinsicsSource.NOMINAL_FOV,
            calibration_state=CalibrationState.UNCALIBRATED,
            nominal_fov_deg=self._config.nominal_diagonal_fov_deg,
        )

    def resolve_candidate(self, frame: RGBFrame) -> IntrinsicsObservation:
        return self.resolve(frame)


class CalibratedCameraIntrinsicsProvider:
    """Resolve optional per-camera calibration without device-model assumptions."""

    source = IntrinsicsSource.CALIBRATED

    def __init__(self, calibrations: Mapping[str, CameraIntrinsics] | None = None) -> None:
        self._calibrations = dict(calibrations or {})

    @classmethod
    def from_user_config(cls, path: Path | None = None) -> CalibratedCameraIntrinsicsProvider:
        return cls(load_calibrated_intrinsics(path))

    def resolve_candidate(self, frame: RGBFrame) -> IntrinsicsObservation | None:
        calibrated = self._calibrations.get(frame.camera_name)
        if calibrated is None:
            return None
        height, width = frame.rgb.shape[:2]
        source_aspect = calibrated.width / calibrated.height
        target_aspect = width / height
        if not math.isclose(source_aspect, target_aspect, rel_tol=1e-6, abs_tol=1e-9):
            return None
        scale_x = width / calibrated.width
        scale_y = height / calibrated.height
        intrinsics = CameraIntrinsics(
            width=width,
            height=height,
            fx=calibrated.fx * scale_x,
            fy=calibrated.fy * scale_y,
            cx=(calibrated.cx + 0.5) * scale_x - 0.5,
            cy=(calibrated.cy + 0.5) * scale_y - 0.5,
        )
        return IntrinsicsObservation(
            intrinsics=intrinsics,
            source=IntrinsicsSource.CALIBRATED,
            calibration_state=CalibrationState.CALIBRATED,
        )


def default_camera_intrinsics_path() -> Path:
    override = os.environ.get(CAMERA_INTRINSICS_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "Vision2Grasp" / "camera-intrinsics.json"
    return Path.home() / ".config" / "vision2grasp" / "camera-intrinsics.json"


def load_calibrated_intrinsics(path: Path | None = None) -> dict[str, CameraIntrinsics]:
    source = Path(path or default_camera_intrinsics_path())
    if not source.is_file():
        return {}
    document = json.loads(source.read_text(encoding="utf-8"))
    if document.get("schema_version") != CAMERA_INTRINSICS_SCHEMA_VERSION:
        raise ValueError("camera intrinsics file has an unsupported schema_version")
    cameras = document.get("cameras")
    if not isinstance(cameras, dict):
        raise ValueError("camera intrinsics file must contain a cameras object")
    result: dict[str, CameraIntrinsics] = {}
    for camera_name, values in cameras.items():
        if not isinstance(camera_name, str) or not camera_name.strip() or not isinstance(values, dict):
            raise ValueError("camera intrinsics entries must use non-empty camera names")
        result[camera_name] = CameraIntrinsics(
            width=int(values["width"]),
            height=int(values["height"]),
            fx=float(values["fx"]),
            fy=float(values["fy"]),
            cx=float(values["cx"]),
            cy=float(values["cy"]),
        )
    return result


class PriorityCameraIntrinsicsProvider:
    """Device-agnostic CALIBRATED -> metadata -> predicted -> nominal resolver."""

    def __init__(
        self,
        providers: Sequence[CameraIntrinsicsCandidateProvider],
    ) -> None:
        self._providers = tuple(providers)
        if not self._providers:
            raise ValueError("at least one camera intrinsics source is required")
        priorities = []
        for provider in self._providers:
            try:
                priorities.append(INTRINSICS_SOURCE_PRIORITY.index(provider.source))
            except (AttributeError, ValueError) as error:
                raise ValueError("camera intrinsics candidate has an unsupported source") from error
        if priorities != sorted(set(priorities)):
            raise ValueError("camera intrinsics providers are not in frozen priority order")

    def resolve(self, frame: RGBFrame) -> IntrinsicsObservation:
        for provider in self._providers:
            observation = provider.resolve_candidate(frame)
            if observation is None:
                continue
            try:
                priority = INTRINSICS_SOURCE_PRIORITY.index(observation.source)
            except ValueError as error:
                raise ValueError(
                    f"unsupported phone intrinsics source: {observation.source.value}"
                ) from error
            if provider.source is not observation.source:
                raise ValueError("camera intrinsics provider returned the wrong source")
            return observation
        raise IntrinsicsUnavailableError("camera intrinsics are unavailable")
