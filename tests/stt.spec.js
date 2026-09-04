const { test, expect } = require("@playwright/test");

const BASE = process.env.TEST_BASE_URL || "http://localhost:8080";

async function installRecognitionMock(page, { standard = false, withTts = false } = {}) {
  await page.addInitScript(({ useStandard, includeTts }) => {
    delete window.SpeechRecognition;
    delete window.webkitSpeechRecognition;

    window.__sttTest = {
      instances: [],
      starts: 0,
      stops: 0,
      aborts: 0,
      speakCancels: 0,
      latest() {
        return this.instances[this.instances.length - 1];
      },
      result(text, final = true) {
        const recognition = this.latest();
        const result = [{ transcript: text, confidence: 0.9 }];
        result.isFinal = final;
        recognition.onresult({ results: [result], resultIndex: 0 });
      },
      error(code) {
        const recognition = this.latest();
        recognition.onerror({ error: code, message: "raw details must stay hidden" });
      },
      end() {
        const recognition = this.latest();
        if (recognition.onend) recognition.onend();
      },
    };

    class MockRecognition {
      constructor() {
        this.lang = "";
        this.continuous = true;
        this.interimResults = true;
        this.maxAlternatives = 0;
        this.started = false;
        window.__sttTest.instances.push(this);
      }
      start() {
        if (this.started) throw new Error("recognition has already started");
        this.started = true;
        window.__sttTest.starts += 1;
        if (this.onstart) this.onstart();
      }
      stop() {
        window.__sttTest.stops += 1;
      }
      abort() {
        window.__sttTest.aborts += 1;
      }
    }

    Object.defineProperty(
      window,
      useStandard ? "SpeechRecognition" : "webkitSpeechRecognition",
      { configurable: true, value: MockRecognition },
    );

    if (includeTts) {
      class MockUtterance {}
      Object.defineProperty(window, "SpeechSynthesisUtterance", {
        configurable: true,
        value: MockUtterance,
      });
      Object.defineProperty(window, "speechSynthesis", {
        configurable: true,
        value: {
          getVoices: () => [{ name: "English", lang: "en-GH" }],
          speak: () => {},
          pause: () => {},
          resume: () => {},
          cancel: () => { window.__sttTest.speakCancels += 1; },
          addEventListener: () => {},
        },
      });
    }
  }, { useStandard: standard, includeTts: withTts });
}

async function enterApp(page, name = "SttUser") {
  await page.goto(BASE + "/index.html");
  await page.fill("#nameInput", `${name}${Date.now()}`);
  await page.click(".start-btn");
  await expect(page.locator("#chatInput")).toBeVisible();
}

