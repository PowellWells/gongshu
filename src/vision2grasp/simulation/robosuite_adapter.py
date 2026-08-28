"""RGB-D simulation adapter backed by robosuite's Lift environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import CameraIntrinsics, PandaProprioception, RGBDFrame


# robosuite reads this setting while importing MuJoCo's rendering bindings.
os.environ.setdefault("MUJOCO_GL", "wgl")


@dataclass(frozen=True, slots=True)
class RobosuiteSimulationConfig:
    """Configuration for the stage-2 robosuite RGB-D adapter."""

    environment: str = "Lift"
    robot: str = "Panda"
    controller: str = "OSC_POSE"
    camera_name: str = "agentview"
    camera_width: int = 640
    camera_height: int = 480
    control_frequency_hz: int = 20
    horizon: int = 300
    seed: int | None = 7

    def __post_init__(self) -> None:
        if not self.environment:
            raise ValueError("environment must not be empty")
        if not self.robot:
            raise ValueError("robot must not be empty")
        if not self.controller:
            raise ValueError("controller must not be empty")
        if not self.camera_name:
            raise ValueError("camera_name must not be empty")
        if self.camera_width <= 0 or self.camera_height <= 0:
            raise ValueError("camera dimensions must be positive")
        if self.control_frequency_hz <= 0:
            raise ValueError("control_frequency_hz must be positive")
        if self.horizon <= 0:
            raise ValueError("horizon must be positive")


class _SimulationData(Protocol):
    time: float
    body_xpos: Any
    body_xmat: Any


class _SimulationModel(Protocol):
    def body_name2id(self, name: str) -> int: ...


class _Simulation(Protocol):
    data: _SimulationData
    model: _SimulationModel


class _RobosuiteEnvironment(Protocol):
    action_dim: int
    sim: _Simulation

    def reset(self) -> Mapping[str, Any]: ...

    def step(
        self, action: NDArray[np.float64]
    ) -> tuple[Mapping[str, Any], float, bool, Mapping[str, Any]]: ...

    def close(self) -> None: ...


def _make_robosuite_environment(
    config: RobosuiteSimulationConfig, seed: int | None
) -> _RobosuiteEnvironment:
    """Create robosuite lazily so importing the package stays lightweight."""

    import robosuite as suite
    import robosuite.macros as macros
    from robosuite.controllers.composite.composite_controller_factory import (
        refactor_composite_controller_config,
    )

    macros.IMAGE_CONVENTION = "opencv"
    if config.environment == "BottleLift":
        # Importing registers the environment with robosuite's EnvMeta.
        from .bottle_lift import BottleLift  # noqa: F401

    arm_config = suite.load_part_controller_config(default_controller=config.controller)
    controller_config = refactor_composite_controller_config(
        arm_config,
        robot_type=config.robot,
        arms=["right"],
    )
    environment = suite.make(
        env_name=config.environment,
        robots=config.robot,
        controller_configs=controller_config,
        has_renderer=False,
        has_offscreen_renderer=True,
        use_camera_obs=True,
        use_object_obs=False,
        camera_names=config.camera_name,
        camera_heights=config.camera_height,
        camera_widths=config.camera_width,
        camera_depths=True,
        camera_segmentations=None,
        control_freq=config.control_frequency_hz,
        horizon=config.horizon,
        ignore_done=True,
        hard_reset=False,
        seed=seed,
    )
    return cast(_RobosuiteEnvironment, environment)


def _metric_depth(
    simulation: _Simulation, normalized_depth: NDArray[np.floating[Any]]
) -> NDArray[np.floating[Any]]:
    from robosuite.utils.camera_utils import get_real_depth_map

    return get_real_depth_map(simulation, normalized_depth)


def _camera_intrinsic_matrix(
    simulation: _Simulation, camera_name: str, height: int, width: int
) -> NDArray[np.floating[Any]]:
    from robosuite.utils.camera_utils import get_camera_intrinsic_matrix

    return get_camera_intrinsic_matrix(simulation, camera_name, height, width)


def _world_from_camera_matrix(
    simulation: _Simulation, camera_name: str
) -> NDArray[np.floating[Any]]:
    from robosuite.utils.camera_utils import get_camera_extrinsic_matrix

    return get_camera_extrinsic_matrix(simulation, camera_name)


class RobosuiteRGBDSimulator:
    """Own robosuite and expose RGB-D plus robot-only OSC proprioception."""

    def __init__(self, config: RobosuiteSimulationConfig | None = None) -> None:
        self._config = config or RobosuiteSimulationConfig()
        self._environment: _RobosuiteEnvironment | None = None
        self._latest_observation: Mapping[str, Any] | None = None
        self._next_frame_id = 0
        self._closed = False

    def reset(self, *, seed: int | None = None) -> RGBDFrame:
        """Reset the episode and return its first synchronized RGB-D frame.

        Passing an explicit seed recreates the environment because robosuite 1.5.2
        applies its random seed at environment construction time.
        """

        self._require_open()
        if seed is not None and self._environment is not None:
            self._dispose_environment()

        if self._environment is None:
            effective_seed = self._config.seed if seed is None else seed
            self._environment = _make_robosuite_environment(self._config, effective_seed)

        self._latest_observation = self._environment.reset()
        return self._frame_from_observation(self._latest_observation)

    def capture(self) -> RGBDFrame:
        """Return a frame for the latest synchronized simulator observation."""

        self._require_open()
        if self._environment is None or self._latest_observation is None:
            raise RuntimeError("reset() must be called before capture()")
        return self._frame_from_observation(self._latest_observation)

    @property
    def action_dimension(self) -> int:
        """Return the configured action width after environment reset."""

        self._require_open()
        if self._environment is None:
            raise RuntimeError("reset() must be called before reading action_dimension")
        return int(self._environment.action_dim)

    def robot_state(self) -> PandaProprioception:
        """Return Panda end-effector-site and gripper proprioception only."""

        self._require_open()
        if self._environment is None or self._latest_observation is None:
            raise RuntimeError("reset() must be called before robot_state()")

        observation = self._latest_observation
        required = (
            "robot0_eef_pos",
            "robot0_eef_quat_site",
            "robot0_gripper_qpos",
        )
        missing = [key for key in required if key not in observation]
        if missing:
            raise KeyError(
                f"missing robot proprioception {missing}; available keys: "
                f"{sorted(observation)}"
            )

        position = np.asarray(observation["robot0_eef_pos"], dtype=np.float64)
        quaternion = np.asarray(
            observation["robot0_eef_quat_site"], dtype=np.float64
        )
        gripper_qpos = np.asarray(
            observation["robot0_gripper_qpos"], dtype=np.float64
        )
        if position.shape != (3,):
            raise ValueError(f"robot0_eef_pos must have shape (3,), got {position.shape}")
        if quaternion.shape != (4,):
            raise ValueError(
                "robot0_eef_quat_site must have shape (4,), "
                f"got {quaternion.shape}"
            )

        world_from_eef = np.eye(4, dtype=np.float64)
        world_from_eef[:3, :3] = _xyzw_quaternion_to_matrix(quaternion)
        world_from_eef[:3, 3] = position
        return PandaProprioception(
            timestamp_s=float(self._environment.sim.data.time),
            world_from_eef=world_from_eef,
            gripper_qpos=gripper_qpos.copy(),
        )

    def apply_action(self, action: NDArray[np.float64]) -> RGBDFrame:
        """Advance the simulator by one control step and return the new frame."""

        self._require_open()
        if self._environment is None:
            raise RuntimeError("reset() must be called before apply_action()")

        action_array = np.asarray(action, dtype=np.float64)
        expected_shape = (int(self._environment.action_dim),)
        if action_array.shape != expected_shape:
            raise ValueError(
                f"action must have shape {expected_shape}, got {action_array.shape}"
            )
        if not np.all(np.isfinite(action_array)):
            raise ValueError("action must contain only finite values")

        self._latest_observation = self._environment.step(action_array.copy())[0]
        return self._frame_from_observation(self._latest_observation)

    def close(self) -> None:
        """Release robosuite resources; repeated calls are safe."""

        if self._closed:
            return
        self._dispose_environment()
        self._closed = True

    def _evaluation_object_pose(
        self, object_name: str
    ) -> NDArray[np.float64]:
        """Private truth hook consumed only by ``vision2grasp.evaluation``."""

        self._require_open()
        if self._environment is None:
            raise RuntimeError("reset() must be called before evaluation truth access")
        if self._config.environment != "BottleLift" or object_name != "bottle":
            raise ValueError("evaluation truth is restricted to BottleLift/bottle")

        body_id = self._environment.sim.model.body_name2id("bottle_main")
        position = np.asarray(
            self._environment.sim.data.body_xpos[body_id], dtype=np.float64
        )
        rotation = np.asarray(
            self._environment.sim.data.body_xmat[body_id], dtype=np.float64
        ).reshape(3, 3)
        world_from_object = np.eye(4, dtype=np.float64)
        world_from_object[:3, :3] = rotation
        world_from_object[:3, 3] = position
        return world_from_object

    def _dispose_environment(self) -> None:
        environment = self._environment
        self._environment = None
        self._latest_observation = None
        if environment is not None:
            environment.close()

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("simulator is closed")

    def _frame_from_observation(self, observation: Mapping[str, Any]) -> RGBDFrame:
        environment = self._environment
        if environment is None:
            raise RuntimeError("simulator environment is not initialized")

        rgb_key = f"{self._config.camera_name}_image"
        depth_key = f"{self._config.camera_name}_depth"
        missing = [key for key in (rgb_key, depth_key) if key not in observation]
        if missing:
            raise KeyError(
                f"missing RGB-D observations {missing}; available keys: "
                f"{sorted(observation)}"
            )

        expected_rgb_shape = (
            self._config.camera_height,
            self._config.camera_width,
            3,
        )
        expected_depth_shape = (
            self._config.camera_height,
            self._config.camera_width,
        )

        rgb_source = np.asarray(observation[rgb_key])
        if rgb_source.shape != expected_rgb_shape:
            raise ValueError(
                f"RGB observation must have shape {expected_rgb_shape}, "
                f"got {rgb_source.shape}"
            )
        if rgb_source.dtype != np.uint8:
            raise ValueError(f"RGB observation must use uint8, got {rgb_source.dtype}")
        rgb = rgb_source.copy()

        normalized_depth = np.asarray(observation[depth_key]).squeeze()
        if normalized_depth.shape != expected_depth_shape:
            raise ValueError(
                f"depth observation must have shape {expected_depth_shape}, "
                f"got {normalized_depth.shape}"
            )
        depth_m = np.asarray(
            _metric_depth(environment.sim, normalized_depth), dtype=np.float32
        )
        if depth_m.shape != expected_depth_shape:
            raise ValueError(
                f"metric depth must have shape {expected_depth_shape}, got {depth_m.shape}"
            )
        if not np.all(np.isfinite(depth_m)) or np.any(depth_m <= 0.0):
            raise ValueError("metric depth must contain only finite positive values")

        intrinsic_matrix = np.asarray(
            _camera_intrinsic_matrix(
                environment.sim,
                self._config.camera_name,
                self._config.camera_height,
                self._config.camera_width,
            ),
            dtype=np.float64,
        )
        if intrinsic_matrix.shape != (3, 3) or not np.all(
            np.isfinite(intrinsic_matrix)
        ):
            raise ValueError("camera intrinsic matrix must be a finite 3x3 matrix")

        world_from_camera = np.asarray(
            _world_from_camera_matrix(environment.sim, self._config.camera_name),
            dtype=np.float64,
        )
        if world_from_camera.shape != (4, 4) or not np.all(
            np.isfinite(world_from_camera)
        ):
            raise ValueError("world_from_camera must be a finite 4x4 matrix")

        frame = RGBDFrame(
            frame_id=self._next_frame_id,
            timestamp_s=float(environment.sim.data.time),
            camera_name=self._config.camera_name,
            rgb=rgb,
            depth_m=depth_m.copy(),
            intrinsics=CameraIntrinsics(
                width=self._config.camera_width,
                height=self._config.camera_height,
                fx=float(intrinsic_matrix[0, 0]),
                fy=float(intrinsic_matrix[1, 1]),
                cx=float(intrinsic_matrix[0, 2]),
                cy=float(intrinsic_matrix[1, 2]),
            ),
            world_from_camera=world_from_camera.copy(),
        )
        self._next_frame_id += 1
        return frame


def _xyzw_quaternion_to_matrix(
    quaternion: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Convert robosuite's site quaternion convention without importing it."""

    norm = float(np.linalg.norm(quaternion))
    if not np.isfinite(norm) or norm <= 1e-12:
        raise ValueError("robot0_eef_quat_site must be a finite non-zero quaternion")
    x, y, z, w = quaternion / norm
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
