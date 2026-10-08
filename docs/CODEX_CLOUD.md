# Codex Cloud development / Codex Cloud 云端开发

This guide describes the smallest reproducible cloud workflow for the
Gongshu / 公输 repository. It is a development smoke path, not a replacement
for the Windows desktop or robot experiment environment.

## Repository and branch

Use the private `PowellWells/Vision2Grasp` repository after its GitHub access
has been authorized for the ChatGPT account that will run Codex Cloud. Keep
the existing public `PowellWells/gongshu` repository unchanged. Start cloud
tasks from the approved development branch and review the diff before any
commit or pull request.

## Install script

Codex Cloud can use this setup sequence in a Python 3.12 Linux environment:

```bash
python -m pip install --upgrade pip setuptools
python -m pip install -r requirements-cloud.txt
python -m pip install -e . --no-deps
```

`requirements-cloud.txt` is intentionally limited to the no-model contract
smoke path. Installing `pyproject.toml` without `--no-deps` requests the full
desktop, simulation, computer-vision, and model stack and is not the default
cloud smoke setup.

## Cloud-safe checks

```bash
PYTHONPATH=src python -m pytest -q \
  tests/test_vlm_grounding.py \
  tests/test_contracts.py
```

These checks cover public data contracts and the VLM grounding boundary. They
do not prove camera, robot, CUDA, model, or simulation behavior.

## Local-only checks

Keep the following on the Windows workstation with the relevant assets:

- `Start-Vision2Grasp.cmd`, PySide6 desktop UI, and PowerShell launchers;
- phone-camera/WebRTC pairing, local CA, and LAN access;
- FastSAM, Depth Anything V2, GR-ConvNet, local llama.cpp/VLM, and model caches;
- MuJoCo/robosuite formal validation, GPU execution, Panda control, and real
  camera or robot hardware;
- the optional external `xiezhi.runtime` / `grasp_decision` runtime from the
  Mayflower environment.

If a cloud task touches one of these areas, report the missing dependency or
asset as unavailable. Do not download private or large assets to make a smoke
check appear to pass.

## Secrets and network

Do not put credentials in this repository. If a future task needs an HTTPS
service, configure the smallest allowed domain and use Codex Cloud's personal
vault or network-secret mechanism. Keep the smoke environment secret-free.

## Evidence labels

Use `cloud smoke` for the commands above. Use `local Windows`, `GPU`,
`model-backed`, `simulation`, `camera`, or `hardware` labels for evidence that
requires those local capabilities. A skipped check is not a pass.
