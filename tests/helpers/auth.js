const { expect } = require("@playwright/test");

async function mockAuthenticatedUser(page, options = {}) {
  const user = {
    id: options.id || "test-user-1",
    username: options.username || "Test Farmer",
    preferred_language: options.preferred_language || "en",
  };
  await page.route("**/api/auth/me", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ authenticated: true, user }),
  }));
  return user;
}

async function enterAuthenticatedApp(page, options = {}) {
  const user = await mockAuthenticatedUser(page, options);
  await page.goto((options.base || process.env.TEST_BASE_URL || "http://localhost:8080") + "/index.html");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#userBadge")).toContainText(user.username);
  return user;
}

module.exports = { mockAuthenticatedUser, enterAuthenticatedApp };
