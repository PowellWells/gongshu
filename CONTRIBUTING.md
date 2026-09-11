# Contributing to Gongshu

Thank you for helping improve Gongshu. The project welcomes bug reports,
documentation improvements, reproducible examples, tests, and focused platform
contributions.

## Start with the Project Boundary

Read [GONGSHU_SCOPE.md](GONGSHU_SCOPE.md) before proposing a change. Gongshu is
a modular robot-vision and grasping experimentation platform. Paper-specific
implementations, unpublished experiments, private data, machine-specific
runtime state, and unrelated products are not automatically part of Gongshu
core.

Components that currently coexist in this repository but sit outside the
frozen Gongshu core boundary require explicit maintainer review. Repository
proximity alone is not sufficient justification for expanding the core.

## Before Opening an Issue

- Search existing issues and documentation first.
- Use the bug form for reproducible defects and the feature form for proposals.
- Remove credentials, private network details, personal data, certificates,
  model files without redistribution permission, and private experiment data.
- For security vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of
  opening a public issue.

## Development Setup

The currently validated environment is Windows 11 with Python 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

Some model-backed or simulation workflows require optional external assets and
may not be available in a clean clone. Keep those limitations explicit in code,
tests, and documentation.

## Making a Change

1. Keep the change focused on one problem.
2. Preserve existing public behavior unless the proposal explicitly discusses
   compatibility and migration.
3. Add or update tests for behavior changes.
4. Update documentation when commands, interfaces, limitations, or capability
   claims change.
5. Record the provenance and license of any third-party code, model, dataset,
   media, or fixture.
6. Do not commit generated certificates, private keys, sessions, captures,
   recordings, logs, model caches, benchmark outputs, or user calibration data.

Use concise commit subjects when practical, for example:

```text
fix(camera): handle an expired pairing session
docs: clarify RGB-D input limitations
test(grasp): cover candidate ranking ties
```

## Validation

Run the checks relevant to the change. The current baseline commands are:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\tests -v
.\.venv\Scripts\python.exe -m pip check
node --check .\frontend\apps\gongshu\gongshu.js
node --check .\frontend\apps\gongshu\real-scene.js
node --check .\frontend\apps\gongshu\phone-camera\phone-camera.js
```

If a check cannot run because an optional model, GPU, simulator, camera, or
fixture is unavailable, explain that clearly in the pull request. Do not report
a skipped check as passing.

## Pull Requests

- Open the pull request against the repository's current default branch.
- Explain the problem, the proposed change, and the validation performed.
- Keep refactors separate from behavioral changes whenever possible.
- Link related issues.
- Complete the pull-request checklist honestly.
- Expect maintainers to request changes that preserve the open-source boundary,
  license compatibility, privacy, reproducibility, or realistic capability
  claims.

By contributing, you agree that your contribution is submitted under the
repository's applicable license and that you have the right to provide it.
