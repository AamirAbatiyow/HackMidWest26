#!/bin/bash
set -e

MODEL="${DECIDER_MODEL:-StrandsAgents/strands-decider-2B-qwen3.5-v1-2610}"
PORT="${DECIDER_PORT:-8099}"

echo "Starting Strands Decider server..."
echo "  Model: $MODEL"
echo "  Port:  $PORT"
echo ""

exec strands-decider serve "$MODEL" --port "$PORT" --device cpu
