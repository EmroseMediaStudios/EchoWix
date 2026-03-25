# WickMind — Desktop App

## What This Does

Packages WickMind as a standalone desktop app with **everything included**:
- Bundled Python 3.11 (no Python install needed)
- All Python dependencies pre-installed
- Steve's personality, family memories, people files
- One-click install → runs immediately

The user only needs: **API keys** (OpenAI + ElevenLabs)

## Build Steps (on your Mac)

```bash
cd electron/

# One command does everything:
./build.sh mac       # → WickMind.dmg
./build.sh win       # → WickMind Setup.exe
./build.sh all       # → both
```

First build takes ~5 minutes (downloads and bundles Python + deps).
Subsequent builds are fast (uses cached Python).

## What the Installer Includes

```
WickMind.app/
├── Electron runtime
├── python/              ← standalone Python 3.11 + all pip packages
│   ├── bin/python3
│   └── lib/python3.11/site-packages/
│       ├── flask, openai, elevenlabs, httpx, ...
├── app/                 ← WickMind source
│   ├── app.py
│   ├── personality.md
│   ├── context.md
│   ├── family.md
│   ├── people/
│   ├── templates/
│   └── static/
└── splash.html, main.js, preload.js
```

## What the User Experiences

### First Launch
1. Double-click **WickMind.app** (or **WickMind.exe**)
2. Splash: "Starting WickMind..."
3. Friendly dialog: "Steve needs API keys to come alive"
   - Opens `.env` file in their text editor
   - Clear instructions for each key
4. They paste in keys, save, relaunch

### Every Launch After That
1. Double-click WickMind
2. Splash: "Waking up Steve..." (2-3 seconds)
3. Steve's ready. Chat or call.

### Zero Technical Knowledge Required
- No Terminal
- No Python install
- No pip install
- No browser
- No port numbers
- Just an app icon and API keys

## Data Location

User data lives in:
- **Mac**: `~/Library/Application Support/WickMind/app-data/`
- **Windows**: `%APPDATA%/WickMind/app-data/`

Contains:
- `.env` — API keys
- `.memories/` — conversation memories
- `.conversations/` — chat history
- `.homework/` — homework tracking
- `.quizzes/` — quiz results
- `family.md` — editable family knowledge
- `people/` — per-person knowledge

## Updating the App

When you build a new version:
- Core files (app.py, templates, personality.md) get updated automatically
- User data (memories, conversations, .env) is **never overwritten**
- Family.md, people/ files persist across updates

## Menu Bar

- **Edit Family Memories** — opens family.md
- **Edit Personality** — opens personality.md
- **Edit API Keys** — opens .env
- **Open Data Folder** — shows everything

## If API Keys Stop Working

Menu → Edit API Keys → replace the expired key → restart the app.

Or user can find the file at:
- Mac: `~/Library/Application Support/WickMind/app-data/.env`
- Win: `%APPDATA%/WickMind/app-data/.env`

## Custom App Icon

Place icon files in `electron/icons/`:
- `icon.icns` for Mac (1024×1024)
- `icon.ico` for Windows (256×256)

Generate from a PNG: `npx electron-icon-builder --input=icon.png --output=icons/`
