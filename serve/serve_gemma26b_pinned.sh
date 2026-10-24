#!/bin/bash
# promise-boundary lab: Gemma 4 26B-A4B bf16, single Spark (node 2), native context.
# Envelope matches the recorded bf16 Spark venue line (tbw_base26b_bf16_spark_r1):
# max_model_len 262144, tool parser gemma4. Image vllm/vllm-openai:v0.25.1 (in use on this box).
# clinicbench copy: Lab 23's script with one added flag, --revision, so both Sparks load the same
# weights. Node 1's cache resolves the model name to a newer revision (4d7ae498); see
# docs/explorer-spec.md. Diff against lab23_serve_gemma26b.sh.orig is that flag and these lines.
set -u
CNAME=pb-gemma26b
docker rm -f "$CNAME" 2>/dev/null
docker run -d --name "$CNAME" --gpus all --ipc host --network host \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  vllm/vllm-openai:v0.25.1 \
  google/gemma-4-26B-A4B-it --revision 20da991ab4afab98e8f910c4a2e8f4fbefc404ad \
  --served-model-name gemma-4-26b-a4b \
  --dtype bfloat16 --max-model-len 262144 --gpu-memory-utilization 0.80 \
  --max-num-seqs 16 --enable-prefix-caching \
  --enable-auto-tool-choice --tool-call-parser gemma4 \
  --host 0.0.0.0 --port 8000
"$HOME/serve_instr.sh" "$CNAME"
