const { test, expect } = require("@playwright/test");

const BASE = process.env.TEST_BASE_URL || "http://localhost:8080";

async function enterApp(page, name) {
  await page.goto(BASE + "/index.html");
  await page.fill("#nameInput", name);
  await page.click(".start-btn");
}

async function submitGapQuestion(page, question) {
  await page.fill("#chatInput", question);
  await page.click("#sendBtn");
  await expect(page.locator(".knowledge-gap-topics")).toBeVisible({
    timeout: 15000,
  });
}

test("State D topic click loads canonical suggestions without editing input", async ({
  page,
}) => {
  await enterApp(page, "GapUser");
  await submitGapQuestion(page, "How do I manage alpacas on a farm?");

  await expect(page.locator(".message-card.bot-message").last()).toContainText(
    "couldn't find a sufficiently reliable answer",
  );
  await expect(page.locator(".knowledge-gap-heading")).toHaveText(
    "Topics I can currently help with",
  );
  await expect(page.locator(".knowledge-gap-topic-btn")).toHaveCount(28);

  await page.fill("#chatInput", "keep this draft");
  const requestPromise = page.waitForRequest((request) =>
    request.url().endsWith("/api/topic-suggestions") &&
    request.postDataJSON().topic === "Pepper"
  );
  const pepper = page.locator('.knowledge-gap-topic-btn[data-topic="Pepper"]');
  await expect(pepper).toHaveAttribute("type", "button");
  await pepper.click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({ topic: "Pepper", lang: "en" });
  await expect(page.locator("#chatInput")).toHaveValue("keep this draft");
  const suggestions = page.locator(".suggestions-wrapper .suggestion-btn");
  await expect(suggestions).toHaveCount(5);
  await expect(page.locator(".message-card.bot-message").last()).toContainText(
    "You selected",
  );

  await suggestions.first().click();
  await expect(page.locator(".message-card.user-message").last()).toContainText(/.+/);
  await expect(page.locator(".message-card.bot-message").last()).toContainText(
    /.+/,
    { timeout: 15000 },
  );
});

test("Twi State D topic click loads Twi suggestions without editing input", async ({
  page,
}) => {
  await enterApp(page, "TwiGapUser");
  await page.click("#twBtn");
  await submitGapQuestion(page, "Mɛyɛ dɛn na mafi ostrich kuayɛ ase?");

  await expect(page.locator(".message-card.bot-message").last()).toContainText(
    "Mete ase sɛ eyi yɛ kuayɛ ho asɛmmisa",
  );
  await expect(page.locator(".knowledge-gap-heading")).toHaveText(
    "Kuayɛ nsɛm a metumi aboa wo wɔ ho",
  );
  const maize = page.locator('.knowledge-gap-topic-btn[data-topic="Maize"]');
  await expect(maize).toContainText("Aburoɔ");
  await page.fill("#chatInput", "Twi draft");
  const requestPromise = page.waitForRequest((request) =>
    request.url().endsWith("/api/topic-suggestions") &&
    request.postDataJSON().topic === "Maize"
  );
  await maize.click();
  expect((await requestPromise).postDataJSON()).toEqual({ topic: "Maize", lang: "tw" });
  await expect(page.locator("#chatInput")).toHaveValue("Twi draft");
  await expect(page.locator(".suggestions-wrapper .suggestion-btn")).toHaveCount(5);
  await expect(page.locator(".message-card.bot-message").last()).toContainText("Wapaw");
});

test("State D is readable on mobile and dark mode and remains TTS-playable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    window.__gapSpeechCount = 0;
    class MockUtterance {
      constructor(text) {
        this.text = text;
        this.lang = "";
      }
    }
    const synth = {
      speaking: false,
      paused: false,
      getVoices: () => [{ name: "English", lang: "en-GB", default: true }],
      addEventListener: () => {},
      cancel: () => {},
      pause: () => {},
      resume: () => {},
      speak: (utterance) => {
        window.__gapSpeechCount += 1;
        if (utterance.onstart) utterance.onstart();
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
  });
  await enterApp(page, "MobileGapUser");
  await page.click(".theme-btn");
  await expect(page.locator("body")).toHaveAttribute("data-theme", "night");
  await submitGapQuestion(page, "What feed is suitable for ostriches?");

  const overflow = await page.locator(".knowledge-gap-topics").evaluate((element) =>
    element.scrollWidth > element.clientWidth,
  );
  expect(overflow).toBeFalsy();
  await page.fill("#chatInput", "mobile draft");
  await page.locator('.knowledge-gap-topic-btn[data-topic="Pepper"]').click();
  await expect(page.locator("#chatInput")).toHaveValue("mobile draft");
  await expect(page.locator(".suggestions-wrapper .suggestion-btn")).toHaveCount(5);
  await expect(page.locator(".topic-toggle-btn")).toBeVisible();
  await expect(page.locator("#sendBtn")).toBeVisible();
  const play = page.locator(".message-card.bot-message").last().locator(".tts-button");
  await expect(play).toBeEnabled();
  await play.click();
  await expect.poll(() => page.evaluate(() => window.__gapSpeechCount)).toBe(1);
});
