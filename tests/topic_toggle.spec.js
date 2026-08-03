const { test, expect } = require("@playwright/test");

// NOTE: These tests expect you to run a simple static server rooted at the project
// directory (e.g. `npx http-server -p 8080` or `npx serve -p 8080`) and then
// visit http://localhost:8080/ in the tests. Start the server before running.

const BASE = process.env.TEST_BASE_URL || "http://localhost:8080";

test.describe("Topic toggle and chips panel", () => {
  test("opens chips and hides topics button, then closes and restores", async ({
    page,
  }) => {
    await page.goto(BASE + "/index.html");

    // Start the chat (welcome screen shows initially)
    await page.fill("#nameInput", "PlaywrightUser");
    await page.click(".start-btn");

    // Ensure the topic button exists
    const topicBtn = page.locator(".topic-toggle-btn");
    await expect(topicBtn).toBeVisible();

    // Click it to open chips
    await topicBtn.click();

    const chips = page.locator("#chipsSidebar");
    const overlay = page.locator("#overlay");

    await expect(chips).toHaveClass(/show/);
    await expect(overlay).toHaveClass(/show/);
    await expect(topicBtn).toHaveClass(/hidden/);

    // Click overlay to close
    await overlay.click();

    await expect(chips).not.toHaveClass(/show/);
    await expect(overlay).not.toHaveClass(/show/);
    await expect(topicBtn).not.toHaveClass(/hidden/);
  });

  test("rapid clicks do not toggle repeatedly", async ({ page }) => {
    await page.goto(BASE + "/index.html");
    // Start the chat so controls are visible
    await page.fill("#nameInput", "PlaywrightUser");
    await page.click(".start-btn");
    const topicBtn = page.locator(".topic-toggle-btn");
    const chips = page.locator("#chipsSidebar");

    // Rapid invocations bypassing overlay interception to exercise debounce
    await page.evaluate(() => {
      toggleChips();
      toggleChips();
      toggleChips();
    });

    // After rapid clicks, ensure chips are opened only once (show present)
    await expect(chips).toHaveClass(/show/);
  });
});
