const { test, expect } = require("@playwright/test");

const BASE = process.env.TEST_BASE_URL || "http://localhost:5000";
const RUN_LIVE = process.env.RUN_LIVE_WEATHER === "1";

test("live Flask UI geocodes multiple locations and rejects an invalid one", async ({ page }) => {
  test.skip(!RUN_LIVE, "Set RUN_LIVE_WEATHER=1 to call Open-Meteo through Flask.");
  test.setTimeout(90000);

  await page.goto(BASE + "/index.html");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.fill("#nameInput", "LiveWeatherVerification");
  await page.click(".start-btn");
  await page.click("#weatherBtn");

  for (const location of ["Kumasi", "Accra", "Tamale", "Sunyani", "Wenchi", "Cape Coast", "London"]) {
    await page.fill("#weatherLocation", location);
    const [response] = await Promise.all([
      page.waitForResponse((item) => item.url().includes("/api/weather?") && item.url().includes(encodeURIComponent(location))),
      page.click("#weatherSubmit"),
    ]);
    expect(response.status(), `${location} endpoint status`).toBe(200);
    await expect(page.locator("#weatherPlace"), `${location} result`).toContainText(location);
    await expect(page.locator(".weather-metric")).toHaveCount(5);
    await expect(page.locator(".weather-day")).toHaveCount(3);
  }

  await page.fill("#weatherLocation", "asdfghxyz123");
  const [invalidResponse] = await Promise.all([
    page.waitForResponse((item) => item.url().includes("/api/weather?")),
    page.click("#weatherSubmit"),
  ]);
  expect(invalidResponse.status()).toBe(404);
  await expect(page.locator("#weatherStatus")).toContainText("couldn't find that location");
});
