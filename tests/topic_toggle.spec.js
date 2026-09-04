const { test, expect } = require("@playwright/test");

// NOTE: These tests expect you to run a simple static server rooted at the project
// directory (e.g. `npx http-server -p 8080` or `npx serve -p 8080`) and then
// visit http://localhost:8080/ in the tests. Start the server before running.

const BASE = process.env.TEST_BASE_URL || "http://localhost:8080";

test.describe("Topic and quick-question panels", () => {
  test("renders uncertain agriculture and off-topic router states", async ({
    page,
  }) => {
    await page.goto(BASE + "/index.html");
    await page.fill("#nameInput", "RouterUser");
    await page.click(".start-btn");

    await page.fill(
      "#chatInput",
      "My maize leaves are changing colour and I am not sure why",
    );
    await page.click("#sendBtn");
    await expect(page.locator(".knowledge-gap-topic-btn")).toHaveCount(40, {
      timeout: 15000,
    });
    await expect(page.locator(".message-card.bot-message").last()).toContainText(
      "couldn't find a sufficiently reliable answer",
    );

    await page.fill("#chatInput", "Who won the football match last night?");
    await page.click("#sendBtn");
    await expect(page.locator(".topics-grid-wrapper .topic-btn")).toHaveCount(28, {
      timeout: 15000,
    });
    await expect(page.locator(".message-card.bot-message").last()).toContainText(
      "agricultural assistant",
    );
  });

  test("loads all canonical topics and routes a selected suggestion", async ({
    page,
  }) => {
    await page.goto(BASE + "/index.html");
    await page.fill("#nameInput", "TopicUser");
    await page.click(".start-btn");

    await page.click(".topic-toggle-btn");
    const topicButtons = page.locator("#topicsGridPanel .topic-btn[data-topic]");
    await expect(topicButtons).toHaveCount(28);

    const expectedResponse = await page.request.post(
      BASE + "/api/topic-suggestions",
      { data: { topic: "Maize", lang: "en" } },
    );
    expect(expectedResponse.ok()).toBeTruthy();
    const expected = await expectedResponse.json();

    await page.locator('#topicsGridPanel .topic-btn[data-topic="Maize"]').click();
    const suggestionButtons = page.locator(
      ".suggestions-wrapper .suggestion-btn",
    );
    await expect(suggestionButtons).toHaveCount(expected.suggestions.length);
    await expect(suggestionButtons.first()).toHaveText(
      expected.suggestions[0].text,
    );

    await suggestionButtons.first().click();
    await expect(page.locator(".message-card.bot-message").last()).toContainText(
      /.+/,
      { timeout: 15000 },
    );
  });

  test("renders canonical Twi topic names", async ({ page }) => {
    await page.goto(BASE + "/index.html");
    await page.fill("#nameInput", "TwiTopicUser");
    await page.click(".start-btn");
    await page.click("#twBtn");
    await page.click(".topic-toggle-btn");

    const topicButtons = page.locator("#topicsGridPanel .topic-btn[data-topic]");
    await expect(topicButtons).toHaveCount(28);
    await expect(
      page.locator('#topicsGridPanel .topic-btn[data-topic="Maize"]'),
    ).toContainText("Aburoɔ");
  });

  test("opens and closes the topics panel", async ({
    page,
  }) => {
    await page.goto(BASE + "/index.html");

    // Start the chat (welcome screen shows initially)
    await page.fill("#nameInput", "PlaywrightUser");
    await page.click(".start-btn");

    // Ensure the topic button exists
    const topicBtn = page.locator(".topic-toggle-btn");
    await expect(topicBtn).toBeVisible();

    // Click it to open the topic catalogue
    await topicBtn.click();

    const topicsPanel = page.locator("#topicsPanel");
    const overlay = page.locator("#overlay");

    await expect(topicsPanel).toHaveClass(/show/);
    await expect(overlay).toHaveClass(/show/);
    await expect(topicBtn).toHaveAttribute("aria-expanded", "true");

    // Click overlay to close
    await overlay.click();

    await expect(topicsPanel).not.toHaveClass(/show/);
    await expect(overlay).not.toHaveClass(/show/);
    await expect(topicBtn).toHaveAttribute("aria-expanded", "false");
  });

  test("rapid clicks do not toggle repeatedly", async ({ page }) => {
    await page.goto(BASE + "/index.html");
    // Start the chat so controls are visible
    await page.fill("#nameInput", "PlaywrightUser");
    await page.click(".start-btn");
    const topicBtn = page.locator(".topic-toggle-btn");
    const chips = page.locator("#chipsSidebar");

    // Rapid invocations bypassing overlay interception to exercise debounce
    await page.evaluate(() => {
      toggleChips();
      toggleChips();
      toggleChips();
    });

    // Desktop quick questions start open, so one accepted toggle closes them.
    await expect(chips).toHaveClass(/desktop-hidden/);
  });

  test("bot responses include a manual play control and do not auto-speak", async ({
    page,
  }) => {
    await page.goto(BASE + "/index.html");
    await page.fill("#nameInput", "TTSUser");
    await page.click(".start-btn");

    await page.fill("#chatInput", "How do I grow maize?");
    await page.click("#sendBtn");

    await expect(page.locator(".tts-button").first()).toBeVisible({
      timeout: 15000,
    });
    await expect(page.locator(".tts-button").first()).toContainText(
      /🔊|▶|Play/i,
    );

    const speechState = await page.evaluate(() => {
      const synth = window.speechSynthesis;
      return {
        supported: !!synth,
        speaking: synth ? synth.speaking : false,
      };
    });

    expect(speechState.supported).toBeTruthy();
    expect(speechState.speaking).toBeFalsy();
  });

  test("language switching keeps responses, history, and TTS language isolated", async ({
    page,
  }) => {
    await page.route("**/api/chat", async (route) => {
      const request = route.request();
      const payload = request.postDataJSON();
      if (payload.language === "en") {
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
      await route.continue();
    });

    await page.goto(BASE + "/index.html");
    await page.fill("#nameInput", "LanguageIsolationUser");
    await page.click(".start-btn");

    await page.fill("#chatInput", "What are the signs of good farming soil?");
    await page.click("#sendBtn");
    await page.click("#twBtn");

    await expect(page.locator("#enHistory .history-item")).toHaveCount(1, {
      timeout: 15000,
    });
    await expect(page.locator("#messages")).not.toContainText(
      "Good farming soil is dark",
    );

    await page.locator("#enHistory .history-item").click();
    await expect(page.locator("#messages")).toContainText(
      "Good farming soil is dark",
    );
    await expect(page.locator(".tts-button").last()).toHaveAttribute(
      "data-language",
      "en",
    );

    await page.click("#twBtn");
    await page.fill(
      "#chatInput",
      "Ɛdeɛn na ɛkyerɛ sɛ m'asase yɛ yɛ papa ma okuafo adwuma?",
    );
    await page.click("#sendBtn");
    await expect(page.locator("#twHistory .history-item")).toHaveCount(1, {
      timeout: 15000,
    });
    await expect(page.locator(".message-card.bot-message").last()).toContainText(
      "Asase pa wɔ okuafo adwuma mu",
    );
    await expect(page.locator(".tts-button").last()).toHaveAttribute(
      "data-language",
      "tw",
    );

    const sessionLanguages = await page.evaluate(() => {
      const users = JSON.parse(localStorage.getItem("agribot_all_users"));
      return Object.values(users.languageisolationuser.sessions).map(
        (session) => session.lang,
      );
    });
    expect(sessionLanguages.sort()).toEqual(["en", "tw"]);
  });

  test("high-risk advice displays and stores its safety notice", async ({ page }) => {
    await page.goto(BASE + "/index.html");
    await page.fill("#nameInput", "SafetyNoticeUser");
    await page.click(".start-btn");

    await page.fill("#chatInput", "What fertilizer is best for maize?");
    await page.click("#sendBtn");

    const lastBot = page.locator(".message-card.bot-message").last();
    await expect(lastBot).toContainText("Safety note", { timeout: 15000 });
    await expect(lastBot).toContainText("product label");

    const storedSafetyNotice = await page.evaluate(() => {
      const users = JSON.parse(localStorage.getItem("agribot_all_users"));
      const sessions = Object.values(users.safetynoticeuser.sessions);
      const botMessages = sessions[0].messages.filter(
        (message) => message.role === "bot",
      );
      return botMessages.at(-1).text;
    });
    expect(storedSafetyNotice).toContain("Safety note");
  });

  test("history survives refresh and clear starts a new session without data loss", async ({
    page,
  }) => {
    await page.goto(BASE + "/index.html");
    await page.fill("#nameInput", "HistoryAuditUser");
    await page.click(".start-btn");

    await page.fill(
      "#chatInput",
      "How should I prepare the soil before planting maize?",
    );
    await page.click("#sendBtn");
    await expect(page.locator("#enHistory .history-item")).toHaveCount(1, {
      timeout: 15000,
    });

    await page.reload();
    await expect(page.locator("#appShell")).toBeVisible();
    await expect(page.locator("#enHistory .history-item")).toHaveCount(1);
    await page.locator("#enHistory .history-item").click();
    await expect(page.locator(".message-card.bot-message").last()).toContainText(
      /clear the land/i,
    );

    await page.click(".clear-btn");
    await expect(page.locator(".message-card.bot-message")).toHaveCount(0);
    await expect(page.locator("#enHistory .history-item")).toHaveCount(1);

    await page.fill("#chatInput", "What are the signs of good farming soil?");
    await page.click("#sendBtn");
    await expect(page.locator("#enHistory .history-item")).toHaveCount(2, {
      timeout: 15000,
    });

    const sessions = await page.evaluate(() => {
      const users = JSON.parse(localStorage.getItem("agribot_all_users"));
      return Object.values(users.historyaudituser.sessions).map((session) => ({
        lang: session.lang,
        title: session.title,
        messages: session.messages.length,
      }));
    });
    expect(sessions).toHaveLength(2);
    expect(sessions.every((session) => session.lang === "en")).toBeTruthy();
    expect(sessions.every((session) => session.title.length > 0)).toBeTruthy();
    expect(sessions.every((session) => session.messages === 2)).toBeTruthy();
  });
});
