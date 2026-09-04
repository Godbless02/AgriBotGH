// ── CONSTANTS ────────────────────────────────────────────────────
const API = "";
const STORAGE_KEY_CURRENT = "agribot_current_user"; // who is logged in now
const STORAGE_KEY_ALL = "agribot_all_users"; // all user profiles + their chats
const STORAGE_KEY_THEME = "agribot_theme_preference";
const DARK_THEME_QUERY = "(prefers-color-scheme: dark)";

// ── STATE ────────────────────────────────────────────────────────
let currentUser = "";
let currentLang = "en";
let enSessionId = null;
let twSessionId = null;
let welcomeLang = "en";
let isDarkTheme = false;
let systemThemeMedia = null;
let weatherRequestController = null;
let weatherReturnFocus = null;
// simple toggle locks to prevent double-triggering
let chipsToggleLock = false;
let sidebarToggleLock = false;
let activeSpeech = {
  button: null,
  utterance: null,
  audio: null,
  controller: null,
  requestId: 0,
  clips: [],
  clipIndex: 0,
  engine: null,
  lang: "en",
  isPlaying: false,
  isPaused: false,
};
let availableSpeechVoices = [];
let speechVoiceListenerRegistered = false;
let activeRecognition = null;

const WEATHER_TEXT = {
  en: {
    button: "Weather", eyebrow: "Farm planning", title: "Local weather",
    locationLabel: "Town or city", placeholder: "e.g. Kumasi", submit: "Check weather",
    loading: "Checking the latest weather…", current: "Current conditions",
    forecast: "3-day forecast", source: "Weather data: Open-Meteo",
    temperature: "Temperature", humidity: "Humidity", wind: "Wind", rainfall: "Rainfall",
    rainChance: "Rain chance", high: "High", low: "Low",
    empty: "Enter a town or city to check the weather.", unavailable: "Weather information is temporarily unavailable. Please try again.",
    backendUnavailable: "The AgriBot weather API is not running. Start the application with Flask, then try again.",
    dry: "Little rain is expected today. Check soil moisture before watering.",
    possibleRain: "Rain is possible today. Plan spraying and drying work carefully.",
    likelyRain: "Rain is likely today. Protect harvested produce and avoid spraying before rain.",
    caution: "Forecasts can change. Check again before time-sensitive farm work."
  },
  tw: {
    button: "Ewiem Tebea", eyebrow: "Afuw nhyehyɛe", title: "Mpɔtam ewiem tebea",
    locationLabel: "Kurow anaa kuro", placeholder: "sɛ nhwɛso: Kumasi", submit: "Hwɛ ewiem tebea",
    loading: "Yɛrehwɛ ewiem tebea foforo…", current: "Mprempren ewiem tebea",
    forecast: "Nnansa ewiem tebea", source: "Ewiem tebea ho nsɛm: Open-Meteo",
    temperature: "Ɔhyew", humidity: "Mframa mu nsu", wind: "Mframa", rainfall: "Osu dodow",
    rainChance: "Osu tumi tɔ", high: "Nea ɛkorɔn", low: "Nea ɛba fam",
    empty: "Kyerɛw kurow bi din na yɛnhwɛ ewiem tebea.", unavailable: "Yentumi nnya ewiem tebea ho nsɛm seesei. San sɔ hwɛ.",
    backendUnavailable: "AgriBot ewiem tebea API no nnyina hɔ. Fa Flask hyɛ application no ase na san sɔ hwɛ.",
    dry: "Ɛda adi sɛ osu pii rentɔ nnɛ. Hwɛ asase no mu nsu ansa na woagugu so nsu.",
    possibleRain: "Osu betumi atɔ nnɛ. Yɛ aduro pete ne nnɔbae yow ho nhyehyɛe yiye.",
    likelyRain: "Ɛda adi sɛ osu bɛtɔ nnɛ. Kata nnɔbae a woatwa so na mfa aduro mpete ansa na osu atɔ.",
    caution: "Ewiem tebea betumi asesa. San hwɛ ansa na woayɛ afuw adwuma a ɛhia bere pɔtee."
  }
};

const WEATHER_CONDITIONS_TW = {
  0: "Ewiem atew", 1: "Ewiem atew kakra", 2: "Mununkum kakra", 3: "Mununkum",
  45: "Sum kabii", 48: "Sum kabii", 51: "Osu nketenkete", 53: "Osu nketenkete",
  55: "Osu nketenkete a emu yɛ den", 61: "Osu kakra", 63: "Osu", 65: "Osu kɛse",
  80: "Osu kakra", 81: "Osu", 82: "Osu kɛse", 95: "Aprannaa"
};

// ══════════════════════════════════════════════════════════════════
// STORAGE HELPERS — all data stored per username
// ══════════════════════════════════════════════════════════════════

function getAllUsers() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY_ALL)) || {};
  } catch {
    return {};
  }
}

function saveAllUsers(users) {
  localStorage.setItem(STORAGE_KEY_ALL, JSON.stringify(users));
}

function getUserProfile(name) {
  const all = getAllUsers();
  const key = name.trim().toLowerCase();
  return all[key] || null;
}

function createUserProfile(name, lang) {
  const all = getAllUsers();
  const key = name.trim().toLowerCase();
  if (!all[key]) {
    all[key] = {
      displayName: name.trim(),
      lang: lang,
      sessions: {}, // sessId -> { id, lang, title, messages, createdAt }
    };
    saveAllUsers(all);
  }
  return all[key];
}

function updateUserProfile(name, data) {
  const all = getAllUsers();
  const key = name.trim().toLowerCase();
  if (all[key]) {
    all[key] = { ...all[key], ...data };
    saveAllUsers(all);
  }
}

function saveSessionMessage(name, sessId, lang, title, userMsg, botMsg) {
  const all = getAllUsers();
  const key = name.trim().toLowerCase();
  if (!all[key]) return;

  if (!all[key].sessions[sessId]) {
    all[key].sessions[sessId] = {
      id: sessId,
      lang,
      title,
      messages: [],
      createdAt: Date.now(),
    };
  }
  all[key].sessions[sessId].messages.push(
    { role: "user", text: userMsg, time: getTime() },
    { role: "bot", text: botMsg, time: getTime() },
  );
  saveAllUsers(all);
}

// ══════════════════════════════════════════════════════════════════
// WELCOME SCREEN
// ══════════════════════════════════════════════════════════════════

function selectWelcomeLang(lang) {
  welcomeLang = lang;
  document
    .getElementById("langEnBtn")
    .classList.toggle("active", lang === "en");
  document
    .getElementById("langTwBtn")
    .classList.toggle("active", lang === "tw");
  startChatIfReady();
}

function startChatIfReady() {
  const nameValue = document.getElementById("nameInput").value.trim();
  if (!nameValue) return;
  if (document.getElementById("appShell").style.display === "none") {
    startChat();
  }
}

function startChat() {
  const nameInput = document.getElementById("nameInput").value.trim();
  const errEl = document.getElementById("welcomeError");

  if (!nameInput) {
    errEl.textContent = "Please enter your name to continue.";
    return;
  }
  errEl.textContent = "";

  const profile = getUserProfile(nameInput);

  if (profile) {
    // RETURNING USER — restore their language and sessions
    currentUser = profile.displayName;
    currentLang = profile.lang || welcomeLang;
  } else {
    // NEW USER — create fresh profile
    currentUser = nameInput;
    currentLang = welcomeLang;
    createUserProfile(nameInput, welcomeLang);
  }

  // Remember who is currently using the app
  localStorage.setItem(STORAGE_KEY_CURRENT, currentUser);

  // Launch app
  document.getElementById("welcomeScreen").style.display = "none";
  document.getElementById("appShell").style.display = "flex";
  document.getElementById("appShell").style.flexDirection = "column";
  initApp(profile !== null); // pass true if returning user
}

function changeName() {
  stopSpeechRecognition({ abort: true, clearStatus: true });
  stopSpeech();
  // Save current user's language preference before leaving
  if (currentUser) {
    updateUserProfile(currentUser, { lang: currentLang });
  }
  // Clear current session state
  enSessionId = null;
  twSessionId = null;
  currentUser = "";

  // Go back to welcome screen — blank name field so new user enters their own name
  document.getElementById("appShell").style.display = "none";
  document.getElementById("welcomeScreen").style.display = "flex";
  document.getElementById("nameInput").value = "";
  document.getElementById("welcomeError").textContent = "";
  selectWelcomeLang("en");
}

