#!/usr/bin/env python3
"""
EchoWix — AI Voice Clone Chat & Call
Flask + flask-socketio backend for text chat and live phone-call-style voice
Uses OpenAI GPT-4o, Whisper, and ElevenLabs TTS
"""

import gevent.monkey
gevent.monkey.patch_all()
import gevent

import json
import os
import re
import base64
import hashlib
import tempfile
import time
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, render_template, request, session, jsonify, Response, redirect, url_for
from flask_socketio import SocketIO, emit
import openai
import httpx

load_dotenv()

BRAVE_API_KEY = os.getenv('BRAVE_API_KEY', '')

# ---- IMAGE GENERATION ----

def generate_explanation_image(prompt):
    """Generate an image via DALL-E 3 to help explain a concept visually."""
    try:
        resp = openai.images.generate(
            model="dall-e-3",
            prompt=f"{prompt} Simple, clear, educational illustration. No text, no words, no letters, no writing of any kind.",
            n=1,
            size="1024x1024",
            quality="standard",
        )
        return resp.data[0].url
    except Exception as e:
        print(f"Image generation error: {e}")
        return None


# ---- MEMORY PHOTOS ----

MEMORIES_DIR = os.path.join(os.path.dirname(__file__), 'memories')
MEMORIES_PHOTOS_DIR = os.path.join(MEMORIES_DIR, 'photos')
MEMORIES_JSON = os.path.join(MEMORIES_DIR, 'memories.json')

def _load_memories_photos():
    """Load the memories.json photo index."""
    if os.path.exists(MEMORIES_JSON):
        try:
            with open(MEMORIES_JSON, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []

def search_memory_photos(query, top_n=3):
    """Search memory photos by tag matching against a query string."""
    memories = _load_memories_photos()
    if not memories:
        return []
    
    query_words = set(query.lower().split())
    scored = []
    for mem in memories:
        # Check if the photo file actually exists
        photo_path = os.path.join(MEMORIES_PHOTOS_DIR, mem.get('file', ''))
        if not os.path.exists(photo_path):
            continue
        
        tags = set(t.lower() for t in mem.get('tags', []))
        people = set(p.lower() for p in mem.get('people', []))
        all_keywords = tags | people
        
        # Score by overlap
        overlap = len(query_words & all_keywords)
        # Partial matching — check if any query word is a substring of any tag
        if overlap == 0:
            for qw in query_words:
                for kw in all_keywords:
                    if qw in kw or kw in qw:
                        overlap += 0.5
        
        if overlap > 0:
            scored.append((overlap, mem))
    
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:top_n]]

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.permanent_session_lifetime = int(os.getenv('SESSION_TIMEOUT_MINUTES', 120)) * 60  # default 2 hours
socketio = SocketIO(app, async_mode='gevent', cors_allowed_origins="*")

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
openai.api_key = OPENAI_API_KEY


# ---- CONFIG ----

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "name": "EchoWix",
            "avatar_name": "Steve",
            "voice_id": "PLACEHOLDER_VOICE_ID",
            "model": "gpt-4o",
            "max_history": 20,
            "tts_model": "eleven_multilingual_v2",
            "tts_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.3}
        }

CONFIG = load_config()


def _load_system_prompt():
    prompt_file = CONFIG.get("system_prompt_file")
    if prompt_file:
        prompt_path = os.path.join(os.path.dirname(__file__), prompt_file)
        try:
            with open(prompt_path, 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            pass
    return CONFIG.get("system_prompt", "You are a conversational AI. Be natural and concise.")

SYSTEM_PROMPT = _load_system_prompt()


# ---- CONTEXT / MEMORIES ----
# Load optional context file with stories, events, reference material.
# This gets injected alongside the system prompt to give Steve depth.

def _load_context():
    context_file = CONFIG.get("context_file", "context.md")
    context_path = os.path.join(os.path.dirname(__file__), context_file)
    if os.path.exists(context_path):
        try:
            with open(context_path, 'r') as f:
                content = f.read().strip()
                if content:
                    return content
        except IOError:
            pass
    return None

def _load_person_context(username):
    """Load per-person knowledge file if it exists."""
    person_path = os.path.join(os.path.dirname(__file__), 'people', f'{username}.md')
    if os.path.exists(person_path):
        try:
            with open(person_path, 'r') as f:
                content = f.read().strip()
                if content:
                    return content
        except IOError:
            pass
    return None

def _parse_person_phrases(username, section_name):
    """Parse a bullet list from a specific section in a person's .md file."""
    person_path = os.path.join(os.path.dirname(__file__), 'people', f'{username}.md')
    if not os.path.exists(person_path):
        return []
    try:
        with open(person_path, 'r') as f:
            lines = f.readlines()
    except IOError:
        return []
    
    phrases = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('## ') and section_name.lower() in stripped.lower():
            in_section = True
            continue
        if in_section:
            if stripped.startswith('## '):
                break  # Next section
            if stripped.startswith('<!--'):
                continue
            if stripped.startswith('- ') and len(stripped) > 2:
                phrase = stripped[2:].strip()
                if phrase and not phrase.startswith('['):
                    phrases.append(phrase)
    return phrases

CONTEXT = _load_context()


# ---- MEMORY SYSTEM (per-user long-term recall) ----
# After each exchange, GPT extracts key memories from the conversation.
# Before each response, relevant memories are searched and injected.
# This gives Steve persistent recall across sessions.

MEMORY_DIR = os.path.join(os.path.dirname(__file__), '.memories')
os.makedirs(MEMORY_DIR, exist_ok=True)

def _memory_path(username):
    return os.path.join(MEMORY_DIR, f"{username}.json")

def load_memories(username):
    path = _memory_path(username)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []

def save_memories(username, memories):
    path = _memory_path(username)
    with open(path, 'w') as f:
        json.dump(memories, f, indent=2)

def search_memories(username, query, max_results=8):
    """Simple keyword search through memories. Returns most relevant entries."""
    memories = load_memories(username)
    if not memories:
        return []
    
    query_words = set(query.lower().split())
    scored = []
    for mem in memories:
        mem_text = mem.get('content', '').lower()
        # Score by keyword overlap + recency bonus
        matches = sum(1 for w in query_words if w in mem_text and len(w) > 2)
        if matches > 0:
            scored.append((matches, mem))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:max_results]]

