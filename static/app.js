const taskList = document.querySelector('#task-list');
const dialog = document.querySelector('#task-dialog');
const questionInput = document.querySelector('#question');
const answerBox = document.querySelector('#assistant-response');
const voiceReplyToggle = document.querySelector('#voice-reply-toggle');
const speakButton = document.querySelector('#speak-button');
const voiceSelect = document.querySelector('#assistant-voice-select');
const canSpeak = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
let voiceRepliesEnabled = true;
let latestAnswer = '';
let speechStatus = document.querySelector('#speech-status');
let speechRequestId = 0;
let availableVoices = [];
const voiceStorageKey = 'focusmate-reply-voice';
const welcomeHeading = document.querySelector('#welcome-greeting');
const localClock = document.querySelector('#local-clock');
const localDate = document.querySelector('#local-date');

function updateLocalClock() {
  const now = new Date();
  if (welcomeHeading) {
    const hour = now.getHours();
    const greeting = hour >= 5 && hour < 12
      ? 'Good morning'
      : hour >= 12 && hour < 18
        ? 'Good afternoon'
        : 'Good evening';
    welcomeHeading.textContent = `${greeting}, ${welcomeHeading.dataset.firstName}.`;
  }
  if (localClock) {
    localClock.textContent = now.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    localClock.dateTime = now.toISOString();
  }
  if (localDate) {
    localDate.textContent = now.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
    localDate.dateTime = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  }
}

updateLocalClock();
window.setInterval(updateLocalClock, 30_000);

function setSpeechStatus(message) {
  if (speechStatus) speechStatus.textContent = message;
}

function setAssistantMessage(message, symbol = '❀') {
  const icon = document.createElement('span');
  icon.className = 'response-symbol';
  icon.textContent = symbol;
  const text = document.createElement('p');
  text.textContent = message;
  answerBox.replaceChildren(icon, text);
}

function voiceKey(voice) {
  return voice.voiceURI || `${voice.name}::${voice.lang}`;
}

function getSavedVoice() {
  try {
    return localStorage.getItem(voiceStorageKey) || '';
  } catch {
    return '';
  }
}

function saveVoice(value) {
  try {
    localStorage.setItem(voiceStorageKey, value);
  } catch {
    return;
  }
}

function refreshAvailableVoices() {
  if (!canSpeak || !voiceSelect) return;
  const savedVoice = voiceSelect.value || getSavedVoice();
  availableVoices = window.speechSynthesis.getVoices().slice().sort((first, second) => first.name.localeCompare(second.name));
  voiceSelect.replaceChildren(new Option('Automatic', ''));
  availableVoices.forEach((voice) => {
    voiceSelect.add(new Option(`${voice.name} (${voice.lang})`, voiceKey(voice)));
  });
  voiceSelect.disabled = availableVoices.length === 0;
  voiceSelect.value = availableVoices.some((voice) => voiceKey(voice) === savedVoice) ? savedVoice : '';
}

function speakAnswer(message) {
  if (!canSpeak || !message) {
    setSpeechStatus('Spoken replies are not supported by this browser.');
    return;
  }

  const requestId = ++speechRequestId;
  const synthesis = window.speechSynthesis;
  setSpeechStatus('Starting spoken reply…');
  try {
    synthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(message);
    const language = navigator.language || 'en-US';
    utterance.lang = language;
    utterance.rate = 1;
    utterance.volume = 1;

    const voices = synthesis.getVoices();
    const selectedVoice = voices.find((voice) => voiceSelect?.value && voiceKey(voice) === voiceSelect.value);
    const preferredVoice = selectedVoice || voices.find((voice) => voice.lang.toLowerCase() === language.toLowerCase())
      || voices.find((voice) => voice.lang.toLowerCase().startsWith(language.split('-')[0].toLowerCase()))
      || voices.find((voice) => voice.default)
      || voices[0];
    if (preferredVoice) utterance.voice = preferredVoice;

    utterance.onstart = () => {
      if (requestId === speechRequestId) setSpeechStatus(`Speaking${preferredVoice ? ` with ${preferredVoice.name}` : ''}…`);
    };
    utterance.onend = () => {
      if (requestId === speechRequestId) setSpeechStatus('Reply spoken.');
    };
    utterance.onerror = (event) => {
      if (requestId !== speechRequestId || event.error === 'canceled' || event.error === 'interrupted') return;
      const explanation = event.error === 'not-allowed'
        ? 'The browser blocked speech. Click “Speak reply” to allow playback.'
        : event.error === 'voice-unavailable'
          ? 'No usable system voice is available. Check your browser and operating-system speech settings.'
          : `Speech failed (${event.error || 'unknown error'}). Click “Speak reply” to try again.`;
      setSpeechStatus(explanation);
    };

    synthesis.speak(utterance);
  } catch (error) {
    setSpeechStatus(`Speech could not start: ${error.message || 'unknown error'}. Click “Speak reply” to retry.`);
  }
}

