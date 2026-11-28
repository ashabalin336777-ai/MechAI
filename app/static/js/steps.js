/* Экран «Шаги»: этапы работ из последнего ответа агента — по одному на экране.
 * Этапы берём из нумерованного списка под заголовком «Этап…»; если заголовка нет — все пункты.
 */
(function () {
  "use strict";
  var MC = window.MC;
  var root = document.getElementById("steps-root");
  if (!root || !MC) return;

  var vehicle = root.dataset.vehicle;
  var session = root.dataset.session;
  var KEY_ANSWER = "answer:" + vehicle + ":" + session;
  var KEY_STEP = "step:" + vehicle + ":" + session;

  var emptyEl = document.getElementById("steps-empty");
  var bodyEl = document.getElementById("steps-body");
  var doneEl = document.getElementById("steps-done");
  var progressEl = document.getElementById("step-progress");
  var textEl = document.getElementById("step-text");
  var sourceEl = document.getElementById("step-source");
  var nextBtn = document.getElementById("step-next");
  var backBtn = document.getElementById("step-back");

  var SOURCE_RE = /\[([^\[\]]+?),\s*стр\.\s*(\d+)\]/;
  var NUMBERED_RE = /^\s*(\d+)[.)]\s+(.+)$/;
  var HEADING_RE = /^\s*(#{1,6}\s|\*\*[^*]+\*\*\s*$)/;

  function cleanText(line) {
    return line.replace(/\*\*/g, "").replace(/`(\[[^\[\]]+?,\s*стр\.\s*\d+\])`/g, "$1").trim();
  }

  /* Пункты под заголовком «Этап…»; если заголовка нет — все нумерованные строки ответа. */
  function parseSteps(answer) {
    var lines = answer.split("\n");
    var start = -1;
    for (var i = 0; i < lines.length; i++) {
      if (/этап/i.test(lines[i]) && HEADING_RE.test(lines[i])) {
        start = i + 1;
        break;
      }
    }
    var scope = [];
    if (start >= 0) {
      for (var j = start; j < lines.length; j++) {
        if (HEADING_RE.test(lines[j])) break;
        scope.push(lines[j]);
      }
    } else {
      scope = lines;
    }
    var steps = [];
    scope.forEach(function (line) {
      var match = line.match(NUMBERED_RE);
      if (!match) return;
      var text = cleanText(match[2]);
      var source = text.match(SOURCE_RE);
      steps.push({
        text: text,
        source: source ? source[1] + ", стр. " + source[2] : "",
      });
    });
    return steps;
  }

  function readSaved(key) {
    try {
      return sessionStorage.getItem(key);
    } catch (error) {
      return null;
    }
  }

  function render(steps, index) {
    var step = steps[index];
    progressEl.textContent = "Шаг " + (index + 1) + " из " + steps.length;
    textEl.textContent = step.text;
    sourceEl.textContent = step.source ? "Источник: " + step.source : "Источник в ответе не указан";
    backBtn.disabled = index === 0;
  }

  function finish() {
    bodyEl.hidden = true;
    doneEl.hidden = false;
  }

  function init() {
    var answer = readSaved(KEY_ANSWER);
    var steps = answer ? parseSteps(answer) : [];
    if (!steps.length) {
      emptyEl.hidden = false;
      return;
    }
    var index = Math.min(parseInt(readSaved(KEY_STEP) || "0", 10) || 0, steps.length - 1);
    bodyEl.hidden = false;
    render(steps, index);

    nextBtn.addEventListener("click", function () {
      if (index + 1 >= steps.length) {
        try {
          sessionStorage.removeItem(KEY_STEP);
        } catch (error) {
          // Прогресс просто не сохранится.
        }
        finish();
        return;
      }
      index += 1;
      try {
        sessionStorage.setItem(KEY_STEP, String(index));
      } catch (error) {
        // Без хранилища прогресс не сохранится между экранами.
      }
      render(steps, index);
    });
    backBtn.addEventListener("click", function () {
      if (index === 0) return;
      index -= 1;
      render(steps, index);
    });
  }

  init();
})();
