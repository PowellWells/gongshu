# Gongshu Open-Source Freeze v0.1

Freeze name: `gongshu-freeze-v0.1`
Record date: 2026-09-11
Status: Approved governance freeze; canonical Git reference: `refs/tags/gongshu-freeze-v0.1`

## Freeze Purpose

This record captures the source baseline, core capabilities, known limitations,
and open-source risks identified at the start of Gongshu phase-one governance.
It is a boundary and provenance checkpoint, not a claim that the current source
tree is already a final public release.

No source code, frontend code, directory layout, or application architecture is
changed by this freeze record.

## Source Baseline

- Repository: `G:\Vision2Grasp`
- Remote: `https://github.com/PowellWells/gongshu.git`
- Branch at inspection: `codex/bottle-end-to-end-loop`
- Commit: `8379bcb3e26644a7c29f9f7ddcabfe87f15fe89b`
- Commit date: `2026-09-10T16:21:16+08:00`
- Commit subject: `docs: link v0.1.0 demo video`
- Git description before governance files: `v0.1.0-2-g8379bcb-dirty`
- Existing release tag: `v0.1.0`

The recorded commit identifies the committed source baseline only. It does not
contain pre-existing working-tree changes.

## Pre-Existing Working-Tree State

The working tree was not clean when this governance phase began. Thirteen
pre-existing changes were present under `frontend/`:

- seven tracked image files were deleted from the working tree;
- six portal or introductory frontend files were modified;
- the changes concerned Jingwei, XUANSHU portal, and introductory brand assets.

Review determined that the seven image deletions were unintended. They were
restored to the committed baseline. The six text changes were confirmed as
intentional fixes for the XUANSHU introductory playback sequence and were
preserved in the immediately preceding commit:

`b610ea36df271c12e024a109dc10a9388c2fcb7b`

The fixes remain outside the long-term Gongshu core boundary and are retained as
documented migration debt. The working tree was reconciled before the governance
commit and annotated freeze tag were created.

## Core Capabilities at the Freeze

The repository currently contains the following Gongshu platform capabilities:

- local phone-camera RGB acquisition over a trusted private LAN;
- OpenCV image, array, and camera input sources;
- RGB and RGB-D data contracts;
- target segmentation, candidate presentation, selection, and target locking;
- monocular depth and RGB-D provider interfaces;
- camera-intrinsics selection, spatial observation, and point-cloud processing;
- geometric target localization and table calibration;
- planar, PCA, and pixel-wise Top-K grasp-planning implementations;
- robot-control abstractions and a Panda OSC execution implementation;
- MuJoCo and robosuite simulation and validation components;
- target-appearance mapping, validation recordings, and playback;
- lift evaluation and reproducible run-artifact export;
- a Gongshu experiment workspace covering vision, spatial perception, grasp
  planning, and simulation validation;
- model-asset resolution with pinned revisions, file sizes, and SHA-256 checks.

Concrete third-party models and runtimes are not the definition of Gongshu core.
Their status is governed by GONGSHU_SCOPE.md and THIRD_PARTY_NOTICES.md.

## Validation Snapshot

During the read-only repository audit on 2026-09-11, the existing Python test
suite reported:

```text
Ran 197 tests in 63.341s
OK
```

The run used the existing local environment and local ignored model and fixture
assets. It is not evidence that a clean clone provides identical coverage. The
run also emitted robosuite optional-dependency warnings, a socket
`ResourceWarning`, and graphics-context fallback messages.

## Known Functional Limitations

- The currently documented and tested primary platform is Windows 11 with
  Python 3.12.
- Phone Camera currently provides RGB input, not calibrated RGB-D input.
- Monocular depth is an approximate research output and is not equivalent to a
  calibrated depth sensor measurement.
- Grasp execution is primarily validated in simulation.
- The repository does not contain a validated end-to-end deployment on a
  physical robot.
- Current model-backed workflows require external model assets.
- A clean source clone may skip model- or fixture-dependent tests.
- CUDA is optional, and CPU execution may be slow for model-backed workflows.
- Public Python, HTTP, configuration, and artifact interfaces have not yet been
  declared stable.
- Legacy and newer pipeline paths coexist and have not yet received a formal
  compatibility or deprecation designation.

## Known Open-Source Boundary Limitations

- XUANSHU LAB, Jingwei Moment, Hetu, and brand-portal content still coexist with
  Gongshu in the repository. They are not Gongshu core under
  GONGSHU_SCOPE.md.
- Research-hold material has not yet received a final public/private ownership
  decision.
- Third-party backends have not yet been separated into installation extras.
- Packaging metadata still treats several heavy or copyleft components as
  ordinary dependencies.
- Source, model, and application-bundle distribution boundaries are not yet
  fully automated.
- The release packaging path has not yet been converted to an explicit content
  allowlist.
- The local `main`, remote `main`, release branch, and current development line
  are not yet organized into a single release history.

## License Snapshot

- Original Gongshu source code: Apache License 2.0.
- Third-party source code: remains under its respective license.
- Model weights and datasets: remain under their respective terms and are not
  covered by the Gongshu Apache License 2.0 grant.
- Media and brand assets: remain subject to their respective ownership and
  license status.
- Strong-copyleft and AGPL components: optional backends; not included in a
  default permissive-license claim.

Known third-party records are maintained in THIRD_PARTY_NOTICES.md. Adding the
project LICENSE does not by itself certify every possible combined binary or
model bundle as license-compliant.

## Sensitive-Information Snapshot

The source audit identified the following boundary risks:

- the ignored local `artifacts/camera/secrets/` directory contains generated
  certificate and private-key material;
- ignored local artifacts also contain model weights, logs, calibration data,
  benchmark output, and generated run media;
- `CODEX_HANDOFF.md` is currently ignored but existed in repository history and
  contains internal development context and machine-specific paths;
- repository history, release assets, images, videos, and future bundles still
  require a dedicated publication review.

No currently tracked private-key, certificate-key, environment-secret, or model
weight file extension was found in the inspected HEAD tree. Private-key marker
text found in a camera test is test-fixture validation rather than a committed
private key. This is a point-in-time review, not a guarantee that no sensitive
content exists anywhere in repository history or external release storage.

## Explicitly Out of Scope for This Freeze

This freeze does not:

- modify `src/` or core application logic;
- modify `frontend/` beyond the six confirmed introductory playback fixes;
- move or delete directories;
- change application behavior, dependencies, APIs, or schemas;
- decide or implement paper algorithms;
- reorganize Git branches or rewrite Git history;
- certify a Windows bundle containing third-party backends;
- represent a v1.0 API stability promise.

## Freeze Tag Invariants

The canonical freeze reference is the annotated tag
`gongshu-freeze-v0.1`. It must:

1. point directly to the governance commit containing this document;
2. use the message `Gongshu governance freeze v0.1`;
3. include the preceding frontend playback fix commit in its history;
4. be created only from a clean working tree;
5. be pushed without force or history rewriting.
