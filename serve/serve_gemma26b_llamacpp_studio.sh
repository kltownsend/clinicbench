#!/bin/bash
# clinicbench speed test: Gemma 4 26B-A4B on the M5 Ultra Studio under llama.cpp b11399
# (commit 2ca15f5404760548c39e7b92bd43116a09414a1a), bf16 GGUF converted from the same
# weights the Sparks serve (revision 20da991a, files checked byte-identical).
# Sampling matches what vLLM applies from the model's generation_config when the driver sends
# no temperature: temperature 1.0, top-k 64, top-p 0.95, no min-p. Thinking off, as on the Sparks: llama.cpp's template turns it on by
# default (vLLM's doesn't), so --reasoning-budget 0.
# Context is 16,384 tokens per slot (llama-server splits -c across slots); bench prompts are a few
# hundred tokens. Not the Sparks' 262,144 envelope: a speed test, not a cell venue.
# usage: serve_gemma26b_llamacpp_studio.sh <parallel slots>
set -u
NP="${1:?usage: serve_gemma26b_llamacpp_studio.sh <parallel slots>}"
GGUF="$HOME/models/gguf/gemma-4-26B-A4B-it-bf16/gemma-4-26B-A4B-it-20da991a-bf16.gguf"
LOG="$HOME/cb-convert/llama-server-np${NP}-$(date +%Y%m%d_%H%M%S).log"
pkill -f "llama-server .*gemma-4-26B-A4B-it-20da991a" ; sleep 2
nohup "$HOME/src/llama.cpp/build/bin/llama-server" -m "$GGUF" --alias gemma-4-26b-a4b \
  -ngl 99 -np "$NP" -c $((16384 * NP)) --jinja \
  --temp 1.0 --top-k 64 --top-p 0.95 --min-p 0 --reasoning-budget 0 \
  --host 0.0.0.0 --port 8080 > "$LOG" 2>&1 < /dev/null &
echo "serve log -> $LOG"
