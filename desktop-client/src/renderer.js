const state = {
    serverUrl: '',
    tenantId: '',
    accessToken: '',
    refreshToken: '',
    websocket: null,
    reconnectTimer: null,
    reconnectAttempts: 0,
    pollingTimer: null,
    realtimeDisabled: false,
};

const elements = {
    appVersion: document.getElementById('appVersion'),
    serverUrl: document.getElementById('serverUrl'),
    tenantId: document.getElementById('tenantId'),
    username: document.getElementById('username'),
    password: document.getElementById('password'),
    loginForm: document.getElementById('loginForm'),
    loginButton: document.getElementById('loginButton'),
    logoutButton: document.getElementById('logoutButton'),
    refreshButton: document.getElementById('refreshButton'),
    loginMessage: document.getElementById('loginMessage'),
    connectionDot: document.getElementById('connectionDot'),
    connectionText: document.getElementById('connectionText'),
    soldCount: document.getElementById('soldCount'),
    availableCount: document.getElementById('availableCount'),
    inventoryDays: document.getElementById('inventoryDays'),
    staleNinety: document.getElementById('staleNinety'),
    carsList: document.getElementById('carsList'),
    salesList: document.getElementById('salesList'),
    financeList: document.getElementById('financeList'),
    liveFeed: document.getElementById('liveFeed'),
};

elements.appVersion.textContent = window.desktopBridge?.appVersion || '0.1.0';

function loadPersistedSession() {
    const saved = JSON.parse(localStorage.getItem('desktop.session') || '{}');
    state.serverUrl = saved.serverUrl || 'http://127.0.0.1:8000';
    state.tenantId = saved.tenantId || '';
    state.accessToken = saved.accessToken || '';
    state.refreshToken = saved.refreshToken || '';

    elements.serverUrl.value = state.serverUrl;
    elements.tenantId.value = state.tenantId;
}

function persistSession() {
    localStorage.setItem('desktop.session', JSON.stringify({
        serverUrl: state.serverUrl,
        tenantId: state.tenantId,
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
    }));
}

function clearSession() {
    state.accessToken = '';
    state.refreshToken = '';
    state.realtimeDisabled = false;
    state.reconnectAttempts = 0;
    disconnectRealtime();
    stopPolling();
    persistSession();
}

function setMessage(text, type = 'muted') {
    elements.loginMessage.className = `message-strip ${type}`;
    elements.loginMessage.textContent = text;
}

function setConnection(status, text) {
    elements.connectionDot.className = `dot ${status}`;
    elements.connectionText.textContent = text;
}

