# Local VLM grounding architecture

This is the object-level grounding path integrated into the existing Gongshu
workspace. The VLM is not a robot controller and does not produce a 6D grasp.

```mermaid
flowchart LR
  A[Start-Vision2Grasp.cmd] --> B[Start-XUANSHU-LAB.cmd]
  B --> C[LocalServiceController]
  C --> D[llama.cpp llama-server\nQwen3-VL-4B Q4 GGUF + mmproj]
  C --> E[Gongshu backend :8765]
  F[RGB frame + natural-language instruction] --> G[LocalVLMGrounder\n/v1/chat/completions]
  D --> G
  G --> H[grounding schema\nbbox + point + evidence]
  H --> I[FastSAM TargetPerception\nselect_at(point)]
  I --> J[target mask + SceneSnapshot]
  J --> K[Depth / point cloud]
  K --> L[GR-ConvNet Top-K]
  L --> M[Xiezhi Decision]
  M --> N[Gongshu execution]
  N --> O[MuJoCo validation]
  C -. close window .-> P[stop backend + stop owned VLM]
```

The stable application boundary is:

```text
POST /api/vlm/ground
  instruction
  + current frozen RGB analysis frame
    -> gongshu.vlm-target-selection/v1
       grounding {bbox_xyxy, point_xy, confidence, evidence}
       target_perception {selected_target, scene_snapshot}
```

The final mask is always the existing FastSAM mask. If the VLM service or
assets are unavailable, the canonical launcher fails with an explicit asset
error rather than silently substituting a stub.
