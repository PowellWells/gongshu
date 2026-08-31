"""Simulation boundary with lazy heavy-runtime imports."""

from .interfaces import RGBDSimulator
from .validation_contracts import (
    CameraMode,
    SimulationState,
    ValidationRequest,
    ValidationResult,
    ValidationScenario,
    ValidationSceneTransform,
)
from .validation_service import MuJoCoValidationService, VALIDATION_SCHEMA_VERSION
from .recording import (
    PlaybackSession,
    SimulationRecording,
    ValidationRun,
)

__all__ = [
    "CameraDirector",
    "CameraMode",
    "MuJoCoValidationService",
    "PlaybackSession",
    "NativePandaValidation",
    "NativePandaValidationConfig",
    "RGBDSimulator",
    "RobosuiteRGBDSimulator",
    "RobosuiteSimulationConfig",
    "SimulationState",
    "SimulationRecording",
    "VALIDATION_SCHEMA_VERSION",
    "ValidationRequest",
    "ValidationResult",
    "ValidationRun",
    "ValidationScenario",
    "ValidationSceneTransform",
]


def __getattr__(name: str):
    if name in {"RobosuiteRGBDSimulator", "RobosuiteSimulationConfig"}:
        from .robosuite_adapter import RobosuiteRGBDSimulator, RobosuiteSimulationConfig

        return {
            "RobosuiteRGBDSimulator": RobosuiteRGBDSimulator,
            "RobosuiteSimulationConfig": RobosuiteSimulationConfig,
        }[name]
    if name in {"CameraDirector", "NativePandaValidation", "NativePandaValidationConfig"}:
        from .native_panda_validation import (
            CameraDirector,
            NativePandaValidation,
            NativePandaValidationConfig,
        )

        return {
            "CameraDirector": CameraDirector,
            "NativePandaValidation": NativePandaValidation,
            "NativePandaValidationConfig": NativePandaValidationConfig,
        }[name]
    raise AttributeError(name)
