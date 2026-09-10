const { test, expect } = require("@playwright/test");

const BASE = process.env.TEST_BASE_URL || "http://127.0.0.1:5000";
const user = { id: "user-1", username: "Ama Farmer", preferred_language: "tw" };

async function mockUnauthenticated(page) {
  await page.route("**/api/auth/me", (route) => route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: "Authentication required." }) }));
}

test("numeric registration names stay on the registration screen without an API request", async ({ page }) => {
  await mockUnauthenticated(page);
  const requests = [];
  await page.route("**/api/auth/register", (route) => {
    requests.push(route.request());
    return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ authenticated: true, user }) });
  });
  await page.goto(BASE + "/index.html");
  await page.getByRole("button", { name: "Register", exact: true }).first().click();
  await page.fill("#registerUsername", "Kofi123");
  await page.fill("#registerPassword", "private-password");
  await page.fill("#registerConfirmPassword", "private-password");
  await page.getByRole("button", { name: /Register and enter/ }).click();
  await expect(page.locator("#registerError")).toHaveText("Please enter a valid name using letters, spaces, hyphens or apostrophes only.");
  await expect(page.locator("#authRegisterForm")).toBeVisible();
  await expect(page.locator("#appShell")).toBeHidden();
  expect(requests).toHaveLength(0);
});

test("register success opens the authenticated app without storing passwords", async ({ page }) => {
  await mockUnauthenticated(page);
  await page.route("**/api/auth/register", (route) => route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ authenticated: true, user }) }));
  await page.goto(BASE + "/index.html");
  await page.getByRole("button", { name: "Register", exact: true }).first().click();
  await page.fill("#registerUsername", user.username);
  await page.fill("#registerPassword", "private-password");
  await page.fill("#registerConfirmPassword", "private-password");
  await page.getByRole("button", { name: /Register and enter/ }).click();
  await expect(page.locator("#userBadge")).toContainText(user.username);
  await expect(page.locator("#appShell")).toBeVisible();
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain("private-password");
});

test("duplicate registration remains on the register screen with a friendly error", async ({ page }) => {
  await mockUnauthenticated(page);
  await page.route("**/api/auth/register", (route) => route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: "That username is already taken. Please choose another." }) }));
  await page.goto(BASE + "/index.html");
  await page.getByRole("button", { name: "Register", exact: true }).first().click();
  await page.fill("#registerUsername", "Ama");
  await page.fill("#registerPassword", "private-password");
  await page.fill("#registerConfirmPassword", "private-password");
  await page.getByRole("button", { name: /Register and enter/ }).click();
  await expect(page.locator("#registerError")).toContainText("already taken");
  await expect(page.locator("#authRegisterForm")).toBeVisible();
});

test("login, reload restoration, and logout use auth endpoints", async ({ page }) => {
  await mockUnauthenticated(page);
  await page.route("**/api/auth/login", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ authenticated: true, user }) }));
  await page.route("**/api/auth/logout", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ authenticated: false }) }));
  await page.goto(BASE + "/index.html");
  await page.fill("#loginUsername", user.username);
  await page.fill("#loginPassword", "private-password");
  await page.getByRole("button", { name: "Login", exact: true }).last().click();
  await expect(page.locator("#appShell")).toBeVisible();
  await page.route("**/api/auth/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ authenticated: true, user }) }));
  await page.reload();
  await expect(page.locator("#userBadge")).toContainText(user.username);
  await page.getByRole("button", { name: "Logout", exact: true }).first().click();
  await expect(page.locator("#authLoginForm")).toBeVisible();
});

test("invalid login has a generic response and auth is usable on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await mockUnauthenticated(page);
  await page.route("**/api/auth/login", (route) => route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: "Invalid username or password." }) }));
  await page.goto(BASE + "/index.html");
  await page.fill("#loginUsername", "unknown");
  await page.fill("#loginPassword", "private-password");
  await page.getByRole("button", { name: "Login", exact: true }).last().click();
  await expect(page.locator("#welcomeError")).toHaveText("Invalid username or password.");
  await expect(page.locator("#authLoginForm")).toBeVisible();
});

test("a delayed response remains scoped to the account that submitted it", async ({ page }) => {
  const accountA = { id: "user-a", username: "Account A", preferred_language: "en" };
  const accountB = { id: "user-b", username: "Account B", preferred_language: "en" };
  let releaseResponse;
  let markIntercepted;
  const responseGate = new Promise((resolve) => { releaseResponse = resolve; });
  const intercepted = new Promise((resolve) => { markIntercepted = resolve; });

  await page.route("**/api/auth/me", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ authenticated: true, user: accountA }),
  }));
  await page.route("**/api/auth/logout", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ authenticated: false }),
  }));
  await page.route("**/api/auth/login", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ authenticated: true, user: accountB }),
  }));
  await page.route("**/api/chat", async (route) => {
    markIntercepted();
    await responseGate;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        type: "answer",
        text: "Private delayed answer for account A",
        language: "en",
      }),
    });
  });

  await page.goto(BASE + "/index.html");
  await expect(page.locator("#userBadge")).toContainText(accountA.username);
  await page.fill("#chatInput", "Account A private question");
  await page.click("#sendBtn");
  await intercepted;

  await page.getByRole("button", { name: "Logout", exact: true }).first().click();
  await page.fill("#loginUsername", accountB.username);
  await page.fill("#loginPassword", "private-password");
  await page.getByRole("button", { name: "Login", exact: true }).last().click();
  await expect(page.locator("#userBadge")).toContainText(accountB.username);

  releaseResponse();
  await expect.poll(() => page.evaluate(() => {
    const users = JSON.parse(localStorage.getItem("agribot_all_users") || "{}");
    return JSON.stringify(users["account a"] || {});
  })).toContain("Private delayed answer for account A");
  await expect(page.locator("#messages")).not.toContainText("Private delayed answer for account A");
  const accountBHistory = await page.evaluate(() => {
    const users = JSON.parse(localStorage.getItem("agribot_all_users") || "{}");
    return JSON.stringify(users["account b"] || {});
  });
  expect(accountBHistory).not.toContain("Private delayed answer for account A");
});