// ══════════════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════════════

function weatherText() {
  return WEATHER_TEXT[currentLang === "tw" ? "tw" : "en"];
}

function updateWeatherLanguage() {
  const text = weatherText();
  const values = {
    weatherBtnLabel: text.button, weatherEyebrow: text.eyebrow, weatherTitle: text.title,
    weatherLocationLabel: text.locationLabel, weatherSubmit: text.submit,
    weatherCurrentLabel: text.current, weatherForecastTitle: text.forecast, weatherSource: text.source
  };
  Object.entries(values).forEach(([id, value]) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  });
  const input = document.getElementById("weatherLocation");
  if (input) input.placeholder = text.placeholder;
}

function openWeatherPanel() {
  const overlay = document.getElementById("weatherOverlay");
  weatherReturnFocus = document.activeElement;
  overlay.hidden = false;
  document.body.classList.add("weather-open");
  updateWeatherLanguage();
  window.setTimeout(() => document.getElementById("weatherLocation").focus(), 0);
}

function closeWeatherPanel() {
  document.getElementById("weatherOverlay").hidden = true;
  document.body.classList.remove("weather-open");
  if (weatherRequestController) weatherRequestController.abort();
  if (weatherReturnFocus && typeof weatherReturnFocus.focus === "function") weatherReturnFocus.focus();
}

function weatherMetric(label, value) {
  const card = document.createElement("div");
  card.className = "weather-metric";
  const valueElement = document.createElement("strong");
  valueElement.textContent = value;
  const labelElement = document.createElement("span");
  labelElement.textContent = label;
  card.append(valueElement, labelElement);
  return card;
}

function formatWeatherDate(value) {
  const date = new Date(`${value}T12:00:00`);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("en-GH", {
    weekday: "short", day: "numeric", month: "short"
  }).format(date);
}

function weatherCondition(item) {
  if (currentLang === "tw") return WEATHER_CONDITIONS_TW[item.weather_code] || "Ewiem tebea";
  return item.condition || "Weather conditions";
}

function renderWeather(data) {
  const text = weatherText();
  const units = data.units || {};
  const current = data.current;
  const location = data.location;
  document.getElementById("weatherPlace").textContent = [location.name, location.admin1, location.country].filter(Boolean).join(", ");
  document.getElementById("weatherCondition").textContent = weatherCondition(current);
  document.getElementById("weatherMetrics").replaceChildren(
    weatherMetric(text.temperature, `${Math.round(current.temperature)}${units.temperature || "°C"}`),
    weatherMetric(text.humidity, `${Math.round(current.humidity)}${units.humidity || "%"}`),
    weatherMetric(text.wind, `${Math.round(current.wind_speed)} ${units.wind_speed || "km/h"}`),
    weatherMetric(text.rainfall, `${current.precipitation} ${units.precipitation || "mm"}`),
    weatherMetric(text.rainChance, `${Math.round(current.rain_probability)}${units.precipitation_probability || "%"}`)
  );
  const probability = Number(current.rain_probability) || 0;
  const guidance = probability >= 60 ? text.likelyRain : probability >= 30 ? text.possibleRain : text.dry;
  document.getElementById("weatherGuidance").textContent = `${guidance} ${text.caution}`;
  const forecast = document.getElementById("weatherForecast");
  forecast.replaceChildren();
  data.forecast.forEach((day) => {
    const card = document.createElement("article");
    card.className = "weather-day";
    const date = document.createElement("strong");
    date.textContent = formatWeatherDate(day.date);
    const condition = document.createElement("span");
    condition.className = "weather-day-condition";
    condition.textContent = weatherCondition(day);
    const temperature = document.createElement("span");
    temperature.textContent = `${text.high} ${Math.round(day.temperature_max)}° · ${text.low} ${Math.round(day.temperature_min)}°`;
    const rain = document.createElement("span");
    rain.textContent = `${text.rainChance}: ${Math.round(day.precipitation_probability)}%`;
    card.append(date, condition, temperature, rain);
    forecast.appendChild(card);
  });
  document.getElementById("weatherStatus").textContent = "";
  document.getElementById("weatherResults").hidden = false;
}

async function loadWeather(location) {
  const text = weatherText();
  const status = document.getElementById("weatherStatus");
  const results = document.getElementById("weatherResults");
  const submit = document.getElementById("weatherSubmit");
  if (!location.trim()) {
    status.textContent = text.empty;
    return;
  }
  if (weatherRequestController) weatherRequestController.abort();
  weatherRequestController = new AbortController();
  const activeController = weatherRequestController;
  const timeout = window.setTimeout(() => activeController.abort(), 12000);
  results.hidden = true;
  status.textContent = text.loading;
  submit.disabled = true;
  try {
    const response = await fetch(`${API}/api/weather?location=${encodeURIComponent(location.trim())}`, {
      headers: { Accept: "application/json" }, signal: activeController.signal
    });
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) throw new Error(text.backendUnavailable);
    const payload = await response.json();
    if (response.status === 404 && !payload.code) throw new Error(text.backendUnavailable);
    if (!response.ok || !payload.success) throw new Error(payload.error || text.unavailable);
    renderWeather(payload);
  } catch (error) {
    if (error.name !== "AbortError" || !document.getElementById("weatherOverlay").hidden) {
      status.textContent = error.name === "AbortError" ? text.unavailable : (error.message || text.unavailable);
    }
  } finally {
    window.clearTimeout(timeout);
    submit.disabled = false;
    if (weatherRequestController === activeController) weatherRequestController = null;
  }
}

function initializeWeather() {
  document.getElementById("weatherForm").addEventListener("submit", (event) => {
    event.preventDefault();
    loadWeather(document.getElementById("weatherLocation").value);
  });
  document.getElementById("weatherOverlay").addEventListener("click", (event) => {
    if (event.target.id === "weatherOverlay") closeWeatherPanel();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.getElementById("weatherOverlay").hidden) closeWeatherPanel();
  });
}

function initApp(isReturning) {
  document.getElementById("userBadge").textContent = "👤 " + currentUser;
  document
    .getElementById("chatInput")
    .addEventListener("input", updateCharCount);
  document.getElementById("chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSend();
    }
  });

  setLanguageUI(currentLang);
  updateSuggestions();

  // Always start with a new session for this visit
  enSessionId = generateId();
  twSessionId = generateId();

  renderWelcome(isReturning);
  loadSidebarHistory();
}

window.onload = function () {
  initializeTheme();
  initializeWeather();
  initializeSpeechSynthesis();
  initializeSpeechRecognition();
  const lastUser = localStorage.getItem(STORAGE_KEY_CURRENT);
  if (lastUser) {
    const profile = getUserProfile(lastUser);
    if (profile) {
      // Auto-login the last user
      currentUser = profile.displayName;
      currentLang = profile.lang || "en";
      document.getElementById("welcomeScreen").style.display = "none";
      document.getElementById("appShell").style.display = "flex";
      document.getElementById("appShell").style.flexDirection = "column";
      initApp(true);
      return;
    }
  }
  // Show welcome screen for new visitor
  document.getElementById("welcomeScreen").style.display = "flex";
  document.getElementById("appShell").style.display = "none";
};

// ══════════════════════════════════════════════════════════════════
// SESSION HELPERS
// ══════════════════════════════════════════════════════════════════

function generateId() {
  return "sess_" + Date.now() + "_" + Math.random().toString(36).substr(2, 8);
}

function getCurrentSessionId() {
  return currentLang === "en" ? enSessionId : twSessionId;
}

function getWelcomeText(isReturning) {
  if (currentLang === "en") {
    return isReturning
      ? `Welcome back, ${currentUser}! 🌱 Great to see you again. Ask me anything about crops, soil, pests, livestock or fish farming.`
      : `Hello ${currentUser}! 🌱 I am AgriBotGH, your bilingual farming assistant. Ask me anything about crops, soil, pests, livestock or fish farming in English or Twi!`;
  } else {
    return isReturning
      ? `Akwaaba bio, ${currentUser}! 🌱 Ɛyɛ me anigye sɛ mehuu wo bio. Bisa me nsɛmfua biara fa okuafo adwuma ho!`
      : `Akwaaba ${currentUser}! 🌱 Yɛfrɛ me AgriBotGH. Bisa me nsɛmfua biara ɛfa okuafo adwuma ho wɔ English anaa Twi!`;
  }
}

