#!/bin/bash
# WickMind Launch Script
cd "$(dirname "$0")"

echo "🔥 WickMind Launcher"
echo ""

# Find Python
PYTHON=""
for cmd in python3 python; do
    if command -v $cmd &>/dev/null; then
        PYTHON=$cmd
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "❌ Python not found. Install Python 3.10+ from python.org"
    exit 1
fi

# Create venv if needed
if [ ! -d ".venv" ] || [ ! -f ".venv/bin/activate" -a ! -f ".venv/Scripts/activate" ]; then
    echo "📦 Creating virtual environment..."
    $PYTHON -m venv .venv
    # Force reinstall deps
    rm -f .venv/.deps_installed
fi

# Activate venv (Mac/Linux vs Windows)
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f ".venv/Scripts/activate" ]; then
    source .venv/Scripts/activate
else
    echo "❌ Virtual environment is broken. Deleting and retrying..."
    rm -rf .venv
    $PYTHON -m venv .venv
    source .venv/bin/activate
fi

# Install deps if needed
if [ ! -f ".venv/.deps_installed" ]; then
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt -q
    touch .venv/.deps_installed
fi

# Check .env
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "⚠️  Created .env from .env.example — edit it with your API keys."
        exit 1
    fi
    echo "⚠️  No .env file found. Create one with your API keys."
    exit 1
fi

echo "✨ Starting WickMind on http://localhost:7751"
echo "   Press Ctrl+C to stop"
echo ""

python app.py