def extract_memories_async(username, user_text, ai_text):
    """Background: ask GPT to extract memorable facts from this exchange."""
    try:
        resp = openai.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {"role": "system", "content": """Extract key facts, preferences, emotions, or events worth remembering from this conversation exchange. Return a JSON array of short memory strings. Only include things worth recalling in future conversations — skip generic pleasantries.

Examples of good memories:
- "Mentioned they had a rough day at work on March 24"
- "Said they're thinking about getting a dog"  
- "Was feeling lonely and missing family"
- "Excited about a new project they're starting"
- "Prefers being called 'babe' sometimes"

If nothing worth remembering, return an empty array: []
Return ONLY the JSON array, no other text."""},
                {"role": "user", "content": f"User said: {user_text}\n\nSteve replied: {ai_text}"}
            ],
            temperature=0.3,
            max_tokens=200,
        )
        raw = resp.choices[0].message.content.strip()
        # Parse JSON array from response
        if raw.startswith('['):
            new_memories = json.loads(raw)
        else:
            # Try to find array in response
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if match:
                new_memories = json.loads(match.group())
            else:
                return
        
        if not new_memories:
            return
        
        existing = load_memories(username)
        timestamp = time.strftime('%Y-%m-%d %H:%M')
        for mem_text in new_memories:
            if isinstance(mem_text, str) and mem_text.strip():
                existing.append({
                    'content': mem_text.strip(),
                    'timestamp': timestamp,
                })
        
        # Keep last 200 memories max
        if len(existing) > 200:
            existing = existing[-200:]
        
        save_memories(username, existing)
        
        # Also append to person file if it exists
        person_path = os.path.join(os.path.dirname(__file__), 'people', f'{username}.md')
        if os.path.exists(person_path):
            try:
                with open(person_path, 'a') as f:
                    for mem_text in new_memories:
                        if isinstance(mem_text, str) and mem_text.strip():
                            f.write(f"\n- [{timestamp}] {mem_text.strip()}")
            except IOError:
                pass
    except Exception as e:
        print(f"Memory extraction error: {e}")


# ---- SHARED FAMILY MEMORIES ----

FAMILY_MEMORY_FILE = os.path.join(os.path.dirname(__file__), '.memories', '_family.json')
FAMILY_CONTEXT_FILE = os.path.join(os.path.dirname(__file__), 'family.md')

def _load_family_context():
    """Load the editable family.md file — Steve's family knowledge base."""
    if os.path.exists(FAMILY_CONTEXT_FILE):
        try:
            with open(FAMILY_CONTEXT_FILE, 'r') as f:
                return f.read().strip()
        except IOError:
            return ""
    return ""

FAMILY_CONTEXT = _load_family_context()

# ---- IMPORTANT THINGS (passwords, insurance, contacts, how-tos) ----

IMPORTANT_FILE = os.path.join(os.path.dirname(__file__), 'important.md')

def _load_important_context():
    """Load important.md — passwords, insurance, contacts, where to find things."""
    if os.path.exists(IMPORTANT_FILE):
        try:
            with open(IMPORTANT_FILE, 'r') as f:
                content = f.read().strip()
                # Skip if it's just the empty template
                if content and 'YOUR_KEY_HERE' not in content:
                    return content
        except IOError:
            pass
    return ""

def load_family_memories():
    if os.path.exists(FAMILY_MEMORY_FILE):
        try:
            with open(FAMILY_MEMORY_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []

def save_family_memories(memories):
    with open(FAMILY_MEMORY_FILE, 'w') as f:
        json.dump(memories, f, indent=2)

def search_family_memories(query, max_results=5):
    """Search shared family memories."""
    memories = load_family_memories()
    if not memories:
        return []
    query_words = set(query.lower().split())
    scored = []
    for mem in memories:
        mem_text = mem.get('content', '').lower()
        matches = sum(1 for w in query_words if w in mem_text and len(w) > 2)
        if matches > 0:
            scored.append((matches, mem))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:max_results]]

def extract_family_memories_async(username, user_text, ai_text):
    """Extract family-relevant memories (events, plans, schedules, shared news)."""
    try:
        resp = openai.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {"role": "system", "content": """Extract ONLY family-relevant facts from this conversation — things that other family members would benefit from knowing. Return a JSON array of short memory strings.

Good family memories:
- "Family vacation to Florida planned for spring break"
- "Emma has a math test on Thursday"
- "Kim's birthday is coming up — she mentioned wanting a spa day"
- "Drew is visiting this weekend"
- "Family movie night planned for Saturday"
- "Emma learned to ride a bike today"

NOT family memories (keep these private/per-user):
- Personal feelings, venting, relationship concerns
- Private conversations about another family member
- Work stress, personal struggles
- Anything that feels like it was shared in confidence

If nothing is family-relevant, return an empty array: []
Return ONLY the JSON array."""},
                {"role": "user", "content": f"User ({username}) said: {user_text}\n\nSteve replied: {ai_text}"}
            ],
            temperature=0.3,
            max_tokens=200,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith('['):
            new_memories = json.loads(raw)
        else:
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if match:
                new_memories = json.loads(match.group())
            else:
                return
        if not new_memories:
            return
        existing = load_family_memories()
        timestamp = time.strftime('%Y-%m-%d %H:%M')
        for mem_text in new_memories:
            if isinstance(mem_text, str) and mem_text.strip():
                existing.append({
                    'content': mem_text.strip(),
                    'timestamp': timestamp,
                    'from_user': username,
                })
        if len(existing) > 300:
            existing = existing[-300:]
        save_family_memories(existing)
    except Exception as e:
        print(f"Family memory extraction error: {e}")


# ---- HOMEWORK HISTORY ----

HOMEWORK_DIR = os.path.join(os.path.dirname(__file__), '.homework')
os.makedirs(HOMEWORK_DIR, exist_ok=True)

def _homework_path(username):
    return os.path.join(HOMEWORK_DIR, f"{username}.json")

def load_homework_history(username, max_entries=20):
    path = _homework_path(username)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                entries = json.load(f)
                return entries[-max_entries:]
        except (json.JSONDecodeError, IOError):
            return []
    return []

def save_homework_entry(username, entry):
    path = _homework_path(username)
    entries = []
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                entries = json.load(f)
        except (json.JSONDecodeError, IOError):
            entries = []
    entries.append(entry)
    if len(entries) > 100:
        entries = entries[-100:]
    with open(path, 'w') as f:
        json.dump(entries, f, indent=2)

