/* Голосовой ввод (ТЗ §10): «Говорить» → запись до 30 с → POST /api/stt → текст в поле ввода.
 * Отправку механик делает сам. Аудио после распознавания не хранится: куски записи отбрасываются.
 * Без согласия (localStorage voice_consent_at) и без MediaRecorder микрофон не включается.
 */
(function () {
  "use strict";
  var MC = (window.MC = window.MC || {});
  var root = document.getElementById("chat-root");
  var button = document.getElementById("mic-btn");
  var input = document.getElementById("message");
  var statusEl = document.getElementById("voice-status");
  var consentBox = document.getElementById("voice-consent");
  var consentCheck = document.getElementById("voice-consent-check");
  var consentBtn = document.getElementById("voice-consent-btn");
  if (!root || !button || !input) return;

  var CONSENT_KEY = "voice_consent_at";
  var MAX_MS = 30000;
  var MAX_BYTES = 10 * 1024 * 1024;
  var MIME_CHOICES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

  var recorder = null;
  var stream = null;
  var chunks = [];
  var stopTimer = null;
  var uploading = false;
  MC.inputMode = "text";

  function say(text) {
    statusEl.textContent = text;
    statusEl.hidden = !text;
  }

  function consentGiven() {
    try {
      return !!localStorage.getItem(CONSENT_KEY);
    } catch (error) {
      return false;
    }
  }

  function consentValue() {
    try {
      return localStorage.getItem(CONSENT_KEY) || "";
    } catch (error) {
      return "";
    }
  }

  function storeConsent() {
    try {
      localStorage.setItem(CONSENT_KEY, new Date().toISOString());
    } catch (error) {
      // Без хранилища согласие спросят снова при следующей записи.
    }
  }

  function recordingSupported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }

  function pickMime() {
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
    for (var i = 0; i < MIME_CHOICES.length; i += 1) {
      if (MediaRecorder.isTypeSupported(MIME_CHOICES[i])) return MIME_CHOICES[i];
    }
    return "";
  }

  function setRecording(on) {
    button.setAttribute("aria-pressed", on ? "true" : "false");
    button.textContent = on ? "Остановить" : "Говорить";
  }

  function messageFor(status, detail) {
    if (typeof detail === "string" && detail) return detail;
    if (status === 0) return MC.errorMessage(0);
    if (status >= 500) return "Сервис распознавания речи временно недоступен. Повторите или введите вопрос текстом.";
    return "Не удалось распознать запись. Повторите или введите вопрос текстом.";
  }

  async function startRecording() {
    say("");
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      say(
        error && error.name === "NotAllowedError"
          ? "Доступ к микрофону запрещён. Разрешите его в настройках браузера или введите вопрос текстом."
          : "Микрофон не найден или занят. Введите вопрос текстом."
      );
      return;
    }
    chunks = [];
    var mime = pickMime();
    recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    recorder.addEventListener("dataavailable", function (event) {
      if (event.data && event.data.size) chunks.push(event.data);
    });
    recorder.addEventListener("stop", onStop);
    recorder.start();
    setRecording(true);
    say("Слушаю. Нажмите «Остановить», когда закончите. Не больше 30 секунд.");
    stopTimer = setTimeout(stopRecording, MAX_MS);
  }

  function stopRecording() {
    clearTimeout(stopTimer);
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }

  function releaseMicrophone() {
    if (stream) stream.getTracks().forEach(function (track) { track.stop(); });
    stream = null;
    recorder = null;
  }

  function onStop() {
    var type = (recorder && recorder.mimeType) || "audio/webm";
    var blob = new Blob(chunks, { type: type });
    chunks = [];
    releaseMicrophone();
    setRecording(false);
    if (!blob.size) {
      say("Запись пустая. Нажмите «Говорить» и повторите.");
      return;
    }
    if (blob.size > MAX_BYTES) {
      say("Запись больше 10 МБ. Запишите короче.");
      return;
    }
    upload(blob);
  }

  async function upload(blob) {
    uploading = true;
    button.disabled = true;
    say("Распознаю речь…");
    var form = new FormData();
    form.append("audio", blob, "voice-record");
    form.append("consent_at", consentValue());
    form.append("vehicle_id", root.dataset.vehicle);
    form.append("session_id", root.dataset.session);
    try {
      var response = await fetch("/api/stt", { method: "POST", body: form });
      var data = await response.json().catch(function () { return {}; });
      if (!response.ok) {
        say(messageFor(response.status, data.detail));
        return;
      }
      var text = (data.text || "").trim();
      if (!text) {
        say("Речь не распознана. Попробуйте ещё раз или введите вопрос текстом.");
        return;
      }
      var typed = input.value.trim();
      input.value = typed ? typed + " " + text : text;
      MC.inputMode = "voice";
      say("Проверьте текст и нажмите «Отправить».");
      input.focus();
    } catch (error) {
      say(MC.errorMessage(0));
    } finally {
      uploading = false;
      button.disabled = false;
    }
  }

  function showConsent() {
    consentBox.hidden = false;
    // Композер закреплён внизу экрана: блок согласия переводим в центр, иначе его перекроет.
    if (consentBox.scrollIntoView) consentBox.scrollIntoView({ block: "center" });
    consentCheck.focus({ preventScroll: true });
  }

  var composer = document.getElementById("composer");
  if (composer) {
    composer.addEventListener("submit", function () {
      say("");
    });
  }

  button.addEventListener("click", function () {
    if (recorder && recorder.state !== "inactive") {
      stopRecording();
      return;
    }
    if (uploading) return;
    if (!recordingSupported()) {
      say("Голосовой ввод не работает в этом браузере. Введите вопрос текстом.");
      return;
    }
    if (!consentGiven()) {
      showConsent();
      return;
    }
    startRecording();
  });

  if (consentCheck && consentBtn) {
    consentCheck.addEventListener("change", function () {
      consentBtn.disabled = !consentCheck.checked;
    });
    consentBtn.addEventListener("click", function () {
      storeConsent();
      consentBox.hidden = true;
      startRecording();
    });
  }
})();