function renderWelcome(isReturning) {
  const msgs = document.getElementById("messages");
  msgs.innerHTML = "";
  const box = document.createElement("div");
  box.className = "welcome-bubble";
  box.textContent = getWelcomeText(isReturning || false);
  msgs.appendChild(box);
  scrollBottom();
}

// ══════════════════════════════════════════════════════════════════
// APPEND MESSAGE
// ══════════════════════════════════════════════════════════════════

function cleanTextForSpeech(text) {
  return String(text || "")
    .replace(/<[^>]*>/g, " ")
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/www\.\S+/g, " ")
    .replace(/!\[.*?\]\(.*?\)/g, " ")
    .replace(/\[(.*?)\]\((.*?)\)/g, "$1")
    .replace(/[#*_>`]/g, " ")
    .replace(/(^|\s)[•·‣◦\-*]\s*/g, "$1")
    .replace(/^#+\s*/gm, "")
    .replace(/\n+/g, " ")
    .replace(/\s{2,}/g, " ")
    .replace(/[\u{1F300}-\u{1FAFF}]/gu, " ")
    .replace(/[\uFE0E\uFE0F]/g, "")
    .trim();
}

function supportsSpeechSynthesis() {
  return (
    "speechSynthesis" in window &&
    "SpeechSynthesisUtterance" in window &&
    typeof window.speechSynthesis.getVoices === "function" &&
    typeof window.speechSynthesis.speak === "function" &&
    typeof window.speechSynthesis.cancel === "function"
  );
}

function refreshSpeechVoices() {
  if (!supportsSpeechSynthesis()) {
    availableSpeechVoices = [];
    return availableSpeechVoices;
  }
  try {
    availableSpeechVoices = window.speechSynthesis.getVoices() || [];
  } catch (_error) {
    availableSpeechVoices = [];
  }
  return availableSpeechVoices;
}

function initializeSpeechSynthesis() {
  if (!supportsSpeechSynthesis()) return;
  refreshSpeechVoices();
  if (speechVoiceListenerRegistered) return;
  const synth = window.speechSynthesis;
  if (typeof synth.addEventListener === "function") {
    synth.addEventListener("voiceschanged", refreshSpeechVoices);
  } else {
    synth.onvoiceschanged = refreshSpeechVoices;
  }
  speechVoiceListenerRegistered = true;
}

function getSpeechRecognitionConstructor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function supportsSpeechRecognition() {
  return typeof getSpeechRecognitionConstructor() === "function";
}

function setSpeechRecognitionStatus(message = "", visible = Boolean(message)) {
  const status = document.getElementById("sttStatus");
  if (!status) return;
  status.textContent = message;
  status.hidden = !visible;
}

function setMicrophoneButtonState(state = "idle") {
  const button = document.getElementById("micBtn");
  if (!button) return;

  const icon = button.querySelector(".mic-icon");
  const label = button.querySelector(".mic-label");
  const stateLabels = {
    idle: "Speak",
    listening: "Stop",
    stopping: "Stopping...",
  };
  const isActive = state === "listening" || state === "stopping";
  if (icon) icon.textContent = isActive ? "⏹" : "🎤";
  if (label) label.textContent = stateLabels[state] || stateLabels.idle;
  button.dataset.state = state;
  button.classList.toggle("is-listening", isActive);
  button.disabled = state === "stopping";
  button.setAttribute("aria-pressed", isActive ? "true" : "false");
  button.setAttribute(
    "aria-label",
    state === "listening"
      ? "Stop listening"
      : state === "stopping"
        ? "Stopping voice input"
        : "Speak your question",
  );
}

function updateSpeechRecognitionAvailability({ clearStatus = true } = {}) {
  const button = document.getElementById("micBtn");
  if (!button || activeRecognition) return;

  setMicrophoneButtonState("idle");
  if (!supportsSpeechRecognition()) {
    button.disabled = true;
    button.title = "Voice input is not supported in this browser. You can still type your question.";
    setSpeechRecognitionStatus(
      "Voice input is not supported in this browser. Please type your question.",
      true,
    );
    return;
  }

  if (currentLang === "tw") {
    button.disabled = true;
    button.title = "Twi voice input is not available in the browsers tested for this release. Please type your Twi question.";
    setSpeechRecognitionStatus(
      "Twi voice input is not available in the browsers tested for this release. Please type your Twi question.",
      true,
    );
    return;
  }

  button.disabled = false;
  button.title = "Speak your question";
  if (clearStatus) setSpeechRecognitionStatus("", false);
}

function speechRecognitionErrorMessage(errorCode) {
  const messages = {
    "not-allowed": "Microphone permission was denied. Please allow it in your browser or type your question.",
    "service-not-allowed": "Voice input is not allowed in this browser. Please type your question.",
    "audio-capture": "No working microphone was found. Please check your device or type your question.",
    "no-speech": "I couldn't hear a question. Please try again or type it.",
    network: "The browser's voice-recognition service is unavailable. Please try again or type your question.",
    aborted: "Voice input stopped. You can try again or type your question.",
    "language-not-supported": "English voice recognition is not available in this browser. Please type your question.",
  };
  return messages[errorCode] || "Voice input could not complete. Please try again or type your question.";
}

function initializeSpeechRecognition() {
  updateSpeechRecognitionAvailability();
}

function startSpeechRecognition() {
  if (activeRecognition || currentLang !== "en") {
    updateSpeechRecognitionAvailability({ clearStatus: false });
    return;
  }

  const Recognition = getSpeechRecognitionConstructor();
  if (typeof Recognition !== "function") {
    updateSpeechRecognitionAvailability({ clearStatus: false });
    return;
  }

  stopSpeech();
  const recognition = new Recognition();
  recognition.lang = "en-GH";
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  recognition.__hasResult = false;
  recognition.__hasError = false;
  recognition.__stopRequested = false;

  recognition.onstart = () => {
    if (activeRecognition !== recognition) return;
    setMicrophoneButtonState("listening");
    setSpeechRecognitionStatus("Listening... Speak one question, then review the text before sending.", true);
  };

  recognition.onresult = (event) => {
    if (activeRecognition !== recognition) return;
    const finalParts = [];
    const results = event && event.results ? Array.from(event.results) : [];
    for (const result of results) {
      if (result && result.isFinal !== false && result[0] && result[0].transcript) {
        finalParts.push(result[0].transcript);
      }
    }
    const transcript = finalParts.join(" ").replace(/\s+/g, " ").trim();
    if (!transcript) return;

    recognition.__hasResult = true;
    const input = document.getElementById("chatInput");
    const limit = Number(input.maxLength) > 0 ? Number(input.maxLength) : 2000;
    input.value = transcript.slice(0, limit);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
    setSpeechRecognitionStatus("Voice captured. Review or edit the question, then press Send.", true);
  };

  recognition.onerror = (event) => {
    if (activeRecognition !== recognition) return;
    recognition.__hasError = true;
    const errorCode = event && event.error ? event.error : "unknown";
    activeRecognition = null;
    setSpeechRecognitionStatus(speechRecognitionErrorMessage(errorCode), true);
    updateSpeechRecognitionAvailability({ clearStatus: false });
  };

  recognition.onend = () => {
    if (activeRecognition !== recognition) return;
    activeRecognition = null;
    if (!recognition.__hasResult && !recognition.__hasError) {
      setSpeechRecognitionStatus(
        recognition.__stopRequested
          ? "Voice input stopped. Review any captured text or try again."
          : "Listening ended without a question. Please try again or type it.",
        true,
      );
    }
    updateSpeechRecognitionAvailability({ clearStatus: false });
  };

  activeRecognition = recognition;
  setMicrophoneButtonState("listening");
  setSpeechRecognitionStatus("Starting microphone...", true);
  try {
    recognition.start();
  } catch (_error) {
    if (activeRecognition === recognition) activeRecognition = null;
    setSpeechRecognitionStatus(
      "The microphone could not start. Please try again or type your question.",
      true,
    );
    updateSpeechRecognitionAvailability({ clearStatus: false });
  }
}

function stopSpeechRecognition({ abort = false, clearStatus = false } = {}) {
  const recognition = activeRecognition;
  if (!recognition) {
    if (clearStatus) setSpeechRecognitionStatus("", false);
    updateSpeechRecognitionAvailability({ clearStatus });
    return;
  }

  if (abort) {
    activeRecognition = null;
  } else {
    recognition.__stopRequested = true;
    setMicrophoneButtonState("stopping");
  }

  try {
    if (abort && typeof recognition.abort === "function") recognition.abort();
    else if (typeof recognition.stop === "function") recognition.stop();
  } catch (_error) {
    if (activeRecognition === recognition) activeRecognition = null;
  }

  if (abort) {
    if (clearStatus) setSpeechRecognitionStatus("", false);
    updateSpeechRecognitionAvailability({ clearStatus });
  }
}

function toggleSpeechRecognition() {
  if (activeRecognition) {
    stopSpeechRecognition();
    return;
  }
  startSpeechRecognition();
}

function isVoiceSuitableForLanguage(voice, lang = "en") {
  if (!voice) return false;
  const target = String(lang || "en").toLowerCase();
  const voiceLang = String(voice.lang || "").toLowerCase();
  const primaryTag = voiceLang.split("-")[0];
  if (target === "tw") {
    return ["tw", "ak"].includes(primaryTag) || /twi|akan/i.test(voice.name || "");
  }
  return primaryTag === "en";
}

function getSpeechVoice(lang = "en") {
  if (!supportsSpeechSynthesis()) return null;
  const voices = availableSpeechVoices.length
    ? availableSpeechVoices
    : refreshSpeechVoices();
  if (!voices.length) return null;

  const target = String(lang || "en").toLowerCase();
  const preferred = voices.find((voice) =>
    isVoiceSuitableForLanguage(voice, target),
  );
  if (preferred) return preferred;

  if (target === "tw") {
    const fallback = voices.find((voice) =>
      /en/.test(voice.lang.toLowerCase()),
    );
    if (fallback) return fallback;
  }

  return (
    voices.find((voice) => /en/.test(voice.lang.toLowerCase())) || voices[0]
  );
}

function setTtsStatus(controlRow, message, visible = true) {
  const statusEl = controlRow.querySelector(".tts-status");
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.hidden = !visible;
  statusEl.classList.toggle(
    "is-neutral",
    /^(Preparing|Speaking|Paused)/.test(message),
  );
}

function updateTtsButton(button, state) {
  if (!button) return;
  button.dataset.state = state;
  const labelMap = {
    idle: "🔊 Listen",
    preparing: "Preparing...",
    playing: "⏸ Pause",
    paused: "▶ Resume",
    error: "⚠️ Audio",
  };
  const accessibleLabelMap = {
    idle: "Listen to this response",
    preparing: "Preparing natural Twi audio",
    playing: "Pause this response",
    paused: "Resume this response",
    error: "Audio is unavailable for this response",
  };
  button.textContent = labelMap[state] || labelMap.idle;
  button.setAttribute(
    "aria-label",
    accessibleLabelMap[state] || accessibleLabelMap.idle,
  );
  button.classList.toggle("is-playing", state === "playing");
  button.classList.toggle("is-paused", state === "paused");
  button.disabled = state === "preparing" || state === "error";

  const controls = button.closest(".tts-controls");
  if (!controls) return;
  const stopBtn = controls.querySelector(".tts-stop");
  if (stopBtn) {
    stopBtn.hidden = state === "idle" || state === "error";
  }
}

function clearActiveSpeechState() {
  activeSpeech.button = null;
  activeSpeech.utterance = null;
  activeSpeech.audio = null;
  activeSpeech.controller = null;
  activeSpeech.clips = [];
  activeSpeech.clipIndex = 0;
  activeSpeech.engine = null;
  activeSpeech.isPlaying = false;
  activeSpeech.isPaused = false;
  activeSpeech.lang = "en";
}

function stopSpeech(resetButton = true) {
  const previousButton = activeSpeech.button;
  const previousAudio = activeSpeech.audio;
  const previousController = activeSpeech.controller;
  activeSpeech.requestId += 1;
  clearActiveSpeechState();

  if (previousController) {
    try {
      previousController.abort();
    } catch (_error) {
      // Cancellation is best-effort; reset the UI regardless.
    }
  }
  if (previousAudio) {
    previousAudio.onended = null;
    previousAudio.onerror = null;
    try {
      previousAudio.pause();
      previousAudio.removeAttribute("src");
      previousAudio.load();
    } catch (_error) {
      // Text remains readable if media cancellation is unavailable.
    }
  }

  if (previousButton && resetButton) {
    const controls = previousButton.closest(".tts-controls");
    updateTtsButton(previousButton, "idle");
    if (controls) setTtsStatus(controls, "", false);
  }

  if (supportsSpeechSynthesis()) {
    try {
      window.speechSynthesis.cancel();
    } catch (_error) {
      // Text chat remains usable if a browser speech engine fails to cancel.
    }
  }
}

function setTtsUnavailable(button, controls) {
  setTtsStatus(
    controls,
    "Audio is currently unavailable. You can still read the response above.",
    true,
  );
  updateTtsButton(button, "error");
  clearActiveSpeechState();
}

function startBrowserSpeech(button, cleanText, lang = "en", statusOverride = "") {
  const controls = button.closest(".tts-controls");
  if (!controls) return;
  if (!supportsSpeechSynthesis()) {
    setTtsUnavailable(button, controls);
    return;
  }

  const voice = getSpeechVoice(lang);
  const usesFallbackVoice =
    lang === "tw" && !isVoiceSuitableForLanguage(voice, "tw");
  const speakingStatus = statusOverride || (usesFallbackVoice
    ? "No Twi/Akan voice is installed. Using a fallback voice; Twi pronunciation may be inaccurate."
    : "Speaking...");
  const utterance = new SpeechSynthesisUtterance(cleanText);
  utterance.lang = voice ? voice.lang : lang === "tw" ? "tw-GH" : "en-GH";
  utterance.voice = voice;
  utterance.rate = 1;
  utterance.pitch = 1;
  utterance.volume = 1;

  utterance.onstart = () => {
    if (activeSpeech.utterance !== utterance) return;
    activeSpeech.button = button;
    activeSpeech.utterance = utterance;
    activeSpeech.engine = "browser";
    activeSpeech.lang = lang;
    activeSpeech.isPlaying = true;
    activeSpeech.isPaused = false;
    updateTtsButton(button, "playing");
    setTtsStatus(controls, speakingStatus, true);
  };

  utterance.onpause = () => {
    if (activeSpeech.utterance !== utterance) return;
    activeSpeech.isPlaying = false;
    activeSpeech.isPaused = true;
    updateTtsButton(button, "paused");
    setTtsStatus(controls, "Paused", true);
  };

  utterance.onresume = () => {
    if (activeSpeech.utterance !== utterance) return;
    activeSpeech.isPlaying = true;
    activeSpeech.isPaused = false;
    updateTtsButton(button, "playing");
    setTtsStatus(controls, speakingStatus, true);
  };

  utterance.onend = () => {
    if (activeSpeech.utterance !== utterance) return;
    updateTtsButton(button, "idle");
    setTtsStatus(controls, "", false);
    clearActiveSpeechState();
  };

  utterance.onerror = (event) => {
    if (activeSpeech.utterance !== utterance) return;
    const reason = event && event.error ? event.error : "unknown";
    if (["canceled", "interrupted"].includes(reason)) {
      updateTtsButton(button, "idle");
      setTtsStatus(controls, "", false);
      clearActiveSpeechState();
      return;
    }
    setTtsStatus(
      controls,
      `Audio is currently unavailable. You can still read the response above. (${reason})`,
      true,
    );
    updateTtsButton(button, "error");
    clearActiveSpeechState();
  };

  activeSpeech.button = button;
  activeSpeech.utterance = utterance;
  activeSpeech.engine = "browser";
  activeSpeech.lang = lang;
  activeSpeech.isPlaying = false;
  activeSpeech.isPaused = false;

  try {
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  } catch (_error) {
    setTtsUnavailable(button, controls);
  }
}

function fallbackToBrowserSpeech(button, cleanText, requestId) {
  if (
    activeSpeech.requestId !== requestId ||
    activeSpeech.button !== button ||
    !["preparing", "abena"].includes(activeSpeech.engine)
  ) return;
  if (activeSpeech.audio) {
    activeSpeech.audio.onended = null;
    activeSpeech.audio.onerror = null;
    try {
      activeSpeech.audio.pause();
    } catch (_error) {
      // Continue to the browser fallback.
    }
  }
  activeSpeech.controller = null;
  activeSpeech.audio = null;
  activeSpeech.clips = [];
  activeSpeech.clipIndex = 0;
  activeSpeech.engine = "fallback";
  startBrowserSpeech(
    button,
    cleanText,
    "tw",
    "Natural Twi voice is unavailable. Using browser fallback; pronunciation may be inaccurate.",
  );
}

function playAbenaClip(button, cleanText, requestId) {
  if (
    activeSpeech.requestId !== requestId ||
    activeSpeech.button !== button ||
    activeSpeech.engine !== "abena"
  ) return;
  const controls = button.closest(".tts-controls");
  if (!controls) return;
  if (activeSpeech.clipIndex >= activeSpeech.clips.length) {
    updateTtsButton(button, "idle");
    setTtsStatus(controls, "", false);
    clearActiveSpeechState();
    return;
  }

  const clip = activeSpeech.clips[activeSpeech.clipIndex];
  const audio = new Audio(`data:${clip.mime_type};base64,${clip.audio_base64}`);
  activeSpeech.audio = audio;
  audio.onended = () => {
    if (activeSpeech.requestId !== requestId || activeSpeech.audio !== audio) return;
    activeSpeech.clipIndex += 1;
    activeSpeech.audio = null;
    playAbenaClip(button, cleanText, requestId);
  };
  audio.onerror = () => {
    if (activeSpeech.requestId !== requestId || activeSpeech.audio !== audio) return;
    audio.onended = null;
    audio.onerror = null;
    fallbackToBrowserSpeech(button, cleanText, requestId);
  };

  activeSpeech.isPlaying = true;
  activeSpeech.isPaused = false;
  updateTtsButton(button, "playing");
  setTtsStatus(controls, "Speaking with a natural Twi voice...", true);
  try {
    const playResult = audio.play();
    if (playResult && typeof playResult.catch === "function") {
      playResult.catch(() => {
        if (activeSpeech.requestId !== requestId || activeSpeech.audio !== audio) return;
        fallbackToBrowserSpeech(button, cleanText, requestId);
      });
    }
  } catch (_error) {
    fallbackToBrowserSpeech(button, cleanText, requestId);
  }
}

async function startAbenaTwiSpeech(button, cleanText) {
  const controls = button.closest(".tts-controls");
  if (!controls) return;
  const controller = new AbortController();
  const requestId = activeSpeech.requestId + 1;
  activeSpeech.requestId = requestId;
  activeSpeech.button = button;
  activeSpeech.controller = controller;
  activeSpeech.engine = "preparing";
  activeSpeech.lang = "tw";
  updateTtsButton(button, "preparing");
  setTtsStatus(controls, "Preparing natural Twi audio...", true);

  try {
    const response = await fetch(`${API}/api/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: cleanText, language: "twi" }),
      signal: controller.signal,
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = null;
    }
    if (
      activeSpeech.requestId !== requestId ||
      activeSpeech.button !== button ||
      controller.signal.aborted
    ) return;
    const clips = payload && Array.isArray(payload.clips) ? payload.clips : [];
    const validClips = clips.length > 0 && clips.every((clip) =>
      clip &&
      typeof clip.audio_base64 === "string" &&
      clip.audio_base64.length > 0 &&
      typeof clip.mime_type === "string" &&
      clip.mime_type.startsWith("audio/")
    );
    if (!response.ok || !payload || payload.success !== true || !validClips) {
      fallbackToBrowserSpeech(button, cleanText, requestId);
      return;
    }
    activeSpeech.controller = null;
    activeSpeech.engine = "abena";
    activeSpeech.clips = clips;
    activeSpeech.clipIndex = 0;
    playAbenaClip(button, cleanText, requestId);
  } catch (error) {
    if (
      (error && error.name === "AbortError") ||
      activeSpeech.requestId !== requestId ||
      controller.signal.aborted
    ) return;
    fallbackToBrowserSpeech(button, cleanText, requestId);
  }
}

function speakBotResponse(button, text, lang = "en") {
  stopSpeechRecognition({ abort: true, clearStatus: true });
  const controls = button.closest(".tts-controls");
  if (!controls) return;
  const cleanText = cleanTextForSpeech(text);
  if (!cleanText) {
    setTtsStatus(controls, "There is no spoken text available for this response.", true);
    return;
  }

  if (activeSpeech.button && activeSpeech.button !== button) stopSpeech(true);

  if (button.dataset.state === "playing") {
    if (activeSpeech.engine === "abena" && activeSpeech.audio) {
      activeSpeech.audio.pause();
    } else if (supportsSpeechSynthesis()) {
      window.speechSynthesis.pause();
    }
    activeSpeech.isPlaying = false;
    activeSpeech.isPaused = true;
    updateTtsButton(button, "paused");
    setTtsStatus(controls, "Paused", true);
    return;
  }

  if (button.dataset.state === "paused") {
    if (activeSpeech.engine === "abena" && activeSpeech.audio) {
      const resumed = activeSpeech.audio.play();
      if (resumed && typeof resumed.catch === "function") {
        const requestId = activeSpeech.requestId;
        resumed.catch(() => fallbackToBrowserSpeech(button, cleanText, requestId));
      }
    } else if (supportsSpeechSynthesis()) {
      window.speechSynthesis.resume();
    }
    activeSpeech.isPlaying = true;
    activeSpeech.isPaused = false;
    updateTtsButton(button, "playing");
    setTtsStatus(
      controls,
      activeSpeech.engine === "abena" ? "Speaking with a natural Twi voice..." : "Speaking...",
      true,
    );
    return;
  }

  if (lang === "tw") startAbenaTwiSpeech(button, cleanText);
  else startBrowserSpeech(button, cleanText, lang);
}

function appendMessage(text, role, messageLang = currentLang) {
  const msgs = document.getElementById("messages");
  const card = document.createElement("div");
  card.className = `message-card ${role}-message`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "bot") {
    const icon = document.createElement("span");
    icon.className = "msg-icon";
    icon.textContent = "🤖";
    bubble.appendChild(icon);
  }
  const span = document.createElement("span");
  span.textContent = text;
  bubble.appendChild(span);
  card.appendChild(bubble);

  if (role === "bot") {
    const controls = document.createElement("div");
    controls.className = "tts-controls";

    const playBtn = document.createElement("button");
    playBtn.type = "button";
    playBtn.className = "tts-button";
    playBtn.dataset.state = "idle";
    updateTtsButton(playBtn, "idle");
    playBtn.dataset.language = messageLang;
    if (!supportsSpeechSynthesis() && messageLang !== "tw") {
      playBtn.disabled = true;
      updateTtsButton(playBtn, "error");
      playBtn.title = "Browser speech synthesis is unavailable";
    } else if (messageLang === "tw") {
      playBtn.title =
        "Play with the natural Twi voice; browser speech remains available as a fallback";
    }
    playBtn.addEventListener("click", () => {
      speakBotResponse(playBtn, text, messageLang);
    });

    const stopBtn = document.createElement("button");
    stopBtn.type = "button";
    stopBtn.className = "tts-stop";
    stopBtn.textContent = "■ Stop";
    stopBtn.title = "Stop speech";
    stopBtn.setAttribute("aria-label", "Stop speaking this response");
    stopBtn.hidden = true;
    stopBtn.addEventListener("click", () => {
      stopSpeech();
    });

    const status = document.createElement("div");
    status.className = "tts-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.hidden = true;

    controls.appendChild(playBtn);
    controls.appendChild(stopBtn);
    controls.appendChild(status);
    card.appendChild(controls);
  }

  const ts = document.createElement("div");
  ts.className = "msg-time" + (role === "user" ? " right" : "");
  ts.textContent = getTime();
  card.appendChild(ts);

  msgs.appendChild(card);
  scrollBottom();
}

function showTyping() {
  const msgs = document.getElementById("messages");
  const card = document.createElement("div");
  card.className = "message-card bot-message";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const dots = document.createElement("div");
  dots.className = "typing-bubble";
  dots.innerHTML = "<span></span><span></span><span></span>";
  bubble.appendChild(dots);
  card.appendChild(bubble);
  msgs.appendChild(card);
  scrollBottom();
  return card;
}

// ══════════════════════════════════════════════════════════════════
// SIDEBAR HISTORY — shows only THIS user's chats
// ══════════════════════════════════════════════════════════════════

function loadSidebarHistory() {
  const all = getAllUsers();
  const key = currentUser.trim().toLowerCase();
  const profile = all[key];

  const enList = document.getElementById("enHistory");
  const twList = document.getElementById("twHistory");

  if (!profile || !profile.sessions) {
    enList.innerHTML = '<p class="history-empty">None yet</p>';
    twList.innerHTML = '<p class="history-empty">None yet</p>';
    return;
  }

  const sessions = Object.values(profile.sessions).sort(
    (a, b) => b.createdAt - a.createdAt,
  );

  const enSessions = sessions.filter((s) => s.lang === "en");
  const twSessions = sessions.filter((s) => s.lang === "tw");

  function render(list, container, activeSessId) {
    container.innerHTML = "";
    if (list.length === 0) {
      container.innerHTML = '<p class="history-empty">None yet</p>';
      return;
    }
    list.forEach((sess) => {
      const item = document.createElement("div");
      item.className =
        "history-item" + (sess.id === activeSessId ? " active" : "");
      item.textContent = sess.title;
      item.title = sess.title;
      item.onclick = () => loadSession(sess.id, sess.lang);
      container.appendChild(item);
    });
  }

  render(enSessions, enList, enSessionId);
  render(twSessions, twList, twSessionId);
}

function loadSession(sessId, lang) {
  const all = getAllUsers();
  const key = currentUser.trim().toLowerCase();
  const profile = all[key];
  if (!profile) return;

  const sess = profile.sessions[sessId];
  if (!sess) return;
  stopSpeechRecognition({ abort: true, clearStatus: true });
  stopSpeech();

  // Switch language UI if needed
  if (lang !== currentLang) {
    currentLang = lang;
    setLanguageUI(lang);
  }

  // Mark as current session
  if (lang === "en") enSessionId = sessId;
  else twSessionId = sessId;

  // Render messages
  const msgs = document.getElementById("messages");
  msgs.innerHTML = "";
  sess.messages.forEach((msg) => appendMessage(msg.text, msg.role, sess.lang));
  loadSidebarHistory();
}

// ══════════════════════════════════════════════════════════════════
// LANGUAGE SWITCH
// ══════════════════════════════════════════════════════════════════

function switchLanguage(lang) {
  if (lang === currentLang) return;
  stopSpeechRecognition({ abort: true, clearStatus: true });
  stopSpeech();
  currentLang = lang;
  updateUserProfile(currentUser, { lang });
  setLanguageUI(lang);

  // Give this language a fresh session if it doesn't have one yet
  if (lang === "en" && !enSessionId) enSessionId = generateId();
  if (lang === "tw" && !twSessionId) twSessionId = generateId();

  renderWelcome(false);
  loadSidebarHistory();
}

function setLanguageUI(lang) {
  updateWeatherLanguage();
  document.getElementById("enBtn").classList.toggle("active", lang === "en");
  document.getElementById("twBtn").classList.toggle("active", lang === "tw");
  document.getElementById("langIndicator").innerHTML =
    `Chatting in: <strong>${lang === "en" ? "English" : "Twi"}</strong>`;
  document.getElementById("chatInput").placeholder =
    lang === "en"
      ? "Type your farming question here..."
      : "Kyerɛ wo asemmisa ha...";
  document.getElementById("enChips").style.display =
    lang === "en" ? "flex" : "none";
  updateSpeechRecognitionAvailability();
  document.getElementById("twChips").style.display =
    lang === "tw" ? "flex" : "none";
  updateQuickQuestions();
  updateSuggestions();
  const topicsPanel = document.getElementById("topicsPanel");
  if (topicsPanel && topicsPanel.classList.contains("show")) {
    loadTopicsPanel();
  }
}

// ══════════════════════════════════════════════════════════════════
// CLEAR & NEW CHAT
// ══════════════════════════════════════════════════════════════════

function clearChat() {
  stopSpeechRecognition({ abort: true, clearStatus: true });
  stopSpeech();
  if (currentLang === "en") enSessionId = generateId();
  else twSessionId = generateId();
  renderWelcome(false);
  loadSidebarHistory();
}

function newChat() {
  clearChat();
}

// ══════════════════════════════════════════════════════════════════
// CHIPS (QUICK QUESTIONS)
// ══════════════════════════════════════════════════════════════════

function fillChip(el) {
  submitQuestion(el.textContent.trim());
}

const quickQuestionsData = {};

function updateQuickQuestions() {
  const language = currentLang === "tw" ? "tw" : "en";
  const container = document.getElementById(`${language}Chips`);
  if (!container) return;

  const render = (suggestions) => {
    container.innerHTML = "";
    suggestions.forEach((suggestion) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = suggestion.text;
      button.addEventListener("click", () => submitQuestion(suggestion.text));
      container.appendChild(button);
    });
  };

  if (quickQuestionsData[language]) {
    render(quickQuestionsData[language]);
    return;
  }
  fetch(`${API}/api/quick-suggestions?lang=${encodeURIComponent(language)}`)
    .then((response) => {
      if (!response.ok) throw new Error("Could not load quick questions");
      return response.json();
    })
    .then((data) => {
      quickQuestionsData[language] = data.suggestions || [];
      render(quickQuestionsData[language]);
    })
    .catch(() => {
      container.innerHTML = "";
    });
}

function fillHelpExample(text) {
  document.getElementById("chatInput").value = text;
  updateCharCount();
  document.getElementById("chatInput").focus();
}

function toggleChips() {
  // prevent rapid double toggles
  if (chipsToggleLock) return;
  chipsToggleLock = true;
  setTimeout(() => (chipsToggleLock = false), 300);
  const sidebar = document.getElementById("chipsSidebar");
  const topicsPanel = document.getElementById("topicsPanel");
  const overlay = document.getElementById("overlay");
  const topicBtn = document.querySelector(".topic-toggle-btn");
  if (window.innerWidth > 768) {
    const hidden = sidebar.classList.toggle("desktop-hidden");
    document.body.classList.toggle("chips-collapsed", hidden);
    overlay.classList.remove("show");
    return;
  }
  // visual debounce state to give immediate feedback
  if (topicBtn) {
    topicBtn.classList.add("debounced");
    // mark temporarily disabled for assistive tech
    topicBtn.setAttribute("aria-disabled", "true");
    setTimeout(() => {
      topicBtn.classList.remove("debounced");
      topicBtn.removeAttribute("aria-disabled");
    }, 350);
  }
  const opened = sidebar.classList.toggle("show");
  if (opened) {
    // Close topics panel if it's open
    topicsPanel.classList.remove("show");
    overlay.classList.add("show");
    if (topicBtn) {
      topicBtn.classList.add("hidden");
      topicBtn.setAttribute("aria-expanded", "true");
      topicBtn.setAttribute("aria-hidden", "true");
      topicBtn.setAttribute("aria-disabled", "true");
      topicBtn.setAttribute("tabindex", "-1");
    }
    if (window.innerWidth <= 768) {
      document.getElementById("sidebar").classList.remove("mobile-open");
    }
  } else {
    overlay.classList.remove("show");
    if (topicBtn) {
      topicBtn.classList.remove("hidden");
      topicBtn.setAttribute("aria-expanded", "false");
      topicBtn.removeAttribute("aria-hidden");
      topicBtn.removeAttribute("aria-disabled");
      topicBtn.removeAttribute("tabindex");
    }
  }
}

function closeChips() {
  const sidebar = document.getElementById("chipsSidebar");
  const overlay = document.getElementById("overlay");
  const topicBtn = document.querySelector(".topic-toggle-btn");

  if (window.innerWidth > 768) {
    sidebar.classList.add("desktop-hidden");
    document.body.classList.add("chips-collapsed");
  } else {
    sidebar.classList.remove("show");
  }
  overlay.classList.remove("show");
  if (topicBtn) {
    topicBtn.classList.remove("hidden", "debounced");
    topicBtn.setAttribute("aria-expanded", "false");
    topicBtn.removeAttribute("aria-hidden");
    topicBtn.removeAttribute("aria-disabled");
    topicBtn.removeAttribute("tabindex");
  }
}

// ══════════════════════════════════════════════════════════════════
// THEME
// ══════════════════════════════════════════════════════════════════

function toggleTheme() {
  const theme = isDarkTheme ? "light" : "dark";
  localStorage.setItem(STORAGE_KEY_THEME, theme);
  applyTheme(theme);
}

function getStoredThemePreference() {
  const preference = localStorage.getItem(STORAGE_KEY_THEME);
  return preference === "dark" || preference === "light" ? preference : null;
}

function getAutomaticTheme(date = new Date()) {
  if (typeof window.matchMedia === "function") {
    return window.matchMedia(DARK_THEME_QUERY).matches ? "dark" : "light";
  }
  const hour = date.getHours();
  return hour >= 19 || hour < 6 ? "dark" : "light";
}

function applyTheme(theme) {
  isDarkTheme = theme === "dark";
  if (isDarkTheme) document.body.dataset.theme = "night";
  else delete document.body.dataset.theme;

  const button = document.getElementById("themeBtn");
  if (button) {
    const target = isDarkTheme ? "light" : "dark";
    button.textContent = isDarkTheme ? "☀️" : "🌙";
    button.title = `Switch to ${target} theme`;
    button.setAttribute("aria-label", `Switch to ${target} theme`);
    button.setAttribute("aria-pressed", String(isDarkTheme));
    button.dataset.currentTheme = isDarkTheme ? "dark" : "light";
  }
}

function handleSystemThemeChange(event) {
  if (getStoredThemePreference() === null) {
    applyTheme(event.matches ? "dark" : "light");
  }
}

function initializeTheme() {
  const explicitPreference = getStoredThemePreference();
  applyTheme(explicitPreference || getAutomaticTheme());
  if (typeof window.matchMedia !== "function") return;

  systemThemeMedia = window.matchMedia(DARK_THEME_QUERY);
  if (typeof systemThemeMedia.addEventListener === "function") {
    systemThemeMedia.addEventListener("change", handleSystemThemeChange);
  } else if (typeof systemThemeMedia.addListener === "function") {
    systemThemeMedia.addListener(handleSystemThemeChange);
  }
}

// ══════════════════════════════════════════════════════════════════
// SIDEBAR MOBILE
// ══════════════════════════════════════════════════════════════════

function toggleSidebar() {
  if (sidebarToggleLock) return;
  sidebarToggleLock = true;
  setTimeout(() => (sidebarToggleLock = false), 300);

  const sidebar = document.getElementById("sidebar");
  const overlay = document.getElementById("overlay");
  const isOpen = sidebar.classList.toggle("mobile-open");
  overlay.classList.toggle("show", isOpen);
}

function toggleSidebarCollapse() {
  const sidebar = document.getElementById("sidebar");
  const isCollapsed = sidebar.classList.toggle("collapsed");
  const toggleBtn = document.getElementById("desktopSidebarToggle");
  if (toggleBtn) {
    toggleBtn.textContent = isCollapsed ? "⟩" : "⟨";
    toggleBtn.setAttribute(
      "aria-label",
      isCollapsed ? "Expand sidebar" : "Collapse sidebar",
    );
  }
}

function closeSidebar() {
  document.getElementById("sidebar").classList.remove("mobile-open");
  document.getElementById("overlay").classList.remove("show");
  document.getElementById("chipsSidebar").classList.remove("show");
  document.getElementById("topicsPanel").classList.remove("show");
  const topicBtn = document.querySelector(".topic-toggle-btn");
  if (topicBtn) topicBtn.classList.remove("hidden");
  if (topicBtn) topicBtn.classList.remove("debounced");
  if (topicBtn) {
    topicBtn.setAttribute("aria-expanded", "false");
    topicBtn.removeAttribute("aria-hidden");
    topicBtn.removeAttribute("aria-disabled");
    topicBtn.removeAttribute("tabindex");
  }
}

// ══════════════════════════════════════════════════════════════════
// TOPICS PANEL
// ══════════════════════════════════════════════════════════════════

let topicsPanelToggleLock = false;

// Topic metadata is loaded from Flask; suggestion text comes from canonical
// record links returned by /api/topic-suggestions.
let topicsData = null;
let topicsRequest = null;

function fetchTopicsData() {
  if (topicsData) return Promise.resolve(topicsData);
  if (topicsRequest) return topicsRequest;

  topicsRequest = fetch(`${API}/api/topics`)
    .then((response) => {
      if (!response.ok) throw new Error("Could not load topics");
      return response.json();
    })
    .then((data) => {
      if (!data || typeof data !== "object" || Array.isArray(data)) {
        throw new Error("Invalid topics response");
      }
      topicsData = data;
      return topicsData;
    })
    .finally(() => {
      topicsRequest = null;
    });

  return topicsRequest;
}
function toggleTopicsPanel() {
  if (topicsPanelToggleLock) return;
  topicsPanelToggleLock = true;
  setTimeout(() => (topicsPanelToggleLock = false), 300);

  const panel = document.getElementById("topicsPanel");
  const overlay = document.getElementById("overlay");
  const topicBtn = document.querySelector(".topic-toggle-btn");

  const opened = panel.classList.toggle("show");

  if (opened) {
    loadTopicsPanel();
    overlay.classList.add("show");
    if (topicBtn) {
      topicBtn.setAttribute("aria-expanded", "true");
    }
    if (window.innerWidth <= 768) {
      document.getElementById("sidebar").classList.remove("mobile-open");
    }
  } else {
    overlay.classList.remove("show");
    if (topicBtn) {
      topicBtn.setAttribute("aria-expanded", "false");
    }
  }
}

function closeTopicsPanel() {
  document.getElementById("topicsPanel").classList.remove("show");
  document.getElementById("overlay").classList.remove("show");
  const topicBtn = document.querySelector(".topic-toggle-btn");
  if (topicBtn) topicBtn.setAttribute("aria-expanded", "false");
}

async function loadTopicsPanel() {
  const gridPanel = document.getElementById("topicsGridPanel");
  gridPanel.textContent = currentLang === "tw" ? "Yɛretwe nsɛmti…" : "Loading topics…";

  try {
    const catalogue = await fetchTopicsData();
    gridPanel.innerHTML = "";
    Object.entries(catalogue).forEach(([topic, data]) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "topic-btn";
      btn.dataset.topic = topic;
      const displayName = currentLang === "tw" ? data.tw_name || topic : topic;

      const icon = document.createElement("span");
      icon.className = "topic-icon";
      icon.textContent = data.icon || "🌱";
      const name = document.createElement("span");
      name.className = "topic-name";
      name.textContent = displayName;
      btn.append(icon, name);
      btn.setAttribute("aria-label", displayName);
      btn.onclick = () => selectTopicFromPanel(topic);
      gridPanel.appendChild(btn);
    });
  } catch (error) {
    gridPanel.innerHTML = "";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "topic-btn";
    retry.textContent =
      currentLang === "tw"
        ? "Yɛantumi antwe nsɛmti no. San sɔ hwɛ."
        : "Topics could not be loaded. Try again.";
    retry.onclick = loadTopicsPanel;
    gridPanel.appendChild(retry);
  }
}

function selectTopicFromPanel(topic) {
  const data = topicsData && topicsData[topic];
  if (!data) return;

  const displayName = currentLang === "tw" ? data.tw_name || topic : topic;
  const icon = data.icon || "🌱";

  // Close the panel
  document.getElementById("topicsPanel").classList.remove("show");
  document.getElementById("overlay").classList.remove("show");
  const topicBtn = document.querySelector(".topic-toggle-btn");
  if (topicBtn) topicBtn.setAttribute("aria-expanded", "false");

  // Show user message
  const userMsg = `${icon} ${displayName}`;
  appendMessage(userMsg, "user");

  // Show follow-up
  const followUp =
    currentLang === "tw"
      ? `Wapaw **${icon} ${displayName}**.\n\nDɛn na wopɛ sɛ wonim? Asɛmmisa bi a wotumi bisa:`
      : `You selected **${icon} ${displayName}**.\n\nWhat would you like to know? Here are some ideas:`;
  appendMessage(followUp, "bot");

  // Fetch backend-linked suggestions so every button carries a stable record ID.
  fetch(`${API}/api/topic-suggestions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, lang: currentLang }),
  })
    .then((response) => {
      if (!response.ok) throw new Error("Could not load topic suggestions");
      return response.json();
    })
    .then((responseData) => appendSuggestionButtons(responseData.suggestions, topic))
    .catch(() => {
      appendMessage(
        currentLang === "tw"
          ? "Yɛantumi antwe asɛmmisa no amma. Yɛsrɛ wo san sɔ hwɛ."
          : "The suggested questions could not be loaded. Please try again.",
        "bot",
      );
    });
}