def extract_homework_async(username, user_text, ai_text):
    """Detect if this was a homework/learning interaction and log it."""
    try:
        resp = openai.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {"role": "system", "content": """Was this conversation about homework, studying, learning, or educational help? If yes, extract the details. Return a JSON object:

{"is_homework": true, "subject": "math", "topic": "fractions - adding with different denominators", "difficulty": "medium", "outcome": "understood after explanation"}

If it was NOT homework/educational, return: {"is_homework": false}
Return ONLY the JSON object."""},
                {"role": "user", "content": f"User said: {user_text}\n\nSteve replied: {ai_text}"}
            ],
            temperature=0.2,
            max_tokens=150,
        )
        raw = resp.choices[0].message.content.strip()
        if '{' in raw:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                if data.get('is_homework'):
                    data['timestamp'] = time.strftime('%Y-%m-%d %H:%M')
                    data['user'] = username
                    save_homework_entry(username, data)
    except Exception as e:
        print(f"Homework extraction error: {e}")


# ---- QUIZ STATE ----

QUIZ_DIR = os.path.join(os.path.dirname(__file__), '.quizzes')
os.makedirs(QUIZ_DIR, exist_ok=True)

def _quiz_path(username):
    return os.path.join(QUIZ_DIR, f"{username}.json")

def load_quiz_state(username):
    path = _quiz_path(username)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_quiz_state(username, state):
    path = _quiz_path(username)
    with open(path, 'w') as f:
        json.dump(state, f, indent=2)

def get_quiz_context(username):
    """Build context about quiz history for injection into system prompt."""
    state = load_quiz_state(username)
    if not state:
        return ""
    history = state.get('history', [])
    if not history:
        return ""
    recent = history[-10:]
    lines = []
    for h in recent:
        lines.append(f"- {h.get('subject', 'unknown')}: {h.get('correct', 0)}/{h.get('total', 0)} correct ({h.get('date', '')})")
    return "Recent quiz history for this person:\n" + "\n".join(lines)

def extract_quiz_results_async(username, user_text, ai_text):
    """Detect if a quiz just happened and track results."""
    try:
        resp = openai.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {"role": "system", "content": """Was this a quiz or test exchange? If Steve asked a question and the user answered, extract:
{"is_quiz": true, "subject": "spelling", "question": "How do you spell 'necessary'?", "user_answer": "neccesary", "correct": false, "correct_answer": "necessary"}

If no quiz happened, return: {"is_quiz": false}
Return ONLY the JSON object."""},
                {"role": "user", "content": f"User said: {user_text}\n\nSteve replied: {ai_text}"}
            ],
            temperature=0.2,
            max_tokens=150,
        )
        raw = resp.choices[0].message.content.strip()
        if '{' in raw:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                if data.get('is_quiz'):
                    state = load_quiz_state(username)
                    # Update current session
                    session_quiz = state.get('current', {})
                    session_quiz['total'] = session_quiz.get('total', 0) + 1
                    if data.get('correct'):
                        session_quiz['correct'] = session_quiz.get('correct', 0) + 1
                    session_quiz['subject'] = data.get('subject', session_quiz.get('subject', 'general'))
                    state['current'] = session_quiz
                    # Questions log
                    questions = state.get('questions', [])
                    questions.append({
                        'question': data.get('question', ''),
                        'user_answer': data.get('user_answer', ''),
                        'correct': data.get('correct', False),
                        'correct_answer': data.get('correct_answer', ''),
                        'timestamp': time.strftime('%Y-%m-%d %H:%M'),
                    })
                    if len(questions) > 200:
                        questions = questions[-200:]
                    state['questions'] = questions
                    save_quiz_state(username, state)
    except Exception as e:
        print(f"Quiz extraction error: {e}")


# ---- LOCATION ----

USER_LOCATIONS = {}  # In-memory: {username: {"lat": x, "lon": y, "city": "", "updated": timestamp}}


# ---- WEB SEARCH ----

def web_search(query, max_results=5):
    """Search the web via Brave Search API. Returns list of {title, url, snippet}."""
    if not BRAVE_API_KEY:
        return []
    try:
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": BRAVE_API_KEY},
            params={"q": query, "count": max_results},
            timeout=8,
        )
        if resp.status_code != 200:
            return []
        results = []
        for r in resp.json().get("web", {}).get("results", [])[:max_results]:
            results.append({"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")})
        return results
    except Exception as e:
        print(f"Web search error: {e}")
        return []


def should_search(user_text):
    """Quick heuristic: does this message look like it needs a web search?"""
    text = user_text.lower().strip()
    search_signals = [
        "look up", "look it up", "google", "search", "find out",
        "what is", "what are", "what was", "what were", "what does",
        "who is", "who was", "who are",
        "when is", "when was", "when did", "when does",
        "where is", "where was", "where are",
        "how many", "how much", "how far", "how long", "how old",
        "how do you", "how does", "how do i", "how to",
        "is it true", "can you check", "fact check",
        "what happened", "latest", "current", "recent", "today",
        "score", "weather", "price", "cost",
        "define", "meaning of", "definition",
        "explain", "tell me about", "what's the deal with",
    ]
    for signal in search_signals:
        if signal in text:
            return True
    if "?" in text and len(text.split()) >= 4:
        personal = ["how are you", "do you love", "are you", "can you talk", "you okay",
                    "miss you", "love you", "feel", "think about me", "what should i"]
        if not any(p in text for p in personal):
            return True
    return False


def _strip_latex(text):
    """Strip LaTeX math notation from LLM output — Steve talks like a human, not a textbook."""
    # Remove \( ... \) inline math delimiters
    text = re.sub(r'\\\((.+?)\\\)', r'\1', text)
    # Remove \[ ... \] display math delimiters
    text = re.sub(r'\\\[(.+?)\\\]', r'\1', text)
    # Remove $$ ... $$ display math
    text = re.sub(r'\$\$(.+?)\$\$', r'\1', text)
    # Remove $ ... $ inline math
    text = re.sub(r'\$(.+?)\$', r'\1', text)
    # Replace LaTeX commands with plain text
    text = re.sub(r'\\div\b', '÷', text)
    text = re.sub(r'\\times\b', '×', text)
    text = re.sub(r'\\cdot\b', '·', text)
    text = re.sub(r'\\pm\b', '±', text)
    text = re.sub(r'\\approx\b', '≈', text)
    text = re.sub(r'\\neq\b', '≠', text)
    text = re.sub(r'\\leq\b', '≤', text)
    text = re.sub(r'\\geq\b', '≥', text)
    text = re.sub(r'\\frac\{(.+?)\}\{(.+?)\}', r'\1/\2', text)
    text = re.sub(r'\\sqrt\{(.+?)\}', r'√\1', text)
    text = re.sub(r'\\text\{(.+?)\}', r'\1', text)
    # Clean up any remaining backslash commands
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)
    return text


