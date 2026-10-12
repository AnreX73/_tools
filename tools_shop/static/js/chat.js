document.addEventListener('alpine:init', () => {
    Alpine.data('supportChat', () => ({
        open: false, connected: false, connecting: false, sending: false,
        operator: false, messages: [], draft: '', error: '', status: '',
        socket: null, socketPath: '', retryTimer: null, retries: 0, pending: null,
        init() {
            this.socketPath = this.$el.dataset.socketPath || '';
            this.operator = Boolean(this.socketPath);
        },
        show() {
            this.open = true;
            this.retries = 0;
            this.connect();
            this.$nextTick(() => this.$refs.input.focus());
        },
        close() {
            this.open = false;
            this.stop();
            this.$refs.launcher?.focus();
        },
        stop() {
            clearTimeout(this.retryTimer);
            const socket = this.socket;
            this.socket = null;
            socket?.close();
            this.connected = false;
            this.connecting = false;
            this.sending = false;
        },
        destroy() { this.open = false; this.stop(); },
        async connect() {
            if (!this.open || this.connected || this.connecting) return;
            clearTimeout(this.retryTimer);
            this.connecting = true;
            this.error = '';
            this.status = 'Подключаемся…';
            try {
                if (!this.socketPath) {
                    const response = await fetch(this.$el.dataset.startUrl, {
                        method: 'POST', credentials: 'same-origin',
                        headers: { 'X-CSRFToken': this.$el.querySelector('[name=csrfmiddlewaretoken]').value },
                    });
                    if (!response.ok) throw new Error('Не удалось открыть чат. Попробуйте ещё раз.');
                    this.socketPath = (await response.json()).socket_path;
                }
                if (!this.open) return;
                const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${this.socketPath}`);
                this.socket = socket;
                socket.onmessage = (event) => {
                    if (this.socket !== socket) return;
                    let data;
                    try { data = JSON.parse(event.data); } catch { return; }
                    if (data.type === 'history') {
                        data.messages.forEach(message => this.addMessage(message));
                        this.connected = true;
                        this.connecting = false;
                        this.retries = 0;
                        this.status = 'Чат подключён';
                        if (this.pending && !this.messages.some(m => m.client_id === this.pending.client_id && m.is_staff === this.operator)) {
                            this.sending = true;
                            socket.send(JSON.stringify(this.pending));
                        }
                    } else if (data.type === 'message') {
                        this.addMessage(data.message);
                    } else if (data.type === 'error') {
                        this.error = data.message;
                        this.sending = false;
                    }
                };
                socket.onclose = (event) => {
                    if (this.socket !== socket) return;
                    this.socket = null;
                    this.connected = false;
                    this.connecting = false;
                    this.sending = false;
                    this.status = 'Соединение прервано';
                    if (event.code === 4403 || event.code === 1008) {
                        this.socketPath = this.operator ? this.socketPath : '';
                        this.error = 'Доступ к чату недоступен. Попробуйте подключиться снова.';
                    } else { this.scheduleRetry(); }
                };
                socket.onerror = () => { this.status = 'Не удалось подключиться'; };
            } catch (error) {
                this.connecting = false;
                this.error = error.message;
                this.status = 'Чат временно недоступен';
                this.scheduleRetry();
            }
        },
        scheduleRetry() {
            if (!this.open || this.retries >= 5) return;
            const delay = Math.min(1000 * 2 ** this.retries++, 15000);
            this.retryTimer = setTimeout(() => this.connect(), delay);
        },
        addMessage(message) {
            if (!this.messages.some(item => item.id === message.id)) {
                this.messages.push(message);
                this.messages.sort((a, b) => a.id - b.id);
            }
            if (this.pending?.client_id === message.client_id && message.is_staff === this.operator) {
                if (this.draft.trim() === this.pending.text) this.draft = '';
                this.pending = null;
                this.sending = false;
            }
            this.$nextTick(() => { this.$refs.messages.scrollTop = this.$refs.messages.scrollHeight; });
        },
        send() {
            if (!this.connected || this.sending || !this.draft.trim() || this.socket?.readyState !== WebSocket.OPEN) return;
            this.error = '';
            const text = this.draft.trim();
            if (!this.pending || this.pending.text !== text) {
                const bytes = crypto.getRandomValues(new Uint8Array(16));
                bytes[6] = (bytes[6] & 15) | 64;
                bytes[8] = (bytes[8] & 63) | 128;
                const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
                const client_id = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
                this.pending = { text, client_id };
            }
            this.sending = true;
            this.socket.send(JSON.stringify(this.pending));
        },
        formatTime(value) {
            return new Date(value).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
        },
    }));
});
