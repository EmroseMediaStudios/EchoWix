#!/bin/bash

# EchoWix Launch Script
# Creates virtual environment, installs deps, and starts the Flask app

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "🚀 EchoWix Launcher"
echo "================================"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
echo "✓ Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📚 Installing dependencies..."
pip install -q -r requirements.txt

# Check for .env file
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found!"
    echo "📋 Copy .env.example to .env and add your API keys:"
    echo "   cp .env.example .env"
    echo "   nano .env"
    exit 1
fi

# Start the app
echo ""
echo "✨ Starting EchoWix on http://localhost:7751"
echo "🎤 Press Ctrl+C to stop"
echo ""

python app.py
