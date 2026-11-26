/* Экран заявки: секции как в ТОиР, отправка после галочки «Состав проверил».
 * Черновик и вердикт берём из sessionStorage (их положил чат). Подтверждение — POST /api/tickets/confirm.
 */
(function () {
  "use strict";
  var MC = window.MC;
  var root = document.getElementById("ticket-root");
  if (!root || !MC) return;

  var vehicle = root.dataset.vehicle;
  var session = root.dataset.session;
  var KEY_DRAFT = "draft:" + vehicle + ":" + session;
  var KEY_VERDICT = "verdict:" + vehicle + ":" + session;
  var URGENCY = { high: "высокий", medium: "средний", low: "низкий" };

  var emptyEl = document.getElementById("ticket-empty");
  var bodyEl = document.getElementById("ticket-body");
  var statusEl = document.getElementById("ticket-status");
  var sendBtn = document.getElementById("send-ticket");
  var checkedBox = document.getElementById("checked-box");

  function readJson(key) {
    try {
      var raw = sessionStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function setText(id, text) {
    document.getElementById(id).textContent = text;
  }

  function fillList(id, items, emptyText) {
    var list = document.getElementById(id);
    list.innerHTML = "";
    if (!items || !items.length) {
      var item = document.createElement("li");
      item.textContent = emptyText;
      list.appendChild(item);
      return;
    }
    items.forEach(function (text) {
      var li = document.createElement("li");
      li.textContent = text;
      list.appendChild(li);
    });
  }

  function render(draft, verdict) {
    var ticket = draft.ticket || {};
    setText("t-type", ticket.anomaly_type + (verdict && verdict.headline ? " · " + verdict.headline : ""));
    setText("t-conclusion", ticket.conclusion || "—");
    var reasons = verdict && verdict.reasons ? verdict.reasons.join("; ") : "";
    setText(
      "t-urgency",
      (URGENCY[ticket.urgency] || "—") + (reasons ? " — " + reasons : "")
    );
    fillList("t-operations", ticket.operations, "Работы не указаны");
    fillList("t-parts", ticket.spare_parts, "Запчасти не указаны");
    var refs = (ticket.references || []).map(function (ref) {
      return ref.manual + ", стр. " + ref.pdf_page;
    });
    fillList("t-refs", refs, "Ссылок на руководство нет");
    bodyEl.hidden = false;
  }

  function showStatus(kind, text) {
    statusEl.hidden = false;
    statusEl.className = "notice " + kind;
    statusEl.textContent = text;
  }

  async function confirm(draft) {
    sendBtn.disabled = true;
    showStatus("", "Отправляем в ТОиР…");
    try {
      var response = await MC.postJson("/api/tickets/confirm", {
        draft_id: draft.draft_id,
        confirm_token: draft.confirm_token,
      });
      var data = null;
      try {
        data = await response.json();
      } catch (error) {
        data = null;
      }
      if (response.ok) {
        showStatus("notice-ok", "✅ Заявка " + data.ticket_id + " создана");
        sendBtn.textContent = "Заявка отправлена";
        return;
      }
      showStatus("notice-error", MC.errorMessage(response.status, data && data.detail));
    } catch (error) {
      showStatus("notice-error", MC.errorMessage(0));
    }
    sendBtn.disabled = !checkedBox.checked;
  }

  function init() {
    var draft = readJson(KEY_DRAFT);
    if (!draft || !draft.ticket) {
      emptyEl.hidden = false;
      return;
    }
    render(draft, readJson(KEY_VERDICT));
    sendBtn.addEventListener("click", function () {
      if (!checkedBox.checked) return;
      confirm(draft);
    });
  }

  init();
})();
