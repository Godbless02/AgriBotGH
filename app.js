// ── CONSTANTS ────────────────────────────────────────────────────
const API = "";
const STORAGE_KEY_CURRENT = "agribot_current_user"; // who is logged in now
const STORAGE_KEY_ALL = "agribot_all_users"; // all user profiles + their chats

// ── STATE ────────────────────────────────────────────────────────
let currentUser = "";
let currentLang = "en";
let enSessionId = null;
let twSessionId = null;
let welcomeLang = "en";
let isDarkTheme = false;
// simple toggle locks to prevent double-triggering
let chipsToggleLock = false;
let sidebarToggleLock = false;
let activeSpeech = {
  button: null,
  utterance: null,
  lang: "en",
  isPlaying: false,
  isPaused: false,
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
    .trim();
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
  if (!("speechSynthesis" in window)) return null;

  const voices = window.speechSynthesis.getVoices();
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
}

function updateTtsButton(button, state) {
  if (!button) return;
  button.dataset.state = state;
  const labelMap = {
    idle: "🔊 Play",
    playing: "⏸ Pause",
    paused: "▶ Resume",
    error: "⚠️ Audio",
  };
  button.textContent = labelMap[state] || labelMap.idle;
  button.classList.toggle("is-playing", state === "playing");
  button.classList.toggle("is-paused", state === "paused");

  const controls = button.closest(".tts-controls");
  if (!controls) return;
  const stopBtn = controls.querySelector(".tts-stop");
  if (stopBtn) {
    stopBtn.hidden = state === "idle" || state === "error";
  }
}

function stopSpeech(resetButton = true) {
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }

  if (activeSpeech.button && resetButton) {
    const controls = activeSpeech.button.closest(".tts-controls");
    updateTtsButton(activeSpeech.button, "idle");
    if (controls) setTtsStatus(controls, "", false);
  }

  activeSpeech.button = null;
  activeSpeech.utterance = null;
  activeSpeech.isPlaying = false;
  activeSpeech.isPaused = false;
  activeSpeech.lang = "en";
}

