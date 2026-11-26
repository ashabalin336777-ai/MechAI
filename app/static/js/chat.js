/* Чат агента на странице /vehicles/{id}/chat.
 * Ответ идёт потоком SSE из POST /api/chat (или /api/action/get_diagnosis).
 * Карточка вердикта — первой, ответ — ниже, черновик заявки — ссылкой на экран заявки.
 */
(function () {
  "use strict";
  var MC = window.MC;
  var root = document.getElementById("chat-root");
  if (!root || !MC) return;

  var vehicle = root.dataset.vehicle;
  var session = root.dataset.session;
  var messagesEl = document.getElementById("messages");
  var verdictEl = document.getElementById("verdict");
  var metaEl = document.getElementById("meta");
  var composer = document.getElementById("composer");
  var input = document.getElementById("message");
  var sendBtn = document.getElementById("send-btn");
  var diagBtn = document.getElementById("diagnosis-btn");
  var popEl = document.getElementById("glossary-pop");
  var chips = Array.prototype.slice.call(document.querySelectorAll(".chip"));
  var busy = false;
  var lastRequest = null;

  var KEY_VERDICT = "verdict:" + vehicle + ":" + session;
  var KEY_ANSWER = "answer:" + vehicle + ":" + session;
  var KEY_DRAFT = "draft:" + vehicle + ":" + session;

  var ICONS = { green: "🟢", yellow: "🟡", orange: "🟠", red: "🔴", grey: "⚪" };
  var QUALITY = { good: "хорошее", warning: "с помехами", bad: "плохое" };
  var URGENCY = { high: "высокий", medium: "средний", low: "низкий" };
  var GLOSSARY = {
    ТНВД: "топливный насос высокого давления",
    ОЖ: "охлаждающая жидкость",
    ГРМ: "газораспределительный механизм",
    ЦПГ: "цилиндропоршневая группа",
    КШМ: "кривошипно-шатунный механизм",
    ДВС: "двигатель внутреннего сгорания",
    ТОиР: "техническое обслуживание и ремонт",
  };
  var GLOSSARY_RE = new RegExp(
    "(?<![\\p{L}])(" + Object.keys(GLOSSARY).join("|") + ")(?![\\p{L}])",
    "gu"
  );

  function setBusy(value) {
    busy = value;
    if (sendBtn) sendBtn.disabled = value;
    if (diagBtn) diagBtn.disabled = value;
    chips.forEach(function (chip) {
      chip.disabled = value;
    });
  }

  function scrollToEnd(node) {
    if (node && node.scrollIntoView) node.scrollIntoView({ block: "end" });
  }

  function addBubble(kind, label) {
    var item = document.createElement("li");
    item.className = "bubble bubble-" + kind;
    var body = document.createElement("div");
    body.className = "bubble-body";
    body.textContent = label;
    item.appendChild(body);
    messagesEl.appendChild(item);
    scrollToEnd(item);
    return item;
  }

  function addRetry(item, request) {
    var retry = document.createElement("button");
    retry.type = "button";
    retry.className = "btn btn-secondary retry";
    retry.textContent = "Повторить";
    retry.addEventListener("click", function () {
      item.remove();
      run(request);
    });
    item.appendChild(retry);
  }

  function renderVerdict(data) {
    try {
      sessionStorage.setItem(KEY_VERDICT, JSON.stringify(data));
    } catch (error) {
      // Без хранилища карточка останется на экране, но после перезагрузки пропадёт.
    }
    var reasons = (data.reasons || []).slice(0, 3);
    var confidence = data.confidence == null ? "нет данных" : Math.round(data.confidence * 100) + " %";
    var quality = QUALITY[data.signal_quality] || "—";
    var urgency = data.urgency ? URGENCY[data.urgency] + " — " + (reasons[0] || "") : "не назначен";
    verdictEl.innerHTML =
      '<section class="verdict verdict-' + MC.esc(data.light) + '" aria-label="Итог проверки">' +
      '<p class="verdict-line"><span class="verdict-icon" aria-hidden="true">' +
      (ICONS[data.light] || "⚪") +
      "</span><strong>" + MC.esc(data.headline) + "</strong></p>" +
      '<dl class="verdict-facts">' +
      "<div><dt>Уверенность</dt><dd>" + confidence + "</dd></div>" +
      "<div><dt>Качество записи</dt><dd>" + quality + "</dd></div>" +
      "<div><dt>Приоритет</dt><dd>" + MC.esc(urgency) + "</dd></div>" +
      "</dl>" +
      '<ul class="verdict-reasons">' +
      reasons.map(function (r) {
        return "<li>" + MC.esc(r) + "</li>";
      }).join("") +
      "</ul></section>";
  }

  function restoreVerdict() {
    try {
      var saved = sessionStorage.getItem(KEY_VERDICT);
      if (saved) renderVerdict(JSON.parse(saved));
    } catch (error) {
      // Повреждённая запись в хранилище не должна ломать экран.
    }
  }

  function formatAnswer(text) {
    var html = MC.renderMarkdown(text);
    if (MC.currentMode() === "novice") {
      html = html.replace(GLOSSARY_RE, function (term) {
        return '<button type="button" class="term" data-term="' + term + '">' + term + "</button>";
      });
    }
    return html;
  }

  function showGlossary(term) {
    if (!popEl || !GLOSSARY[term]) return;
    popEl.textContent = term + " — " + GLOSSARY[term] + ". Нажмите ещё раз, чтобы закрыть.";
    popEl.hidden = false;
  }

  messagesEl.addEventListener("click", function (event) {
    var target = event.target.closest(".term");
    if (!target) return;
    if (!popEl.hidden && popEl.dataset.term === target.dataset.term) {
      popEl.hidden = true;
      popEl.dataset.term = "";
      return;
    }
    popEl.dataset.term = target.dataset.term;
    showGlossary(target.dataset.term);
  });

  function handleEvent(state, name, data) {
    if (name === "token") {
      if (!state.text) {
        state.body.textContent = "";
        state.body.classList.add("bubble-stream");
      }
      state.text += data.text || "";
      state.body.textContent = state.text;
    } else if (name === "verdict") {
      renderVerdict(data);
      scrollToEnd(verdictEl);
    } else if (name === "answer_final") {
      state.final = data.text || "";
      state.body.classList.remove("bubble-stream");
      state.body.classList.add("answer");
      state.body.innerHTML = formatAnswer(state.final);
      try {
        sessionStorage.setItem(KEY_ANSWER, state.final);
      } catch (error) {
        // Без хранилища шаги откроются только из чата.
      }
    } else if (name === "ticket_draft") {
      try {
        sessionStorage.setItem(KEY_DRAFT, JSON.stringify(data));
      } catch (error) {
        // Черновик останется у агента в этом ходе; без хранилища экран заявки не откроется.
      }
      var ready = addBubble("system", "Черновик заявки готов. Проверьте состав и подтвердите.");
      var link = document.createElement("a");
      link.className = "btn btn-primary";
      link.href = "/vehicles/" + vehicle + "/ticket?session=" + session;
      link.textContent = "Открыть заявку";
      ready.appendChild(link);
    } else if (name === "meta") {
      var ttft = data.ttft_ms != null ? (data.ttft_ms / 1000).toFixed(1) + " с до ответа" : "";
      var speed = data.tok_per_s != null ? Math.round(data.tok_per_s) + " ток/с" : "";
      metaEl.textContent = [ttft, speed].filter(Boolean).join(" · ");
      metaEl.hidden = !metaEl.textContent;
    } else if (name === "error") {
      state.failed = true;
      state.body.textContent = data.message || MC.errorMessage(500);
      state.item.classList.add("bubble-error");
      addRetry(state.item, state.request);
    }
  }

  async function run(request) {
    setBusy(true);
    lastRequest = request;
    var item = addBubble("agent", "Агент думает…");
    var body = item.querySelector(".bubble-body");
    var state = { item: item, body: body, text: "", final: "", failed: false, request: request };
    try {
      var response = await MC.postJson(request.url, request.body);
      if (!response.ok) {
        var detail = null;
        try {
          detail = (await response.json()).detail;
        } catch (error) {
          detail = null;
        }
        throw { status: response.status, message: MC.errorMessage(response.status, detail) };
      }
      await MC.readStream(response, function (name, data) {
        handleEvent(state, name, data);
      });
    } catch (error) {
      state.failed = true;
      body.textContent = error && error.message ? error.message : MC.errorMessage(500);
      item.classList.add("bubble-error");
      addRetry(item, request);
    }
    if (!state.failed && !state.final && !state.text) {
      body.textContent = MC.errorMessage(500);
      item.classList.add("bubble-error");
      addRetry(item, request);
    }
    if (!state.failed && state.final && MC.currentMode() === "novice" && request.message === "Этапы работ") {
      window.location.href = "/vehicles/" + vehicle + "/steps?session=" + session;
    }
    setBusy(false);
    scrollToEnd(item);
  }

  function send(label, url, body, request) {
    if (busy) return;
    addBubble("me", label);
    run(Object.assign({ url: url, body: body }, request || {}));
  }

  function askMessage(text) {
    send(text, "/api/chat", {
      vehicle_id: vehicle,
      session_id: session,
      message: text,
      ui_mode: MC.currentMode(),
    }, { message: text });
  }

  function askDiagnosis() {
    send("Получить результат диагностики", "/api/action/get_diagnosis", {
      vehicle_id: vehicle,
      session_id: session,
      ui_mode: MC.currentMode(),
    }, { message: "" });
  }

  if (composer) {
    composer.addEventListener("submit", function (event) {
      event.preventDefault();
      var text = (input.value || "").trim();
      if (!text) return;
      input.value = "";
      askMessage(text);
    });
  }
  if (diagBtn) diagBtn.addEventListener("click", askDiagnosis);
  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      askMessage(chip.dataset.msg);
    });
  });

  restoreVerdict();
  if (root.dataset.auto === "yes") {
    askDiagnosis();
  }
})();
