# Chandra vLLM Server Setup Guide

## Overview
This setup uses vLLM to serve the Chandra OCR model, providing an OpenAI-compatible API for fast inference.

## Requirements
- NVIDIA GPU with CUDA support (recommended: 24GB+ VRAM for the full model)
- Python 3.8+
- CUDA 11.8 or higher

## Installation

### 1. Install vLLM
```bash
# Activate your virtual environment
source backend/venv/bin/activate

# Install vLLM with CUDA support
pip install vllm

# Or install from source for latest features
# pip install git+https://github.com/vllm-project/vllm.git
```

### 2. Install additional dependencies
```bash
pip install requests pillow pymupdf
```

## Usage

### Start the vLLM Server

**Option 1: Using the startup script (recommended)**
```bash
bash backend/start_chandra_vllm.sh
```

**Option 2: Manual command**
```bash
vllm serve datalab-to/chandra \
    --host 0.0.0.0 \
    --port 8000 \
    --gpu-memory-utilization 0.9 \
    --trust-remote-code \
    --max-model-len 4096
```

The server will:
- Download the model (~17GB) on first run (cached for future use)
- Start an OpenAI-compatible API at `http://localhost:8000`
- Use GPU for fast inference

### Use the Client

Once the server is running, use the client script:
```bash
python3 backend/chandra_vllm_client.py
```

## Configuration

### Server Settings (in `start_chandra_vllm.sh`):
- `PORT=8000` - API port
- `GPU_MEMORY_UTILIZATION=0.9` - GPU memory usage (0.0-1.0)
- `TENSOR_PARALLEL_SIZE=1` - Number of GPUs for model parallelism
- `--max-model-len 4096` - Maximum sequence length

### Client Settings (in `chandra_vllm_client.py`):
- `VLLM_SERVER` - Server endpoint
- `input_pdf` - Path to input PDF
- `output_dir` - Output directory

## Advantages of vLLM

1. **Fast Inference**: vLLM is optimized for high-throughput serving
2. **Memory Efficient**: PagedAttention reduces memory usage
3. **API Compatible**: OpenAI-compatible API for easy integration
4. **Batching**: Automatic request batching for better GPU utilization
5. **Model Caching**: Model downloaded once, reused forever

## Troubleshooting

### Server won't start
- Check CUDA installation: `nvidia-smi`
- Verify GPU memory: Make sure you have enough VRAM
- Check port availability: `lsof -i :8000`

### Out of memory
- Reduce `--gpu-memory-utilization` to 0.7 or 0.8
- Reduce `--max-model-len` to 2048
- Try using CPU (much slower): remove `.cuda()` calls

### Model download issues
- Check internet connection
- Verify Hugging Face access
- Clear cache if corrupted: `rm -rf ~/.cache/huggingface/hub/models--datalab-to--chandra`

## Comparison: vLLM vs Direct Model Loading

| Aspect | vLLM Server | Direct Loading |
|--------|-------------|----------------|
| Setup | One-time server start | Load model each run |
| Speed | Very fast (optimized) | Slower |
| Memory | Efficient (paged) | Uses more memory |
| API | RESTful HTTP | Python only |
| Reuse | Multiple clients | Single process |

## Next Steps

After getting good results with Chandra, you can integrate it into `ocr_then_gemini.py` to replace or complement Tesseract OCR!