if (!canSpeak) {
  voiceReplyToggle.disabled = true;
  voiceReplyToggle.textContent = 'Spoken replies unavailable';
  voiceReplyToggle.setAttribute('aria-pressed', 'false');
  speakButton.disabled = true;
  if (voiceSelect) voiceSelect.disabled = true;
  setSpeechStatus('This browser does not support spoken replies. Try a recent version of Chrome or Edge.');
} else {
  setSpeechStatus('Spoken replies are ready.');
  refreshAvailableVoices();
  window.speechSynthesis.addEventListener('voiceschanged', () => {
    refreshAvailableVoices();
    if (window.speechSynthesis.getVoices().length === 0) {
      setSpeechStatus('No system voices found yet. Check your browser or operating-system speech settings.');
    } else if (!window.speechSynthesis.speaking && !window.speechSynthesis.pending) {
      setSpeechStatus('Spoken replies are ready.');
    }
  });
  if (window.speechSynthesis.getVoices().length === 0) {
    setSpeechStatus('Waiting for browser voices. Check system speech settings if nothing is listed.');
  }
  voiceReplyToggle.addEventListener('click', () => {
    voiceRepliesEnabled = !voiceRepliesEnabled;
    voiceReplyToggle.textContent = `Voice replies: ${voiceRepliesEnabled ? 'On' : 'Off'}`;
    voiceReplyToggle.setAttribute('aria-pressed', String(voiceRepliesEnabled));
    if (!voiceRepliesEnabled) {
      speechRequestId += 1;
      window.speechSynthesis.cancel();
      setSpeechStatus('Spoken replies are off.');
    } else {
      setSpeechStatus('Spoken replies are on. Use “Speak reply” if automatic playback is blocked.');
    }
  });
}

voiceSelect?.addEventListener('change', () => {
  saveVoice(voiceSelect.value);
  const selectedVoice = availableVoices.find((voice) => voiceKey(voice) === voiceSelect.value);
  setSpeechStatus(selectedVoice ? `Reply voice set to ${selectedVoice.name}.` : 'Using automatic voice selection.');
});

speakButton.addEventListener('click', () => {
  if (latestAnswer) speakAnswer(latestAnswer);
  else setSpeechStatus('Ask a question first, then use “Speak reply”.');
});

async function toggleTask(button) {
  const item = button.closest('.task-item');
  const response = await fetch(`/api/tasks/${item.dataset.taskId}/toggle`, { method: 'POST' });
  if (!response.ok) return;
  const result = await response.json();
  item.classList.toggle('is-done', Boolean(result.completed));
  button.textContent = result.completed ? '✓' : '';
}