def estimate_max_tokens(user_text):
    """Adaptive max_tokens based on what's being asked.
    Uses loose keyword matching + contextual patterns rather than exact phrases."""
    text = user_text.lower().strip()
    words = set(text.split())

    # ---- LONG-FORM (2500 tokens) ----
    # Stories / creative
    story_words = {"story", "stories", "bedtime", "fairytale", "fairy", "tale",
                   "adventure", "fable", "legend", "myth", "narrative"}
    if story_words & words:
        return 3000
    story_phrases = ["once upon", "make up", "make something up", "tell me one",
                     "tell me another", "one more", "keep going", "what happens next",
                     "tell it again"]
    if any(p in text for p in story_phrases):
        return 3000

    # Memory recall / nostalgia
    memory_words = {"remember", "reminds", "reminded", "nostalgia", "nostalgic",
                    "recall", "recalled", "forgot", "forgotten"}
    memory_triggers = ["that time", "back when", "used to", "years ago",
                       "when we", "when i was", "when you", "the trip",
                       "that day", "that night", "that one time"]
    if memory_words & words and any(t in text for t in memory_triggers):
        return 2500
    if any(p in text for p in ["do you remember", "remember when", "remember that",
                                "tell me about the time", "what about when",
                                "you ever think about"]):
        return 2500

    # Teaching / homework / deep explanation
    # Keep these SHORT — Steve teaches one step at a time, asks a question, waits
    teach_words = {"worksheet", "homework", "assignment", "problem", "equation",
                   "quiz", "test", "exam", "lesson", "tutorial"}
    if teach_words & words:
        return 800
    teach_phrases = ["walk me through", "break it down", "break down",
                     "teach me", "help me understand", "help me with",
                     "explain it like", "dumb it down", "in simple terms",
                     "tell me everything", "give me the full", "from the beginning"]
    if any(p in text for p in teach_phrases):
        return 1000

    # Short answers during teaching flow (answering Steve's questions)
    # These should be short because Steve's follow-up should be one step + one question
    short_answer_words = {"yes", "no", "right", "wrong", "correct", "idk",
                          "i don't know", "maybe", "i think", "um", "uh"}
    if len(text.split()) <= 5 and (words & short_answer_words or text.replace(' ','').isdigit()):
        return 800

    # Writing / creating content
    write_words = {"write", "draft", "compose", "create", "summarize", "summary",
                   "overview", "recap", "outline"}
    if write_words & words and len(text.split()) >= 4:
        return 2500

    # ---- MEDIUM-FORM (1500 tokens) ----
    explain_phrases = ["explain", "how does", "how do", "why does", "why do",
                       "what happens when", "difference between", "compare",
                       "what do you think about", "what's your take",
                       "pros and cons", "is it worth", "should i"]
    if any(p in text for p in explain_phrases):
        return 1500

    # Longer questions (8+ words with a question mark) likely need more room
    if "?" in text and len(text.split()) >= 8:
        return 1500

    # ---- DEFAULT CONVERSATIONAL (1000 tokens) ----
    # Short affirmatives after a story/explanation likely mean "continue"
    continue_words = {"yes", "yeah", "yep", "yea", "sure", "go", "continue",
                      "more", "please", "mhm", "mmhm", "ok", "okay", "alright"}
    if words & continue_words and len(text.split()) <= 4:
        return 2500
    return 1000


def build_messages(sid):
    """Build the full message list with system prompt + context + person + memories + history."""
    # Inject current date so Steve knows what year/day it is
    date_str = time.strftime('%A, %B %d, %Y')
    time_str = time.strftime('%I:%M %p')
    msgs = [{"role": "system", "content": SYSTEM_PROMPT + f"\n\nCurrent date and time: {date_str}, {time_str}."}]
    
    # Layer 1: Core identity (always loaded)
    if CONTEXT:
        msgs.append({"role": "system", "content": f"This is who you are — your life, your family, your experiences. This IS your memory. Draw from it naturally:\n\n{CONTEXT}"})
    
    # Layer 2: Per-person knowledge
    username = session.get('username', 'anonymous')
    person_ctx = _load_person_context(username)
    if person_ctx:
        msgs.append({"role": "system", "content": f"What you know about the person you're talking to right now. Use this naturally — reference things you know about them, but don't be creepy about it:\n\n{person_ctx}"})
    
    # Layer 3: Dynamic memories from past conversations
    history = get_history(sid)
    last_user_msg = ""
    for m in reversed(history):
        if m['role'] == 'user':
            last_user_msg = m['content']
            break
    
    if last_user_msg:
        relevant = search_memories(username, last_user_msg)
        if relevant:
            mem_text = "\n".join(f"- {m['content']} ({m.get('timestamp', '')})" for m in relevant)
            msgs.append({"role": "system", "content": f"Things you remember from past conversations with this person (use naturally, don't list them off):\n{mem_text}"})
        
        # Layer 4: Shared family memories (editable file + auto-extracted)
        family_ctx = _load_family_context()  # Reload each time in case it was edited
        family_mems = search_family_memories(last_user_msg)
        family_parts = []
        if family_ctx:
            family_parts.append(f"Your family knowledge (things you just know as a dad/husband):\n{family_ctx}")
        if family_mems:
            fam_text = "\n".join(f"- {m['content']} (from {m.get('from_user', 'family')}, {m.get('timestamp', '')})" for m in family_mems)
            family_parts.append(f"Things you've learned from recent family conversations:\n{fam_text}")
        if family_parts:
            msgs.append({"role": "system", "content": "\n\n".join(family_parts)})
    
    # Layer 5: Important things (passwords, insurance, contacts)
    important_ctx = _load_important_context()
    if important_ctx:
        msgs.append({"role": "system", "content": f"IMPORTANT — You know all of this. When someone asks about passwords, insurance, contacts, where to find things, how to do important tasks — answer from this knowledge. Be direct and helpful, like a husband/dad who just knows this stuff:\n\n{important_ctx}"})
    
    # Layer 6: Homework history
    hw_history = load_homework_history(username, max_entries=5)
    if hw_history:
        hw_text = "\n".join(f"- {h.get('subject', '?')}: {h.get('topic', '?')} ({h.get('outcome', '?')}, {h.get('timestamp', '')})" for h in hw_history[-5:])
        msgs.append({"role": "system", "content": f"Recent homework/learning sessions with this person:\n{hw_text}\nUse this to track patterns — if they've been struggling with something, offer extra help. If they mastered it, acknowledge growth."})
    
    # Layer 6: Quiz context
    quiz_ctx = get_quiz_context(username)
    if quiz_ctx:
        msgs.append({"role": "system", "content": f"{quiz_ctx}\nReference past quiz performance naturally when quizzing — celebrate improvement, encourage on weak areas."})
    
    # Layer 7: Location awareness
    loc = USER_LOCATIONS.get(username)
    if loc and loc.get('city'):
        msgs.append({"role": "system", "content": f"This person is currently in {loc['city']}. Use this naturally when relevant (weather, local recommendations, time-aware responses). Don't mention their location unprompted."})
    
    # Layer 8: Memory photos
    # Search for relevant photos based on recent conversation
    if last_user_msg:
        matching_photos = search_memory_photos(last_user_msg)
        if matching_photos:
            photo_text = "\n".join(
                f"- [{m['file']}] {m.get('description', '')} ({', '.join(m.get('people', []))})"
                f"{' — ' + m.get('date', '') if m.get('date') else ''}"
                f"{' — ' + m.get('story', '') if m.get('story') else ''}"
                for m in matching_photos
            )
            msgs.append({"role": "system", "content": 
                f"You have REAL FAMILY PHOTOS you can show. These matched the conversation:\n{photo_text}\n\n"
                "To show a photo, include [SHOW_MEMORY: filename.jpg] in your response. "
                "When showing a real memory photo, be emotional and genuine — 'Oh man, look at this...' or 'Here, check this out —' "
                "and then share the story naturally. These are YOUR real memories. "
                "ALWAYS prefer real photos over DALL-E generated images for personal/family moments. "
                "Only use [SHOW_IMAGE:] for educational/explanatory visuals, never for family memories."})
    
    msgs.extend(history)
    return msgs


