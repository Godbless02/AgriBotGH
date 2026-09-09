const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  use: { baseURL: process.env.TEST_BASE_URL || "http://127.0.0.1:5000" },
  webServer: {
    command: "python app.py",
    env: {
      ...process.env,
      AGRIBOT_TEST_MODE: "1",
      ABENA_TTS_ENABLED: "false",
    },
    url: "http://127.0.0.1:5000/api/health",
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
