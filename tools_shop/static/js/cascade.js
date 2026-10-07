// Десктоп: каскадная навигация по каталогу (раздел 2 ТЗ).
//
// Каждый узел (категория) — кнопка с data-depth на родительском .cascade-node.
// Клик по узлу делает htmx-запрос (shop:cascade_level), который добавляет
// колонку того же уровня справа (#cascade-col-<depth>) в #cascade-columns
// (hx-swap="beforeend"). Активное/раскрытое состояние узла — это сама кнопка
// (is-active + aria-expanded), без отдельного дропдауна: раскрытая колонка
// справа и есть визуальный аккордеон.
//
// Этот контроллер отвечает за то, что htmx сам не умеет:
//   - перед открытием нового узла убрать колонки ПРАВЕЕ текущего уровня;
//   - повторный клик по раскрытому узлу схлопывает его и колонки правее, без запроса;
//   - подсветка активного пути во всех колонках;
//   - горизонтальный скролл каскада к свежедобавленной колонке;
//   - восстановление каскада по прямой ссылке (data-cascade-path на #cascade-columns).
(function () {
    "use strict";

    function columnsEl() {
        return document.getElementById("cascade-columns");
    }

    // Убирает колонки с data-depth > depth и снимает активность с узлов,
    // чей data-depth > depth (т.е. включая сам узел depth, если вызвано с depth-1).
    function pruneBelow(depth) {
        var columns = columnsEl();
        if (columns) {
            Array.prototype.slice.call(columns.querySelectorAll(".cascade-column")).forEach(function (col) {
                if (Number(col.dataset.depth) > depth) col.remove();
            });
        }
        document.querySelectorAll(".cascade-node").forEach(function (node) {
            if (Number(node.dataset.depth) > depth) {
                var btn = node.querySelector(".cascade-node-head");
                if (btn) { btn.setAttribute("aria-expanded", "false"); btn.classList.remove("is-active"); }
            }
        });
    }

    function clearActiveAt(depth) {
        document.querySelectorAll('.cascade-node[data-depth="' + depth + '"] .cascade-node-head').forEach(function (btn) {
            btn.classList.remove("is-active");
            btn.setAttribute("aria-expanded", "false");
        });
    }

    function scrollToEnd() {
        var columns = columnsEl();
        if (columns) columns.scrollTo({ left: columns.scrollWidth, behavior: "smooth" });
    }

    // Чтобы было место для колонок каскада: hero на главной скрывается не только при
    // поиске, но и как только появилась хотя бы одна колонка каскада.
    function syncWorkspaceVisibility() {
        var columns = columnsEl();
        var hasColumns = !!(columns && columns.querySelector(".cascade-column"));
        document.body.classList.toggle("cascade-active", hasColumns);
    }

    window.cascadeNav = {
        // Клик по кнопке узла. event — клик, depth — уровень узла (1..N).
        toggle: function (event, depth) {
            var btn = event.currentTarget;
            var alreadyOpen = btn.classList.contains("is-active") && btn.getAttribute("aria-expanded") === "true";

            if (alreadyOpen) {
                // Повторный клик по раскрытому узлу: схлопнуть, убрать колонки правее,
                // без запроса к серверу.
                event.preventDefault();
                pruneBelow(depth - 1);
                syncWorkspaceVisibility();
                return;
            }

            // Раскрываем новый узел: сначала убираем всё правее текущего уровня
            // (включая колонку depth, которая будет перезаписана ответом сервера)
            // и снимаем активность с братьев на этом же уровне.
            pruneBelow(depth - 1);
            clearActiveAt(depth);
            btn.classList.add("is-active");
            btn.setAttribute("aria-expanded", "true");
            // htmx продолжит запрос сам (hx-get на этой же кнопке).
        },
    };

    document.body.addEventListener("htmx:afterSwap", function (evt) {
        if (evt.target && evt.target.id === "cascade-columns") {
            scrollToEnd();
            syncWorkspaceVisibility();
        }
    });

    // Восстановление каскада при обычной загрузке страницы категории на десктопе:
    // #cascade-columns несёт data-cascade-path="slug1,slug2,...", контроллер
    // последовательно "кликает" по узлам того же пути через реальные htmx-запросы
    // (shop:cascade_level) — те же данные и разметка, что при ручной навигации.
    // Кнопка каждого узла ищется по hx-get="/cascade/<slug>/", без отдельного id.
    document.addEventListener("DOMContentLoaded", function () {
        var columns = columnsEl();
        if (!columns || !columns.dataset.cascadePath) return;
        var path = columns.dataset.cascadePath.split(",").filter(Boolean);
        if (!path.length || window.htmx === undefined) return;

        function findNodeButton(slug) {
            return document.querySelector('.cascade-node-head[hx-get="/cascade/' + slug + '/"]');
        }

        function openNext(index) {
            if (index >= path.length) return;
            var btn = findNodeButton(path[index]);
            if (!btn) return;
            btn.classList.add("is-active");
            btn.setAttribute("aria-expanded", "true");
            window.htmx.ajax("GET", btn.getAttribute("hx-get"), { target: "#cascade-columns", swap: "beforeend" })
                .then(function () { openNext(index + 1); });
        }
        openNext(0);
    });
})();
