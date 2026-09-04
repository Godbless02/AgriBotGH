const { test, expect } = require("@playwright/test");

const BASE = process.env.TEST_BASE_URL || "http://localhost:8080";

async function enterApp(page, name) {
  await page.goto(BASE + "/index.html");
  await page.fill("#nameInput", name);
  await page.click(".start-btn");
}

async function installSpeechMock(page, voices) {
  await page.addInitScript((availableVoices) => {
    let voiceList = availableVoices;
    const listeners = {};
    window.__speechTest = {
      speak: 0,
      pause: 0,
      resume: 0,
      cancel: 0,
      lastLang: null,
      lastVoice: null,
      lastText: null,
      spokenTexts: [],
      utterances: [],
      current: null,
      setVoices(voices) {
        voiceList = voices;
        (listeners.voiceschanged || []).forEach((listener) => listener());
        if (typeof synth.onvoiceschanged === "function") {
          synth.onvoiceschanged();
        }
      },
      endCurrent() {
        const utterance = this.current;
        if (utterance && utterance.onend) utterance.onend();
      },
      errorCurrent(reason = "synthesis-failed") {
        const utterance = this.current;
        if (utterance && utterance.onerror) utterance.onerror({ error: reason });
      },
      errorUtterance(index, reason = "interrupted") {
        const utterance = this.utterances[index];
        if (utterance && utterance.onerror) utterance.onerror({ error: reason });
      },
    };

    class MockUtterance {
      constructor(text) {
        this.text = text;
        this.lang = "";
        this.voice = null;
      }
    }

    const synth = {
      speaking: false,
      paused: false,
      getVoices: () => voiceList,
      addEventListener(name, listener) {
        if (!listeners[name]) listeners[name] = [];
        listeners[name].push(listener);
      },
      speak(utterance) {
        window.__speechTest.speak += 1;
        window.__speechTest.lastLang = utterance.lang;
        window.__speechTest.lastVoice = utterance.voice
          ? utterance.voice.name
          : null;
        window.__speechTest.lastText = utterance.text;
        window.__speechTest.spokenTexts.push(utterance.text);
        window.__speechTest.current = utterance;
        window.__speechTest.utterances.push(utterance);
        this.speaking = true;
        this.paused = false;
        if (utterance.onstart) utterance.onstart();
      },
      pause() {
        window.__speechTest.pause += 1;
        this.paused = true;
        this.speaking = false;
        const utterance = window.__speechTest.current;
        if (utterance && utterance.onpause) utterance.onpause();
      },
      resume() {
        window.__speechTest.resume += 1;
        this.paused = false;
        this.speaking = true;
        const utterance = window.__speechTest.current;
        if (utterance && utterance.onresume) utterance.onresume();
      },
      cancel() {
        window.__speechTest.cancel += 1;
        this.paused = false;
        this.speaking = false;
      },
    };

    Object.defineProperty(window, "SpeechSynthesisUtterance", {
      configurable: true,
      value: MockUtterance,
    });
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: synth,
    });
  }, voices);
}

async function mockAbenaUnavailable(page) {
  await page.route("**/api/tts", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        success: false,
        code: "provider_unavailable",
        fallback_allowed: true,
      }),
    });
  });
}

async function installAudioMock(page) {
  await page.addInitScript(() => {
    window.__audioTest = { instances: [], play: 0, pause: 0, load: 0 };
    class MockAudio {
      constructor(src) {
        this.src = src;
        this.onended = null;
        this.onerror = null;
        window.__audioTest.instances.push(this);
      }
      play() {
        window.__audioTest.play += 1;
        return Promise.resolve();
      }
      pause() {
        window.__audioTest.pause += 1;
      }
      load() {
        window.__audioTest.load += 1;
      }
      removeAttribute(name) {
        if (name === "src") this.src = "";
      }
    }
    Object.defineProperty(window, "Audio", { configurable: true, value: MockAudio });
  });
}

