const { test, expect } = require("@playwright/test");

const BASE = process.env.TEST_BASE_URL || "http://localhost:8080";
const WIDTHS = [1920, 1440, 1366, 1280, 1024, 768, 480, 390, 375];

for (const width of WIDTHS) {
  test(`complete chat layout remains usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({
      width,
      height: width <= 768 ? 844 : 900,
    });
    await page.goto(BASE + "/index.html");
    await page.fill("#nameInput", `Responsive${width}`);
    await page.click(".start-btn");

    await expect(page.locator("#chatInput")).toBeVisible();
    await expect(page.locator("#micBtn")).toBeVisible();
    await expect(page.locator("#sendBtn")).toBeVisible();
    await expect(page.locator(".topic-toggle-btn")).toBeVisible();
    await expect(page.locator("#suggestionsList .suggestion-pill").first()).toBeVisible({
      timeout: 15000,
    });

    await page.evaluate(() =>
      appendMessage(
        "A practical farming response with enough text to verify wrapping and speech controls.",
        "bot",
        "en",
      ),
    );
    await expect(page.locator(".tts-button")).toBeVisible();

    const horizontalFit = await page.evaluate(() => {
      const viewportWidth = document.documentElement.clientWidth;
      const selectors = [
        ".topbar",
        ".chat-area",
        ".input-bar",
        "#chatInput",
        "#micBtn",
        "#sendBtn",
        ".topic-toggle-btn",
        ".suggestions-bar",
        ".tts-controls",
      ];
      const outOfBounds = selectors.filter((selector) => {
        const element = document.querySelector(selector);
        if (!element || element.getClientRects().length === 0) return false;
        const box = element.getBoundingClientRect();
        return box.left < -1 || box.right > viewportWidth + 1;
      });
      return {
        documentFits: document.documentElement.scrollWidth <= viewportWidth,
        outOfBounds,
      };
    });
    expect(horizontalFit.documentFits).toBeTruthy();
    expect(horizontalFit.outOfBounds).toEqual([]);

    const chatWidthBeforeDrawer = await page.locator(".chat-area").evaluate(
      (element) => element.getBoundingClientRect().width,
    );

    if (width <= 768) {
      await expect(page.locator("#sidebar")).toBeHidden();
      await page.click(".mobile-menu-btn");
      await expect(page.locator("#sidebar")).toBeVisible();
      const drawer = await page.locator("#sidebar").boundingBox();
      expect(drawer.width).toBeLessThanOrEqual(280);
      const chatWidthWithDrawer = await page.locator(".chat-area").evaluate(
        (element) => element.getBoundingClientRect().width,
      );
      expect(Math.abs(chatWidthWithDrawer - chatWidthBeforeDrawer)).toBeLessThan(2);
      await page.locator("#overlay").click({ position: { x: width - 5, y: 5 } });
      await expect(page.locator("#sidebar")).toBeHidden();

      await page.click(".chips-toggle-float");
      await expect(page.locator("#chipsSidebar")).toBeVisible();
      const chips = await page.locator("#chipsSidebar").boundingBox();
      expect(chips.width).toBeLessThanOrEqual(width + 1);
      await page.locator("#chipsSidebar .chips-close").click();
    } else {
      const sidebarBefore = await page.locator("#sidebar").boundingBox();
      await page.click("#desktopSidebarToggle");
      await expect(page.locator("#sidebar")).toHaveClass(/collapsed/);
      await page.waitForTimeout(220);
      const sidebarAfter = await page.locator("#sidebar").boundingBox();
      expect(sidebarAfter.width).toBeLessThan(sidebarBefore.width);
      expect(sidebarAfter.width).toBeLessThanOrEqual(58);

      await page.locator("#chipsSidebar .chips-close").click();
      await expect(page.locator("#chipsSidebar")).toBeHidden();
      await expect(page.locator(".chips-toggle-float")).toBeVisible();
      await page.waitForTimeout(350);
      await page.locator(".chips-toggle-float").click();
      await expect(page.locator("#chipsSidebar")).toBeVisible();
    }

    await page.click(".topic-toggle-btn");
    await expect(page.locator("#topicsPanel")).toHaveClass(/show/);
    await expect(page.locator("#topicsGridPanel .topic-btn")).toHaveCount(28, {
      timeout: 15000,
    });
    await page.waitForTimeout(250);
    const topicsBounds = await page.locator("#topicsPanel").boundingBox();
    expect(topicsBounds.x).toBeGreaterThanOrEqual(-1);
    expect(topicsBounds.x + topicsBounds.width).toBeLessThanOrEqual(width + 1);
    await page.locator("#topicsPanel .topics-close").click();

    await page.fill("#chatInput", "help");
    await page.click("#sendBtn");
    await expect(page.locator(".topics-grid .topic-btn")).toHaveCount(28, {
      timeout: 15000,
    });
    await expect(page.locator("#enHistory .history-item")).toHaveCount(1);
  });
}