function normalizeServerUrl(value) {
    return (value || '')
        .trim()
        .replace(/^['"`\u2018\u2019\u201C\u201D]+/, '')
        .replace(/['"`\u2018\u2019\u201C\u201D]+$/, '')
        .replace(/\/$/, '');
}

async function parseJsonOrThrow(response, endpointLabel) {
    const rawText = await response.text();
    try {
        return rawText ? JSON.parse(rawText) : {};
    } catch (_error) {
        const preview = rawText.slice(0, 140).replace(/\s+/g, ' ');
        throw new Error(`استجابة غير صالحة من ${endpointLabel}: ${preview}`);
    }
}

function resolveWsUrl() {
    const base = new URL(state.serverUrl);
    base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
    base.pathname = `/ws/tenants/${state.tenantId}/events/`;
    base.search = `token=${encodeURIComponent(state.accessToken)}`;
    return base.toString();
}

async function request(path, options = {}, allowRetry = true) {
    const headers = new Headers(options.headers || {});
    headers.set('Accept', 'application/json');

    if (state.accessToken) {
        headers.set('Authorization', `Bearer ${state.accessToken}`);
    }
    if (state.tenantId) {
        headers.set('X-Tenant-ID', state.tenantId);
    }
    if (options.body && !headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
    }

    const response = await fetch(`${state.serverUrl}${path}`, {
        ...options,
        headers,
    });

    if (response.status === 401 && allowRetry && state.refreshToken) {
        const refreshed = await refreshAccessToken();
        if (refreshed) {
            return request(path, options, false);
        }
    }

    return response;
}

async function refreshAccessToken() {
    if (!state.refreshToken) {
        return false;
    }

    const response = await fetch(`${state.serverUrl}/api/auth/token/refresh/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        body: JSON.stringify({ refresh: state.refreshToken }),
    });

    if (!response.ok) {
        clearSession();
        setMessage('انتهت الجلسة. يلزم تسجيل الدخول مجدداً.', 'error');
        return false;
    }

    const payload = await response.json();
    state.accessToken = payload.access;
    if (payload.refresh) {
        state.refreshToken = payload.refresh;
    }
    persistSession();
    return true;
}

async function login(event) {
    event.preventDefault();
    elements.loginButton.disabled = true;
    setMessage('جارٍ التحقق من بيانات الدخول...', 'muted');

    state.serverUrl = normalizeServerUrl(elements.serverUrl.value);
    state.tenantId = (elements.tenantId.value || '').trim().toLowerCase();

    try {
        const response = await fetch(`${state.serverUrl}/api/auth/token/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            body: JSON.stringify({
                tenant_id: state.tenantId,
                username: elements.username.value,
                password: elements.password.value,
            }),
        });

        const payload = await parseJsonOrThrow(response, '/api/auth/token/');
        if (!response.ok) {
            const firstMessage = extractErrorMessage(payload) || 'فشل تسجيل الدخول إلى الخادم.';
            throw new Error(firstMessage);
        }

        state.accessToken = payload.access;
        state.refreshToken = payload.refresh;
        persistSession();

        setMessage('تم فتح الجلسة بنجاح. جارٍ تحميل البيانات...', 'success');
        await hydrateDashboard();
        connectRealtime();
    } catch (error) {
        clearSession();
        setMessage(error.message || 'تعذر تسجيل الدخول.', 'error');
        setConnection('warn', 'تعذر الاتصال بالخادم');
    } finally {
        elements.loginButton.disabled = false;
    }
}

function extractErrorMessage(payload) {
    if (!payload || typeof payload !== 'object') {
        return '';
    }

    const firstKey = Object.keys(payload)[0];
    if (!firstKey) {
        return '';
    }

    const value = payload[firstKey];
    if (Array.isArray(value) && value.length) {
        return String(value[0]);
    }
    return typeof value === 'string' ? value : '';
}

function renderList(target, rows, renderItem) {
    if (!rows.length) {
        target.className = `${target.id === 'liveFeed' ? 'live-feed' : 'list-shell'} empty-state`;
        target.textContent = 'لا توجد بيانات حالياً.';
        return;
    }

    target.className = target.id === 'liveFeed' ? 'live-feed' : 'list-shell';
    target.innerHTML = rows.map(renderItem).join('');
}

function moneyText(value, currency = '') {
    return `${value ?? '0'} ${currency}`.trim();
}

async function hydrateDashboard() {
    const [summaryResponse, carsResponse, salesResponse, vouchersResponse, paymentsResponse] = await Promise.all([
        request('/api/reports/summary/'),
        request('/api/cars/?is_sold=false'),
        request('/api/sales/'),
        request('/api/finance-vouchers/'),
        request('/api/debt-payments/'),
    ]);

    const responses = [summaryResponse, carsResponse, salesResponse, vouchersResponse, paymentsResponse];
    const unauthorized = responses.find((response) => response.status === 401);
    if (unauthorized) {
        throw new Error('انتهت الجلسة أو تعذر المصادقة على الطلبات.');
    }

    const [summary, cars, sales, vouchers, payments] = await Promise.all([
        parseJsonOrThrow(summaryResponse, '/api/reports/summary/'),
        parseJsonOrThrow(carsResponse, '/api/cars/'),
        parseJsonOrThrow(salesResponse, '/api/sales/'),
        parseJsonOrThrow(vouchersResponse, '/api/finance-vouchers/'),
        parseJsonOrThrow(paymentsResponse, '/api/debt-payments/'),
    ]);

    elements.soldCount.textContent = summary.sold_count ?? 0;
    elements.availableCount.textContent = summary.available_count ?? 0;
    elements.inventoryDays.textContent = summary.average_days_in_inventory ?? 0;
    elements.staleNinety.textContent = summary.stale_cars?.['90_plus'] ?? 0;

    renderList(elements.carsList, cars.slice(0, 8), (car) => `
        <article class="list-item">
            <div class="item-row">
                <h4 class="item-title">${escapeHtml(car.brand)} ${escapeHtml(car.model_name)}</h4>
                <span class="item-chip">${escapeHtml(car.currency)}</span>
            </div>
            <div class="item-subtitle">VIN: ${escapeHtml(car.vin)}</div>
            <div class="item-meta">تكلفة كلية: ${moneyText(car.total_cost_price, car.currency)} | ربح متوقع: ${moneyText(car.expected_profit, car.currency)}</div>
        </article>
    `);

    renderList(elements.salesList, sales.slice(0, 8), (sale) => `
        <article class="list-item">
            <div class="item-row">
                <h4 class="item-title">${escapeHtml(sale.customer_name || 'عميل')}</h4>
                <span class="item-chip">${moneyText(sale.sale_price, sale.currency)}</span>
            </div>
            <div class="item-subtitle">${escapeHtml(sale.car_brand || '')} ${escapeHtml(sale.car_model_name || '')} | ${escapeHtml(sale.car_vin || '')}</div>
            <div class="item-meta">المدفوع: ${moneyText(sale.amount_paid, sale.currency)} | المتبقي: ${moneyText(sale.remaining_amount, sale.currency)}</div>
        </article>
    `);

    const financeRows = [...vouchers.slice(0, 4), ...payments.slice(0, 4)];
    renderList(elements.financeList, financeRows, (item) => {
        const title = item.voucher_number || item.receipt_number || 'عملية';
        const subtitle = item.person_name || item.customer_name || '';
        const amount = item.amount || item.paid_amount || '0';
        const currency = item.currency || '';
        const meta = item.reason || item.car_vin || '';
        return `
            <article class="list-item">
                <div class="item-row">
                    <h4 class="item-title">${escapeHtml(title)}</h4>
                    <span class="item-chip">${moneyText(amount, currency)}</span>
                </div>
                <div class="item-subtitle">${escapeHtml(subtitle)}</div>
                <div class="item-meta">${escapeHtml(meta)}</div>
            </article>
        `;
    });

    setConnection('live', 'الجلسة نشطة والخادم متصل');
}

function appendEvent(eventType, payload) {
    const currentItems = Array.from(elements.liveFeed.querySelectorAll('.event-item')).map((node) => node.outerHTML);
    const nextItem = `
        <article class="event-item">
            <div class="item-row">
                <h4 class="item-title">${escapeHtml(eventType)}</h4>
                <span class="event-time">${new Date().toLocaleTimeString('ar-SA')}</span>
            </div>
            <div class="item-meta">${escapeHtml(JSON.stringify(payload))}</div>
        </article>
    `;
    const rows = [nextItem, ...currentItems].slice(0, 15);
    elements.liveFeed.className = 'live-feed';
    elements.liveFeed.innerHTML = rows.join('');
}

function disconnectRealtime() {
    if (state.reconnectTimer) {
        clearTimeout(state.reconnectTimer);
        state.reconnectTimer = null;
    }

    if (state.websocket) {
        state.websocket.onclose = null;
        state.websocket.close();
        state.websocket = null;
    }
}

function startPolling() {
    stopPolling();
    if (!state.accessToken) {
        return;
    }

    state.pollingTimer = setInterval(async () => {
        try {
            await hydrateDashboard();
        } catch (_error) {
            // Keep polling active; the connection may recover later.
        }
    }, 15000);
}

function stopPolling() {
    if (state.pollingTimer) {
        clearInterval(state.pollingTimer);
        state.pollingTimer = null;
    }
}

function scheduleReconnect() {
    if (!state.accessToken || !state.serverUrl || !state.tenantId || state.realtimeDisabled) {
        return;
    }

    if (state.reconnectTimer) {
        clearTimeout(state.reconnectTimer);
    }

    state.reconnectAttempts += 1;
    if (state.reconnectAttempts >= 8) {
        state.realtimeDisabled = true;
        setConnection('warn', 'تم التحويل إلى تحديث دوري كل 15 ثانية');
        appendEvent('socket.disabled', { reason: 'max_retries_reached' });
        startPolling();
        return;
    }

    const delayMs = Math.min(30000, 1000 * (2 ** Math.min(state.reconnectAttempts, 5)));

    state.reconnectTimer = setTimeout(() => {
        connectRealtime();
    }, delayMs);
}

function connectRealtime() {
    if (state.realtimeDisabled) {
        startPolling();
        return;
    }

    disconnectRealtime();
    setConnection('idle', 'جارٍ فتح قناة التحديث اللحظي');

    try {
        state.websocket = new WebSocket(resolveWsUrl());
    } catch (error) {
        setConnection('warn', 'تعذر إنشاء اتصال WebSocket');
        return;
    }

    state.websocket.onopen = () => {
        state.reconnectAttempts = 0;
        stopPolling();
        setConnection('live', 'التحديث اللحظي متصل');
        appendEvent('socket.open', { tenant_id: state.tenantId });
    };

    state.websocket.onmessage = async (event) => {
        const payload = JSON.parse(event.data);
        appendEvent(payload.type || 'event', payload.payload || payload);

        if (payload.type === 'model.changed' || payload.type === 'model.deleted') {
            try {
                await hydrateDashboard();
            } catch (error) {
                setMessage(error.message || 'تعذر تحديث اللوحة بعد الحدث اللحظي.', 'error');
            }
        }
    };

    state.websocket.onclose = () => {
        setConnection('warn', 'انقطع الاتصال اللحظي وسيعاد المحاولة');
        scheduleReconnect();
    };

    state.websocket.onerror = () => {
        setConnection('warn', 'حدث خطأ في الاتصال اللحظي');
    };
}

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

async function bootstrapFromSession() {
    loadPersistedSession();
    if (!state.accessToken || !state.serverUrl || !state.tenantId) {
        setConnection('idle', 'بانتظار تسجيل الدخول');
        return;
    }

    try {
        await hydrateDashboard();
        startPolling();
        connectRealtime();
        setMessage('تم استعادة الجلسة السابقة.', 'success');
    } catch (error) {
        clearSession();
        setMessage('تعذر استعادة الجلسة السابقة. سجّل الدخول من جديد.', 'error');
        setConnection('warn', 'يلزم إعادة تسجيل الدخول');
    }
}

elements.loginForm.addEventListener('submit', login);
elements.logoutButton.addEventListener('click', () => {
    clearSession();
    setMessage('تم إنهاء الجلسة المحلية.', 'muted');
    setConnection('idle', 'غير متصل');
});
elements.refreshButton.addEventListener('click', async () => {
    try {
        await hydrateDashboard();
        setMessage('تم تحديث البيانات من الخادم.', 'success');
    } catch (error) {
        setMessage(error.message || 'تعذر تحديث البيانات.', 'error');
    }
});

bootstrapFromSession();