async function mockAbenaSuccess(page, clips = null) {
  const audioClips = clips || [
    { audio_base64: "UklGRi10ZXN0", mime_type: "audio/wav", duration_seconds: 1 },
  ];
  await page.route("**/api/tts", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        language: "twi",
        provider: "abena",
        voice: "abena_twi_lite",
        chunk_count: audioClips.length,
        clips: audioClips,
      }),
    });
  });
}

test.describe("Text-to-speech controls", () => {
  test("supports play, pause, resume, stop, and one active message", async ({
    page,
  }) => {
    await installSpeechMock(page, [{ name: "Ghana English", lang: "en-GH" }]);
    await enterApp(page, "TtsControlsUser");
    await page.evaluate(() => {
      appendMessage("First farming response", "bot", "en");
      appendMessage("Second farming response", "bot", "en");
    });

    const buttons = page.locator(".tts-button");
    const stops = page.locator(".tts-stop");
    await buttons.nth(0).click();
    await expect(buttons.nth(0)).toHaveAttribute("data-state", "playing");
    await buttons.nth(0).click();
    await expect(buttons.nth(0)).toHaveAttribute("data-state", "paused");
    await expect(page.locator(".tts-status").nth(0)).toHaveText("Paused");
    await buttons.nth(0).click();
    await expect(buttons.nth(0)).toHaveAttribute("data-state", "playing");

    await buttons.nth(1).click();
    await expect(buttons.nth(0)).toHaveAttribute("data-state", "idle");
    await expect(buttons.nth(1)).toHaveAttribute("data-state", "playing");
    await stops.nth(1).click();
    await expect(buttons.nth(1)).toHaveAttribute("data-state", "idle");
    await expect(page.locator(".tts-status").nth(1)).toBeHidden();

    const events = await page.evaluate(() => window.__speechTest);
    expect(events.speak).toBe(2);
    expect(events.pause).toBe(1);
    expect(events.resume).toBe(1);
    expect(events.cancel).toBeGreaterThanOrEqual(3);
    expect(events.lastLang).toBe("en-GH");
    expect(events.spokenTexts).toEqual([
      "First farming response",
      "Second farming response",
    ]);
  });

  test("uses an Akan voice for Twi when available", async ({ page }) => {
    await mockAbenaUnavailable(page);
    await installSpeechMock(page, [
      { name: "Ghana English", lang: "en-GH" },
      { name: "Akan Voice", lang: "ak-GH" },
    ]);
    await enterApp(page, "TwiVoiceUser");
    await page.evaluate(() => appendMessage("Akwaaba okuafo", "bot", "tw"));
    await page.locator(".tts-button").click();

    const speech = await page.evaluate(() => window.__speechTest);
    expect(speech.lastVoice).toBe("Akan Voice");
    expect(speech.lastLang).toBe("ak-GH");
    expect(speech.lastText).toBe("Akwaaba okuafo");
    await expect(page.locator(".tts-status")).toContainText("browser fallback");
  });

  test("discloses when Twi must use a fallback voice", async ({ page }) => {
    await mockAbenaUnavailable(page);
    await installSpeechMock(page, [{ name: "English Voice", lang: "en-GB" }]);
    await enterApp(page, "FallbackVoiceUser");
    await page.evaluate(() => appendMessage("Akwaaba okuafo", "bot", "tw"));
    await page.locator(".tts-button").click();

    await expect(page.locator(".tts-status")).toContainText(
      "pronunciation may be inaccurate",
    );
    const speech = await page.evaluate(() => window.__speechTest);
    expect(speech.lastVoice).toBe("English Voice");
    expect(speech.lastLang).toBe("en-GB");
  });

  test("fails readably when browser speech support is unavailable", async ({
    page,
  }) => {
    await page.addInitScript(() => {
      delete window.speechSynthesis;
      delete window.SpeechSynthesisUtterance;
    });
    await enterApp(page, "NoSpeechUser");
    await page.evaluate(() => appendMessage("Readable response", "bot", "en"));
    const button = page.locator(".tts-button");
    await expect(button).toBeDisabled();
    await expect(button).toHaveAttribute(
      "aria-label",
      "Audio is unavailable for this response",
    );
    await expect(page.locator(".bubble").last()).toContainText("Readable response");
  });

  test("refreshes asynchronously loaded voices without an exact-name dependency", async ({
    page,
  }) => {
    await installSpeechMock(page, []);
    await enterApp(page, "DelayedVoiceUser");
    await page.evaluate(() => {
      window.__speechTest.setVoices([
        { name: "Any Available English", lang: "en-ZA" },
      ]);
      appendMessage("Use 15 kg of fertilizer on 20% of the plot.", "bot", "en");
    });
    await page.locator(".tts-button").click();
    const speech = await page.evaluate(() => window.__speechTest);
    expect(speech.lastVoice).toBe("Any Available English");
    expect(speech.lastLang).toBe("en-ZA");
    expect(speech.lastText).toBe("Use 15 kg of fertilizer on 20% of the plot.");
  });

  test("speech end and genuine errors reset only the associated control", async ({
    page,
  }) => {
    await installSpeechMock(page, [{ name: "English", lang: "en-US" }]);
    await enterApp(page, "SpeechEventsUser");
    await page.evaluate(() => appendMessage("A farming response", "bot", "en"));
    const button = page.locator(".tts-button");
    const status = page.locator(".tts-status");
    await button.click();
    await page.evaluate(() => window.__speechTest.endCurrent());
    await expect(button).toHaveAttribute("data-state", "idle");
    await expect(status).toBeHidden();

    await button.click();
    await page.evaluate(() => window.__speechTest.errorCurrent("network"));
    await expect(button).toHaveAttribute("data-state", "error");
    await expect(status).toContainText("Audio is currently unavailable");
  });

  test("submitting a new question stops current speech without making a TTS request", async ({
    page,
  }) => {
    await installSpeechMock(page, [{ name: "English", lang: "en-GB" }]);
    await page.route("**/api/chat", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ type: "answer", text: "Dataset answer", language: "en" }),
      });
    });
    await enterApp(page, "NewQuestionStopsSpeech");
    await page.evaluate(() => appendMessage("Old spoken answer", "bot", "en"));
    await page.locator(".tts-button").click();
    const cancelBefore = await page.evaluate(() => window.__speechTest.cancel);
    await page.fill("#chatInput", "What fertilizer is best for maize?");
    await page.click("#sendBtn");
    await expect(page.locator(".tts-button").first()).toHaveAttribute(
      "data-state",
      "idle",
    );
    const speech = await page.evaluate(() => window.__speechTest);
    expect(speech.cancel).toBeGreaterThan(cancelBefore);
    expect(speech.speak).toBe(1);
  });

  test("cleans markup and emoji while preserving agricultural quantities", async ({
    page,
  }) => {
    await installSpeechMock(page, [{ name: "English", lang: "en-GH" }]);
    await enterApp(page, "SpeechCleanupUser");
    await page.evaluate(() =>
      appendMessage("<b>Apply</b> 2 bags of NPK 15-15-15 per acre 🌱", "bot", "en"),
    );
    await page.locator(".tts-button").click();
    const speech = await page.evaluate(() => window.__speechTest);
    expect(speech.lastText).toBe("Apply 2 bags of NPK 15-15-15 per acre");
  });

  test("late cancellation events cannot corrupt the newly active response", async ({
    page,
  }) => {
    await installSpeechMock(page, [{ name: "English", lang: "en-GH" }]);
    await enterApp(page, "CancellationRaceUser");
    await page.evaluate(() => {
      appendMessage("First response", "bot", "en");
      appendMessage("Second response", "bot", "en");
    });
    const buttons = page.locator(".tts-button");
    await buttons.nth(0).click();
    await buttons.nth(1).click();
    await page.evaluate(() => window.__speechTest.errorUtterance(0));
    await expect(buttons.nth(0)).toHaveAttribute("data-state", "idle");
    await expect(buttons.nth(1)).toHaveAttribute("data-state", "playing");
  });

  test("language changes and chat clearing stop active playback", async ({ page }) => {
    await mockAbenaUnavailable(page);
    await installSpeechMock(page, [
      { name: "English", lang: "en-GH" },
      { name: "Akan", lang: "ak-GH" },
    ]);
    await enterApp(page, "SpeechResetUser");
    await page.evaluate(() => appendMessage("English response", "bot", "en"));
    await page.locator(".tts-button").click();
    const beforeLanguage = await page.evaluate(() => window.__speechTest.cancel);
    await page.click("#twBtn");
    expect(await page.evaluate(() => window.__speechTest.cancel)).toBeGreaterThan(
      beforeLanguage,
    );

    await page.evaluate(() => appendMessage("Twi mmuae", "bot", "tw"));
    await page.locator(".tts-button").click();
    const beforeClear = await page.evaluate(() => window.__speechTest.cancel);
    await page.evaluate(() => clearChat());
    expect(await page.evaluate(() => window.__speechTest.cancel)).toBeGreaterThan(
      beforeClear,
    );
  });
});

