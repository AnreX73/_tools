// Строка поиска в шапке: htmx грузит подсказки, Alpine управляет
// открытием панели и навигацией с клавиатуры (↑ ↓ Enter Esc, «/» — фокус).
document.addEventListener("alpine:init", () => {
    Alpine.data("searchBox", () => ({
        open: false,
        active: -1,

        init() {
            this.$el.addEventListener("htmx:afterSwap", () => {
                this.setActive(-1);
                this.open = this.hasItems() && document.activeElement === this.$refs.input;
            });
        },

        items() {
            return Array.from(this.$refs.panel.querySelectorAll("[data-suggest-item]"));
        },
        hasItems() {
            return this.$refs.panel.children.length > 0;
        },

        show() {
            if (this.hasItems()) this.open = true;
        },
        close() {
            this.open = false;
            this.setActive(-1);
        },

        // Esc при открытой панели только закрывает её (без очистки поля,
        // которую браузер делает для type="search"); повторный Esc — штатно.
        escape(event) {
            if (this.open) {
                event.preventDefault();
                this.close();
            } else {
                this.$refs.input.blur();
            }
        },

        setActive(index) {
            const items = this.items();
            items.forEach((el, n) => {
                el.classList.toggle("is-active", n === index);
                el.setAttribute("aria-selected", n === index ? "true" : "false");
            });
            this.active = index;
            const current = items[index];
            this.$refs.input.setAttribute("aria-activedescendant", current ? current.id : "");
            if (current) current.scrollIntoView({ block: "nearest" });
        },

        move(step) {
            const items = this.items();
            if (!items.length) return;
            this.open = true;
            let next = this.active + step;
            if (next < 0) next = items.length - 1;
            if (next >= items.length) next = 0;
            this.setActive(next);
        },

        submit(event) {
            const current = this.items()[this.active];
            if (this.open && current) {
                event.preventDefault();
                window.location.href = current.href;
                return;
            }
            if (!this.$refs.input.value.trim()) event.preventDefault();
        },

        focusShortcut(event) {
            const el = document.activeElement;
            const typing = el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
            if (typing) return;
            event.preventDefault();
            this.$refs.input.focus();
            this.$refs.input.select();
        },
    }));
});
