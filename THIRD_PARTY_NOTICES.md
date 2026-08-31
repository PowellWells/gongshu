# Third-party model and runtime notices

## GR-ConvNet Jacquard RGB-D

- Official code and checkpoint repository: <https://github.com/skumra/robotic-grasping>
- Pinned code commit: `183c6f68c44c1c7ff0f07707e2db6fcfd6840d2d`
- Vendored inference architecture: `src/vision2grasp/_vendor/grconvnet`
- Checkpoint: `jacquard-rgbd-grconvnet3-drop0-ch32/epoch_48_iou_0.93`
- Size: `7,661,004` bytes
- SHA-256: `adfb2cbbb8df2708a732e12ddc4db114f3ec399ffb5d403ca75c5b5b9e769171`
- License: BSD-3-Clause. The vendored license is at
  `src/vision2grasp/_vendor/grconvnet/LICENSE`.

The official checkpoint is a legacy `torch.save(model)` artifact. It is loaded
only after exact size and SHA-256 verification; its state dictionary is then
copied into the pinned vendored architecture. The network consumes a 224x224
target-aware RGB-D crop using the upstream Jacquard normalization order and
produces real pixel-wise quality, angle, and width maps. The target mask gates
candidate extraction but is not used to erase RGB-D context before inference.
Network quality is an uncalibrated grasp score, not a success probability.

The upstream-compatible resize and Gaussian postprocessing use `scikit-image`
(BSD-3-Clause). It is a runtime dependency, not vendored source.

## Depth Anything V2 Metric Indoor Small

- Official code: <https://github.com/DepthAnything/Depth-Anything-V2>
- Pinned code commit: `a561b849ebae10a6f5ef49e26c83cbbcd36c71bf`
- Vendored subtree: `metric_depth/depth_anything_v2`
- Official checkpoint repository: <https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-Hypersim-Small>
- Pinned model revision: `3bc65d4e14a6786a61acec16453c50e12bf5f338`
- Checkpoint: `depth_anything_v2_metric_hypersim_vits.pth`
- Size: `99,222,290` bytes
- SHA-256: `b782898d8a3e8be1f639de33837ed85e9b4b73e40f8f5e5cd99067588d722545`
- License: Apache-2.0. The vendored license is at
  `src/vision2grasp/_vendor/depth_anything_v2/LICENSE`.

The model is a metric-scaled monocular estimator trained for indoor scenes.
Vision2Grasp exposes Phone Mode output as **Approx. Metric**. It is not a
sensor-grade metric-depth measurement, and nominal FOV intrinsics do not
restore absolute scale.

## FastSAM Small

- Official project: <https://github.com/CASIA-IVA-Lab/FastSAM>
- Verified download mirror: <https://github.com/ultralytics/assets/releases/tag/v8.4.0>
- Asset release: `v8.4.0`
- Checkpoint: `FastSAM-s.pt`
- Size: `23,851,578` bytes
- SHA-256: `c9f78716a81c7aff0d608ccc73e1b82ab3aaad86005049f6a92106a0be6d0844`
- Current upstream project and Ultralytics asset repository license: AGPL-3.0.

FastSAM is currently executed through Ultralytics. The pinned Ultralytics
runtime in this repository uses the AGPL-3.0 license family; formal product
distribution must review all runtime, model, and transitive dependency terms.