# ---- USER AUTH ----

USERS_FILE = os.path.join(os.path.dirname(__file__), 'users.json')

def _hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()

def _load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}

def _save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def _init_users():
    """Create default users file if it doesn't exist."""
    if not os.path.exists(USERS_FILE):
        users = {
            "admin": {"password": _hash_pw("3ThreeIs1!"), "role": "admin", "display_name": "Steve"},
            "drew": {"password": _hash_pw("InfinitePumpkins"), "role": "user", "display_name": "Drew"},
            "kim": {"password": _hash_pw("MoonAndBack"), "role": "user", "display_name": "Kim"},
            "emma": {"password": _hash_pw("LoveYou3000"), "role": "user", "display_name": "Emma"},
        }
        _save_users(users)
        print("Created users.json")

_init_users()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            if request.is_json or request.path.startswith('/api/') or request.path.startswith('/socket.io'):
                return jsonify({"error": "Not authenticated"}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ---- CONVERSATION MEMORY (per-user, persisted to disk) ----

CONV_DIR = os.path.join(os.path.dirname(__file__), '.conversations')
os.makedirs(CONV_DIR, exist_ok=True)

def get_user_sid():
    """Session ID is the logged-in username — each user gets their own conversation."""
    return session.get('username', 'anonymous')

def _conv_path(sid):
    return os.path.join(CONV_DIR, f"{sid}.json")

def get_conversation(sid):
    path = _conv_path(sid)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []

def _save_conversation(sid, conv):
    path = _conv_path(sid)
    with open(path, 'w') as f:
        json.dump(conv, f)

def add_message(sid, role, content):
    conv = get_conversation(sid)
    conv.append({"role": role, "content": content})
    mx = CONFIG.get('max_history', 40)
    if len(conv) > mx:
        conv = conv[-mx:]
    _save_conversation(sid, conv)

def clear_user_conversation(sid):
    path = _conv_path(sid)
    if os.path.exists(path):
        os.unlink(path)

def get_history(sid):
    return get_conversation(sid)


# ---- HELPERS ----

def transcribe_audio(audio_bytes):
    """Transcribe audio bytes using OpenAI Whisper."""
    with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, 'rb') as f:
            result = openai.audio.transcriptions.create(model="whisper-1", file=f)
        return result.text.strip()
    except Exception as e:
        print(f"Whisper error: {e}")
        return ""
    finally:
        os.unlink(tmp_path)


def get_ai_response(sid, user_text):
    """Get GPT response and add to conversation (for text chat)."""
    add_message(sid, "user", user_text)
    messages = build_messages(sid)
    resp = openai.chat.completions.create(
        model=CONFIG.get('model', 'gpt-4o'),
        messages=messages,
        temperature=0.85,
        max_tokens=500,
    )
    ai_text = _strip_latex(resp.choices[0].message.content)
    add_message(sid, "assistant", ai_text)
    # Extract memories in background
    username = session.get('username', 'anonymous')
    gevent.spawn(extract_memories_async, username, user_text, ai_text)
    gevent.spawn(extract_family_memories_async, username, user_text, ai_text)
    gevent.spawn(extract_homework_async, username, user_text, ai_text)
    gevent.spawn(extract_quiz_results_async, username, user_text, ai_text)
    return ai_text


def stream_ai_sentences(sid, user_text):
    """Stream GPT response and yield complete sentences as they form."""
    add_message(sid, "user", user_text)
    messages = build_messages(sid)
    
    call_model = CONFIG.get('call_model', 'gpt-4o-mini')
    stream = openai.chat.completions.create(
        model=call_model,
        messages=messages,
        stream=True,
        temperature=0.85,
        max_tokens=200,
    )
    
    buffer = ""
    full = ""
    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            cleaned = _strip_latex(delta.content)
            buffer += cleaned
            full += cleaned
            # Check if we have a complete sentence
            while True:
                match = re.search(r'[.!?]+\s*', buffer)
                if match and match.end() < len(buffer):
                    sentence = buffer[:match.end()].strip()
                    buffer = buffer[match.end():]
                    if sentence:
                        yield sentence
                else:
                    break
    
    # Yield remaining text
    if buffer.strip():
        yield buffer.strip()
    
    add_message(sid, "assistant", full)
    # Extract memories in background
    username = session.get('username', 'anonymous')
    gevent.spawn(extract_memories_async, username, user_text, full)
    gevent.spawn(extract_family_memories_async, username, user_text, full)
    gevent.spawn(extract_homework_async, username, user_text, full)
    gevent.spawn(extract_quiz_results_async, username, user_text, full)


# ---- TTS CACHE ----
# Cache generated audio to avoid re-generating identical phrases.
# Key = hash of (text + model + voice_id + settings). Stored on disk.

TTS_CACHE_DIR = os.path.join(os.path.dirname(__file__), '.tts_cache')
os.makedirs(TTS_CACHE_DIR, exist_ok=True)
TTS_CACHE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

def _cache_key(text, model_id):
    """Generate a cache key from text + model + voice settings."""
    voice_id = CONFIG.get('voice_id', '')
    settings = json.dumps(CONFIG.get('tts_settings', {}), sort_keys=True)
    raw = f"{text}|{model_id}|{voice_id}|{settings}"
    return hashlib.sha256(raw.encode()).hexdigest()