function updateSuggestions() {
  const list = document.getElementById("suggestionsList");
  const bar = document.getElementById("suggestionsBar");
  if (!list || !bar) return;

  list.innerHTML = "";

  const render = (suggestions) => {
    list.innerHTML = "";
    if (suggestions.length === 0) {
      bar.style.display = "none";
      return;
    }
    bar.style.display = "flex";
    suggestions.slice(0, 3).forEach((suggestion) => {
      const text = typeof suggestion === "string" ? suggestion : suggestion.text;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "suggestion-pill";
      btn.textContent = text;
      btn.addEventListener("click", () => submitQuestion(text));
      list.appendChild(btn);
    });
  };

  fetch(`${API}/api/topic-suggestions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic: "Maize", lang: currentLang }),
  })
    .then((response) => {
      if (!response.ok) throw new Error("Could not load starter suggestions");
      return response.json();
    })
    .then((data) => render(data.suggestions || []))
    .catch(() => render([]));
}

// ══════════════════════════════════════════════════════════════════
// UTILS
// ══════════════════════════════════════════════════════════════════

function getTime() {
  const now = new Date();
  let h = now.getHours();
  const m = now.getMinutes().toString().padStart(2, "0");
  const ap = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${h}:${m} ${ap}`;
}

function scrollBottom() {
  const msgs = document.getElementById("messages");
  msgs.scrollTop = msgs.scrollHeight;
}

function updateCharCount() {
  const len = document.getElementById("chatInput").value.length;
  document.getElementById("charCount").textContent = `${len}/2000`;
}

// ══════════════════════════════════════════════════════════════════
// SMART RESPONSE HANDLER
// Handles 5 response types from backend:
//   "answer"        — normal farming answer
//   "topics"        — show all topics grid (off-topic or vague)
//   "off_topic"     — not farming related, show topics
//   "low_confidence"— farming topic detected but no exact match
//   "knowledge_gap" — farming intent, but no reliable dataset answer
// ══════════════════════════════════════════════════════════════════

function handleSend() {
  return submitQuestion();
}

function submitQuestion(question = null) {
  const input = document.getElementById("chatInput");
  if (typeof question === "string") {
    input.value = question;
    updateCharCount();
  }
  stopSpeechRecognition({ abort: true, clearStatus: true });
  const text = input.value.trim();
  if (!text) return;
  stopSpeech();

  const requestLang = currentLang;
  appendMessage(text, "user", requestLang);
  input.value = "";
  updateCharCount();

  const typingEl = showTyping();
  const sessId = getCurrentSessionId();

  fetch(`${API}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: text,
      language: requestLang,
      session_id: sessId,
      username: currentUser,
    }),
  })
    .then(async (response) => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Request failed");
      if (data.language && data.language !== requestLang) {
        throw new Error("The server returned a response in the wrong language.");
      }
      return data;
    })
    .then((data) => {
      typingEl.remove();
      renderBotResponse(data, sessId, text, requestLang);
    })
    .catch((error) => {
      typingEl.remove();
      if (currentLang === requestLang && getCurrentSessionId() === sessId) {
        appendMessage(
          error.message ||
            "Sorry, the server is not responding. Please make sure the app is running.",
          "bot",
          requestLang,
        );
      }
    });
}

function renderBotResponse(data, sessId, userText, responseLang = currentLang) {
  const type = data.type || "answer";
  const botText = data.safety_notice
    ? `${data.text}\n\n${data.safety_notice}`
    : data.text;
  const isActiveSession =
    currentLang === responseLang && getCurrentSessionId() === sessId;

  saveSessionMessage(
    currentUser,
    sessId,
    responseLang,
    userText.length > 35 ? userText.substring(0, 35) + "..." : userText,
    userText,
    botText,
  );
  loadSidebarHistory();

  if (!isActiveSession) return;

  if (type === "answer") {
    // Normal answer
    appendMessage(botText, "bot", responseLang);
  } else if (type === "topics" || type === "off_topic") {
    // Show topic selection grid
    appendMessage(botText, "bot", responseLang);
    appendTopicsGrid(data.topics, data.topic_icons, data.topic_names_tw);
  } else if (type === "low_confidence") {
    // Topic detected but no exact match — show suggestions for that topic
    appendMessage(botText, "bot", responseLang);
    appendSuggestionButtons(data.suggestions, data.topic);
  } else if (type === "knowledge_gap") {
    appendMessage(botText, "bot", responseLang);
    appendKnowledgeGapTopics(
      data.available_topics,
      data.available_topic_icons,
      data.available_topic_names_tw,
      responseLang,
    );
  }
}

function appendKnowledgeGapTopics(topics, icons, twNames, responseLang) {
  const msgs = document.getElementById("messages");
  const wrapper = document.createElement("section");
  wrapper.className = "knowledge-gap-topics";
  wrapper.setAttribute("aria-label", "Supported agricultural topics");

  const heading = document.createElement("h3");
  heading.className = "knowledge-gap-heading";
  heading.textContent =
    responseLang === "tw"
      ? "Kuayɛ nsɛm a metumi aboa wo wɔ ho"
      : "Topics I can currently help with";

  const grid = document.createElement("div");
  grid.className = "topics-grid knowledge-gap-grid";

  (Array.isArray(topics) ? topics : []).forEach((topic) => {
    const displayName =
      responseLang === "tw" && twNames && twNames[topic]
        ? twNames[topic]
        : topic;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "topic-btn knowledge-gap-topic-btn";
    btn.dataset.topic = topic;
    btn.setAttribute(
      "aria-label",
      responseLang === "tw"
        ? `Fa ${displayName} hyɛ asɛmmisa no mu`
        : `Add ${displayName} to your question`,
    );

    const iconEl = document.createElement("span");
    iconEl.className = "topic-icon";
    iconEl.setAttribute("aria-hidden", "true");
    iconEl.textContent = (icons && icons[topic]) || "🌱";
    const nameEl = document.createElement("span");
    nameEl.className = "topic-name";
    nameEl.textContent = displayName;
    btn.append(iconEl, nameEl);
    btn.addEventListener("click", () => {
      const input = document.getElementById("chatInput");
      input.value = displayName;
      updateCharCount();
      input.focus();
    });
    grid.appendChild(btn);
  });

  wrapper.append(heading, grid);
  msgs.appendChild(wrapper);
  scrollBottom();
}

function appendTopicsGrid(topics, icons, twNames) {
  const msgs = document.getElementById("messages");
  const wrapper = document.createElement("div");
  wrapper.className = "topics-grid-wrapper";

  const grid = document.createElement("div");
  grid.className = "topics-grid";

  topics.forEach((topic) => {
    const btn = document.createElement("button");
    btn.className = "topic-btn";
    // Show Twi name when in Twi mode
    const displayName =
      currentLang === "tw" && twNames && twNames[topic]
        ? twNames[topic]
        : topic;
    btn.type = "button";
    btn.dataset.topic = topic;
    const iconEl = document.createElement("span");
    iconEl.className = "topic-icon";
    iconEl.textContent = icons[topic] || "🌱";
    const nameEl = document.createElement("span");
    nameEl.className = "topic-name";
    nameEl.textContent = displayName;
    btn.append(iconEl, nameEl);
    btn.onclick = () => selectTopic(topic, icons[topic]);
    grid.appendChild(btn);
  });

  wrapper.appendChild(grid);
  msgs.appendChild(wrapper);
  scrollBottom();
}

function selectTopic(topic, icon) {
  fetch(`${API}/api/topic-suggestions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, lang: currentLang }),
  })
    .then((response) => {
      if (!response.ok) throw new Error("Could not load topic suggestions");
      return response.json();
    })
    .then((data) => {
      const displayName = data.display_name || topic;
      const topicIcon = data.icon || icon || "🌱";
      const followUp =
        currentLang === "tw"
          ? `Wapaw **${topicIcon} ${displayName}**.\n\nDɛn na wopɛ sɛ wonim? Asɛmmisa bi a wotumi bisa:`
          : `You selected **${topicIcon} ${displayName}**.\n\nWhat would you like to know? Here are some ideas:`;
      appendMessage(followUp, "bot");
      appendSuggestionButtons(data.suggestions, topic);
    })
    .catch(() => {
      appendMessage(
        currentLang === "tw"
          ? "Yɛantumi antwe asɛmmisa no amma. Yɛsrɛ wo san sɔ hwɛ."
          : "The suggested questions could not be loaded. Please try again.",
        "bot",
      );
    });
}

function appendSuggestionButtons(suggestions, topic) {
  const msgs = document.getElementById("messages");
  const wrapper = document.createElement("div");
  wrapper.className = "suggestions-wrapper";

  suggestions.forEach((suggestion) => {
    const text = typeof suggestion === "string" ? suggestion : suggestion.text;
    const btn = document.createElement("button");
    btn.className = "suggestion-btn";
    btn.textContent = text;
    btn.onclick = () => submitQuestion(text);
    wrapper.appendChild(btn);
  });

  msgs.appendChild(wrapper);
  scrollBottom();
}
