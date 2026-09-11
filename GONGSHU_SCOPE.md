# Gongshu Open-Source Scope

Status: Boundary Freeze v0.1
Effective date: 2026-09-11

## Purpose

This document defines the open-source boundary of Gongshu. It distinguishes the
long-term platform from optional integrations, research-specific work, unrelated
products, local runtime data, and third-party material.

The boundary is intentionally conservative. A component is not part of the
stable Gongshu core merely because it currently exists in the same repository.

## Project Positioning

Gongshu is a local-first, modular experimentation platform for robot vision and
grasping. It connects visual input, target perception, spatial understanding,
grasp planning, control abstractions, evaluation, and physics-based validation
in an observable and reproducible workflow.

The current platform focuses on software experimentation and simulation. It is
not a safety-certified robot control system and does not claim validated
end-to-end deployment on physical robots.

## Included in Gongshu

The long-term Gongshu scope includes:

- robot-vision input abstractions;
- RGB and RGB-D frame handling;
- local camera and image input;
- target perception and target-selection contracts;
- spatial understanding, camera intrinsics, depth, and point-cloud processing;
- geometric localization and calibration;
- grasp-planning contracts, planners, and feasibility checks;
- robot-control abstractions;
- simulation environments and validation services;
- evaluation and reproducible run-artifact tooling;
- the Gongshu experiment workspace and its direct application entry points;
- configuration, schemas, tests, documentation, and release tooling required to
  maintain the platform.

Inclusion in this scope does not automatically make every current symbol a
stable public API. API stability is governed separately.

## Optional Backends and Integrations

Concrete third-party models, runtimes, and hardware-specific integrations are
optional backends rather than the definition of Gongshu core. This category
currently includes, without limitation:

- Ultralytics and FastSAM;
- Depth Anything V2;
- GR-ConvNet;
- robosuite;
- specific robot, camera, model, or dataset adapters.

These integrations retain their own license conditions. An optional backend may
be unavailable, separately installed, or excluded from a particular Gongshu
distribution without changing the identity of the core platform.

At Boundary Freeze v0.1, dependency and packaging metadata have not yet been
reorganized to fully enforce this optional-backend policy. The policy in this
document records the intended open-source boundary; it does not claim that the
current installation layout already implements that separation.

## Not Included in Gongshu

The Gongshu open-source project does not include:

- paper-specific source code or unpublished research implementations;
- paper experiment configurations, ablation studies, dedicated dataset splits,
  result tables, or figure-generation pipelines;
- private or restricted datasets;
- unpublished checkpoints or model weights without redistribution permission;
- XUANSHU brand portals or ecosystem launchers;
- Jingwei Moment or other non-Gongshu products;
- Hetu or planned world-model products;
- internal handoff documents, private planning notes, or agent context;
- user captures, uploaded media, recordings, logs, sessions, calibration data,
  local certificates, private keys, or machine-specific runtime state;
- credentials, tokens, private network details, or personally identifying data.

Some out-of-scope components still exist in the repository at Boundary Freeze
v0.1. They are recorded as known boundary debt. This document does not move or
delete them.

## Research-Hold Boundary

Code or configuration whose relationship to an active paper or unpublished
research direction is unresolved must remain in research hold. Research-hold
material is not automatically part of Gongshu core, must not be promoted as a
stable public interface, and must not be deleted or relocated until its
ownership and publication status are confirmed.

This boundary document does not determine paper algorithms or paper claims.

## License Boundary

Original Gongshu source code is made available under the Apache License 2.0,
subject to the repository's LICENSE file.

The Apache License 2.0 declaration does not replace or override licenses that
apply to third-party code, model weights, datasets, media, fonts, trademarks, or
other incorporated material. Such material remains subject to its respective
license and attribution requirements. THIRD_PARTY_NOTICES.md records known
third-party components and must be consulted before use or redistribution.

Components under the GNU Affero General Public License or another strong
copyleft license are treated as optional backends. They are not included in a
default permissive-license claim. Any combined distribution that includes such
components requires a separate license-compliance review.

Model availability does not imply permission to redistribute a model. Source
code releases, model assets, and application bundles are separate distribution
boundaries.

## Data, Privacy, and Runtime Boundary

Runtime data belongs outside the tracked source tree. Generated certificates,
private keys, sessions, captures, uploads, recordings, logs, model caches,
benchmark outputs, and user calibration files must not be committed or included
in source releases.

Examples and tests intended for public distribution must use fixtures with
documented provenance and redistribution permission. Sensitive or
machine-specific output must be redacted before it is attached to an issue or
shared publicly.

## Capability Claims

Gongshu documentation and releases must distinguish among implemented,
experimental, planned, and unsupported capabilities.

In particular:

- monocular depth must not be described as calibrated sensor-grade RGB-D;
- MuJoCo or robosuite results must not be described as physical-robot results;
- local phone-camera input must not be described as a completed real-robot
  grasping loop;
- an interface or placeholder must not be described as an available backend;
- a model score must not be described as a calibrated success probability
  unless such calibration is separately demonstrated.

## Boundary Change Control

Changes to this boundary require an explicit governance review. A proposed
addition must state:

1. why the component is reusable beyond one paper or experiment;
2. whether it belongs to core or an optional backend;
3. its license, data, model, and privacy implications;
4. its maintenance owner;
5. its documentation, example, and test obligations;
6. whether it changes an existing public contract or capability claim.

No feature becomes Gongshu core solely through repository proximity or prior
inclusion in a prototype release.
