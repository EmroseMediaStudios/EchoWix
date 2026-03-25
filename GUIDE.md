# WickMind — Complete Guide

_Steve, your AI dad/husband/friend, as a desktop app._

## What Is WickMind?

WickMind is an AI that talks, thinks, and remembers like Steve. It's a voice clone + personality clone that can:
- **Chat** via text or voice calls
- **Remember** past conversations per person
- **Help with homework** step-by-step (like sitting at the kitchen table)
- **Quiz** kids on any subject
- **Show real family photos** when reminiscing
- **Generate images** to explain concepts visually
- **Play ambient sounds** (rain, ocean, fireplace)
- **Look things up** online when asked
- **Know important family info** (passwords, insurance, contacts)

---

## Files You Can Edit

Everything Steve knows comes from files you can edit with any text editor. Changes take effect immediately — no restart needed.

### 📝 personality.md — Who Steve Is
Steve's personality, humor style, how he talks, how he teaches, how he loves. 
**Edit when:** You want to change how Steve acts, talks, or responds.

### 👨‍👩‍👧‍👦 family.md — Family Knowledge
What Steve knows about the family — members, important dates, family stories, inside jokes, favorites.
**Edit when:** You want Steve to know about a new family event, update birthdays, add inside jokes.

### 🔑 important.md — Critical Information
Passwords, insurance policies, contacts, where to find important documents, how-to instructions for important tasks. Steve answers questions like "what's the WiFi password?" or "who's our life insurance company?" from this file.
**Edit when:** Passwords change, you get new insurance, new contacts, etc.

### 📖 context.md — Steve's Life Story
Steve's background, life experiences, career history, the stuff that makes him *him*. This is his autobiography that he draws from naturally in conversation.
**Edit when:** You want Steve to know about new life experiences or correct something.

### 👤 people/ — Per-Person Knowledge
One file per person Steve talks to (e.g., `people/emma.md`, `people/kim.md`). Contains what Steve knows specifically about that person — their interests, what they're working on, how to talk to them.
**Edit when:** You want Steve to know something specific about a person.

### 📸 memories/ — Real Family Photos
Photos Steve can pull up during conversations. Put photos in `memories/photos/` and describe them in `memories/memories.json`.

**How to add a photo:**
1. Put the photo file in `memories/photos/` (e.g., `wedding.jpg`)
2. Open `memories/memories.json` and add an entry:
```json
{
  "tags": ["wedding", "marriage", "ceremony"],
  "description": "Steve and Kim at the altar",
  "file": "wedding.jpg",
  "date": "2008-06-15",
  "people": ["Steve", "Kim"],
  "story": "Best day of my life. Kim looked absolutely stunning."
}
```
3. Steve will show this photo when someone mentions weddings, marriage, etc.

### 🔐 .env — API Keys
The keys that make Steve work. Only edit if keys expire.
- `OPENAI_API_KEY` — Steve's brain (from platform.openai.com)
- `ELEVENLABS_API_KEY` — Steve's voice (from elevenlabs.io)
- `BRAVE_API_KEY` — Steve's ability to search the web (optional, from brave.com/search/api)

---

## Features

### 💬 Text Chat
Type messages to Steve. He remembers the conversation and builds memories over time.

### 📞 Voice Calls
Click the phone icon to start a voice call. Talk naturally — Steve listens, thinks, and responds with his actual voice. 2.5 second pause detection means he waits for you to finish your thought.

### 📚 Homework Help
Steve teaches step-by-step. He asks ONE question at a time, waits for an answer, then guides to the next step. Never gives away the answer — helps kids figure it out themselves. Works for math, science, history, anything.

### 🎯 Quiz Mode
"Quiz me on state capitals" — Steve becomes an encouraging quiz master. Tracks score, adjusts difficulty, celebrates wins.

### 📸 Memory Photos
"Show me a picture from our wedding" — Steve pulls up real family photos and tells the story behind them. Way better than AI-generated images for personal moments.

