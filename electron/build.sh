#!/bin/bash
# Build WickMind Electron app
# Run from the electron/ directory

set -e

echo "🔨 Building WickMind..."

# Install electron dependencies
if [ ! -d "node_modules" ]; then
    echo "📦 Installing Electron dependencies..."
    npm install
fi

# Create icons directory if needed
mkdir -p icons

# Check for icon files
if [ ! -f "icons/icon.icns" ] && [ ! -f "icons/icon.ico" ]; then
    echo "⚠️  No icon files found in icons/"
    echo "   Place icon.icns (Mac) and/or icon.ico (Windows) in the icons/ folder"
    echo "   Building without custom icons..."
fi

# Determine platform
case "$(uname -s)" in
    Darwin*)
        echo "🍎 Building for macOS..."
        npm run build-mac
        ;;
    Linux*)
        echo "🐧 Building for both platforms..."
        npm run build-all
        ;;
    MINGW*|CYGWIN*|MSYS*)
        echo "🪟 Building for Windows..."
        npm run build-win
        ;;
esac

echo ""
echo "✅ Build complete! Check the dist/ folder."
echo ""
echo "📁 Output:"
ls -la dist/ 2>/dev/null || echo "   (check dist/ folder)"
