/* Общие функции интерфейса: экранирование, чтение SSE, понятные тексты ошибок.
 * Все тексты для механика — на русском. Без сборщика: подключается обычным script. */
(function () {
  "use strict";
  var MC = (window.MC = window.MC || {});

  var ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  MC.esc = function (text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return ESCAPES[c];
    });
  };

  MC.errorMessage = function (status, detail) {
    if (status === 0 || status === undefined) {
      return "Нет связи с сервером. Проверьте сеть и повторите.";
    }
    if (status === 404) {
      return detail || "Не найдено. Проверьте номер и вернитесь к списку.";
    }
    if (status >= 500) {
      return "Сервис временно недоступен. Повторите через минуту.";
    }
    return detail || "Не получилось выполнить действие. Повторите.";
  };

  MC.toast = function (text) {
    var el = document.getElementById("toast");
    if (!el) return;
    el.textContent = text;
    el.hidden = false;
    clearTimeout(MC._toastTimer);
    MC._toastTimer = setTimeout(function () {
      el.hidden = true;
    }, 4000);
  };

  function parseBlock(block, onEvent) {
    var name = "message";
    var data = [];
    block.split("\n").forEach(function (line) {
      if (line.indexOf("event:") === 0) name = line.slice(6).trim();
      else if (line.indexOf("data:") === 0) data.push(line.slice(5).trim());
    });
    if (!data.length) return;
    try {
      onEvent(name, JSON.parse(data.join("\n")));
    } catch (error) {
      // Битый кусок потока пропускаем: следующие события всё равно придут.
    }
  }

  /* Читает text/event-stream из fetch (EventSource не умеет POST). */
  MC.readStream = async function (response, onEvent) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder("utf-8");
    var buffer = "";
    for (;;) {
      var chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      var parts = buffer.split("\n\n");
      buffer = parts.pop();
      parts.forEach(function (part) {
        parseBlock(part, onEvent);
      });
    }
    if (buffer.trim()) parseBlock(buffer, onEvent);
  };

  MC.postJson = async function (url, body) {
    var response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (error) {
      throw { status: 0, message: MC.errorMessage(0) };
    }
    return response;
  };
})();
