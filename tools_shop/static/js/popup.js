// Всплывающее окно при входе на сайт (shop/partials/popup_notice.html).
//
// Показывается один раз за сессию браузера: факт показа запоминается в
// sessionStorage (ключ привязан к id окна) — при переходах по сайту и повторной
// загрузке в той же вкладке окно не всплывает снова.
// Закрытие: крестик, кнопка без ссылки, фон (backdrop) или Esc.
(function () {
    "use strict";

    var STORAGE_PREFIX = "popup_seen_";

    function wasSeen(id) {
        try {
            return sessionStorage.getItem(STORAGE_PREFIX + id) === "1";
        } catch (e) {
            return false;
        }
    }

    function markSeen(id) {
        try {
            sessionStorage.setItem(STORAGE_PREFIX + id, "1");
        } catch (e) {
            // приватный режим — просто покажем окно ещё раз
        }
    }

    function init() {
        var dialog = document.getElementById("site-popup");
        if (!dialog) return;

        var id = dialog.dataset.popupId || "0";

        // уже показывали в этой сессии — второй раз не открываем
        if (wasSeen(id)) return;
        markSeen(id);

        function close() {
            if (dialog.open) dialog.close();
        }

        // клик по фону закрывает: точки вне прямоугольника самого диалога
        dialog.addEventListener("click", function (event) {
            var box = dialog.getBoundingClientRect();
            var inside = event.clientX >= box.left && event.clientX <= box.right &&
                         event.clientY >= box.top && event.clientY <= box.bottom;
            if (!inside) close();
        });

        dialog.querySelectorAll("[data-popup-close]").forEach(function (el) {
            el.addEventListener("click", close);
        });

        // Esc закрывает нативно; фиксируем закрытие на случай будущей логики
        dialog.addEventListener("close", function () { markSeen(id); });

        if (typeof dialog.showModal === "function") {
            dialog.showModal();
        } else {
            dialog.setAttribute("open", "");
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