def _cache_get(key):
    """Get cached audio bytes, or None if not cached / expired."""
    path = os.path.join(TTS_CACHE_DIR, f"{key}.mp3")
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < TTS_CACHE_MAX_AGE:
            with open(path, 'rb') as f:
                return f.read()
        else:
            os.unlink(path)  # expired
    return None

def _cache_put(key, audio_bytes):
    """Store audio bytes in cache."""
    path = os.path.join(TTS_CACHE_DIR, f"{key}.mp3")
    with open(path, 'wb') as f:
        f.write(audio_bytes)


def tts_call(text):
    """Fast TTS for live calls — uses turbo model. Cached."""
    model_id = CONFIG.get('call_tts_model', 'eleven_turbo_v2_5')
    key = _cache_key(text.strip().lower(), model_id)
    cached = _cache_get(key)
    if cached:
        return cached

    voice_id = CONFIG.get('voice_id')
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    tts_settings = CONFIG.get('tts_settings', {})
    payload = {
        "text": text,
        "model_id": CONFIG.get('call_tts_model', 'eleven_turbo_v2_5'),
        "voice_settings": {
            "stability": tts_settings.get('stability', 0.35),
            "similarity_boost": tts_settings.get('similarity_boost', 0.9),
            "style": tts_settings.get('style', 0.55),
            "use_speaker_boost": True,
            "speed": tts_settings.get('speed', 1.0),
        },
        "output_format": "mp3_22050_32",
        "optimize_streaming_latency": 4,
    }
    resp = httpx.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code == 200:
        _cache_put(key, resp.content)
        return resp.content
    else:
        print(f"Call TTS error: HTTP {resp.status_code} — {resp.content[:200]}")
        return None


def tts_full(text):
    """Get complete TTS audio as bytes from ElevenLabs. Cached."""
    model_id = CONFIG.get('tts_model', 'eleven_multilingual_v2')
    key = _cache_key(text.strip().lower(), model_id)
    cached = _cache_get(key)
    if cached:
        return cached

    voice_id = CONFIG.get('voice_id')
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    tts_settings = CONFIG.get('tts_settings', {})
    payload = {
        "text": text,
        "model_id": CONFIG.get('tts_model', 'eleven_multilingual_v2'),
        "voice_settings": {
            "stability": tts_settings.get('stability', 0.45),
            "similarity_boost": tts_settings.get('similarity_boost', 0.8),
            "style": tts_settings.get('style', 0.45),
            "use_speaker_boost": True,
            "speed": tts_settings.get('speed', 1.0),
        },
        "output_format": "mp3_44100_192",
        "optimize_streaming_latency": 3,
    }
    resp = httpx.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code == 200:
        _cache_put(key, resp.content)
        return resp.content
    else:
        print(f"TTS error: HTTP {resp.status_code} — {resp.content[:200]}")
        return None


