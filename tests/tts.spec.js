const { test, expect } = require("@playwright/test");

const BASE = process.env.TEST_BASE_URL || "http://localhost:8080";

async function enterApp(page, name) {
  await page.goto(BASE + "/index.html");
  await page.fill("#nameInput", name);
  await page.click(".start-btn");
}

async function installSpeechMock(page, voices) {
  await page.addInitScript((availableVoices) => {
    window.__speechTest = {
      speak: 0,
      pause: 0,
      resume: 0,
      cancel: 0,
      lastLang: null,
      lastVoice: null,
      current: null,
    };

    class MockUtterance {
      constructor(text) {
        this.text = text;
        this.lang = "";
        this.voice = null;
      }
    }

    const synth = {
      speaking: false,
      paused: false,
      getVoices: () => availableVoices,
      speak(utterance) {
        window.__speechTest.speak += 1;
        window.__speechTest.lastLang = utterance.lang;
        window.__speechTest.lastVoice = utterance.voice
          ? utterance.voice.name
          : null;
        window.__speechTest.current = utterance;
        this.speaking = true;
        this.paused = false;
        if (utterance.onstart) utterance.onstart();
      },
      pause() {
        window.__speechTest.pause += 1;
        this.paused = true;
        this.speaking = false;
        const utterance = window.__speechTest.current;
        if (utterance && utterance.onpause) utterance.onpause();
      },
      resume() {
        window.__speechTest.resume += 1;
        this.paused = false;
        this.speaking = true;
        const utterance = window.__speechTest.current;
        if (utterance && utterance.onresume) utterance.onresume();
      },
      cancel() {
        window.__speechTest.cancel += 1;
        this.paused = false;
        this.speaking = false;
      },
    };

    Object.defineProperty(window, "SpeechSynthesisUtterance", {
      configurable: true,
      value: MockUtterance,
    });
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: synth,
    });
  }, voices);
}

test.describe("Text-to-speech controls", () => {
  test("supports play, pause, resume, stop, and one active message", async ({
    page,
  }) => {
    await installSpeechMock(page, [{ name: "Ghana English", lang: "en-GH" }]);
    await enterApp(page, "TtsControlsUser");
    await page.evaluate(() => {
      appendMessage("First farming response", "bot", "en");
      appendMessage("Second farming response", "bot", "en");
    });

    const buttons = page.locator(".tts-button");
    const stops = page.locator(".tts-stop");
    await buttons.nth(0).click();
    await expect(buttons.nth(0)).toHaveAttribute("data-state", "playing");
    await buttons.nth(0).click();
    await expect(buttons.nth(0)).toHaveAttribute("data-state", "paused");
    await expect(page.locator(".tts-status").nth(0)).toHaveText("Paused");
    await buttons.nth(0).click();
    await expect(buttons.nth(0)).toHaveAttribute("data-state", "playing");

    await buttons.nth(1).click();
    await expect(buttons.nth(0)).toHaveAttribute("data-state", "idle");
    await expect(buttons.nth(1)).toHaveAttribute("data-state", "playing");
    await stops.nth(1).click();
    await expect(buttons.nth(1)).toHaveAttribute("data-state", "idle");
    await expect(page.locator(".tts-status").nth(1)).toBeHidden();

    const events = await page.evaluate(() => window.__speechTest);
    expect(events.speak).toBe(2);
    expect(events.pause).toBe(1);
    expect(events.resume).toBe(1);
    expect(events.cancel).toBeGreaterThanOrEqual(3);
    expect(events.lastLang).toBe("en-GH");
  });

  test("uses an Akan voice for Twi when available", async ({ page }) => {
    await installSpeechMock(page, [
      { name: "Ghana English", lang: "en-GH" },
      { name: "Akan Voice", lang: "ak-GH" },
    ]);
    await enterApp(page, "TwiVoiceUser");
    await page.evaluate(() => appendMessage("Akwaaba okuafo", "bot", "tw"));
    await page.locator(".tts-button").click();

    const speech = await page.evaluate(() => window.__speechTest);
    expect(speech.lastVoice).toBe("Akan Voice");
    expect(speech.lastLang).toBe("ak-GH");
    await expect(page.locator(".tts-status")).toHaveText("Speaking...");
  });

  test("discloses when Twi must use a fallback voice", async ({ page }) => {
    await installSpeechMock(page, [{ name: "English Voice", lang: "en-GB" }]);
    await enterApp(page, "FallbackVoiceUser");
    await page.evaluate(() => appendMessage("Akwaaba okuafo", "bot", "tw"));
    await page.locator(".tts-button").click();

    await expect(page.locator(".tts-status")).toContainText(
      "Twi pronunciation may be inaccurate",
    );
    const speech = await page.evaluate(() => window.__speechTest);
    expect(speech.lastVoice).toBe("English Voice");
    expect(speech.lastLang).toBe("en-GB");
  });

  test("fails readably when browser speech support is unavailable", async ({
    page,
  }) => {
    await page.addInitScript(() => {
      delete window.speechSynthesis;
      delete window.SpeechSynthesisUtterance;
    });
    await enterApp(page, "NoSpeechUser");
    await page.evaluate(() => appendMessage("Readable response", "bot", "en"));
    const button = page.locator(".tts-button");
    await button.click();
    await expect(button).toBeDisabled();
    await expect(page.locator(".tts-status")).toContainText(
      "Audio is currently unavailable",
    );
  });
});
