/* Markdown ответа агента для мобильного экрана механика: заголовки, списки, абзацы, жирный,
 * ссылки на руководство («📖 документ, стр. N»). Сначала экранируем весь текст, затем размечаем,
 * поэтому HTML из ответа модели не выполняется. Подключается после common.js.
 */
(function () {
  "use strict";
  var MC = (window.MC = window.MC || {});

  var HEADING_RE = /^(#{1,6})\s+(.+)$/;
  var RULE_RE = /^(-{3,}|\*{3,}|_{3,})$/;
  var TABLE_SEP_RE = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$/;
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

  /* Таблица начинается строкой с «|» и строкой-разделителем вида |---|---|. */
  function isTableStart(lines, i) {
    if (i + 1 >= lines.length) return false;
    var head = lines[i].trim();
    var sep = lines[i + 1].trim();
    return head.indexOf("|") !== -1 && sep.indexOf("|") !== -1 && TABLE_SEP_RE.test(sep);
  }

  function splitRow(line) {
    var row = line.trim();
    if (row.charAt(0) === "|") row = row.slice(1);
    if (row.charAt(row.length - 1) === "|") row = row.slice(0, -1);
    return row.split("|").map(function (cell) {
      return cell.trim();
    });
  }

  /* Таблица в блоке с прокруткой: широкие OCR-таблицы не ломают страницу. */
  function renderTable(lines, start) {
    var head = splitRow(lines[start]);
    var rows = [];
    var i = start + 2;
    while (i < lines.length) {
      var line = lines[i].trim();
      if (!line || line.indexOf("|") === -1) break;
      rows.push(splitRow(line));
      i++;
    }
    var th = head
      .map(function (cell) {
        return "<th>" + inline(cell) + "</th>";
      })
      .join("");
    var tr = rows
      .map(function (cells) {
        return (
          "<tr>" +
          cells
            .map(function (cell) {
              return "<td>" + inline(cell) + "</td>";
            })
            .join("") +
          "</tr>"
        );
      })
      .join("");
    var html =
      '<div class="table-wrap" role="region" tabindex="0" aria-label="Таблица: прокрутите вправо, чтобы увидеть все столбцы">' +
      "<table><thead><tr>" +
      th +
      "</tr></thead><tbody>" +
      tr +
      "</tbody></table></div>";
    return { html: html, next: i };
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
      if (isTableStart(lines, i)) {
        var table = renderTable(lines, i);
        html.push(table.html);
        i = table.next;
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
        if (!text || isBlockStart(text) || isTableStart(lines, i)) break;
        para.push(inline(text));
        i++;
      }
      html.push("<p>" + para.join("<br>") + "</p>");
    }
    return html.join("");
  }

  MC.renderMarkdown = renderMarkdown;
})();
