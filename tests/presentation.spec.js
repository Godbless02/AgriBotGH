const { test, expect } = require("@playwright/test");
const fs = require("fs");
const path = require("path");

const BASE = process.env.TEST_BASE_URL || "http://localhost:8080";
const ROOT = path.resolve(__dirname, "..");
const SET_PATH = path.join(
  ROOT,
  "data",
  "evaluation",
  "final_presentation_test_set.json",
);
const REPORT_PATH = path.join(ROOT, "models", "presentation_test_results.json");

test("executes all 10 presentation TTS cases and completes the 80-case report", async ({
  page,
}) => {
  await page.route("**/api/tts", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        success: false,
        code: "disabled_for_automated_test",
        fallback_allowed: true,
      }),
    });
  });
  await page.addInitScript(() => {
    window.__presentationSpeech = { speak: 0, cancel: 0, lastLang: null };
    class MockUtterance {
      constructor(text) {
        this.text = text;
        this.lang = "";
        this.voice = null;
      }
    }
    const voices = [
      { name: "English Ghana", lang: "en-GH" },
      { name: "Akan Ghana", lang: "ak-GH" },
    ];
    const synth = {
      getVoices: () => voices,
      speak(utterance) {
        window.__presentationSpeech.speak += 1;
        window.__presentationSpeech.lastLang = utterance.lang;
        if (utterance.onstart) utterance.onstart();
      },
      cancel() {
        window.__presentationSpeech.cancel += 1;
      },
      pause() {},
      resume() {},
    };
    Object.defineProperty(window, "SpeechSynthesisUtterance", {
      configurable: true,
      value: MockUtterance,
    });
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: synth,
    });
  });

  const testSet = JSON.parse(fs.readFileSync(SET_PATH, "utf8"));
  const cases = testSet.cases.filter((item) => item.group === "tts");
  expect(cases).toHaveLength(10);

  await page.goto(BASE + "/index.html");
  await page.fill("#nameInput", "PresentationTtsUser");
  await page.click(".start-btn");
  const results = [];

  for (const item of cases) {
    const before = await page.evaluate(() => window.__presentationSpeech.speak);
    await page.evaluate(
      ({ message, language }) => appendMessage(message, "bot", language),
      { message: item.message, language: item.language },
    );
    expect(await page.evaluate(() => window.__presentationSpeech.speak)).toBe(
      before,
    );
    const button = page.locator(".tts-button").last();
    await expect(button).toHaveAttribute("data-language", item.language);
    await button.click();
    await expect(button).toHaveAttribute("data-state", "playing");
    const actualLang = await page.evaluate(
      () => window.__presentationSpeech.lastLang,
    );
    expect(actualLang).toBe(item.language === "tw" ? "ak-GH" : "en-GH");
    results.push({
      id: item.id,
      group: "tts",
      passed: true,
      failures: [],
      actual: {
        manual_start: true,
        message_language: item.language,
        voice_language: actualLang,
      },
    });
  }

  await page.locator(".tts-stop").last().click();
  const report = JSON.parse(fs.readFileSync(REPORT_PATH, "utf8"));
  const backendResults = report.results.filter((item) => item.group !== "tts");
  report.results = [...backendResults, ...results];
  report.browser_completed_at_utc = new Date().toISOString();
  report.summary.tts_passed = 10;
  report.summary.tts_failed = 0;
  report.summary.tts_pending_browser = 0;
  report.summary.total_passed = report.summary.backend_passed + 10;
  report.summary.complete =
    report.summary.backend_failed === 0 && report.summary.total_passed === 80;
  fs.writeFileSync(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");

  expect(report.summary.complete).toBeTruthy();
  expect(report.summary.total_passed).toBe(80);
});
