// Простейший слайдер изображений в модальных окнах товара (.image-modal).
//
// Разметка: [data-slider] > [data-slider-track] > img + кнопки
// [data-slider-prev] / [data-slider-next] + [data-slider-counter].
// Все обработчики делегированы на document: карточка товара на десктопе
// подгружается htmx-ом, поэтому инициализацию после swap делать не нужно.
//
// Управление: стрелки, клавиши ← / →, свайп на сенсорных экранах. Листание по
// кругу. Клик по подложке (сам <dialog>, а не его содержимое) закрывает окно.
(function () {
    "use strict";

    var SWIPE_THRESHOLD = 40;  // px, меньше — считаем обычным тапом

    function slidesOf(slider) {
        return Array.prototype.slice.call(
            slider.querySelectorAll("[data-slider-track] img")
        );
    }

    function currentIndex(slides) {
        for (var i = 0; i < slides.length; i++) {
            if (!slides[i].hidden) return i;
        }
        return 0;
    }

    function show(slider, index) {
        var slides = slidesOf(slider);
        if (slides.length < 2) return;
        index = (index + slides.length) % slides.length;
        slides.forEach(function (img, i) {
            img.hidden = i !== index;
        });
        var counter = slider.querySelector("[data-slider-counter]");
        if (counter) counter.textContent = (index + 1) + " / " + slides.length;
    }

    function step(slider, direction) {
        if (!slider) return;
        var slides = slidesOf(slider);
        if (slides.length < 2) return;
        show(slider, currentIndex(slides) + direction);
    }

    document.addEventListener("click", function (event) {
        var target = event.target;
        if (!(target instanceof Element)) return;

        var prev = target.closest("[data-slider-prev]");
        var next = target.closest("[data-slider-next]");
        if (prev || next) {
            step((prev || next).closest("[data-slider]"), prev ? -1 : 1);
            return;
        }

        // клик по подложке (вне содержимого окна) закрывает модалку
        if (target.matches("dialog.image-modal")) target.close();
    });

    document.addEventListener("keydown", function (event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        var dialog = document.querySelector("dialog.image-modal[open]");
        if (!dialog) return;
        var slider = dialog.querySelector("[data-slider]");
        if (!slider || slidesOf(slider).length < 2) return;
        event.preventDefault();
        step(slider, event.key === "ArrowRight" ? 1 : -1);
    });

    // свайп: запоминаем точку начала и сравниваем с точкой отпускания
    var swipe = null;

    document.addEventListener("pointerdown", function (event) {
        if (event.pointerType === "mouse") return;
        var target = event.target;
        if (!(target instanceof Element)) return;
        var track = target.closest("[data-slider-track]");
        if (!track) return;
        swipe = {
            x: event.clientX,
            y: event.clientY,
            slider: track.closest("[data-slider]")
        };
    });

    document.addEventListener("pointerup", function (event) {
        if (!swipe) return;
        var dx = event.clientX - swipe.x;
        var dy = event.clientY - swipe.y;
        var slider = swipe.slider;
        swipe = null;
        if (!slider || Math.abs(dx) < SWIPE_THRESHOLD || Math.abs(dx) <= Math.abs(dy)) return;
        step(slider, dx < 0 ? 1 : -1);
    });

    document.addEventListener("pointercancel", function () {
        swipe = null;
    });
})();
