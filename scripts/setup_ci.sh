#!/usr/bin/env bash
# Installs the render engine on a GitHub Actions Ubuntu runner (models are cached between runs).
set -euo pipefail
cd "$(dirname "$0")/.."
sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg >/dev/null
pip install -q -r requirements.txt
mkdir -p models out stories
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  [ -f "models/$f" ] || curl -sSfL -o "models/$f" "https://huggingface.co/fastrtc/kokoro-onnx/resolve/main/$f"
done
npm i --no-audit --no-fund --silent
mkdir -p hf/demo && cp hf_template/*.json hf/demo/
( cd hf && [ -f package.json ] || npm init -y >/dev/null; npm i --no-audit --no-fund --silent hyperframes@0.9.65 )
echo "engine ready"
