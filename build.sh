#!/usr/bin/env bash
# Exit on error
set -o errexit

echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Generating synthetic scenario data ==="
python -m netcoop generate

echo "=== Building React Web UI ==="
cd web
npm install
npm run build
cd ..

echo "=== Build completed successfully ==="

