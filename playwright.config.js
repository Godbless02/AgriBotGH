const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  use: { baseURL: process.env.TEST_BASE_URL || "http://127.0.0.1:5000" },
  webServer: {
    command: "powershell -NoProfile -Command \"$env:AGRIBOT_TEST_MODE='1'; $env:ABENA_TTS_ENABLED='false'; .\\agribot_env\\Scripts\\python.exe app.py\"",
    url: "http://127.0.0.1:5000/api/health",
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
