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
                if (btn) {
                    btn.setAttribute("aria-expanded", "false");
                    btn.classList.remove("is-active");
                    if (Number(node.dataset.depth) === 1) setDropdown(btn, false);
                }
            }
        });
    }

    function clearActiveAt(depth) {
        document.querySelectorAll('.cascade-node[data-depth="' + depth + '"] .cascade-node-head').forEach(function (btn) {
            btn.classList.remove("is-active");
            btn.setAttribute("aria-expanded", "false");
            if (depth === 1) setDropdown(btn, false);
        });
    }

    function setDropdown(btn, open) {
        var dropdown = btn.parentElement.querySelector(":scope > .cascade-dropdown");
        if (dropdown) dropdown.hidden = !open;
    }

    function syncRootDropdown() {
        // Ищем именно раскрытый узел первого уровня, а не первый в DOM:
        // dropdown живёт под своей основной категорией.
        var rootNode = null;
        var nodes = document.querySelectorAll('.cascade-node[data-depth="1"]');
        for (var i = 0; i < nodes.length; i++) {
            var dd = nodes[i].querySelector(":scope > .cascade-dropdown");
            if (dd && !dd.hidden) { rootNode = nodes[i]; break; }
        }
        if (!rootNode) return;
        var dropdown = rootNode.querySelector(":scope > .cascade-dropdown");
        if (!dropdown || dropdown.hidden) return;
        
        // Пытаемся получить активную подкатегорию из каскада
        var slug = null;
        var active = document.querySelector('.cascade-node[data-depth="2"] .cascade-node-head.is-active');
        if (active) {
            var hxGet = active.getAttribute("hx-get") || "";
            var m = hxGet.match(/\/cascade\/([^\/]+)\//);  
            if (m) slug = m[1];
        }
        
        // Если активная подкатегория не найдена в каскаде, берём второй элемент
        // cascade-path — это подкатегория, которой соответствует элемент dropdown
        // (путь: основная категория, подкатегория, её детки, ...).
        if (!slug) {
            var columns = document.getElementById("cascade-columns");
            if (columns && columns.dataset.cascadePath) {
                var path = columns.dataset.cascadePath.split(",").filter(Boolean);
                if (path.length > 1) {
                    slug = path[1];
                }
            }
        }
        
        dropdown.querySelectorAll(".cascade-dropdown-item").forEach(function (item) {
            var isActive = !!slug && item.dataset.categorySlug === slug;
            item.classList.toggle("is-active", isActive);
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
    var cols = columns ? Array.prototype.slice.call(columns.querySelectorAll(".cascade-column")) : [];
    document.body.classList.toggle("cascade-active", cols.length > 0);

    // Режим «лист»: остаются левая панель и колонка с товарами,
    // все промежуточные колонки подкатегорий скрыты.
    var hasLeaf = cols.some(function (col) { return col.dataset.leaf === "1"; });
    cols.forEach(function (col) {
        col.classList.toggle("is-collapsed", hasLeaf && col.dataset.leaf !== "1");
    });
    if (columns) columns.classList.toggle("has-leaf", hasLeaf);
}

    document.body.addEventListener("htmx:beforeRequest", function (evt) {
    var btn = evt.detail.elt;
    if (!btn || !btn.classList || !btn.classList.contains("cascade-node-head")) return;

    var depth = Number(btn.closest(".cascade-node").dataset.depth);
    var alreadyOpen = btn.classList.contains("is-active") &&
                      btn.getAttribute("aria-expanded") === "true";

    if (depth === 1 && alreadyOpen) {
        // Повторный клик по основной категории: закрываем dropdown и схлопываем её колонку.
        setDropdown(btn, false);
        pruneBelow(0);
        syncWorkspaceVisibility();
        evt.preventDefault();
        return;
    }

    pruneBelow(depth - 1);

    if (alreadyOpen) {
        evt.preventDefault();       // повторный клик по подкатегории схлопывает её по прежним правилам
        syncWorkspaceVisibility();
        return;
    }

    // Открываем новый узел: cascade-active не трогаем,
    // его обновит htmx:afterSwap после вставки колонки.
    clearActiveAt(depth);
    btn.classList.add("is-active");
    btn.setAttribute("aria-expanded", "true");
    // Dropdown основной категории остаётся открыт до выбора другой основной.
    if (depth === 1) setDropdown(btn, true);
    syncRootDropdown();
});
    document.body.addEventListener("htmx:afterSwap", function (evt) {
        if (evt.target && evt.target.id === "cascade-columns") {
            scrollToEnd();
            syncWorkspaceVisibility();
            syncRootDropdown();
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
            if (index >= path.length) {
                // Весь путь восстановлен, финальная синхронизация dropdown
                syncRootDropdown();
                return;
            }
            var btn = findNodeButton(path[index]);
            if (!btn) return;
            btn.classList.add("is-active");
            btn.setAttribute("aria-expanded", "true");
            if (Number(btn.closest(".cascade-node").dataset.depth) === 1) setDropdown(btn, true);
            window.htmx.ajax("GET", btn.getAttribute("hx-get"), { target: "#cascade-columns", swap: "beforeend" })
                .then(function () { 
                    syncRootDropdown();
                    openNext(index + 1); 
                });
        }
        openNext(0);
    });
    
    // Клик по крошке или dropdown-элементу = клик по кнопке этой категории в каскаде (без перезагрузки страницы).
document.addEventListener("click", function (e) {
    var link = e.target.closest("a[data-crumb-slug], a.cascade-dropdown-item");
    if (!link || window.htmx === undefined) return;

    var slug = link.dataset.crumbSlug || link.dataset.categorySlug;
    if (!slug) return;

    var btn = document.querySelector('.cascade-node-head[hx-get="/cascade/' + slug + '/"]');
    if (!btn) return;            // кнопки нет в DOM: сработает обычная ссылка

    e.preventDefault();
    // Сбрасываем «раскрыто», иначе повторный клик по открытому узлу его схлопнет.
    btn.classList.remove("is-active");
    btn.setAttribute("aria-expanded", "false");
    btn.click();                 // дальше всё делает htmx:beforeRequest и hx-push-url
});
})();
