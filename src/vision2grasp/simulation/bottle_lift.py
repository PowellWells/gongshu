"""Single-bottle Lift environment built from robosuite's packaged assets.

The environment follows robosuite 1.5.2's MIT-licensed ``Lift`` model-loading
pattern, replacing its generated cube with the packaged ``BottleObject``.
"""

from __future__ import annotations

from xml.etree.ElementTree import SubElement

from robosuite.environments.manipulation.lift import Lift
from robosuite.environments.manipulation.manipulation_env import ManipulationEnv
from robosuite.models.arenas import TableArena
from robosuite.models.objects import BottleObject
from robosuite.models.tasks import ManipulationTask
from robosuite.utils.placement_samplers import UniformRandomSampler


class BottleLift(Lift):
    """Panda-compatible table task containing one upright visible bottle."""

    def _load_model(self) -> None:
        ManipulationEnv._load_model(self)

        base_position = self.robots[0].robot_model.base_xpos_offset["table"](
            self.table_full_size[0]
        )
        self.robots[0].robot_model.set_base_xpos(base_position)

        arena = TableArena(
            table_full_size=self.table_full_size,
            table_friction=self.table_friction,
            table_offset=self.table_offset,
        )
        arena.set_origin([0.0, 0.0, 0.0])

        bottle = BottleObject(name="bottle")
        self._make_bottle_opaque_blue(bottle)
        # Lift's remaining reset and robot-distance helpers operate on
        # ``self.cube`` structurally, so retain that internal alias only.
        self.bottle = bottle
        self.cube = bottle

        if self.placement_initializer is not None:
            self.placement_initializer.reset()
            self.placement_initializer.add_objects(bottle)
        else:
            self.placement_initializer = UniformRandomSampler(
                name="BottleSampler",
                mujoco_objects=bottle,
                x_range=(-0.015, 0.015),
                y_range=(-0.015, 0.015),
                rotation=0.0,
                ensure_object_boundary_in_range=False,
                ensure_valid_placement=True,
                reference_pos=self.table_offset,
                z_offset=0.004,
                rng=self.rng,
            )

        self.model = ManipulationTask(
            mujoco_arena=arena,
            mujoco_robots=[robot.robot_model for robot in self.robots],
            mujoco_objects=bottle,
        )

    @staticmethod
    def _make_bottle_opaque_blue(bottle: BottleObject) -> None:
        """Keep packaged geometry while making its silhouette camera-visible."""

        for geometry in bottle.worldbody.iter("geom"):
            geometry.attrib.pop("material", None)
            geometry.set("rgba", "0.12 0.45 0.88 1")

        main_body = bottle.worldbody.find("./body/body")
        if main_body is None:
            raise RuntimeError("BottleObject is missing its main body")
        SubElement(
            main_body,
            "geom",
            {
                "name": "bottle_label_visual",
                "type": "cylinder",
                "pos": "0 0 -0.018",
                "size": "0.026 0.022",
                "rgba": "0.94 0.94 0.90 1",
                "group": "1",
                "contype": "0",
                "conaffinity": "0",
                "mass": "1e-8",
            },
        )
        SubElement(
            main_body,
            "geom",
            {
                "name": "bottle_cap_visual",
                "type": "cylinder",
                "pos": "0 0 0.073",
                "size": "0.010 0.006",
                "rgba": "0.92 0.12 0.10 1",
                "group": "1",
                "contype": "0",
                "conaffinity": "0",
                "mass": "1e-8",
            },
        )
