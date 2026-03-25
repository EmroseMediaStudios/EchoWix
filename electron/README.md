# WickMind — Electron Desktop App

## What This Does

Packages WickMind as a standalone desktop app (.dmg for Mac, .exe for Windows) that:

1. Opens with a splash screen ("Starting Steve...")
2. Automatically starts the Python backend
3. Loads the chat interface in its own window
4. Has a menu bar with quick access to edit family.md, personality.md
5. Hides to system tray on close (Mac), fully quits with Cmd+Q

## Prerequisites

On the BUILD machine:
- Node.js 18+ (`brew install node` or nodejs.org)
- Python 3.10+ (for testing)

On the TARGET machine (whoever installs it):
- Python 3.10+ (python.org — one-time install)
- Internet connection (for API calls)
- API keys (OpenAI + ElevenLabs)

## How to Build

```bash
cd electron/
npm install           # First time only
./build.sh            # Builds for current platform
```

Output goes to `electron/dist/`:
- **Mac**: `WickMind-1.0.0-universal.dmg`
- **Windows**: `WickMind Setup 1.0.0.exe`

## How to Build for Both Platforms

From a Mac:
```bash
npm run build-mac     # Makes .dmg
```

For Windows (can cross-compile from Mac but .exe signing needs Windows):
```bash
npm run build-win     # Makes .exe installer
```

## What Gets Bundled

The app bundles these files from the parent directory:
- `app.py` — the server
- `config.json` — voice settings
- `personality.md` — Steve's personality
- `context.md` — Steve's life memories
- `family.md` — editable family knowledge
- `people/` — per-person knowledge files
- `static/` — images, icons
- `templates/` — HTML templates
- `requirements.txt` — Python dependencies
- `.env.example` → copied to `.env` on first run

NOT bundled (created on the target machine):
- `.memories/` — conversation memories
- `.conversations/` — chat history
- `.homework/` — homework tracking
- `.quizzes/` — quiz results
- `.tts_cache/` — voice cache

## First Run (What the User Sees)

1. Double-click WickMind.app (or WickMind.exe)
2. Splash screen: "Starting Steve..."
3. If no `.env` file: dialog explains what API keys are needed, opens the file
4. If no Python deps: auto-installs them (one-time, ~30 seconds)
5. Server starts, chat loads

## Custom Icons

Place your icon files in `icons/`:
- `icon.icns` — Mac icon (1024x1024, use iconutil or an online converter)
- `icon.ico` — Windows icon (256x256)

## Updating Memories Before Packaging

Before building, make sure the parent directory has:
1. Your latest `family.md` with all family memories
2. Your latest `people/*.md` with per-person knowledge
3. Your latest `context.md` with Steve's life context
4. Latest `personality.md`

These get frozen into the app at build time. The user's NEW memories build on top.

## If API Keys Expire

The `.env` file lives inside the app's resources:
- **Mac**: Right-click WickMind.app → Show Package Contents → Contents/Resources/app/.env
- **Windows**: `C:\Users\{user}\AppData\Local\Programs\wickmind\resources\app\.env`

Or use the menu: WickMind → Open Data Folder → edit `.env`
