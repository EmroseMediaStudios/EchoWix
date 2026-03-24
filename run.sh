#!/bin/bash
# EchoWix Launch Script
set -e
cd "$(dirname "$0")"

echo "🔥 EchoWix Launcher"
echo ""

# Create venv if needed
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# Install deps if needed
if [ ! -f ".venv/.deps_installed" ]; then
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt -q
    touch .venv/.deps_installed
fi

# Check .env
if [ ! -f ".env" ]; then
    echo "⚠️  No .env file found. Copy .env.example to .env and add your API keys."
    exit 1
fi

source .env

echo "✨ Starting EchoWix on http://localhost:7751"
echo "   Press Ctrl+C to stop"
echo ""

python app.py
