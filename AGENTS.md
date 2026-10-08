# Vision2Grasp agent instructions

## Repository boundary

This repository contains the Gongshu / 公输 robot-vision platform. Xiezhi / 獬豸
is an internal decision and algorithm capability under Gongshu; it is not a
standalone application or repository. Keep the existing `src/vision2grasp`
layout and the one-way platform contract. Do not import the DaTong Grasp
research repository or copy the external Mayflower runtime into this tree.

The only user-facing Windows entry is `Start-Vision2Grasp.cmd`. The desktop
launcher may optionally discover an external Xiezhi/Mayflower runtime through
`PYTHONPATH`; absence of that runtime must remain an observable degradation,
not a reason to make Gongshu unusable.

## Change and data rules

- Audit the real call chain before changing a contract or module boundary.
- Keep datasets, model weights, captures, experiment outputs, logs, caches,
  certificates, private keys, tokens, and local runtime state out of Git.
- Do not add API keys, access tokens, passwords, camera credentials, or private
  network details to source, tests, fixtures, documentation, or Git history.
- Preserve typed failure and unavailable states. Do not turn a skipped or
  unavailable dependency into a successful experiment result.
- Do not start model downloads, training, large experiments, or real-device
  control as part of a normal code task.

## Validation

For cloud-safe changes, use Python 3.12 and run:

```bash
python -m pip install -r requirements-cloud.txt
python -m pip install -e . --no-deps
PYTHONPATH=src python -m pytest -q tests/test_vlm_grounding.py tests/test_contracts.py
```

The full dependency set, desktop UI, phone camera, model-backed perception,
MuJoCo/robosuite validation, CUDA, and external Xiezhi/Mayflower integration
remain local checks. Use the commands in `docs/CODEX_CLOUD.md` to classify a
result as cloud smoke validation or local experiment evidence.
