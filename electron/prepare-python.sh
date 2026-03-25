#!/bin/bash
# Download and prepare standalone Python for bundling with WickMind
# Run this BEFORE building the Electron app
# Creates python-mac/ and python-win/ directories with self-contained Python + deps

set -e

PYTHON_VERSION="3.11.8"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

echo "🐍 Preparing standalone Python for WickMind..."

# ---- MAC (Apple Silicon + Intel universal) ----
setup_mac() {
    echo ""
    echo "🍎 Setting up macOS Python..."
    local dir="$SCRIPT_DIR/python-mac"
    rm -rf "$dir"
    mkdir -p "$dir"

    # Use python-build-standalone — relocatable, no install needed
    local PBS_TAG="20240224"
    local PBS_URL="https://github.com/indygreg/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PYTHON_VERSION}+${PBS_TAG}-aarch64-apple-darwin-install_only.tar.gz"

    echo "   Downloading standalone Python ${PYTHON_VERSION}..."
    curl -L --progress-bar "$PBS_URL" -o /tmp/python-mac.tar.gz

    echo "   Extracting..."
    tar xzf /tmp/python-mac.tar.gz -C "$dir" --strip-components=1
    rm /tmp/python-mac.tar.gz

    echo "   Installing pip dependencies..."
    "$dir/bin/python3" -m pip install --upgrade pip --quiet
    "$dir/bin/python3" -m pip install -r "$APP_DIR/requirements.txt" --quiet

    # Trim unnecessary stuff to save space
    echo "   Trimming..."
    rm -rf "$dir/share" "$dir/include"
    find "$dir" -name "*.pyc" -delete
    find "$dir" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    find "$dir" -name "test" -type d -exec rm -rf {} + 2>/dev/null || true
    find "$dir" -name "tests" -type d -exec rm -rf {} + 2>/dev/null || true

    local size=$(du -sh "$dir" | cut -f1)
    echo "   ✅ macOS Python ready ($size)"
}

# ---- WINDOWS ----
setup_win() {
    echo ""
    echo "🪟 Setting up Windows Python..."
    local dir="$SCRIPT_DIR/python-win"
    rm -rf "$dir"
    mkdir -p "$dir"

    # Python embeddable package for Windows
    local PY_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip"
    local PIP_URL="https://bootstrap.pypa.io/get-pip.py"

    echo "   Downloading Python ${PYTHON_VERSION} embeddable..."
    curl -L --progress-bar "$PY_URL" -o /tmp/python-win.zip

    echo "   Extracting..."
    unzip -q /tmp/python-win.zip -d "$dir"
    rm /tmp/python-win.zip

    # Enable pip in embedded Python (uncomment import site in ._pth file)
    local pth_file=$(ls "$dir"/python*._pth 2>/dev/null | head -1)
    if [ -n "$pth_file" ]; then
        sed -i'' 's/#import site/import site/' "$pth_file"
    fi

    echo "   Installing pip..."
    curl -L --progress-bar "$PIP_URL" -o /tmp/get-pip.py
    # This part needs to run on Windows or with Wine
    echo "   ⚠️  Windows pip install must be done on a Windows machine or with Wine"
    echo "   Run: python-win\\python.exe /tmp/get-pip.py"
    echo "   Then: python-win\\python.exe -m pip install -r requirements.txt"
    rm /tmp/get-pip.py

    local size=$(du -sh "$dir" | cut -f1)
    echo "   ✅ Windows Python downloaded ($size)"
    echo "   ⚠️  Finish setup on Windows: run setup-win-deps.bat"
}

# ---- MAIN ----
case "${1:-all}" in
    mac)   setup_mac ;;
    win)   setup_win ;;
    all)   setup_mac; setup_win ;;
    *)     echo "Usage: $0 [mac|win|all]"; exit 1 ;;
esac

echo ""
echo "🎉 Done! Now run ./build.sh to create the installer."
