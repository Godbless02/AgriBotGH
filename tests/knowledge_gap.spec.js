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

test("State D renders dataset topics and a click edits rather than submits", async ({
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
  await expect(page.locator(".knowledge-gap-topic-btn")).toHaveCount(40);

  const messageCount = await page.locator(".message-card").count();
  const maize = page.locator('.knowledge-gap-topic-btn[data-topic="Maize"]');
  await expect(maize).toHaveAttribute("type", "button");
  await maize.click();
  await expect(page.locator("#chatInput")).toHaveValue("Maize");
  await expect(page.locator("#chatInput")).toBeFocused();
  await expect(page.locator(".message-card")).toHaveCount(messageCount);
});

test("Twi State D stays localized and uses the same editable topic behavior", async ({
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
  await expect(maize).toContainText("Aburoɔ — Maize");
  await maize.click();
  await expect(page.locator("#chatInput")).toHaveValue("Aburoɔ — Maize");
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
  const play = page.locator(".message-card.bot-message").last().locator(".tts-button");
  await expect(play).toBeEnabled();
  await play.click();
  await expect.poll(() => page.evaluate(() => window.__gapSpeechCount)).toBe(1);
});
