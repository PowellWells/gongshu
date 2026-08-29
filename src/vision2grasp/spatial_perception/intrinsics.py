"""Camera-intrinsics providers for Phone RGB spatial perception."""

from __future__ import annotations

from dataclasses import dataclass
import math

from vision2grasp.contracts import CameraIntrinsics, RGBFrame

from .contracts import CalibrationState, IntrinsicsObservation, IntrinsicsSource


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
