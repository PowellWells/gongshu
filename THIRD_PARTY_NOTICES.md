# Third-party model and runtime notices

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
