"""Local multimodal target grounding through the managed llama.cpp service.

The VLM is deliberately limited to selecting *which* object is requested.  It
never emits a robot action, grasp pose, or execution command.  FastSAM remains
the source of the final object mask used by the Gongshu pipeline.
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GROUNDING_SCHEMA_VERSION = "gongshu.vlm-grounding/v1"


@dataclass(frozen=True, slots=True)
class VLMServiceState:
    url: str
    ready: bool
    message: str
    model: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": GROUNDING_SCHEMA_VERSION,
            "provider": "llama.cpp",
            "runtime": "local",
            "url": self.url,
            "ready": self.ready,
            "message": self.message,
            "model": self.model,
        }


class LocalVLMGrounder:
    """Small stdlib-only client for llama.cpp's OpenAI-compatible endpoint."""

    def __init__(self, *, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("VISION2GRASP_VLM_URL", "http://127.0.0.1:8787")).rstrip("/")
        self.model = model or os.environ.get(
            "VISION2GRASP_VLM_MODEL_NAME", "Qwen3VL-4B-Instruct-Q4_K_M.gguf"
        )

    def state(self, *, timeout: float = 0.8) -> VLMServiceState:
        request = Request(f"{self.base_url}/health", headers={"Cache-Control": "no-cache"})
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, ValueError) as error:
            return VLMServiceState(self.base_url, False, str(error), self.model)
        status = str(payload.get("status", "")).lower()
        return VLMServiceState(
            self.base_url,
            status == "ok",
            "本地 VLM 已就绪" if status == "ok" else f"VLM status={status or 'unknown'}",
            self.model,
        )

    def ground(
        self,
        *,
        instruction: str,
        image_jpeg: bytes,
        image_width: int,
        image_height: int,
        timeout: float = 120.0,
    ) -> dict[str, object]:
        normalized_instruction = instruction.strip()
        if not normalized_instruction:
            raise ValueError("自然语言抓取指令不能为空")
        if not image_jpeg:
            raise ValueError("当前冻结 RGB 帧为空")
        status = self.state()
        if not status.ready:
            raise RuntimeError(f"本地 VLM 不可用：{status.message}")
        prompt = self._prompt(normalized_instruction, image_width, image_height)
        request_payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a visual target grounding component in a robot grasping system. "
                        "Select only the requested object. Never output robot actions, grasp poses, "
                        "or control commands. Return strict JSON and no markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/jpeg;base64," + base64.b64encode(image_jpeg).decode("ascii")
                            },
                        },
                    ],
                },
            ],
            "temperature": 0.0,
            "top_p": 0.1,
            "max_tokens": 256,
            "stream": False,
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
        }
        request = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"本地 VLM 请求失败 HTTP {error.code}: {detail}") from error
        except (OSError, URLError, ValueError) as error:
            raise RuntimeError(f"本地 VLM 请求失败：{error}") from error

        content = self._content(payload)
        parsed = self._parse_json(content)
        return self._validate_result(parsed, normalized_instruction, image_width, image_height)

    @staticmethod
    def _prompt(instruction: str, width: int, height: int) -> str:
        return (
            f"Image size is width={width}, height={height}.\n"
            f"User instruction: {instruction}\n\n"
            "Ground the single object the user wants to grasp. Resolve relative phrases "
            "such as left/right and attributes such as color or object category from the image. "
            "The point must be inside the selected object's visible body, not in the background. "
            "Return exactly this JSON shape:\n"
            '{"target_description":"short description",'
            '"object_category":"object category or unknown",'
            '"bbox_xyxy":[x1,y1,x2,y2],'
            '"point_xy":[x,y],'
            '"confidence":0.0,'
            '"relative_position":"left|center|right|unknown",'
            '"evidence":"short visual evidence"}\n'
            "Return coordinates in a normalized 0..1000 coordinate space, where x=0 is the "
            "left edge, x=1000 is the right edge, y=0 is the top edge, and y=1000 is the "
            "bottom edge. The runtime will map them to original pixels. confidence must be "
            "between 0 and 1. Do not include any other keys."
        )

    @staticmethod
    def _content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("本地 VLM 响应缺少 choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", "")) for item in content if isinstance(item, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("本地 VLM 响应缺少文本 grounding 结果")
        return content.strip()

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
            if match is None:
                raise RuntimeError("本地 VLM 未返回可解析 JSON")
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError as error:
                raise RuntimeError("本地 VLM grounding JSON 无法解析") from error
        if not isinstance(parsed, dict):
            raise RuntimeError("本地 VLM grounding 结果必须是 JSON object")
        return parsed

    @staticmethod
    def _validate_result(
        result: dict[str, Any], instruction: str, width: int, height: int
    ) -> dict[str, object]:
        bbox = result.get("bbox_xyxy")
        point = result.get("point_xy")
        if not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
            raise RuntimeError("本地 VLM bbox_xyxy schema 无效")
        if not isinstance(point, list) or len(point) != 2 or not all(isinstance(v, (int, float)) for v in point):
            raise RuntimeError("本地 VLM point_xy schema 无效")
        normalized_values = [float(v) for v in (*bbox, *point)]
        if not all(0.0 <= value <= 1000.0 for value in normalized_values):
            raise RuntimeError("本地 VLM bbox/point grounding 坐标必须位于归一化 [0, 1000] 范围")
        nx1, ny1, nx2, ny2 = (float(v) for v in bbox)
        npx, npy = (float(v) for v in point)
        x1, y1, x2, y2 = (
            nx1 * width / 1000.0,
            ny1 * height / 1000.0,
            nx2 * width / 1000.0,
            ny2 * height / 1000.0,
        )
        px, py = npx * width / 1000.0, npy * height / 1000.0
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise RuntimeError("本地 VLM bbox 映射后超出原始图像范围")
        if not (0 <= px < width and 0 <= py < height):
            raise RuntimeError("本地 VLM point 映射后超出原始图像范围")
        confidence = result.get("confidence")
        confidence_value = None if confidence is None else float(confidence)
        if confidence_value is not None and not 0 <= confidence_value <= 1:
            raise RuntimeError("本地 VLM confidence 必须位于 [0, 1]")
        return {
            "schema_version": GROUNDING_SCHEMA_VERSION,
            "status": "grounded",
            "instruction": instruction,
            "target_description": str(result.get("target_description", "")).strip(),
            "object_category": str(result.get("object_category", "unknown")).strip() or "unknown",
            "bbox_xyxy": [round(v, 2) for v in (x1, y1, x2, y2)],
            "point_xy": [round(px, 2), round(py, 2)],
            "point_source": "vlm",
            "coordinate_space": "original_pixels",
            "coordinate_transform": "vlm_normalized_1000_to_original",
            "confidence": confidence_value,
            "relative_position": str(result.get("relative_position", "unknown")),
            "evidence": str(result.get("evidence", "")).strip(),
            "image_size_px": {"width": width, "height": height},
        }
