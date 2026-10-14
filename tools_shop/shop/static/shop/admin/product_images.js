(function () {
    "use strict";

    // Отключаем автоматическое обнаружение сразу после загрузки Dropzone.
    // Иначе библиотека сама создаёт экземпляр до передачи url из data-upload-url.
    if (typeof Dropzone !== "undefined") Dropzone.autoDiscover = false;

    function getCookie(name) {
        return document.cookie.split(";").map(function (part) {
            return part.trim();
        }).filter(function (part) {
            return part.indexOf(name + "=") === 0;
        }).map(function (part) {
            return decodeURIComponent(part.slice(name.length + 1));
        })[0] || "";
    }

    function reorder(dropzone) {
        var ids = Array.prototype.map.call(
            dropzone.querySelectorAll(".dz-preview[data-image-id]"),
            function (element) { return Number(element.dataset.imageId); }
        );
        return fetch(dropzone.dataset.reorderUrl, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCookie("csrftoken"),
                "X-Requested-With": "XMLHttpRequest"
            },
            body: JSON.stringify({product: dropzone.element.dataset.productId, ids: ids})
        }).then(function (response) {
            if (!response.ok) throw new Error("Не удалось сохранить порядок изображений");
        });
    }

    function init() {
        var element = document.getElementById("product-images-dropzone");
        if (!element || element.dataset.dropzoneInitialized === "true") return;
        if (typeof Dropzone === "undefined") {
            element.classList.add("product-images-error");
            element.querySelector(".dz-message").textContent = "Не удалось загрузить компонент загрузки изображений.";
            return;
        }

        Dropzone.autoDiscover = false;
        element.dataset.dropzoneInitialized = "true";
        var dropzone;
        try {
            dropzone = new Dropzone(element, {
            url: element.dataset.uploadUrl,
            params: {product: element.dataset.productId},
            paramName: "file",
            acceptedFiles: "image/*",
            maxFilesize: 10,
            addRemoveLinks: true,
            headers: {"X-CSRFToken": getCookie("csrftoken")},
            dictDefaultMessage: "Перетащите изображения сюда или нажмите для выбора",
            dictRemoveFile: "Удалить",
            dictCancelUpload: "Удалить",
            dictCancelUploadConfirmation: "Удалить загрузку?",
            dictFileTooBig: "Изображение не должно быть больше 10 МБ",
            init: function () {
                var instance = this;
                Array.prototype.forEach.call(
                    document.querySelectorAll("#product-images-existing .product-image-existing"),
                    function (item) {
                        var mock = {name: "Изображение", accepted: true, size: 0};
                        instance.emit("addedfile", mock);
                        instance.emit("thumbnail", mock, item.dataset.url);
                        instance.emit("complete", mock);
                        mock.previewElement.draggable = true;
                        mock.previewElement.dataset.imageId = item.dataset.imageId;
                        mock.previewElement.dataset.existing = "true";
                        mock.previewElement.querySelector(".dz-remove").textContent = "Удалить";
                    }
                );
                instance.on("success", function (file, response) {
                    file.previewElement.draggable = true;
                    file.previewElement.dataset.imageId = response.id;
                    file.previewElement.dataset.existing = "true";
                    reorder(instance);
                });
                instance.on("removedfile", function (file) {
                    if (!file.previewElement || !file.previewElement.dataset.imageId) return;
                    var id = file.previewElement.dataset.imageId;
                    fetch(element.dataset.deleteUrl.replace("{id}", id), {
                        method: "POST",
                        headers: {"X-CSRFToken": getCookie("csrftoken")}
                    }).then(function (response) {
                        if (!response.ok) throw new Error("Не удалось удалить изображение");
                        return reorder(instance);
                    }).catch(function (error) {
                        window.alert(error.message);
                    });
                });
                instance.on("queuecomplete", function () { reorder(instance); });
                instance.on("error", function (_file, message) {
                    window.alert(typeof message === "string" ? message : "Ошибка загрузки изображения");
                });
            }
            });
        } catch (error) {
            element.classList.add("product-images-error");
            element.querySelector(".dz-message").textContent = "Не удалось инициализировать загрузку изображений.";
            console.error(error);
            return;
        }

        element.addEventListener("drop", function () {
            window.setTimeout(function () { reorder(dropzone); }, 0);
        });

        var dragged;
        element.addEventListener("dragstart", function (event) {
            if (event.target.classList.contains("dz-preview")) {
                dragged = event.target;
                event.dataTransfer.effectAllowed = "move";
            }
        });
        element.addEventListener("dragover", function (event) {
            var target = event.target.closest(".dz-preview");
            if (!dragged || !target || target === dragged) return;
            event.preventDefault();
            var rect = target.getBoundingClientRect();
            target.parentNode.insertBefore(dragged, event.clientX < rect.left + rect.width / 2 ? target : target.nextSibling);
        });
        element.addEventListener("dragend", function () {
            if (!dragged) return;
            dragged = null;
            reorder(dropzone);
        });
        element.addEventListener("click", function (event) {
            if (event.target.classList.contains("dz-remove")) event.stopPropagation();
        });
    }

    document.addEventListener("DOMContentLoaded", init);
})();
