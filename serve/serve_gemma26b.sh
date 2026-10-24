#!/bin/bash
# The reference reader: Gemma 4 26B-A4B (bf16) on vLLM, the envelope clinicbench's reference cells used.
#   model     google/gemma-4-26B-A4B-it at revision 20da991ab4afab98e8f910c4a2e8f4fbefc404ad (pinned:
#             a newer revision is different weights)
#   context   262144 tokens (the runner's --envelope default; it checks the server reports it)
#   image     vllm/vllm-openai:v0.25.1
#   reasoning off (the model's default), served name gemma-4-26b-a4b
# Needs an NVIDIA GPU with roughly 80 GB or more of memory for the weights and KV cache at this context,
# Docker with the NVIDIA container runtime, and Gemma's license accepted on Hugging Face (set HF_TOKEN
# for the first download). Binds to 127.0.0.1 only: the server has no API key, so don't expose it.
# The container is named cb-gemma26b; an existing container of that name is replaced.
set -u
CNAME=cb-gemma26b
docker rm -f "$CNAME" 2>/dev/null
docker run -d --name "$CNAME" --gpus all --ipc host -p 127.0.0.1:8000:8000 \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" -e HF_TOKEN="${HF_TOKEN:-}" \
  vllm/vllm-openai:v0.25.1 \
  google/gemma-4-26B-A4B-it --revision 20da991ab4afab98e8f910c4a2e8f4fbefc404ad \
  --served-model-name gemma-4-26b-a4b \
  --dtype bfloat16 --max-model-len 262144 --gpu-memory-utilization 0.80 \
  --max-num-seqs 16 --enable-prefix-caching \
  --enable-auto-tool-choice --tool-call-parser gemma4 \
  --host 0.0.0.0 --port 8000
echo "serving on http://127.0.0.1:8000/v1 (logs: docker logs -f $CNAME)"