test.describe("Browser-native speech-to-text", () => {
  test("initializes the standard API and starts only after a user action", async ({ page }) => {
    await installRecognitionMock(page, { standard: true });
    await enterApp(page, "StandardApi");
    expect(await page.evaluate(() => window.__sttTest.instances.length)).toBe(0);
    await expect(page.locator("#micBtn")).toBeEnabled();

    await page.click("#micBtn");
    const state = await page.evaluate(() => {
      const recognition = window.__sttTest.latest();
      return {
        starts: window.__sttTest.starts,
        lang: recognition.lang,
        continuous: recognition.continuous,
        interimResults: recognition.interimResults,
        maxAlternatives: recognition.maxAlternatives,
      };
    });
    expect(state).toEqual({
      starts: 1,
      lang: "en-GH",
      continuous: false,
      interimResults: false,
      maxAlternatives: 1,
    });
    await expect(page.locator("#micBtn")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#sttStatus")).toContainText("Listening");
  });

  test("uses the prefixed API and leaves typing available when unsupported", async ({ page }) => {
    await installRecognitionMock(page);
    await enterApp(page, "PrefixedApi");
    await page.click("#micBtn");
    expect(await page.evaluate(() => window.__sttTest.starts)).toBe(1);

    const unsupported = await page.context().newPage();
    await unsupported.addInitScript(() => {
      delete window.SpeechRecognition;
      delete window.webkitSpeechRecognition;
    });
    await unsupported.goto(BASE + "/index.html");
    await expect(unsupported.locator("#chatInput")).toBeVisible();
    await expect(unsupported.locator("#micBtn")).toBeDisabled();
    await expect(unsupported.locator("#sttStatus")).toContainText("not supported");
    await unsupported.fill("#chatInput", "Typed questions still work");
    await expect(unsupported.locator("#chatInput")).toHaveValue("Typed questions still work");
  });

  test("puts final speech into the editable input and never auto-submits", async ({ page }) => {
    await installRecognitionMock(page);
    let chatRequests = 0;
    await page.route("**/api/chat", async (route) => {
      chatRequests += 1;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ type: "answer", text: "Dataset answer", language: "en" }),
      });
    });
    await enterApp(page, "EditableTranscript");
    await page.click("#micBtn");
    await page.evaluate(() => {
      window.__sttTest.result("What fertilizer is best for maize?");
      window.__sttTest.end();
    });

    await expect(page.locator("#chatInput")).toHaveValue("What fertilizer is best for maize?");
    expect(chatRequests).toBe(0);
    await page.fill("#chatInput", "What fertilizer is best for maize in Ghana?");
    await page.click("#sendBtn");
    await expect.poll(() => chatRequests).toBe(1);
    await expect(page.locator(".user-message .bubble").last()).toContainText("in Ghana");
  });

  test("weather wording is ordinary text until Send uses the existing chat request", async ({ page }) => {
    await installRecognitionMock(page);
    const payloads = [];
    await page.route("**/api/chat", async (route) => {
      payloads.push(route.request().postDataJSON());
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ type: "answer", text: "Existing routing response", language: "en" }),
      });
    });
    await enterApp(page, "WeatherSpeech");
    await page.click("#micBtn");
    await page.evaluate(() => {
      window.__sttTest.result("Will it rain tomorrow in Kumasi?");
      window.__sttTest.end();
    });
    expect(payloads).toHaveLength(0);
    await page.click("#sendBtn");
    await expect.poll(() => payloads.length).toBe(1);
    expect(payloads[0]).toMatchObject({
      message: "Will it rain tomorrow in Kumasi?",
      language: "en",
    });
    expect(payloads[0]).not.toHaveProperty("audio");
    expect(payloads[0]).not.toHaveProperty("speech");
  });

  for (const [code, message] of [
    ["not-allowed", "permission was denied"],
    ["service-not-allowed", "not allowed"],
    ["audio-capture", "No working microphone"],
    ["no-speech", "couldn't hear"],
    ["network", "service is unavailable"],
    ["language-not-supported", "not available"],
    ["unexpected-provider-code", "could not complete"],
  ]) {
    test(`handles ${code} without exposing raw browser errors`, async ({ page }) => {
      await installRecognitionMock(page);
      await enterApp(page, `Error${code}`);
      await page.click("#micBtn");
      await page.evaluate((errorCode) => window.__sttTest.error(errorCode), code);
      await expect(page.locator("#sttStatus")).toContainText(message);
      await expect(page.locator("#sttStatus")).not.toContainText("raw details");
      await expect(page.locator("#micBtn")).toBeEnabled();
      await expect(page.locator("#chatInput")).toBeEditable();
    });
  }

  test("the same control stops cleanly and prevents duplicate starts", async ({ page }) => {
    await installRecognitionMock(page);
    await enterApp(page, "StopDuplicate");
    await page.click("#micBtn");
    await page.click("#micBtn");
    expect(await page.evaluate(() => window.__sttTest.starts)).toBe(1);
    expect(await page.evaluate(() => window.__sttTest.stops)).toBe(1);
    await expect(page.locator("#micBtn")).toHaveAttribute("data-state", "stopping");
    await page.evaluate(() => window.__sttTest.end());
    await expect(page.locator("#micBtn")).toHaveAttribute("data-state", "idle");
  });

  test("language changes and chat reset abort recognition; Twi stays honestly disabled", async ({ page }) => {
    await installRecognitionMock(page);
    await enterApp(page, "LifecycleReset");
    await page.click("#micBtn");
    await page.click("#twBtn");
    expect(await page.evaluate(() => window.__sttTest.aborts)).toBe(1);
    await expect(page.locator("#micBtn")).toBeDisabled();
    await expect(page.locator("#sttStatus")).toContainText("Twi voice input is not available");

    await page.click("#enBtn");
    await page.click("#micBtn");
    await page.evaluate(() => clearChat());
    expect(await page.evaluate(() => window.__sttTest.aborts)).toBe(2);
    await expect(page.locator("#micBtn")).toHaveAttribute("data-state", "idle");
  });

  test("submitting aborts recognition and still uses only the existing pipeline", async ({ page }) => {
    await installRecognitionMock(page);
    await page.route("**/api/chat", (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ type: "answer", text: "Existing answer", language: "en" }),
    }));
    await enterApp(page, "SubmitStops");
    await page.fill("#chatInput", "How can I control fall armyworm?");
    await page.click("#micBtn");
    await page.click("#sendBtn");
    expect(await page.evaluate(() => window.__sttTest.aborts)).toBe(1);
    await expect(page.locator(".user-message .bubble")).toContainText("fall armyworm");
  });

  test("starting the microphone cancels active TTS", async ({ page }) => {
    await installRecognitionMock(page, { withTts: true });
    await enterApp(page, "TtsCoexistence");
    await page.evaluate(() => appendMessage("A spoken farming answer", "bot", "en"));
    await page.locator(".tts-button").click();
    const before = await page.evaluate(() => window.__sttTest.speakCancels);
    await page.click("#micBtn");
    expect(await page.evaluate(() => window.__sttTest.speakCancels)).toBeGreaterThan(before);
    expect(await page.evaluate(() => window.__sttTest.starts)).toBe(1);
  });

  test("starting TTS aborts microphone recognition", async ({ page }) => {
    await installRecognitionMock(page, { withTts: true });
    await enterApp(page, "RecognitionStopsForTts");
    await page.evaluate(() => appendMessage("A bot response", "bot", "en"));
    await page.click("#micBtn");
    await page.locator(".tts-button").click();
    expect(await page.evaluate(() => window.__sttTest.aborts)).toBe(1);
  });

  test("microphone control remains accessible, responsive, and readable in dark mode", async ({ page }) => {
    await installRecognitionMock(page);
    await page.setViewportSize({ width: 375, height: 844 });
    await enterApp(page, "AccessibleMobile");
    await page.click("#themeBtn");
    const state = await page.locator("#micBtn").evaluate((button) => {
      const box = button.getBoundingClientRect();
      const style = getComputedStyle(button);
      return {
        label: button.getAttribute("aria-label"),
        width: box.width,
        height: box.height,
        right: box.right,
        color: style.color,
        background: style.backgroundColor,
        viewport: document.documentElement.clientWidth,
        documentWidth: document.documentElement.scrollWidth,
      };
    });
    expect(state.label).toBe("Speak your question");
    expect(state.width).toBeGreaterThanOrEqual(44);
    expect(state.height).toBeGreaterThanOrEqual(44);
    expect(state.right).toBeLessThanOrEqual(state.viewport + 1);
    expect(state.documentWidth).toBeLessThanOrEqual(state.viewport);
    expect(state.color).not.toBe(state.background);
  });
});
