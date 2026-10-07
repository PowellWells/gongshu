from __future__ import annotations

import unittest

from vision2grasp.vlm_grounding import LocalVLMGrounder


class LocalVLMGroundingContractTests(unittest.TestCase):
    def test_valid_grounding_is_normalized_without_robot_action_fields(self) -> None:
        result = LocalVLMGrounder._validate_result(
            {
                "target_description": "red bottle",
                "object_category": "bottle",
                "bbox_xyxy": [540, 210, 700, 600],
                "point_xy": [620, 400],
                "confidence": 0.91,
                "relative_position": "right",
                "evidence": "visible bottle on the right",
            },
            "抓右边的瓶子",
            1672,
            941,
        )
        self.assertEqual(result["schema_version"], "gongshu.vlm-grounding/v1")
        self.assertEqual(result["point_source"], "vlm")
        self.assertEqual(result["coordinate_space"], "original_pixels")
        self.assertNotIn("action", result)
        self.assertNotIn("grasp_pose", result)

    def test_out_of_frame_grounding_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "bbox"):
            LocalVLMGrounder._validate_result(
                {
                    "bbox_xyxy": [-1, 2, 20, 30],
                    "point_xy": [10, 10],
                },
                "抓左边那个",
                100,
                100,
            )


if __name__ == "__main__":
    unittest.main()
