'use strict';
/* Тема админки = тема сайта: тот же ключ localStorage ('theme') и те же значения light/dark. */
(function () {
    function systemTheme() {
        return window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function apply(theme) {
        document.documentElement.setAttribute('data-theme', theme);
    }

    var saved = null;
    try { saved = localStorage.getItem('theme'); } catch (e) {}
    // у стандартной админки бывает значение "auto" — приводим к light/dark
    apply(saved === 'light' || saved === 'dark' ? saved : systemTheme());

    window.addEventListener('load', function () {
        var buttons = document.getElementsByClassName('theme-toggle');
        Array.prototype.forEach.call(buttons, function (btn) {
            btn.addEventListener('click', function () {
                var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
                apply(next);
                try { localStorage.setItem('theme', next); } catch (e) {}
            });
        });
    });
})();