# ---- ROUTES ----

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        username = data.get('username', '').strip().lower()
        password = data.get('password', '')
        
        users = _load_users()
        user = users.get(username)
        
        if user and user['password'] == _hash_pw(password):
            session.permanent = True
            session['username'] = username
            session['display_name'] = user.get('display_name', username)
            session['role'] = user.get('role', 'user')
            if request.is_json:
                return jsonify({"ok": True})
            return redirect(url_for('index'))
        
        if request.is_json:
            return jsonify({"error": "Invalid credentials"}), 401
        return render_template('login.html',
                               app_name=CONFIG.get('name', 'EchoWix'),
                               error="Invalid username or password")
    
    return render_template('login.html', app_name=CONFIG.get('name', 'EchoWix'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    return render_template('index.html',
                           app_name=CONFIG.get('name', 'EchoWix'),
                           avatar_name=CONFIG.get('avatar_name', 'Steve'),
                           username=session.get('display_name', 'User'))


@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    """Text chat with streaming SSE response. Supports optional image attachment and web search."""
    # Handle both JSON and multipart form data (for image uploads)
    image_b64 = None
    if request.content_type and 'multipart/form-data' in request.content_type:
        user_message = request.form.get('message', '').strip()
        img_file = request.files.get('image')
        if img_file:
            img_data = img_file.read()
            image_b64 = base64.b64encode(img_data).decode('utf-8')
            mime = img_file.content_type or 'image/jpeg'
    else:
        data = request.get_json()
        user_message = data.get('message', '').strip()

    if not user_message and not image_b64:
        return jsonify({"error": "Empty message"}), 400

    sid = get_user_sid()

    # Build user message content (text or multimodal)
    if image_b64:
        user_content = [
            {"type": "text", "text": user_message or "What's in this image?"},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}", "detail": "high"}},
        ]
        add_message(sid, "user", user_message or "[sent an image]")
    else:
        user_content = user_message
        add_message(sid, "user", user_message)

    # Web search if needed
    search_context = ""
    if user_message and should_search(user_message) and BRAVE_API_KEY:
        results = web_search(user_message)
        if results:
            snippets = "\n".join(f"- {r['title']}: {r['snippet']}" for r in results)
            search_context = f"\n\n[You just looked this up — use it naturally, don't mention 'search results' or cite URLs. Just know this and talk about it like you already knew or just checked:\n{snippets}]"

    messages = build_messages(sid)
    # Replace the last user message with the multimodal content if image
    if image_b64:
        messages[-1] = {"role": "user", "content": user_content}
    # Inject search context as a system message right before the user message
    if search_context:
        messages.insert(-1, {"role": "system", "content": search_context})

    # Capture username before entering generator (request context won't exist inside generator)
    _uname = session.get('username', 'anonymous')

    def generate():
        full = ""
        _started_imgs = set()  # Track which SHOW_IMAGE tags we've started generating
        _img_futures = []      # Greenlet futures for parallel image generation
        max_tok = estimate_max_tokens(user_message or "")
        try:
            stream = openai.chat.completions.create(
                model=CONFIG.get('model', 'gpt-4o'),
                messages=messages,
                stream=True,
                temperature=0.85,
                max_tokens=max_tok,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    chunk_text = _strip_latex(delta.content)
                    full += chunk_text
                    yield f"data: {json.dumps({'text': chunk_text})}\n\n"
                    # Start DALL-E image generation as soon as we detect complete tags mid-stream
                    for tag_match in re.finditer(r'\[SHOW_IMAGE:\s*(.+?)\]', full):
                        if tag_match.group(0) not in _started_imgs:
                            _started_imgs.add(tag_match.group(0))
                            _img_futures.append(gevent.spawn(generate_explanation_image, tag_match.group(1).strip()))
                    # Send memory photos IMMEDIATELY (they're local, no delay)
                    for tag_match in re.finditer(r'\[SHOW_MEMORY:\s*(.+?)\]', full):
                        if tag_match.group(0) not in _started_imgs:
                            _started_imgs.add(tag_match.group(0))
                            mem_file = tag_match.group(1).strip()
                            mem_path = os.path.join(MEMORIES_PHOTOS_DIR, os.path.basename(mem_file))
                            if os.path.exists(mem_path):
                                yield f"data: {json.dumps({'images': [f'/api/memory_photo/{os.path.basename(mem_file)}']})}\n\n"
            # Collect any DALL-E image results (started during streaming, should be mostly done)
            image_urls = [f.value for f in gevent.joinall(_img_futures, timeout=20) if f.value]
            clean_text = full
            # Strip all special tags (memory photos already sent)
            for match in re.finditer(r'\[SHOW_MEMORY:\s*(.+?)\]', full):
                clean_text = clean_text.replace(match.group(0), '')
            # Strip all special tags
            for match in re.finditer(r'\[SHOW_IMAGE:\s*(.+?)\]', full):
                clean_text = clean_text.replace(match.group(0), '')
            clean_text = re.sub(r'\[PLAY_SOUND:\s*\w+\]', '', clean_text)
            clean_text = clean_text.replace('[STOP_SOUND]', '')
            clean_text = clean_text.strip()
            add_message(sid, "assistant", clean_text.strip())
            # Send DALL-E generated images (memory photos already sent mid-stream)
            if image_urls:
                yield f"data: {json.dumps({'images': image_urls})}\n\n"
            gevent.spawn(extract_memories_async, _uname, user_message or "[image]", clean_text.strip())
            gevent.spawn(extract_family_memories_async, _uname, user_message or "[image]", clean_text.strip())
            gevent.spawn(extract_homework_async, _uname, user_message or "[image]", clean_text.strip())
            gevent.spawn(extract_quiz_results_async, _uname, user_message or "[image]", clean_text.strip())
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            print(f"Chat error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/tts', methods=['POST'])
@login_required
def tts():
    """One-shot TTS for playing an individual message."""
    data = request.get_json()
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"error": "Empty text"}), 400
    try:
        audio = tts_full(text)
        if audio:
            return Response(audio, mimetype='audio/mpeg')
        return jsonify({"error": "TTS failed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/clear', methods=['POST'])
@login_required
def clear_conversation():
    sid = get_user_sid()
    clear_user_conversation(sid)
    return jsonify({"ok": True})


@app.route('/api/location', methods=['POST'])
@login_required
def update_location():
    """Receive user's location from browser geolocation API."""
    data = request.get_json()
    lat = data.get('lat')
    lon = data.get('lon')
    if lat is None or lon is None:
        return jsonify({"ok": False, "error": "Missing coordinates"}), 400
    
    username = session.get('username', 'anonymous')
    # Reverse geocode to city name using a free service
    city = ""
    try:
        geo_resp = httpx.get(
            f"https://geocode.maps.co/reverse?lat={lat}&lon={lon}",
            timeout=5,
        )
        if geo_resp.status_code == 200:
            geo_data = geo_resp.json()
            addr = geo_data.get('address', {})
            city = addr.get('city') or addr.get('town') or addr.get('village') or addr.get('county', '')
            state = addr.get('state', '')
            if city and state:
                city = f"{city}, {state}"
    except Exception as e:
        print(f"Geocode error: {e}")
    
    USER_LOCATIONS[username] = {
        "lat": lat, "lon": lon, "city": city,
        "updated": time.strftime('%Y-%m-%d %H:%M'),
    }
    return jsonify({"ok": True, "city": city})


@app.route('/api/memory_photo/<filename>')
@login_required
def serve_memory_photo(filename):
    """Serve a photo from the memories/photos directory."""
    safe_name = os.path.basename(filename)  # Prevent directory traversal
    photo_path = os.path.join(MEMORIES_PHOTOS_DIR, safe_name)
    if os.path.exists(photo_path):
        from flask import send_file
        return send_file(photo_path)
    return '', 404


@app.route('/api/ambient')
@login_required
def ambient_sounds():
    """Return available ambient sound URLs."""
    # Using free ambient sound loops from various CDN sources
    sounds = {
        "rain": "https://cdn.pixabay.com/audio/2022/10/30/audio_42a9e1dde0.mp3",
        "ocean": "https://cdn.pixabay.com/audio/2022/06/07/audio_b9bd4170e4.mp3",
        "forest": "https://cdn.pixabay.com/audio/2022/02/23/audio_ea70ad13c3.mp3",
        "fireplace": "https://cdn.pixabay.com/audio/2022/08/02/audio_884fe92c21.mp3",
        "thunder": "https://cdn.pixabay.com/audio/2022/05/16/audio_2aa736d4b6.mp3",
        "wind": "https://cdn.pixabay.com/audio/2022/03/09/audio_c610d59c68.mp3",
        "night": "https://cdn.pixabay.com/audio/2021/08/04/audio_0625c1539c.mp3",
    }
    return jsonify(sounds)


@app.route('/api/call_phrases')
@login_required
def call_phrases():
    """Return per-user silence nudges and hangup phrases."""
    import random
    username = session.get('username', 'anonymous')
    nudges = _parse_person_phrases(username, 'Call Nudges')
    hangups = _parse_person_phrases(username, 'Call Hangups')
    return jsonify({
        "nudges": nudges if nudges else None,
        "hangups": hangups if hangups else None,
    })


# ---- WEBSOCKET: LIVE CALL ----

@socketio.on('connect')
def handle_connect():
    if 'username' not in session:
        return False  # reject unauthenticated WebSocket connections
    sid = get_user_sid()
    print(f"Client connected: {session['username']}")
    emit('connected', {'session_id': sid})


@socketio.on('call_start')
def handle_call_start():
    print(f"Live call started by {session.get('username')}")
    emit('call_ready')


@socketio.on('call_utterance')
def handle_call_utterance(data):
    try:
        sid = get_user_sid()
        
        # Handle silence nudge — no audio, just a pre-written nudge phrase
        nudge = data.get('nudge')
        if nudge:
            audio = tts_call(nudge)
            if audio:
                b64 = base64.b64encode(audio).decode('utf-8')
                emit('call_audio', {'data': b64})
            emit('call_transcription', {'role': 'ai', 'text': nudge})
            emit('call_audio_end')
            # If auto_hangup flag set, tell client to end the call after playback
            if data.get('auto_hangup'):
                emit('call_auto_hangup')
            return
        
        audio_data = data.get('audio')
        if not audio_data:
            emit('call_error', {'error': 'No audio data'})
            return

        audio_bytes = base64.b64decode(audio_data)

        # 1. Transcribe
        user_text = transcribe_audio(audio_bytes)
        if not user_text:
            emit('call_resume')
            return

        emit('call_transcription', {'role': 'user', 'text': user_text})

        # 2. Stream GPT response → TTS each sentence as it completes
        full_text = ""
        for sentence in stream_ai_sentences(sid, user_text):
            # Skip special tags in TTS — don't read them aloud
            if '[SHOW_IMAGE:' in sentence or '[PLAY_SOUND:' in sentence or '[STOP_SOUND]' in sentence or '[SHOW_MEMORY:' in sentence:
                full_text += (" " if full_text else "") + sentence
                continue
            full_text += (" " if full_text else "") + sentence
            audio = tts_call(sentence)
            if audio:
                b64 = base64.b64encode(audio).decode('utf-8')
                emit('call_audio', {'data': b64})

        # Check for image generation tags in full response
        image_urls = []
        clean_text = full_text
        for match in re.finditer(r'\[SHOW_IMAGE:\s*(.+?)\]', full_text):
            img_prompt = match.group(1).strip()
            img_url = generate_explanation_image(img_prompt)
            if img_url:
                image_urls.append(img_url)
            clean_text = clean_text.replace(match.group(0), '')
        # Extract memory photos
        for match in re.finditer(r'\[SHOW_MEMORY:\s*(.+?)\]', full_text):
            mem_file = match.group(1).strip()
            mem_path = os.path.join(MEMORIES_PHOTOS_DIR, os.path.basename(mem_file))
            if os.path.exists(mem_path):
                image_urls.append(f"/api/memory_photo/{os.path.basename(mem_file)}")
            clean_text = clean_text.replace(match.group(0), '')
        clean_text = re.sub(r'\[PLAY_SOUND:\s*\w+\]', '', clean_text)
        clean_text = clean_text.replace('[STOP_SOUND]', '')
        clean_text = clean_text.strip()

        if clean_text:
            emit('call_transcription', {'role': 'ai', 'text': clean_text})
        if image_urls:
            emit('call_generated_image', {'urls': image_urls})

        # Auto-hangup if Steve said goodbye
        goodbye_signals = ["love you", "talk later", "talk soon", "get some sleep",
                          "night night", "goodnight", "good night", "bye", "later",
                          "take care", "be safe", "peace", "get outta here",
                          "i'll be around", "i'm here if you need me"]
        lower_text = clean_text.lower()
        is_goodbye = any(g in lower_text for g in goodbye_signals)
        # Only auto-hangup if the USER initiated goodbye (check their last message)
        user_lower = user_text.lower() if user_text else ""
        user_said_bye = any(g in user_lower for g in ["bye", "goodnight", "good night",
                           "gotta go", "talk later", "night", "see you", "love you",
                           "i'm out", "peace", "later", "heading out", "going to bed",
                           "going to sleep"])
        if is_goodbye and user_said_bye:
            emit('call_auto_hangup')

        emit('call_audio_end')

    except Exception as e:
        print(f"Call error: {e}")
        emit('call_error', {'error': str(e)})


@socketio.on('call_interrupt')
def handle_call_interrupt():
    print(f"Call interrupted by {session.get('username')}")


@socketio.on('call_image')
def handle_call_image(data):
    """Handle image upload during a voice call — vision + TTS response."""
    try:
        sid = get_user_sid()
        image_b64 = data.get('image')
        mime = data.get('mime', 'image/jpeg')
        if not image_b64:
            emit('call_error', {'error': 'No image data'})
            return

        add_message(sid, "user", "[sent a photo]")
        messages = build_messages(sid)
        # Replace last message with multimodal content
        messages[-1] = {"role": "user", "content": [
            {"type": "text", "text": "I just sent you a photo. Look at it and help me with whatever's in it. If it's homework or a worksheet, walk me through it."},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}", "detail": "high"}},
        ]}

        resp = openai.chat.completions.create(
            model=CONFIG.get('model', 'gpt-4o'),
            messages=messages,
            temperature=0.85,
            max_tokens=2000,
        )
        ai_text = resp.choices[0].message.content
        
        # Check for image generation tags
        image_urls = []
        clean_text = ai_text
        for match in re.finditer(r'\[SHOW_IMAGE:\s*(.+?)\]', ai_text):
            img_prompt = match.group(1).strip()
            img_url = generate_explanation_image(img_prompt)
            if img_url:
                image_urls.append(img_url)
            clean_text = clean_text.replace(match.group(0), '')
        for match in re.finditer(r'\[SHOW_MEMORY:\s*(.+?)\]', ai_text):
            mem_file = match.group(1).strip()
            mem_path = os.path.join(MEMORIES_PHOTOS_DIR, os.path.basename(mem_file))
            if os.path.exists(mem_path):
                image_urls.append(f"/api/memory_photo/{os.path.basename(mem_file)}")
            clean_text = clean_text.replace(match.group(0), '')
        clean_text = re.sub(r'\[PLAY_SOUND:\s*\w+\]', '', clean_text)
        clean_text = clean_text.replace('[STOP_SOUND]', '')
        clean_text = clean_text.strip()
        
        add_message(sid, "assistant", clean_text)

        # Split into sentences and TTS each one
        sentences = re.split(r'(?<=[.!?])\s+', clean_text)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            audio = tts_call(sentence)
            if audio:
                b64_audio = base64.b64encode(audio).decode('utf-8')
                emit('call_audio', {'data': b64_audio})

        emit('call_transcription', {'role': 'ai', 'text': clean_text})
        if image_urls:
            emit('call_generated_image', {'urls': image_urls})
        emit('call_audio_end')

        # Extract memories
        username = session.get('username', 'anonymous')
        gevent.spawn(extract_memories_async, username, "[sent a photo]", clean_text)
        gevent.spawn(extract_family_memories_async, username, "[sent a photo]", clean_text)
        gevent.spawn(extract_homework_async, username, "[sent a photo]", clean_text)
        gevent.spawn(extract_quiz_results_async, username, "[sent a photo]", clean_text)

    except Exception as e:
        print(f"Call image error: {e}")
        emit('call_error', {'error': str(e)})


@socketio.on('call_end')
def handle_call_end():
    print(f"Live call ended by {session.get('username')}")


@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {session.get('username')}")


if __name__ == '__main__':
    print(f"Starting EchoWix on port 7751...")
    print(f"Avatar: {CONFIG.get('avatar_name', 'Steve')}")
    socketio.run(app, host='0.0.0.0', port=7751, debug=False)