function updateTaskBoard(action, task) {
  if (!taskList || !task) return;
  let item = taskList.querySelector(`[data-task-id="${task.id}"]`);

  if (action === 'created') {
    taskList.querySelector('.empty-state')?.remove();
    item = document.createElement('article');
    item.className = 'task-item';
    item.dataset.taskId = task.id;

    const checkButton = document.createElement('button');
    checkButton.className = 'task-check';
    checkButton.type = 'button';
    checkButton.setAttribute('aria-label', `Mark ${task.title} complete`);
    const content = document.createElement('div');
    content.className = 'task-content';
    const meta = document.createElement('div');
    meta.className = 'task-meta';
    const due = document.createElement('span');
    due.className = 'task-time';
    due.textContent = task.due;
    meta.append(due);
    if (task.priority === 'high') {
      const priority = document.createElement('span');
      priority.className = 'priority high';
      priority.textContent = 'Focus';
      meta.append(priority);
    }
    const title = document.createElement('h3');
    title.textContent = task.title;
    const detail = document.createElement('p');
    detail.textContent = task.detail || '';
    content.append(meta, title, detail);
    const arrow = document.createElement('span');
    arrow.className = 'task-arrow';
    arrow.textContent = '↗';
    item.append(checkButton, content, arrow);
    taskList.prepend(item);
  } else if (action === 'completed' && item) {
    item.classList.add('is-done');
    const checkButton = item.querySelector('.task-check');
    checkButton.textContent = '✓';
    checkButton.setAttribute('aria-label', `Mark ${task.title} incomplete`);
    taskList.append(item);
  }

  const items = [...taskList.querySelectorAll('.task-item')];
  const completed = items.filter((taskItem) => taskItem.classList.contains('is-done')).length;
  const completionCount = document.querySelector('.completion strong');
  const progress = document.querySelector('.progress-track span');
  if (completionCount) completionCount.textContent = `${completed}/${items.length}`;
  if (progress) progress.style.width = `${items.length ? (completed / items.length) * 100 : 0}%`;
}

taskList?.addEventListener('click', (event) => {
  if (event.target.classList.contains('task-check')) toggleTask(event.target);
});

document.querySelector('#open-task')?.addEventListener('click', () => dialog.showModal());
document.querySelector('.dialog-close')?.addEventListener('click', () => dialog.close());
document.querySelector('#task-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = {
    title: document.querySelector('#task-title').value,
    due: document.querySelector('#task-due').value || 'Anytime',
    detail: document.querySelector('#task-detail').value,
  };
  const response = await fetch('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  if (response.ok) window.location.reload();
});

async function askAssistant(question = questionInput.value.trim()) {
  if (!question) return;
  setAssistantMessage('Thinking...', '◌');
  try {
    const response = await fetch('/api/assistant', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'I could not answer that right now.');
    latestAnswer = result.answer;
    updateTaskBoard(result.action, result.task);
    speakButton.disabled = !canSpeak || !latestAnswer;
    setAssistantMessage(result.answer);
    if (voiceRepliesEnabled) speakAnswer(latestAnswer);
    else setSpeechStatus('Spoken replies are off. Click “Speak reply” to hear this answer.');
  } catch (error) {
    setAssistantMessage(error.message, '!');
    setSpeechStatus('No spoken reply because the assistant could not answer.');
  } finally {
    questionInput.value = '';
  }
}

document.querySelector('#ask-button')?.addEventListener('click', () => askAssistant());
questionInput?.addEventListener('keydown', (event) => { if (event.key === 'Enter') askAssistant(); });
document.querySelectorAll('[data-question]').forEach((button) => button.addEventListener('click', () => askAssistant(button.dataset.question)));

const voiceButton = document.querySelector('#voice-button');
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (voiceButton && SpeechRecognition) {
  const recognition = new SpeechRecognition();
  recognition.lang = navigator.language || 'en-US';
  recognition.onstart = () => {
    voiceButton.classList.add('listening');
    voiceButton.setAttribute('aria-pressed', 'true');
    setSpeechStatus('Listening. Say a task or ask a question.');
  };
  recognition.onend = () => {
    voiceButton.classList.remove('listening');
    voiceButton.setAttribute('aria-pressed', 'false');
  };
  recognition.onerror = (event) => {
    const message = event.error === 'not-allowed'
      ? 'Microphone access was blocked. Allow microphone access in your browser settings.'
      : event.error === 'no-speech'
        ? 'I did not hear anything. Tap the microphone and try again.'
        : `Voice input failed (${event.error || 'unknown error'}).`;
    setSpeechStatus(message);
  };
  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript.trim();
    if (!transcript) return;
    questionInput.value = transcript;
    askAssistant(transcript);
  };
  voiceButton.addEventListener('click', () => {
    try {
      recognition.start();
    } catch (error) {
      setAssistantMessage('Voice input is already starting. Please try again in a moment.', '!');
    }
  });
} else if (voiceButton) {
  voiceButton.title = 'Voice input is not supported in this browser';
  voiceButton.disabled = true;
}