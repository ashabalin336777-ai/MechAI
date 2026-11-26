/* Переключатель «Аа»: Стандартный → Новичок → Крупный. Выбор хранится в localStorage. */
(function () {
  "use strict";
  var NAMES = { standard: "Стандартный", novice: "Новичок", senior: "Крупный" };
  var ORDER = ["standard", "novice", "senior"];
  var button = document.getElementById("mode-toggle");

  function current() {
    var mode = document.documentElement.dataset.mode;
    return NAMES[mode] ? mode : "standard";
  }

  function paint(mode) {
    if (!button) return;
    button.textContent = "Аа · " + NAMES[mode];
    button.setAttribute("aria-label", "Режим: " + NAMES[mode] + ". Нажмите, чтобы сменить");
  }

  function apply(mode) {
    document.documentElement.dataset.mode = mode;
    try {
      localStorage.setItem("mode", mode);
    } catch (error) {
      // Режим просто не запомнится, если хранилище закрыто.
    }
    paint(mode);
  }

  window.MC = window.MC || {};
  window.MC.currentMode = current;

  if (button) {
    paint(current());
    button.addEventListener("click", function () {
      var next = ORDER[(ORDER.indexOf(current()) + 1) % ORDER.length];
      apply(next);
    });
  }
})();
