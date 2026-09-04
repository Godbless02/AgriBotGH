const { test, expect } = require("@playwright/test");

const BASE = process.env.TEST_BASE_URL || "http://localhost:8080";

const weatherPayload = {
  success: true,
  location: { name: "Kumasi", admin1: "Ashanti", country: "Ghana", latitude: 6.6885, longitude: -1.6244, timezone: "Africa/Accra" },
  current: { temperature: 28.4, humidity: 74, precipitation: 0.2, wind_speed: 9.6, weather_code: 61, condition: "Light rain", rain_probability: 70 },
  forecast: [
    { date: "2026-08-30", temperature_max: 30, temperature_min: 21, precipitation_probability: 70, precipitation_sum: 3, weather_code: 61, condition: "Light rain" },
    { date: "2026-08-31", temperature_max: 29, temperature_min: 20, precipitation_probability: 45, precipitation_sum: 1, weather_code: 2, condition: "Partly cloudy" },
    { date: "2026-09-01", temperature_max: 31, temperature_min: 21, precipitation_probability: 20, precipitation_sum: 0, weather_code: 1, condition: "Mostly clear" },
  ],
  units: { temperature: "°C", humidity: "%", precipitation: "mm", wind_speed: "km/h", precipitation_probability: "%" },
  source: "Open-Meteo",
  guidance: "Weather forecasts can change."
};

async function enterApp(page, name) {
  await page.goto(BASE + "/index.html");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.fill("#nameInput", name);
  await page.click(".start-btn");
}

test("farmer can retrieve current Kumasi weather and a three-day forecast", async ({ page }) => {
  let requestedLocation = "";
  await page.route("**/api/weather?*", async (route) => {
    requestedLocation = new URL(route.request().url()).searchParams.get("location");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(weatherPayload) });
  });
  await enterApp(page, "WeatherFarmer");

  const chatWidth = await page.locator(".chat-area").evaluate((element) => element.getBoundingClientRect().width);
  await page.click("#weatherBtn");
  await expect(page.locator("#weatherPanel")).toBeVisible();
  expect(await page.locator(".chat-area").evaluate((element) => element.getBoundingClientRect().width)).toBe(chatWidth);
  await page.fill("#weatherLocation", "Kumasi");
  await page.click("#weatherSubmit");

  await expect(page.locator("#weatherPlace")).toContainText("Kumasi, Ashanti, Ghana");
  await expect(page.locator("#weatherCondition")).toHaveText("Light rain");
  await expect(page.locator(".weather-metric")).toHaveCount(5);
  await expect(page.locator(".weather-day")).toHaveCount(3);
  await expect(page.locator("#weatherGuidance")).toContainText("Protect harvested produce");
  expect(requestedLocation).toBe("Kumasi");
});

test("weather errors are friendly and do not affect chat", async ({ page }) => {
  await page.route("**/api/weather?*", (route) => route.fulfill({
    status: 404,
    contentType: "application/json",
    body: JSON.stringify({ success: false, code: "location_not_found", error: "Location could not be found. Try adding the region or country." })
  }));
  await enterApp(page, "WeatherErrorFarmer");
  await page.click("#weatherBtn");
  await page.fill("#weatherLocation", "Unknown farm");
  await page.click("#weatherSubmit");
  await expect(page.locator("#weatherStatus")).toContainText("Location could not be found");
  await page.keyboard.press("Escape");
  await expect(page.locator("#weatherOverlay")).toBeHidden();
  await expect(page.locator("#chatInput")).toBeVisible();
});

test("static-server responses identify the missing Flask backend", async ({ page }) => {
  await page.route("**/api/weather?*", (route) => route.fulfill({
    status: 404, contentType: "text/html", body: "<html>Not found</html>"
  }));
  await enterApp(page, "MissingBackendFarmer");
  await page.click("#weatherBtn");
  await page.fill("#weatherLocation", "Accra");
  await page.click("#weatherSubmit");
  await expect(page.locator("#weatherStatus")).toContainText("weather API is not running");
  await expect(page.locator("#weatherStatus")).not.toContainText("Location");
});

test("weather panel is responsive and follows the Twi interface", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/weather?*", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(weatherPayload)
  }));
  await enterApp(page, "TwiWeatherFarmer");
  await page.click(".mobile-menu-btn");
  await page.click("#twBtn");
  await page.locator("#overlay").click({ position: { x: 380, y: 10 } });
  await page.click("#weatherBtn");
  await expect(page.locator("#weatherTitle")).toHaveText("Mpɔtam ewiem tebea");
  await expect(page.locator("#weatherLocation")).toHaveAttribute("placeholder", "sɛ nhwɛso: Kumasi");
  const panel = await page.locator("#weatherPanel").boundingBox();
  expect(panel.width).toBeLessThanOrEqual(390);
  await page.fill("#weatherLocation", "Kumasi");
  await page.click("#weatherSubmit");
  await expect(page.locator("#weatherCondition")).toHaveText("Osu kakra");
  await expect(page.locator(".weather-day")).toHaveCount(3);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBeTruthy();
});
