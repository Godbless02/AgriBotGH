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

function getSpeechVoice(lang = "en") {
  if (!("speechSynthesis" in window)) return null;

  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return null;

  const target = String(lang || "en").toLowerCase();
  const matchByLang = (voiceLang) =>
    voiceLang.toLowerCase().includes(target) ||
    (target === "tw" && /twi|akan|ak/.test(voiceLang.toLowerCase()));

  const preferred = voices.find((voice) => matchByLang(voice.lang));
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
    updateTtsButton(activeSpeech.button, "idle");
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

  if (!("speechSynthesis" in window)) {
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
    stopSpeech(false);
  }

  if (button.dataset.state === "playing") {
    window.speechSynthesis.pause();
    activeSpeech.isPlaying = false;
    activeSpeech.isPaused = true;
    updateTtsButton(button, "paused");
    setTtsStatus(controls, "Paused", false);
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
  const utterance = new SpeechSynthesisUtterance(cleanText);
  utterance.lang = voice ? voice.lang : "en-US";
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
    setTtsStatus(controls, "Speaking...", true);
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
    setTtsStatus(controls, "Speaking...", true);
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

function appendMessage(text, role) {
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
    playBtn.addEventListener("click", () => {
      speakBotResponse(playBtn, text, currentLang);
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
  sess.messages.forEach((msg) => appendMessage(msg.text, msg.role));
  loadSidebarHistory();
}

// ══════════════════════════════════════════════════════════════════
// LANGUAGE SWITCH
// ══════════════════════════════════════════════════════════════════

function switchLanguage(lang) {
  if (lang === currentLang) return;
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
}

// ══════════════════════════════════════════════════════════════════
// CLEAR & NEW CHAT
// ══════════════════════════════════════════════════════════════════

function clearChat() {
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

// Hardcoded topics data with English names, Twi names, icons, and suggestions
const TOPICS_DATA = {
  "Soil & Land Preparation": {
    icon: "🌍",
    tw_name: "Asase ne Afuo Siesie",
    suggestions_en: [
      "How do I know if my soil is good for farming?",
      "How do I prevent soil erosion on my farm?",
      "How do I make compost at home?",
      "What is the best way to transplant seedlings?",
      "What is crop rotation and why is it important?",
    ],
    suggestions_tw: [
      "Ɛdeɛn na ɛkyerɛ sɛ m'asase yɛ papa ma okuafo adwuma?",
      "Ɛdeɛn na mema asase amma ɛnhuru wɔ m'afuo mu?",
      "Ɛdeɛn na meyɛ compost wɔ fie?",
      "Kwan bɛn na ɛyɛ papa a yɛfa so si nnua nketewa baabi foforo?",
      "Dea ɛyɛ sɛ wosesa nnuaba gu asase mu na adɛn na ɛyɛ papa?",
    ],
  },
  "Fertilizer & Nutrients": {
    icon: "🧪",
    tw_name: "Ferefere ne Aduan",
    suggestions_en: [
      "What does NPK mean on a fertilizer bag?",
      "Can I use animal manure instead of chemical fertilizer?",
      "How do I know if my fertilizer is working?",
      "Can over-fertilizing damage my crops?",
      "What is green manure and how do I use it?",
    ],
    suggestions_tw: [
      "Dɛn na NPK kyerɛ wɔ ferefere bag so?",
      "Metumi de mmoa dɔteɛ adi dwuma mmom sen nnuru ferefere?",
      "Ɛdeɛn na menim sɛ m'ferefere yɛ adwuma?",
      "Ferefere dodo tumi sɛe m'nnuaba anaa?",
      "Dɛn na nhwiren-tew ferefere yɛ na ɛdeɛn na mefa di dwuma?",
    ],
  },
  Maize: {
    icon: "🌽",
    tw_name: "Aburoɔ",
    suggestions_en: [
      "When is the best time to plant maize in Ghana?",
      "What fertilizer should I apply to maize and when?",
      "How do I identify a fall armyworm attack on my maize?",
      "How do I control weeds in my maize farm?",
      "How many bags of maize can I expect from one acre?",
    ],
    suggestions_tw: [
      "Bere bɛn na ɛyɛ ɔkorɔ sɛ wode aburow to mu wɔ Ghana?",
      "Ferefere bɛn na mede to aburoɔ ho na bere bɛn?",
      "Dɛn na ɛkyerɛ sɛ fall armyworm atu mako wɔ me aburoɔ afuom?",
      "Dɛn na menyɛ nhaban foforo a wɔ me aburoɔ afuom mu?",
      "Sacks aburoɔ ahe na mebetumi anya fi eka baako mu?",
    ],
  },
  Cassava: {
    icon: "🥔",
    tw_name: "Bankye",
    suggestions_en: [
      "How do I select good cassava stems for planting?",
      "How do I process cassava into gari?",
      "What diseases affect cassava and how do I manage them?",
      "What is the best cassava variety for making fufu?",
      "How much profit can I make from one acre of cassava?",
    ],
    suggestions_tw: [
      "Dɛn na menyɛ sɛ mepick bankye abɔ pa sɛ mede to mu?",
      "Dɛn na menyɛ bankye ho yɛ gari?",
      "Yadeɛ bɛn na ɛtaa ba bankye ho na dɛn na menyɛ wɔn ho?",
      "Bankye variety bɛn na ɛhia pa ara ma fufu yɛ?",
      "Mfa sika ahe bɛfata me wɔ bankye eka baako mu?",
    ],
  },
  "Plantain & Banana": {
    icon: "🍌",
    tw_name: "Boɔde ne Kwadu",
    suggestions_en: [
      "What type of sucker is best for planting plantain?",
      "How do I control black sigatoka disease in plantain?",
      "How do I know when plantain is ready to harvest?",
      "How do I make plantain chips for sale?",
      "What fertilizer is best for plantain?",
    ],
    suggestions_tw: [
      "Sucker bɛn na ɛhia pa ara sɛ mede to mu wɔ boɔde afuom?",
      "Dɛn na menyɛ black sigatoka yadeɛ ho wɔ boɔde ho?",
      "Dɛn na ɛkyerɛ sɛ boɔde atwa so sɛ wɔbɛyi?",
      "Dɛn na menyɛ boɔde chips ma tɔ?",
      "Ferefere bɛn na ɛyɛ ɔkorɔ ma borɔdɔ?",
    ],
  },
  Yam: {
    icon: "🍠",
    tw_name: "Bayerɛ",
    suggestions_en: [
      "How do I prepare yam setts for planting?",
      "What is the best time to plant yam in Ghana?",
      "How do I build a yam mound and why is it important?",
      "How do I store yam properly after harvest?",
      "Can I grow yam without mounds?",
    ],
    suggestions_tw: [
      "Dɛn na menyɛ bayerɛ setts ansa na mede to mu?",
      "Bere bɛn na ɛyɛ papa pa ara sɛ wede bayerɛ to mu wɔ Ghana?",
      "Dɛn na menyɛ bayerɛ afe anaa stake na ɛyɛ papa adɛn?",
      "Ɛkwan pa bɛn na mede bayerɛ twew na guina yi akyi?",
      "Metumi ato bayerɛ a afe amma?",
    ],
  },
  Cocoyam: {
    icon: "🌿",
    tw_name: "Kɔkɔnte",
    suggestions_en: [
      "How do I grow cocoyam successfully in Ghana?",
      "How do I store cocoyam after harvest?",
      "How do I add value to cocoyam for better income?",
      "What are the common pests and diseases of cocoyam?",
      "What are the marketing opportunities for cocoyam?",
    ],
    suggestions_tw: [
      "Dɛn na menyɛ sɛ meto kɔkɔnte yie wɔ Ghana?",
      "Dɛn na menyɛ kɔkɔnte corms guina yi akyi?",
      "Dɛn na menyɛ sɛ kɔkɔnte bo kɔ so ma sika pa?",
      "Adwummaker ne yadeɛ bɛn na ɛtaa ba kɔkɔnte ho?",
      "Dwa nhyiamu bɛn na ɛwɔ ma kɔkɔnte wɔ Ghana?",
    ],
  },
  Tomatoes: {
    icon: "🍅",
    tw_name: "Ntomatoes",
    suggestions_en: [
      "How do I grow tomatoes in Ghana for good yield?",
      "How do I prevent tomato late blight?",
      "What causes tomato blossom end rot and how do I fix it?",
      "What is the best irrigation method for tomatoes?",
      "What fertilizer programme should I follow for tomatoes?",
    ],
    suggestions_tw: [
      "Dɛn na menyɛ sɛ meto tomatoes yie wɔ Ghana sɛ nnoa pii aba?",
      "Dɛn na menyɛ sɛ tomato late blight annya me nnuaba?",
      "Dɛn ma tomato blossom end rot na dɛn na menyɛ ho?",
      "Quench nhyiamu bɛn na ɛhia pa ara ma tomatoes wɔ Ghana?",
      "Ferefere programme bɛn na mede to tomatoes ho?",
    ],
  },
  Pepper: {
    icon: "🌶️",
    tw_name: "Mako",
    suggestions_en: [
      "How do I raise pepper seedlings?",
      "How do I prevent pepper root rot?",
      "How do I dry and preserve pepper for longer shelf life?",
      "How do I grow bell pepper for high value markets?",
      "What types of pepper are grown in Ghana?",
    ],
    suggestions_tw: [
      "Dɛn na menyɛ pepper seedlings?",
      "Dɛn na menyɛ sɛ pepper root rot annya me nnuaba?",
      "Dɛn na menyɛ pepper tew na kata so sɛ ɛtena mu akyi?",
      "Dɛn na menyɛ bell pepper ma dwa a bo wɔ so wɔ Ghana?",
      "Pepper nhyiamu bɛn na wɔtaa to mu wɔ Ghana?",
    ],
  },
  Onion: {
    icon: "🧅",
    tw_name: "Gyene / Abɔnkɔ",
    suggestions_en: [
      "How do I grow onions in Ghana?",
      "What causes onion bulbs to be small?",
      "How do I control thrips on my onions?",
      "How do I cure and store onions after harvest?",
      "What are the main onion varieties grown in Ghana?",
    ],
    suggestions_tw: [
      "Dɛn na menyɛ sɛ meto abɔnkɔ wɔ Ghana?",
      "Dɛn ma abɔnkɔ bulbs yɛ ketewa?",
      "Ɛdeɛn na metumi kora thrips ase wɔ m'gyene so?",
      "Dɛn na menyɛ sɛ me twew na guina abɔnkɔ yi akyi?",
      "Onion varieties bɛn na wɔtaa to mu wɔ Ghana?",
    ],
  },
  Carrot: {
    icon: "🥕",
    tw_name: "Carrot",
    suggestions_en: [
      "How do I grow carrots in Ghana?",
      "What problems are common in carrot growing?",
      "How do I thin carrot seedlings?",
      "How do I harvest and clean carrots for market?",
      "What fertilizer does carrot need?",
    ],
    suggestions_tw: [
      "Dɛn na menyɛ sɛ meto carrot wɔ Ghana?",
      "Aho yɛ den bɛn na ɛtaa ba carrot nnoa mu?",
      "Dɛn na menyɛ carrot seedlings yi?",
      "Dɛn na menyɛ sɛ meyiyɛ na hohoro carrot ma dwa?",
      "Ferefere bɛn na carrot hia na bere bɛn na mede to ho?",
    ],
  },
  "Garden Eggs": {
    icon: "🍆",
    tw_name: "Ntorɔ / Mako Ntorɔ",
    suggestions_en: [
      "How do I grow garden eggs in Ghana?",
      "What pests attack garden eggs and how do I control them?",
      "How do I manage water for garden eggs?",
      "How long does garden egg take from planting to harvest?",
      "How do I make garden egg farming profitable?",
    ],
    suggestions_tw: [
      "Dɛn na menyɛ sɛ meto ntorɔ wɔ Ghana?",
      "Adwummaker bɛn na ɛtaa tu mako ntorɔ na dɛn na menyɛ wɔn ho?",
      "Dɛn na menyɛ sɛ mede nsuo hwɛ ntorɔ ho?",
      "Bere ahe na ɛkyɛ fi to aba kɔsi ntorɔ yi ediɛ?",
      "Dɛn na menyɛ ntorɔ adwuma sɛ ɛde mfaso ba?",
    ],
  },
  "Palm Oil & Coconut": {
    icon: "🌴",
    tw_name: "Abɛ ne Kuuku",
    suggestions_en: [
      "How do I establish a palm oil plantation in Ghana?",
      "How do I harvest palm fruits properly?",
      "How do I process palm fruits into palm oil?",
      "How do I grow and care for coconut trees?",
      "How do I process coconut into various products?",
    ],
    suggestions_tw: [
      "Dɛn na menyɛ sɛ mefi ase abɛ afuom wɔ Ghana?",
      "Dɛn na menyɛ sɛ meyiyɛ abɛ ntama pa?",
      "Dɛn na menyɛ abɛ ntama yɛ abɛ ɔman wɔ efie?",
      "Dɛn na menyɛ sɛ meto kuuku nnuaba wɔ Ghana?",
      "Dɛn na menyɛ kuuku yɛ nneɛma ahorow ma sika?",
    ],
  },
  "Fish Farming": {
    icon: "🐟",
    tw_name: "Apataa Adwuma",
    suggestions_en: [
      "How do I start fish farming in Ghana?",
      "What is the best fish species to farm in Ghana?",
      "How do I maintain water quality in my fish pond?",
      "What do I feed my fish and how much?",
      "How do I know when my fish are ready for harvest?",
    ],
    suggestions_tw: [
      "Dɛn na menyɛ sɛ meyɛ apataa adwuma wɔ Ghana?",
      "Apataa nnhyiamu bɛn na ɛyɛ ɔkorɔ ma adwuma wɔ Ghana?",
      "Dɛn na menyɛ nsuo a wɔ m'apataa pond mu yɛ pa?",
      "Aduane bɛn na mede ma m'apataa na ahe?",
      "Dɛn na ɛkyerɛ sɛ m'apataa atwa so sɛ wɔbɛyi?",
    ],
  },
  Poultry: {
    icon: "🐔",
    tw_name: "Aboa Kuraa",
    suggestions_en: [
      "How do I start a poultry farm?",
      "What breed of chicken is best for egg production?",
      "How do I prevent diseases in my poultry?",
      "What should I feed my chickens?",
      "How do I build a proper chicken coop?",
    ],
    suggestions_tw: [
      "Dɛn na menyɛ sɛ meyɛ aboa kuraa adwuma?",
      "Aboa kuraa nnhyiamu bɛn na ɛyɛ ɔkorɔ ma mokaa?",
      "Dɛn na menyɛ sɛ yadeɛ annya m'aboa kuraa?",
      "Aduane bɛn na mede ma m'aboa kuraa?",
      "Dɛn na menyɛ aboa kuraa dan pa?",
    ],
  },
  "Goat Rearing": {
    icon: "🐐",
    tw_name: "Odomankoma Rehwɛ",
    suggestions_en: [
      "How do I start goat farming?",
      "What should I feed my goats?",
      "How do I prevent diseases in goats?",
      "What housing do goats need?",
      "When is the best time to breed my goats?",
    ],
    suggestions_tw: [
      "Dɛn na menyɛ sɛ meyɛ odomankoma rehwɛ?",
      "Aduane bɛn na mede ma m'odomankoma?",
      "Dɛn na menyɛ sɛ yadeɛ annya m'odomankoma?",
      "Dan bɛn na odomankoma hia?",
      "Bere bɛn na ɛyɛ ɔkorɔ sɛ mepa m'odomankoma?",
    ],
  },
};

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

function loadTopicsPanel() {
  const gridPanel = document.getElementById("topicsGridPanel");
  gridPanel.innerHTML = "";

  Object.keys(TOPICS_DATA).forEach((topic) => {
    const data = TOPICS_DATA[topic];
    const btn = document.createElement("button");
    btn.className = "topic-btn";
    const displayName = currentLang === "tw" ? data.tw_name : topic;
    btn.innerHTML = `<span class="topic-icon">${data.icon}</span><span class="topic-name">${displayName}</span>`;
    btn.onclick = () => selectTopicFromPanel(topic);
    gridPanel.appendChild(btn);
  });
}

function selectTopicFromPanel(topic) {
  const data = TOPICS_DATA[topic];
  if (!data) return;

  const displayName = currentLang === "tw" ? data.tw_name : topic;
  const icon = data.icon;

  // Close the panel
  document.getElementById("topicsPanel").classList.remove("show");
  document.getElementById("overlay").classList.remove("show");

  // Show user message
  const userMsg =
    currentLang === "tw" ? `${icon} ${displayName}` : `${icon} ${displayName}`;
  appendMessage(userMsg, "user");

  // Show follow-up
  const followUp =
    currentLang === "tw"
      ? `Wapaw **${icon} ${displayName}**.\n\nDɛn na wopɛ sɛ wonim? Asɛmmisa bi a wotumi bisa:`
      : `You selected **${icon} ${displayName}**.\n\nWhat would you like to know? Here are some ideas:`;
  appendMessage(followUp, "bot");

  // Get suggestions for this topic
  const suggestions =
    currentLang === "tw" ? data.suggestions_tw : data.suggestions_en;
  appendSuggestionButtons(suggestions, topic);
}

function getSuggestionSet() {
  const suggestions = {
    en: [
      "When should I plant maize?",
      "What fertilizer should I use for maize?",
      "How do I control maize pests?",
    ],
    tw: [
      "Bere bɛn na ɛsɛ sɛ mede aburoɔ to mu?",
      "Ferefere bɛn na mede aburoɔ ho?",
      "Dɛn na menyɛ sɛ mɛhwɛ aburoɔ adwummaker?",
    ],
  };

  return currentLang === "tw" ? suggestions.tw : suggestions.en;
}

function updateSuggestions() {
  const list = document.getElementById("suggestionsList");
  const bar = document.getElementById("suggestionsBar");
  if (!list || !bar) return;

  const suggestions = getSuggestionSet();
  list.innerHTML = "";

  if (suggestions.length === 0) {
    bar.style.display = "none";
    return;
  }

  bar.style.display = "flex";
  suggestions.forEach((text) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "suggestion-pill";
    btn.textContent = text;
    btn.addEventListener("click", () => {
      document.getElementById("chatInput").value = text;
      updateCharCount();
      document.getElementById("chatInput").focus();
    });
    list.appendChild(btn);
  });
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

function handleSend() {
  const input = document.getElementById("chatInput");
  const text = input.value.trim();
  if (!text) return;

  appendMessage(text, "user");
  input.value = "";
  updateCharCount();

  const typingEl = showTyping();
  const sessId = getCurrentSessionId();

  fetch(`${API}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: text,
      language: currentLang,
      session_id: sessId,
      username: currentUser,
    }),
  })
    .then((r) => r.json())
    .then((data) => {
      typingEl.remove();
      renderBotResponse(data, sessId, text);
    })
    .catch(() => {
      typingEl.remove();
      appendMessage(
        "Sorry, the server is not responding. Please make sure the app is running.",
        "bot",
      );
    });
}

function renderBotResponse(data, sessId, userText) {
  const type = data.type || "answer";

  if (type === "answer") {
    // Normal answer
    appendMessage(data.text, "bot");
    saveSessionMessage(
      currentUser,
      sessId,
      currentLang,
      userText.length > 35 ? userText.substring(0, 35) + "..." : userText,
      userText,
      data.text,
    );
    loadSidebarHistory();
  } else if (type === "topics" || type === "off_topic") {
    // Show topic selection grid
    appendMessage(data.text, "bot");
    appendTopicsGrid(data.topics, data.topic_icons, data.topic_names_tw);
    saveSessionMessage(
      currentUser,
      sessId,
      currentLang,
      userText.length > 35 ? userText.substring(0, 35) + "..." : userText,
      userText,
      data.text,
    );
    loadSidebarHistory();
  } else if (type === "low_confidence") {
    // Topic detected but no exact match — show suggestions for that topic
    appendMessage(data.text, "bot");
    appendSuggestionButtons(data.suggestions, data.topic);
    saveSessionMessage(
      currentUser,
      sessId,
      currentLang,
      userText.length > 35 ? userText.substring(0, 35) + "..." : userText,
      userText,
      data.text,
    );
    loadSidebarHistory();
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
    btn.innerHTML = `<span class="topic-icon">${icons[topic] || "🌱"}</span><span class="topic-name">${displayName}</span>`;
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
    .then((r) => r.json())
    .then((data) => {
      const displayName = data.display_name || topic;
      const followUp =
        currentLang === "tw"
          ? `Wapaw **${icon} ${displayName}**.\n\nDɛn na wopɛ sɛ wonim? Asɛmmisa bi a wotumi bisa:`
          : `You selected **${icon} ${displayName}**.\n\nWhat would you like to know? Here are some ideas:`;
      appendMessage(followUp, "bot");
      appendSuggestionButtons(data.suggestions, topic);
    });
}

function appendSuggestionButtons(suggestions, topic) {
  const msgs = document.getElementById("messages");
  const wrapper = document.createElement("div");
  wrapper.className = "suggestions-wrapper";

  suggestions.forEach((suggestion) => {
    const btn = document.createElement("button");
    btn.className = "suggestion-btn";
    btn.textContent = suggestion;
    btn.onclick = () => {
      document.getElementById("chatInput").value = suggestion;
      updateCharCount();
      handleSend();
    };
    wrapper.appendChild(btn);
  });

  msgs.appendChild(wrapper);
  scrollBottom();
}
