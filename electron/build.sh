#!/bin/bash
# Build WickMind Electron app with bundled Python
# Run from the electron/ directory
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🔨 Building WickMind..."
echo ""

# 1. Install Electron dependencies
if [ ! -d "node_modules" ]; then
    echo "📦 Installing Electron build tools..."
    npm install
fi

# 2. Bundle Python
platform="${1:-mac}"
case "$platform" in
    mac)
        if [ ! -d "python-mac/bin" ]; then
            echo "🐍 Bundling Python for macOS..."
            ./prepare-python.sh mac
        else
            echo "🐍 Python already bundled for macOS ✓"
        fi
        echo ""
        echo "🍎 Building macOS .dmg..."
        npm run build-mac
        ;;
    win)
        if [ ! -d "python-win" ]; then
            echo "🐍 Bundling Python for Windows..."
            ./prepare-python.sh win
        else
            echo "🐍 Python already bundled for Windows ✓"
        fi
        echo ""
        echo "🪟 Building Windows installer..."
        npm run build-win
        ;;
    all)
        if [ ! -d "python-mac/bin" ]; then
            echo "🐍 Bundling Python for macOS..."
            ./prepare-python.sh mac
        fi
        if [ ! -d "python-win" ]; then
            echo "🐍 Bundling Python for Windows..."
            ./prepare-python.sh win
        fi
        echo ""
        echo "🏗️ Building for all platforms..."
        npm run build-all
        ;;
    *)
        echo "Usage: $0 [mac|win|all]"
        exit 1
        ;;
esac

echo ""
echo "✅ Build complete!"
echo ""
echo "📁 Output in dist/:"
ls -lh dist/*.dmg dist/*.exe dist/*.AppImage 2>/dev/null || ls -lh dist/
echo ""
echo "📋 What's inside:"
echo "   • WickMind Electron app"
echo "   • Bundled Python 3.11 (no install needed)"
echo "   • All Python dependencies pre-installed"
echo "   • Steve's personality, family memories, people files"
echo "   • Just needs API keys on first launch"
