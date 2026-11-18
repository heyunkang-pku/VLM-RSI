#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
export PYTHONUNBUFFERED=1
export TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export CUDA_VISIBLE_DEVICES=""
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export RAYON_NUM_THREADS=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
stsg_base_python=/scratch/haozhe/miniconda3/envs/llava/bin/python
stsg_env=/scratch/haozhe/.cache/vlm-rsi/stsg-gate-b-py310-v1
stsg_readonly_site=/scratch/haozhe/.cache/vlm-rsi/video-zero-py310-compat-v1/lib/python3.10/site-packages
exec 8>/scratch/haozhe/.cache/vlm-rsi/stsg-gate-b-environment.lock
flock 8
if [ ! -f "$stsg_env/ready" ]; then
  "$stsg_base_python" -m venv "$stsg_env"
  stsg_site=$("$stsg_env/bin/python" -c 'import site; print(site.getsitepackages()[0])')
  printf '%s\n' "$stsg_readonly_site" > "$stsg_site/readonly-video-dependencies.pth"
  "$stsg_env/bin/python" -m pip install --only-binary=:all: -r requirements-gate-b.txt
  "$stsg_env/bin/python" -m pip check
  touch "$stsg_env/ready"
fi
flock -u 8
"$stsg_env/bin/python" -m pip freeze
"$stsg_env/bin/python" -m unittest discover -s tests -v
exec "$stsg_env/bin/python" -m four_group.event_mcq_v2