### 🖼️ Image Generation
"What does a solar eclipse look like?" — Steve generates an educational image via DALL-E. Used for explanatory visuals, not personal memories.

### 🎵 Ambient Sounds
"Play some rain sounds" — 7 ambient loops: rain, ocean, forest, fireplace, thunder, wind, night. Great for bedtime stories or studying.

### 🔍 Web Search
"What's the weather?" or "Who won the game last night?" — Steve looks it up and explains naturally, like he just checked his phone.

### 📍 Location Aware
Steve knows your city (via browser location) and uses it naturally — weather for your area, local recommendations.

### 🔑 Important Info
"What's the WiFi password?" or "Who's our insurance company?" — Steve knows from `important.md`.

---

## Electron Desktop App

### Building the Installer

On a Mac with Node.js installed:

```bash
cd electron/

# Create bundled.env with API keys (one time, stays local):
cat > bundled.env << 'EOF'
OPENAI_API_KEY=your-key-here
ELEVENLABS_API_KEY=your-key-here
BRAVE_API_KEY=
SECRET_KEY=wickmind-prod-7751
EOF

# Build:
./build.sh mac       # → WickMind.dmg
./build.sh win       # → WickMind Setup.exe
./build.sh all       # → both
```

### What Gets Bundled
- ✅ Python 3.11 (no install needed)
- ✅ All Python dependencies
- ✅ API keys (from bundled.env)
- ✅ Steve's personality, family.md, important.md, context.md
- ✅ Memory photos
- ✅ Per-person knowledge files
- ✅ All icons and images
- ✅ Everything needed to run — zero setup for the end user

### What the User Experiences
1. Double-click WickMind app
2. Steve is ready in ~3 seconds
3. That's it. No setup, no passwords, no configuration.

### App Menu
- **Edit Family Memories** — opens family.md
- **Edit Memory Photos** — opens memories folder
- **Edit Important Info** — opens important.md
- **Edit Personality** — opens personality.md
- **Edit API Keys** — opens .env (only if keys expire)
- **Open Data Folder** — shows all files

### Data Location
- **Mac**: `~/Library/Application Support/WickMind/app-data/`
- **Windows**: `%APPDATA%/WickMind/app-data/`

### USB Installer
```
USB Drive/
├── WickMind-1.0.0.dmg          ← Mac
├── WickMind Setup 1.0.0.exe    ← Windows
└── README.txt                   ← "Double-click the one for your computer"
```

---

## Architecture

```
voice-clone-app/
├── app.py              ← Main Flask server
├── config.json         ← Voice settings, model config
├── personality.md      ← Steve's personality
├── context.md          ← Steve's life story
├── family.md           ← Shared family knowledge
├── important.md        ← Passwords, insurance, contacts
├── people/             ← Per-person knowledge files
│   ├── emma.md
│   ├── kim.md
│   └── drew.md
├── memories/           ← Real family photos
│   ├── README.md
│   ├── memories.json   ← Photo index with tags/stories
│   └── photos/         ← Actual photo files
├── static/img/         ← App icons and avatars
├── templates/          ← HTML (index.html, login.html)
├── electron/           ← Desktop app packaging
│   ├── main.js         ← Electron main process
│   ├── package.json    ← Build config
│   ├── build.sh        ← One-command build
│   ├── prepare-python.sh ← Bundles Python
│   └── bundled.env     ← API keys (local, not in git)
├── .memories/          ← Auto-generated conversation memories
├── .conversations/     ← Chat history
├── .homework/          ← Homework tracking
├── .quizzes/           ← Quiz results
└── .tts_cache/         ← Voice audio cache
```

---

## Making Changes

**Any changes to the git repo get picked up when you build.** The workflow:

1. Edit files (personality, family.md, important.md, add photos, etc.)
2. Test by running `./run.sh` locally
3. When ready for USB: `git pull` → `cd electron && ./build.sh mac`
4. The installer snapshots everything at that moment

**For changes while the app is running:** Most files reload automatically per-request (family.md, important.md, memories). Personality and context reload on server restart.
