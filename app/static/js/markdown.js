/* Markdown ответа агента для мобильного экрана механика: заголовки, списки, абзацы, жирный,
 * ссылки на руководство («📖 документ, стр. N»). Сначала экранируем весь текст, затем размечаем,
 * поэтому HTML из ответа модели не выполняется. Подключается после common.js.
 */
(function () {
  "use strict";
  var MC = (window.MC = window.MC || {});

  var HEADING_RE = /^(#{1,6})\s+(.+)$/;
  var RULE_RE = /^(-{3,}|\*{3,}|_{3,})$/;
  var UL_RE = /^[-*•]\s+/;
  var OL_RE = /^(\d+)[.)]\s+/;
  var CITE_RE = /\[([^\[\]]+?),\s*стр\.\s*(\d+)\]/g;

  function inline(text) {
    return MC.esc(text)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(CITE_RE, '<span class="cite">📖 $1, стр. $2</span>');
  }

  function isBlockStart(line) {
    return HEADING_RE.test(line) || RULE_RE.test(line) || UL_RE.test(line) || OL_RE.test(line);
  }

  function renderList(lines, start, pattern, tag) {
    var items = [];
    var i = start;
    var first = null;
    while (i < lines.length) {
      var line = lines[i].trim();
      var match = pattern.exec(line);
      if (!match) break;
      if (first === null && tag === "ol") first = parseInt(match[1], 10);
      items.push("<li>" + inline(line.replace(pattern, "")) + "</li>");
      i++;
    }
    var open = tag === "ol" && first && first !== 1 ? '<ol start="' + first + '">' : "<" + tag + ">";
    return { html: open + items.join("") + "</" + tag + ">", next: i };
  }

  /* Возвращает HTML. Пустой ввод даёт пустую строку. */
  function renderMarkdown(source) {
    var lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
    var html = [];
    var i = 0;
    while (i < lines.length) {
      var line = lines[i].trim();
      if (!line) {
        i++;
        continue;
      }
      var heading = HEADING_RE.exec(line);
      if (heading) {
        var level = Math.min(heading[1].length + 1, 4);
        html.push("<h" + level + ">" + inline(heading[2]) + "</h" + level + ">");
        i++;
        continue;
      }
      if (RULE_RE.test(line)) {
        html.push('<hr class="sep">');
        i++;
        continue;
      }
      if (UL_RE.test(line)) {
        var ul = renderList(lines, i, UL_RE, "ul");
        html.push(ul.html);
        i = ul.next;
        continue;
      }
      if (OL_RE.test(line)) {
        var ol = renderList(lines, i, OL_RE, "ol");
        html.push(ol.html);
        i = ol.next;
        continue;
      }
      var para = [];
      while (i < lines.length) {
        var text = lines[i].trim();
        if (!text || isBlockStart(text)) break;
        para.push(inline(text));
        i++;
      }
      html.push("<p>" + para.join("<br>") + "</p>");
    }
    return html.join("");
  }

  MC.renderMarkdown = renderMarkdown;
})();
