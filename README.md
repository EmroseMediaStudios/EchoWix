# 🔮 EchoWix — Voice Chat/Call

A Flask-based web application that enables real-time text chat and voice calls with an AI personality using your cloned voice via ElevenLabs TTS.

## Features

- **Chat Mode**: Text-based conversation with streaming responses
- **Voice Call Mode**: Live voice interaction with push-to-talk interface
- **AI Personality**: Configurable system prompt and behavior
- **Voice Cloning**: Uses your ElevenLabs cloned voice for natural-sounding responses
- **Real-time Streaming**: Both text (SSE) and audio (WebSocket) streaming
- **Dark Theme**: Beautiful dark navy/blue/orange interface with glowing effects
- **Conversation Memory**: Maintains context across chat and voice modes

## Tech Stack

- **Backend**: Python Flask + Flask-SocketIO with eventlet
- **Frontend**: Vanilla JavaScript (no framework)
- **AI**: OpenAI GPT-4o (chat), Whisper (speech-to-text), ElevenLabs (TTS)
- **Real-time**: WebSocket (Socket.IO) for voice streaming
- **Port**: 7751

## Prerequisites

- Python 3.8+
- OpenAI API key (for GPT-4o and Whisper)
- ElevenLabs API key (for voice cloning TTS)
- A cloned voice ID from ElevenLabs

## Setup

### 1. Clone and Navigate

```bash
cd /home/ubuntu/.openclaw/workspace/EchoWix
```

### 2. Configure API Keys

```bash
cp .env.example .env
nano .env
```

Fill in your API keys:
- `OPENAI_API_KEY`: Your OpenAI API key
- `ELEVENLABS_API_KEY`: Your ElevenLabs API key
- `SECRET_KEY`: Change to a secure random string

### 3. Configure Personality

Edit `config.json` to customize:
- `name`: AI personality name
- `voice_id`: Your ElevenLabs EchoWix voice ID (replace `PLACEHOLDER_VOICE_ID`)
- `system_prompt`: Custom personality/behavior instructions
- `tts_settings`: Voice settings (stability, similarity, style)

Example:
```json
{
  "name": "Your Clone",
  "voice_id": "YOUR_VOICE_ID_HERE",
  "system_prompt": "You are a helpful, friendly AI..."
}
```

### 4. Launch the App

```bash
chmod +x run.sh
./run.sh
```

The app will:
1. Create a Python virtual environment (if needed)
2. Install dependencies
3. Start the Flask server on `http://localhost:7751`

### 5. Access the App

Open your browser and navigate to: `http://localhost:7751`

## Usage

### Chat Mode
- Type a message and press Enter or click Send
- AI responds with streaming text
- Conversation history is maintained in the session

### Voice Mode
- Click and hold the microphone button to record
- Release to send your voice message
- AI will transcribe, respond, and speak back using your cloned voice
- See transcription and responses displayed below the mic button

### Mode Toggle
- Use the Chat/Voice toggle at the top to switch modes
- Conversation history is shared between modes

## File Structure

```
EchoWix/
├── app.py                  # Flask backend + WebSocket handlers
├── config.json             # Personality/voice configuration
├── .env.example            # API key template
├── .env                    # Your actual API keys (not in git)
├── requirements.txt        # Python dependencies
├── run.sh                  # Launch script
├── README.md               # This file
├── static/                 # Static assets (img/, css/, etc.)
└── templates/
    └── index.html          # Single-page app (HTML + CSS + JS)
```

## Configuration Details

### config.json

- **name**: Display name for the AI personality
- **voice_id**: Your ElevenLabs EchoWix voice ID
- **system_prompt**: Instructions for AI behavior/tone
- **model**: OpenAI model (default: gpt-4o)
- **max_history**: Number of recent messages to keep for context (default: 20)
- **tts_model**: ElevenLabs TTS model (default: eleven_multilingual_v2)
- **tts_settings**: Voice parameters
  - `stability`: 0-1 (higher = more consistent)
  - `similarity_boost`: 0-1 (higher = closer to original voice)
  - `style`: 0-1 (higher = more stylistic variation)

### Environment Variables (.env)

```
OPENAI_API_KEY=sk-your-key
ELEVENLABS_API_KEY=your-key
SECRET_KEY=your-secret
```

## API Endpoints

### HTTP Routes

- **GET /** - Main app page
- **GET /config** - Public config (name, model)
- **POST /api/chat** - Text chat (streaming SSE response)
- **POST /api/tts** - Text-to-speech (audio/mpeg response)

### WebSocket Events

**Client → Server:**
- `voice_start` - Signal start of recording
- `voice_data` - Send audio blob (base64 encoded)

**Server → Client:**
- `connected` - Connection established with session ID
- `voice_ready` - Server ready for voice data
- `transcription` - Transcribed text from user's audio
- `ai_response_text` - AI text response
- `audio_chunk` - Chunk of AI's spoken response (base64 MP3)
- `audio_end` - Audio playback complete
- `voice_error` - Error during voice processing

## Troubleshooting

### Mic Permission Denied
- Browser is blocking microphone access
- Solution: Check your browser's privacy settings for the localhost address

### API Errors
- Verify API keys are correct in `.env`
- Check OpenAI and ElevenLabs account quotas
- Ensure voice_id matches your ElevenLabs clone

### Audio Not Playing
- Check browser console for errors
- Verify audio context is initialized
- Test with a different browser

### WebSocket Connection Issues
- Firewall may be blocking WebSocket connections
- Try port 7751 in firewall rules
- Check Flask-SocketIO is running (eventlet mode)

## Development

### Running in Debug Mode
Edit `run.sh` or run directly:
```bash
source venv/bin/activate
python app.py  # Runs with debug=True
```

### Modifying the UI
Edit `templates/index.html` for layout/styling changes.

### Changing AI Behavior
Edit `config.json` to adjust the system prompt and voice settings.

## Production Notes

- Change `SECRET_KEY` in `.env` to a secure random value
- Set `debug=False` in `app.py` before deploying
- Use a production ASGI server (Gunicorn + eventlet instead of Flask dev server)
- Consider using a reverse proxy (nginx) in front of Flask
- Store `.env` securely outside the repository

## API Rate Limits

- OpenAI: Standard tier limits apply
- ElevenLabs: Check your subscription for monthly character limits
- Socket.IO: No built-in rate limiting; consider adding if needed

## License

Use as you like. Modify the system prompt and voice settings to make it your own!

---

**Need help?** Check the console (F12) for errors. The backend logs will show what's happening server-side.
