#!/bin/bash
# Start Chandra OCR model with vLLM server
# This provides an OpenAI-compatible API for the Chandra model

# Configuration
MODEL_NAME="datalab-to/chandra"
PORT=8000
HOST="0.0.0.0"

# GPU settings
GPU_MEMORY_UTILIZATION=0.9  # Use 90% of GPU memory
TENSOR_PARALLEL_SIZE=1      # Number of GPUs to use

echo "========================================================================"
echo "Starting Chandra vLLM Server"
echo "========================================================================"
echo "Model: $MODEL_NAME"
echo "Port: $PORT"
echo "Host: $HOST"
echo ""
echo "This will download the model (~17GB) on first run."
echo "The server will be accessible at: http://localhost:$PORT"
echo "========================================================================"
echo ""

# Start vLLM server
vllm serve "$MODEL_NAME" \
    --host "$HOST" \
    --port "$PORT" \
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
    --tensor-parallel-size "$TENSOR_PARALLEL_SIZE" \
    --trust-remote-code \
    --max-model-len 4096 \
    --dtype auto

# Alternative with more control:
# python -m vllm.entrypoints.openai.api_server \
#     --model "$MODEL_NAME" \
#     --host "$HOST" \
#     --port "$PORT" \
#     --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
#     --trust-remote-code
