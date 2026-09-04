const { test, expect } = require("@playwright/test");

const BASE = process.env.TEST_BASE_URL || "http://localhost:8080";

async function startChat(page, name = "RegressionUser") {
  await page.goto(BASE + "/index.html");
  await page.fill("#nameInput", name);
  await page.click(".start-btn");
  await expect(page.locator("#enChips .chip")).toHaveCount(8);
}

test.describe("one question-submission pipeline", () => {
  test("right-panel click and manual send use the same request shape", async ({
    page,
  }) => {
    await startChat(page);
    const requests = [];
    page.on("request", (request) => {
      if (request.url().endsWith("/api/chat") && request.method() === "POST") {
        requests.push(request.postDataJSON());
      }
    });

    const quickResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/chat") && response.request().method() === "POST",
    );
    await page.locator("#enChips .chip").first().click();
    const quickPayload = await (await quickResponse).json();
    expect(quickPayload.type).toBe("answer");
    expect(quickPayload.source).toBe("retrieval_v1");

    const question = "How should I prepare the soil before planting maize?";
    const manualResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/chat") && response.request().method() === "POST",
    );
    await page.fill("#chatInput", question);
    await page.click("#sendBtn");
    const manualPayload = await (await manualResponse).json();

    expect(requests).toHaveLength(2);
    expect(requests[0].message).toBe(question);
    expect(requests[1].message).toBe(question);
    expect(requests[0].language).toBe("en");
    expect(requests[1].language).toBe("en");
    expect(requests[0]).not.toHaveProperty("suggestion_id");
    expect(requests[1]).not.toHaveProperty("suggestion_id");
    expect(manualPayload.record_id).toBe(quickPayload.record_id);
    expect(manualPayload.text).toBe(quickPayload.text);
  });

  test("bottom, topic, and Twi suggestions submit through the same function", async ({
    page,
  }) => {
    await startChat(page, "AllSuggestionSources");
    const payloads = [];
    page.on("request", (request) => {
      if (request.url().endsWith("/api/chat") && request.method() === "POST") {
        payloads.push(request.postDataJSON());
      }
    });

    await expect(page.locator("#suggestionsList .suggestion-pill").first()).toBeVisible();
    await page.locator("#suggestionsList .suggestion-pill").first().click();
    await expect.poll(() => payloads.length).toBe(1);

    await page.click(".topic-toggle-btn");
    await page.locator('#topicsGridPanel .topic-btn[data-topic="Cassava"]').click();
    await page.locator(".suggestions-wrapper .suggestion-btn").first().click();
    await expect.poll(() => payloads.length).toBe(2);

    await page.click("#twBtn");
    await expect(page.locator("#twChips .chip")).toHaveCount(6);
    await page.locator("#twChips .chip").first().click();
    await expect.poll(() => payloads.length).toBe(3);

    expect(payloads.map((payload) => payload.language)).toEqual(["en", "en", "tw"]);
    for (const payload of payloads) expect(payload).not.toHaveProperty("suggestion_id");
  });
});

test.describe("intelligent theme priority", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      let dark = true;
      const listeners = new Set();
      window.matchMedia = () => ({
        get matches() {
          return dark;
        },
        media: "(prefers-color-scheme: dark)",
        addEventListener: (_name, listener) => listeners.add(listener),
        removeEventListener: (_name, listener) => listeners.delete(listener),
      });
      window.__setSystemDark = (value) => {
        dark = value;
        listeners.forEach((listener) => listener({ matches: dark }));
      };
    });
  });

  test("uses system dark, tracks changes, and preserves manual override", async ({
    page,
  }) => {
    await page.goto(BASE + "/index.html");
    await expect(page.locator("body")).toHaveAttribute("data-theme", "night");
    await expect(page.locator("#themeBtn")).toHaveAttribute(
      "aria-label",
      "Switch to light theme",
    );
    await expect(page.locator("#themeBtn")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#themeBtn")).toHaveAttribute("data-current-theme", "dark");

    await page.evaluate(() => window.__setSystemDark(false));
    await expect(page.locator("body")).not.toHaveAttribute("data-theme", "night");

    await page.fill("#nameInput", "ThemeUser");
    await page.click(".start-btn");
    await page.click("#themeBtn");
    await expect(page.locator("body")).toHaveAttribute("data-theme", "night");
    expect(await page.evaluate(() => localStorage.getItem("agribot_theme_preference"))).toBe(
      "dark",
    );

    await page.evaluate(() => window.__setSystemDark(false));
    await expect(page.locator("body")).toHaveAttribute("data-theme", "night");
    await page.reload();
    await expect(page.locator("body")).toHaveAttribute("data-theme", "night");
  });

  test("uses night-time fallback when system preference is unavailable", async ({
    page,
  }) => {
    await page.addInitScript(() => {
      window.matchMedia = undefined;
      const NativeDate = Date;
      window.Date = class extends NativeDate {
        constructor(...args) {
          super(...(args.length ? args : ["2026-08-21T22:00:00"]));
        }
      };
    });
    await page.goto(BASE + "/index.html");
    await expect(page.locator("body")).toHaveAttribute("data-theme", "night");
  });
});
