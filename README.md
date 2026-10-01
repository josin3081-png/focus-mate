# Focusmate

Focusmate is a local-first personal work assistant built with Flask and SQLite. It includes:

- Password-hashed account registration and login
- A daily task board with priorities and completion tracking
- A live local clock, date, and time-aware greeting
- Assistant commands that create tasks and mark matching tasks complete
- Task planning replies based on your own task list
- Browser speech recognition for voice questions, where supported
- Spoken assistant replies with selectable browser voices and controls to mute or replay them
- Local arithmetic, including worded operations and percentages, plus quick answers about programming, science, and everyday world facts
- Optional broad knowledge answers from an OpenAI-compatible chat-completions service

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 and create an account. Set `ASSISTANT_SECRET` to a long random value before using this beyond local development.

## General knowledge provider (optional)

The app can answer a small set of common questions, report the local date and time, and evaluate safe arithmetic locally. For broader questions, configure an OpenAI-compatible chat-completions endpoint before starting the app:

```powershell
$env:ASSISTANT_LLM_URL = "https://your-provider.example/v1/chat/completions"
$env:ASSISTANT_LLM_API_KEY = "your-provider-key"
$env:ASSISTANT_LLM_MODEL = "your-model-name"
python app.py
```

Use the endpoint and model required by your provider. The API key is optional for compatible local services that do not require authentication. Without a configured provider, broader questions cannot be answered; the assistant identifies the unanswered question and explains how to enable the provider rather than presenting guesses as facts.

Only general-knowledge questions are sent to the configured provider; task planning and task-list answers stay local. Provider requests include the question and may be processed according to that provider's privacy policy. Voice input and speech output use browser-provided speech features and availability varies by browser and operating system.

### If a reply is not spoken

Voice input uses the browser's speech recognition and requires microphone permission. Tap the microphone and say a question or a direct task command such as “Add a task to prepare the launch notes” or “Mark prepare the launch notes as done.” The assistant can create a task or complete one matching your task list; it will ask for a more exact name if several tasks match.

Spoken replies use browser-installed text-to-speech voices, not a Python voice service. Choose an option in **Reply voice**; available voices depend on the browser and operating system. Use a recent Chrome or Edge browser, check that system audio is audible and a speech voice is installed, and leave **Voice replies: On** enabled. If automatic playback is blocked, click **Speak reply** after the answer appears. The dashboard reports speech errors next to these controls.