function speakBotResponse(button, text, lang = "en") {
  const controls = button.closest(".tts-controls");
  if (!controls) return;

  if (
    !("speechSynthesis" in window) ||
    !("SpeechSynthesisUtterance" in window)
  ) {
    setTtsStatus(
      controls,
      "Audio is currently unavailable. You can still read the response above.",
      true,
    );
    button.disabled = true;
    updateTtsButton(button, "error");
    return;
  }

  const cleanText = cleanTextForSpeech(text);
  if (!cleanText) {
    setTtsStatus(
      controls,
      "There is no spoken text available for this response.",
      true,
    );
    return;
  }

  if (activeSpeech.button && activeSpeech.button !== button) {
    stopSpeech(true);
  }

  if (button.dataset.state === "playing") {
    window.speechSynthesis.pause();
    activeSpeech.isPlaying = false;
    activeSpeech.isPaused = true;
    updateTtsButton(button, "paused");
    setTtsStatus(controls, "Paused", true);
    return;
  }

  if (button.dataset.state === "paused") {
    window.speechSynthesis.resume();
    activeSpeech.isPlaying = true;
    activeSpeech.isPaused = false;
    updateTtsButton(button, "playing");
    setTtsStatus(controls, "Speaking...", true);
    return;
  }

  const voice = getSpeechVoice(lang);
  const usesFallbackVoice =
    lang === "tw" && !isVoiceSuitableForLanguage(voice, "tw");
  const speakingStatus = usesFallbackVoice
    ? "No Twi/Akan voice is installed. Using a fallback voice; Twi pronunciation may be inaccurate."
    : "Speaking...";
  const utterance = new SpeechSynthesisUtterance(cleanText);
  utterance.lang = voice ? voice.lang : lang === "tw" ? "tw-GH" : "en-GH";
  utterance.voice = voice;
  utterance.rate = 1;
  utterance.pitch = 1;
  utterance.volume = 1;

  utterance.onstart = () => {
    activeSpeech.button = button;
    activeSpeech.utterance = utterance;
    activeSpeech.lang = lang;
    activeSpeech.isPlaying = true;
    activeSpeech.isPaused = false;
    updateTtsButton(button, "playing");
    setTtsStatus(controls, speakingStatus, true);
  };

  utterance.onpause = () => {
    activeSpeech.isPlaying = false;
    activeSpeech.isPaused = true;
    updateTtsButton(button, "paused");
    setTtsStatus(controls, "Paused", true);
  };

  utterance.onresume = () => {
    activeSpeech.isPlaying = true;
    activeSpeech.isPaused = false;
    updateTtsButton(button, "playing");
    setTtsStatus(controls, speakingStatus, true);
  };

  utterance.onend = () => {
    if (activeSpeech.button === button) {
      updateTtsButton(button, "idle");
      setTtsStatus(controls, "", false);
    }
    if (activeSpeech.utterance === utterance) {
      stopSpeech(false);
    }
  };

  utterance.onerror = (event) => {
    const reason = event && event.error ? event.error : "unknown";
    setTtsStatus(
      controls,
      `Audio is currently unavailable. You can still read the response above. (${reason})`,
      true,
    );
    updateTtsButton(button, "error");
    stopSpeech(false);
  };

  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
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
    playBtn.textContent = "🔊 Play";
    playBtn.setAttribute("aria-label", "Play this response aloud");
    playBtn.dataset.language = messageLang;
    playBtn.addEventListener("click", () => {
      speakBotResponse(playBtn, text, messageLang);
    });

    const stopBtn = document.createElement("button");
    stopBtn.type = "button";
    stopBtn.className = "tts-stop";
    stopBtn.textContent = "■ Stop";
    stopBtn.title = "Stop speech";
    stopBtn.hidden = true;
    stopBtn.addEventListener("click", () => {
      stopSpeech();
      if (activeSpeech.button) {
        updateTtsButton(activeSpeech.button, "idle");
      }
    });

    const status = document.createElement("div");
    status.className = "tts-status";
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
  document.getElementById("twChips").style.display =
    lang === "tw" ? "flex" : "none";
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
  document.getElementById("chatInput").value = el.textContent;
  updateCharCount();
  document.getElementById("chatInput").focus();
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
  isDarkTheme = !isDarkTheme;
  document.body.dataset.theme = isDarkTheme ? "night" : "";
  document.getElementById("themeBtn").textContent = isDarkTheme ? "☀️" : "🌙";
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
      const suggestionId =
        typeof suggestion === "string" ? null : suggestion.id || null;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "suggestion-pill";
      btn.textContent = text;
      btn.addEventListener("click", () => {
        document.getElementById("chatInput").value = text;
        updateCharCount();
        if (suggestionId) {
          handleSend(suggestionId);
        } else {
          document.getElementById("chatInput").focus();
        }
      });
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
// Handles 4 response types from backend:
//   "answer"        — normal farming answer
//   "topics"        — show all topics grid (off-topic or vague)
//   "off_topic"     — not farming related, show topics
//   "low_confidence"— farming topic detected but no exact match
// ══════════════════════════════════════════════════════════════════

function handleSend(suggestionId = null) {
  const input = document.getElementById("chatInput");
  const text = input.value.trim();
  if (!text) return;

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
      ...(suggestionId ? { suggestion_id: suggestionId } : {}),
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
  }
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
    const suggestionId =
      typeof suggestion === "string" ? null : suggestion.id || null;
    const btn = document.createElement("button");
    btn.className = "suggestion-btn";
    btn.textContent = text;
    btn.onclick = () => {
      document.getElementById("chatInput").value = text;
      updateCharCount();
      handleSend(suggestionId);
    };
    wrapper.appendChild(btn);
  });

  msgs.appendChild(wrapper);
  scrollBottom();
}