test.describe("Abena Twi audio with browser fallback", () => {
  test("Twi sends only text and language to the server and plays returned audio", async ({ page }) => {
    const requests = [];
    await installSpeechMock(page, [{ name: "English", lang: "en-GH" }]);
    await installAudioMock(page);
    await page.route("**/api/tts", async (route) => {
      requests.push(route.request().postDataJSON());
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          clips: [{ audio_base64: "UklGRi10ZXN0", mime_type: "audio/wav" }],
        }),
      });
    });
    await enterApp(page, "NaturalTwiUser");
    await page.evaluate(() => appendMessage("Afuo mu nsɛm", "bot", "tw"));
    await page.locator(".tts-button").click();
    await expect(page.locator(".tts-button")).toHaveAttribute("data-state", "playing");
    expect(requests).toEqual([{ text: "Afuo mu nsɛm", language: "twi" }]);
    const state = await page.evaluate(() => ({
      audio: window.__audioTest,
      speech: window.__speechTest,
    }));
    expect(state.audio.play).toBe(1);
    expect(state.audio.instances[0].src).toContain("data:audio/wav;base64,");
    expect(state.speech.speak).toBe(0);
    await expect(page.locator(".tts-status")).toContainText("natural Twi voice");
  });

  test("English remains browser-native and never calls the Twi endpoint", async ({ page }) => {
    let requests = 0;
    await installSpeechMock(page, [{ name: "English", lang: "en-GH" }]);
    await page.route("**/api/tts", async (route) => {
      requests += 1;
      await route.abort();
    });
    await enterApp(page, "EnglishNativeUser");
    await page.evaluate(() => appendMessage("Plant maize early", "bot", "en"));
    await page.locator(".tts-button").click();
    expect(requests).toBe(0);
    expect(await page.evaluate(() => window.__speechTest.speak)).toBe(1);
  });

  test("plays server chunks sequentially and finishes cleanly", async ({ page }) => {
    await installSpeechMock(page, [{ name: "English", lang: "en-GH" }]);
    await installAudioMock(page);
    await mockAbenaSuccess(page, [
      { audio_base64: "Y2h1bmsx", mime_type: "audio/wav" },
      { audio_base64: "Y2h1bmsy", mime_type: "audio/mpeg" },
    ]);
    await enterApp(page, "ChunkSequenceUser");
    await page.evaluate(() => appendMessage("Twi mmuae tenten", "bot", "tw"));
    const button = page.locator(".tts-button");
    await button.click();
    await expect(button).toHaveAttribute("data-state", "playing");
    await page.evaluate(() => window.__audioTest.instances[0].onended());
    expect(await page.evaluate(() => window.__audioTest.play)).toBe(2);
    await page.evaluate(() => window.__audioTest.instances[1].onended());
    await expect(button).toHaveAttribute("data-state", "idle");
    await expect(page.locator(".tts-status")).toBeHidden();
  });

  test("natural Twi audio supports pause, resume, and stop", async ({ page }) => {
    await installSpeechMock(page, [{ name: "English", lang: "en-GH" }]);
    await installAudioMock(page);
    await mockAbenaSuccess(page);
    await enterApp(page, "NaturalControlsUser");
    await page.evaluate(() => appendMessage("Twi mmuae", "bot", "tw"));
    const button = page.locator(".tts-button");
    await button.click();
    await expect(button).toHaveAttribute("data-state", "playing");
    await button.click();
    await expect(button).toHaveAttribute("data-state", "paused");
    await button.click();
    await expect(button).toHaveAttribute("data-state", "playing");
    await page.locator(".tts-stop").click();
    await expect(button).toHaveAttribute("data-state", "idle");
    const audio = await page.evaluate(() => window.__audioTest);
    expect(audio.play).toBe(2);
    expect(audio.pause).toBeGreaterThanOrEqual(2);
  });

  test("provider unavailability falls back exactly once", async ({ page }) => {
    await installSpeechMock(page, [{ name: "English", lang: "en-GH" }]);
    await mockAbenaUnavailable(page);
    await enterApp(page, "UnavailableFallbackUser");
    await page.evaluate(() => appendMessage("Akwaaba okuafo", "bot", "tw"));
    await page.locator(".tts-button").click();
    await expect(page.locator(".tts-status")).toContainText("browser fallback");
    expect(await page.evaluate(() => window.__speechTest.speak)).toBe(1);
  });

  test("malformed success payload falls back safely", async ({ page }) => {
    await installSpeechMock(page, [{ name: "Akan", lang: "ak-GH" }]);
    await page.route("**/api/tts", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ success: true, clips: [{ mime_type: "audio/wav" }] }),
    }));
    await enterApp(page, "MalformedFallbackUser");
    await page.evaluate(() => appendMessage("Akwaaba", "bot", "tw"));
    await page.locator(".tts-button").click();
    expect(await page.evaluate(() => window.__speechTest.speak)).toBe(1);
  });

  test("network failure falls back without exposing transport details", async ({ page }) => {
    await installSpeechMock(page, [{ name: "English", lang: "en-GH" }]);
    await page.route("**/api/tts", (route) => route.abort("failed"));
    await enterApp(page, "NetworkFallbackUser");
    await page.evaluate(() => appendMessage("Akwaaba", "bot", "tw"));
    await page.locator(".tts-button").click();
    await expect(page.locator(".tts-status")).toContainText("browser fallback");
    await expect(page.locator(".tts-status")).not.toContainText("failed");
  });

  test("stop during preparation aborts without triggering fallback", async ({ page }) => {
    await installSpeechMock(page, [{ name: "English", lang: "en-GH" }]);
    await page.route("**/api/tts", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 400));
      await route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
    });
    await enterApp(page, "PreparationStopUser");
    await page.evaluate(() => appendMessage("Akwaaba", "bot", "tw"));
    const button = page.locator(".tts-button");
    await button.click();
    await expect(button).toHaveAttribute("data-state", "preparing");
    await page.locator(".tts-stop").click();
    await expect(button).toHaveAttribute("data-state", "idle");
    await page.waitForTimeout(500);
    expect(await page.evaluate(() => window.__speechTest.speak)).toBe(0);
  });

  test("rapid duplicate activation makes only one request", async ({ page }) => {
    let requests = 0;
    await installSpeechMock(page, [{ name: "English", lang: "en-GH" }]);
    await installAudioMock(page);
    await page.route("**/api/tts", async (route) => {
      requests += 1;
      await new Promise((resolve) => setTimeout(resolve, 100));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true, clips: [
          { audio_base64: "YXVkaW8=", mime_type: "audio/wav" },
        ] }),
      });
    });
    await enterApp(page, "DuplicateNaturalUser");
    await page.evaluate(() => {
      appendMessage("Akwaaba", "bot", "tw");
      const button = document.querySelector(".tts-button");
      button.click();
      button.click();
    });
    await expect(page.locator(".tts-button")).toHaveAttribute("data-state", "playing");
    expect(requests).toBe(1);
  });

  test("a newer response cancels old natural audio without stale UI changes", async ({ page }) => {
    await installSpeechMock(page, [{ name: "English", lang: "en-GH" }]);
    await installAudioMock(page);
    await mockAbenaSuccess(page);
    await enterApp(page, "NaturalRaceUser");
    await page.evaluate(() => {
      appendMessage("First", "bot", "tw");
      appendMessage("Second", "bot", "tw");
    });
    const buttons = page.locator(".tts-button");
    await buttons.nth(0).click();
    await expect(buttons.nth(0)).toHaveAttribute("data-state", "playing");
    await buttons.nth(1).click();
    await expect(buttons.nth(0)).toHaveAttribute("data-state", "idle");
    await expect(buttons.nth(1)).toHaveAttribute("data-state", "playing");
    await page.evaluate(() => {
      const old = window.__audioTest.instances[0];
      if (old.onended) old.onended();
    });
    await expect(buttons.nth(1)).toHaveAttribute("data-state", "playing");
  });

  test("Twi natural audio works even when browser synthesis is absent", async ({ page }) => {
    await page.addInitScript(() => {
      delete window.speechSynthesis;
      delete window.SpeechSynthesisUtterance;
    });
    await installAudioMock(page);
    await mockAbenaSuccess(page);
    await enterApp(page, "NaturalOnlyUser");
    await page.evaluate(() => appendMessage("Akwaaba", "bot", "tw"));
    const button = page.locator(".tts-button");
    await expect(button).toBeEnabled();
    await button.click();
    await expect(button).toHaveAttribute("data-state", "playing");
  });

  test("provider and browser unavailability leave text readable", async ({ page }) => {
    await page.addInitScript(() => {
      delete window.speechSynthesis;
      delete window.SpeechSynthesisUtterance;
    });
    await mockAbenaUnavailable(page);
    await enterApp(page, "NoAudioEnginesUser");
    await page.evaluate(() => appendMessage("Akwaaba", "bot", "tw"));
    const button = page.locator(".tts-button");
    await button.click();
    await expect(button).toHaveAttribute("data-state", "error");
    await expect(page.locator(".bubble").last()).toContainText("Akwaaba");
  });

  test("media playback failure uses browser fallback", async ({ page }) => {
    await installSpeechMock(page, [{ name: "Akan", lang: "ak-GH" }]);
    await page.addInitScript(() => {
      class BrokenAudio {
        play() { return Promise.reject(new Error("decode failure")); }
        pause() {}
        removeAttribute() {}
        load() {}
      }
      Object.defineProperty(window, "Audio", { configurable: true, value: BrokenAudio });
    });
    await mockAbenaSuccess(page);
    await enterApp(page, "PlaybackFallbackUser");
    await page.evaluate(() => appendMessage("Akwaaba", "bot", "tw"));
    await page.locator(".tts-button").click();
    await expect(page.locator(".tts-status")).toContainText("browser fallback");
    expect(await page.evaluate(() => window.__speechTest.speak)).toBe(1);
  });

  test("language switching cancels natural Twi playback", async ({ page }) => {
    await installSpeechMock(page, [{ name: "English", lang: "en-GH" }]);
    await installAudioMock(page);
    await mockAbenaSuccess(page);
    await enterApp(page, "NaturalLanguageResetUser");
    await page.evaluate(() => appendMessage("Akwaaba", "bot", "tw"));
    await page.locator(".tts-button").click();
    await expect(page.locator(".tts-button")).toHaveAttribute("data-state", "playing");
    await page.click("#twBtn");
    expect(await page.evaluate(() => window.__audioTest.pause)).toBeGreaterThan(0);
  });
});
