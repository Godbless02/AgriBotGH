const { test, expect } = require("@playwright/test");

const BASE = process.env.TEST_BASE_URL || "http://localhost:8080";
const MOBILE_VIEWPORTS = [
  { width: 360, height: 800 },
  { width: 390, height: 844 },
];

const weatherPayload = {
  success: true,
  location: { name: "Kumasi", admin1: "Ashanti", country: "Ghana" },
  current: {
    temperature: 28.4, humidity: 74, precipitation: 0.2,
    wind_speed: 9.6, weather_code: 61, condition: "Light rain",
    rain_probability: 70,
  },
  forecast: [
    { date: "2026-09-05", temperature_max: 30, temperature_min: 21, precipitation_probability: 70, precipitation_sum: 3, weather_code: 61, condition: "Light rain" },
    { date: "2026-09-06", temperature_max: 29, temperature_min: 20, precipitation_probability: 45, precipitation_sum: 1, weather_code: 2, condition: "Partly cloudy" },
    { date: "2026-09-07", temperature_max: 31, temperature_min: 21, precipitation_probability: 20, precipitation_sum: 0, weather_code: 1, condition: "Mostly clear" },
  ],
  units: { temperature: "°C", humidity: "%", precipitation: "mm", wind_speed: "km/h", precipitation_probability: "%" },
  source: "Open-Meteo",
};

async function installRecognitionMock(page, { accelerateStatus = false } = {}) {
  await page.addInitScript(({ accelerate }) => {
    delete window.SpeechRecognition;
    delete window.webkitSpeechRecognition;
    window.__mobileStt = { starts: 0, requestedDelays: [] };
    class MockRecognition {
      start() { window.__mobileStt.starts += 1; }
      stop() {}
      abort() {}
    }
    Object.defineProperty(window, "webkitSpeechRecognition", {
      configurable: true,
      value: MockRecognition,
    });
    if (accelerate) {
      const nativeSetTimeout = window.setTimeout.bind(window);
      window.setTimeout = (callback, delay, ...args) => {
        if (delay === 8000) window.__mobileStt.requestedDelays.push(delay);
        return nativeSetTimeout(callback, delay === 8000 ? 100 : delay, ...args);
      };
    }
  }, { accelerate: accelerateStatus });
}

async function enterApp(page, name) {
  await page.goto(BASE + "/index.html");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.fill("#nameInput", name);
  await page.click(".start-btn");
  await expect(page.locator("#chatInput")).toBeVisible();
}

async function switchToTwi(page) {
  await page.click(".mobile-menu-btn");
  await page.click("#twBtn");
  await page.locator("#overlay").click({ position: { x: 350, y: 10 } });
}

for (const viewport of MOBILE_VIEWPORTS) {
  test(`mobile controls and suggestions fit at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await enterApp(page, `MobileFit${viewport.width}`);

    const weatherIcon = (await page.locator("#weatherBtn span").first().textContent()).trim();
    const initialThemeIcon = (await page.locator("#themeBtn").textContent()).trim();
    expect(weatherIcon).toBe("🌦️");
    expect(weatherIcon).not.toBe(initialThemeIcon);
    await page.click("#themeBtn");
    await expect(page.locator("body")).toHaveAttribute("data-theme", "night");
    expect((await page.locator("#themeBtn").textContent()).trim()).toBe("☀️");
    expect(weatherIcon).not.toBe((await page.locator("#themeBtn").textContent()).trim());

    const assertSuggestionsFit = async () => {
      await expect(page.locator("#suggestionsList .suggestion-pill").first()).toBeVisible();
      const result = await page.locator("#suggestionsList .suggestion-pill").evaluateAll((pills) => ({
        viewportWidth: document.documentElement.clientWidth,
        documentWidth: document.documentElement.scrollWidth,
        pills: pills.map((pill) => {
          const box = pill.getBoundingClientRect();
          return {
            left: box.left,
            right: box.right,
            textFits: pill.scrollWidth <= pill.clientWidth + 1,
            wraps: getComputedStyle(pill).whiteSpace === "normal",
          };
        }),
      }));
      expect(result.documentWidth).toBeLessThanOrEqual(result.viewportWidth);
      for (const pill of result.pills) {
        expect(pill.left).toBeGreaterThanOrEqual(-1);
        expect(pill.right).toBeLessThanOrEqual(result.viewportWidth + 1);
        expect(pill.textFits).toBeTruthy();
        expect(pill.wraps).toBeTruthy();
      }
    };

    await assertSuggestionsFit();
    await switchToTwi(page);
    await assertSuggestionsFit();
  });
}

test("mobile weather close remains visible after panel scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.route("**/api/weather?*", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(weatherPayload),
  }));
  await enterApp(page, "StickyWeather");
  await page.click("#weatherBtn");
  await page.fill("#weatherLocation", "Kumasi");
  await page.click("#weatherSubmit");
  await expect(page.locator(".weather-day")).toHaveCount(3);
  await page.locator("#weatherResults").evaluate((results) => {
    const spacer = document.createElement("div");
    spacer.style.height = "900px";
    spacer.setAttribute("data-test-spacer", "");
    results.appendChild(spacer);
  });
  await page.locator("#weatherPanel").evaluate((panel) => { panel.scrollTop = panel.scrollHeight; });

  const closeBox = await page.locator(".weather-close").boundingBox();
  expect(closeBox.y).toBeGreaterThanOrEqual(0);
  expect(closeBox.y + closeBox.height).toBeLessThanOrEqual(800);
  expect(closeBox.width).toBeGreaterThanOrEqual(44);
  expect(closeBox.height).toBeGreaterThanOrEqual(44);
  await page.click(".weather-close");
  await expect(page.locator("#weatherOverlay")).toBeHidden();
  await expect(page.locator("#chatInput")).toBeVisible();
});

test("Twi microphone explains its unavailable state only after mobile activation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installRecognitionMock(page, { accelerateStatus: true });
  await enterApp(page, "TwiMobileMic");
  await switchToTwi(page);

  const mic = page.locator("#micBtn");
  expect(await mic.evaluate((button) => button.disabled)).toBeFalsy();
  await expect(mic).toHaveAttribute("aria-disabled", "true");
  await expect(page.locator("#sttStatus")).toBeHidden();
  await mic.dispatchEvent("click");
  await expect(page.locator("#sttStatus")).toContainText("Twi voice input is not available");
  expect(await page.evaluate(() => window.__mobileStt.starts)).toBe(0);
  expect(await page.evaluate(() => window.__mobileStt.requestedDelays)).toContain(8000);
  await expect(page.locator("#sttStatus")).toBeHidden();
});

test("desktop hover and keyboard focus explain Twi STT, then English STT is restored", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await installRecognitionMock(page);
  await enterApp(page, "TwiDesktopMic");
  await page.click("#twBtn");
  await expect(page.locator("#sttStatus")).toBeHidden();

  const mic = page.locator("#micBtn");
  await mic.hover();
  await expect(page.locator("#sttStatus")).toContainText("Twi voice input is not available");
  await page.locator("#chatInput").hover();
  await expect(page.locator("#sttStatus")).toBeHidden();
  await mic.focus();
  await expect(page.locator("#sttStatus")).toContainText("Twi voice input is not available");
  await page.locator("#chatInput").focus();
  await expect(page.locator("#sttStatus")).toBeHidden();

  await page.click("#enBtn");
  await expect(mic).not.toHaveAttribute("aria-disabled", "true");
  await expect(mic).toHaveAttribute("aria-label", "Speak your question");
  await mic.click();
  await expect.poll(() => page.evaluate(() => window.__mobileStt.starts)).toBe(1);
});
