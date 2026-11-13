#!/bin/bash
# Fine-tune on a Slurm cluster with AMD GPUs (ROCm), one node. Best effort: the CUDA path is the tested one.
# Fill in the account / partition / paths for your cluster, then:  sbatch train/vlm/slurm_rocm.sbatch
#
# Container: any ROCm PyTorch >= 2.6 image (e.g. a site-provided rocm/pytorch Singularity image) with a venv
# on top that has the pins from train/vlm/setup_remote.sh (transformers / peft / trl / accelerate):
#   singularity exec $SIF bash -c 'python -m venv --system-site-packages venv && venv/bin/pip install \
#       transformers==5.23.0 peft==0.21.3 trl==1.18.0 accelerate==1.15.0 datasets pillow "jinja2>=3.1.6"'
# bitsandbytes / flash-attn are not needed (bf16 LoRA, sdpa attention).
#SBATCH --job-name=bp-vlm
#SBATCH --account=CHANGE_ME
#SBATCH --partition=CHANGE_ME
#SBATCH --nodes=1
#SBATCH --gpus-per-node=8
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=56
#SBATCH --mem=480G
#SBATCH --time=06:00:00
#SBATCH --output=%x-%j.out
set -euo pipefail
WORK=${WORK:-$PWD}                   # holds bp/, train/, cache/vlm/ (data), venv/
SIF=${SIF:?set SIF to the ROCm PyTorch container image}
MODEL=${MODEL:-Qwen/Qwen3-VL-8B-Instruct}
export HF_HOME=$WORK/cache/hf MIOPEN_USER_DB_PATH=/tmp/miopen-$SLURM_JOB_ID MIOPEN_CUSTOM_CACHE_DIR=/tmp/miopen-$SLURM_JOB_ID
export OMP_NUM_THREADS=6 TOKENIZERS_PARALLELISM=false
NG=${SLURM_GPUS_PER_NODE:-8}

srun singularity exec -B "$WORK" "$SIF" bash -c "
  cd $WORK && source venv/bin/activate
  torchrun --standalone --nproc_per_node $NG train/vlm/train.py --model $MODEL --data cache/vlm \
    --out cache/vlm/runs/rocm-\$SLURM_JOB_ID --batch 2 --grad-accum $((16 / NG > 0 ? 16 / NG : 1)) --epochs 1 \
    --save-steps 200 --eval-steps 200 --workers 6
"
