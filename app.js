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
  // prevent rapid double toggles
  if (sidebarToggleLock) return;
  sidebarToggleLock = true;
  setTimeout(() => (sidebarToggleLock = false), 300);
  document.getElementById("sidebar").classList.toggle("mobile-open");
  document.getElementById("overlay").classList.toggle("show");
}
function closeSidebar() {
  document.getElementById("sidebar").classList.remove("mobile-open");
  document.getElementById("overlay").classList.remove("show");
  document.getElementById("chipsSidebar").classList.remove("show");
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
