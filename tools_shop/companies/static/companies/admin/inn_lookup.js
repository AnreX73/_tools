(function () {
    "use strict";

    // ИНН юрлица — 10 цифр, ИП — 12. Промежуточные значения не отправляем:
    // иначе каждый ответ перезаписывал бы поля, пока менеджер ещё печатает.
    var TRIGGER_LENGTHS = [10, 12];
    var DEBOUNCE_MS = 800;
    var FIELDS = [
        "short_name",
        "full_name",
        "legal_form",
        "kpp",
        "ogrn",
        "legal_address"
    ];

    function getCookie(name) {
        return document.cookie.split(";").map(function (part) {
            return part.trim();
        }).filter(function (part) {
            return part.indexOf(name + "=") === 0;
        }).map(function (part) {
            return decodeURIComponent(part.slice(name.length + 1));
        })[0] || "";
    }

    function field(name) {
        return document.getElementById("id_" + name);
    }

    function digits(value) {
        return String(value || "").replace(/\s+/g, "");
    }

    function setField(name, value) {
        var element = field(name);
        if (!element || value === undefined || value === null || value === "") {
            return false;
        }
        if (element.tagName === "SELECT") {
            var option = Array.prototype.find.call(element.options, function (item) {
                return item.value === value;
            });
            if (!option || element.value === value) return false;
            element.value = value;
        } else {
            if (element.value === value) return false;
            element.value = value;
        }
        element.dispatchEvent(new Event("input", { bubbles: true }));
        element.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
    }

    function init() {
        var root = document.querySelector("[data-inn-lookup]");
        if (!root || root.dataset.innLookupReady === "true") return;

        var input = field("inn");
        var kpp = field("kpp");
        var button = root.querySelector("[data-inn-lookup-button]");
        var status = root.querySelector("[data-inn-lookup-status]");
        var url = root.dataset.url;
        if (!input || !button || !status || !url) return;

        root.dataset.innLookupReady = "true";

        var timer = null;
        var lastValue = "";
        var controller = null;
        // Значения на момент открытия страницы. Автоподстановка не трогает
        // только то, что менеджер изменил руками, — иначе ОПФ с дефолтным
        // «ООО» никогда бы не обновилась на «ПАО»/«ИП».
        var initialValues = {};
        FIELDS.forEach(function (name) {
            var element = field(name);
            initialValues[name] = element ? element.value : "";
        });

        function paint(message, level) {
            status.textContent = message || "";
            status.className = "inn-lookup__status" + (level ? " is-" + level : "");
        }

        function fill(fields, overwrite) {
            var changed = 0;
            FIELDS.forEach(function (name) {
                var element = field(name);
                if (!element) return;
                // Автоподстановка не затирает то, что менеджер уже ввёл сам,
                // но обновляет нетронутые значения (включая дефолтную ОПФ).
                if (!overwrite && element.value.trim()
                        && element.value !== initialValues[name]) {
                    return;
                }
                if (setField(name, fields[name])) {
                    changed += 1;
                    // Запоминаем подставленное значение как «нетронутое»:
                    // при следующей смене ИНН его можно обновить снова.
                    initialValues[name] = element.value;
                }
            });
            return changed;
        }

        function hasValues() {
            return FIELDS.some(function (name) {
                var element = field(name);
                return element && element.value.trim();
            });
        }

        function request(overwrite) {
            var inn = digits(input.value);
            if (TRIGGER_LENGTHS.indexOf(inn.length) === -1) return;

            if (controller) controller.abort();
            controller = new AbortController();

            button.disabled = true;
            paint("Ищу организацию…");

            var body = new URLSearchParams();
            body.set("inn", inn);
            body.set("kpp", digits(kpp && kpp.value));

            fetch(url, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "X-CSRFToken": getCookie("csrftoken"),
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
                },
                body: body.toString(),
                signal: controller.signal
            }).then(function (response) {
                return response.json().catch(function () {
                    return {};
                }).then(function (data) {
                    return { ok: response.ok, data: data };
                });
            }).then(function (result) {
                if (!result.data.ok) {
                    paint(
                        result.data.error || "Не удалось получить реквизиты.",
                        "error"
                    );
                    return;
                }
                var changed = fill(result.data.fields || {}, overwrite);
                if (overwrite && !changed) {
                    paint("Реквизиты уже совпадают с данными ЕГРЮЛ.", "");
                    return;
                }
                paint(
                    result.data.notice || "Реквизиты заполнены.",
                    result.data.level
                );
            }).catch(function (error) {
                if (error && error.name === "AbortError") return;
                paint(
                    "Сервис проверки недоступен. Заполните реквизиты вручную.",
                    "error"
                );
            }).finally(function () {
                button.disabled = false;
                controller = null;
            });
        }

        input.addEventListener("input", function () {
            var value = digits(input.value);
            clearTimeout(timer);
            // КПП мог быть подставлен для прошлой организации. Если его не
            // правили руками, очищаем: иначе поиск по новому ИНН уйдёт с
            // чужим КПП и DaData ничего не найдёт.
            if (value !== lastValue && kpp && kpp.value
                    && kpp.value === initialValues.kpp) {
                kpp.value = "";
                initialValues.kpp = "";
                kpp.dispatchEvent(new Event("input", { bubbles: true }));
            }
            if (TRIGGER_LENGTHS.indexOf(value.length) === -1) return;
            if (value === lastValue) return;
            timer = setTimeout(function () {
                lastValue = value;
                request(false);
            }, DEBOUNCE_MS);
        });

        button.addEventListener("click", function () {
            clearTimeout(timer);
            var value = digits(input.value);
            if (TRIGGER_LENGTHS.indexOf(value.length) === -1) {
                paint("Введите ИНН: 10 цифр для юрлица или 12 для ИП.", "error");
                input.focus();
                return;
            }
            if (hasValues() && !window.confirm(
                "Заменить заполненные реквизиты данными из ЕГРЮЛ?"
            )) {
                return;
            }
            lastValue = value;
            request(true);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
