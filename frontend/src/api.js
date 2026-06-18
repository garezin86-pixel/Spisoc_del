const API_BASE = import.meta.env.VITE_API_BASE || "/api";

// ─── Ключи хранилища ──────────────────────────────────────────────────────────
const TOKEN_KEY = "spisoc_token";
const REFRESH_TOKEN_KEY = "spisoc_refresh_token";

export function getAccessToken() {
    return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken() {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function saveTokens(accessToken, refreshToken) {
    localStorage.setItem(TOKEN_KEY, accessToken);
    if (refreshToken) {
        localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
    }
}

export function clearTokens() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
}

// ─── Базовый парсер ответа ────────────────────────────────────────────────────
async function parseResponse(response) {
    const text = await response.text();
    const data = text ? JSON.parse(text) : null;
    if (!response.ok) {
        const message = data?.detail || data?.message || `Ошибка ${response.status}`;
        const error = new Error(message);
        error.status = response.status;
        throw error;
    }
    return data;
}

// ─── Флаг чтобы не запускать несколько рефрешей одновременно ─────────────────
let _isRefreshing = false;
let _refreshPromise = null;

async function tryRefreshToken() {
    // Если рефреш уже идёт — ждём его результата вместо второго запроса
    if (_isRefreshing) {
        return _refreshPromise;
    }

    _isRefreshing = true;
    _refreshPromise = (async () => {
        const refreshToken = getRefreshToken();
        if (!refreshToken) {
            throw new Error("Нет refresh token");
        }

        const response = await fetch(`${API_BASE}/auth/refresh`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: refreshToken }),
        });

        if (!response.ok) {
            throw new Error("Refresh failed");
        }

        const data = await response.json();
        saveTokens(data.access_token, data.refresh_token);
        return data.access_token;
    })()
        .finally(() => {
            _isRefreshing = false;
            _refreshPromise = null;
        });

    return _refreshPromise;
}

// ─── Основной метод запросов ──────────────────────────────────────────────────
export async function apiRequest({
    path,
    method = "GET",
    token = null,
    body = null,
    _retry = false,   // внутренний флаг — защита от бесконечного цикла
}) {
    const headers = {};
    // if (token) {
    //     headers.Authorization = `Bearer ${token}`;
    // }
    const accessToken = token || getAccessToken();
    if (accessToken) {
        headers.Authorization = `Bearer ${accessToken}`;
    }
    if (body !== null) {
        headers["Content-Type"] = "application/json";
    }

    const response = await fetch(`${API_BASE}${path}`, {
        method,
        headers,
        body: body !== null ? JSON.stringify(body) : null,
    });

    // ── Автообновление токена при 401 ────────────────────────────────────────
    if (response.status === 401 && token && !_retry) {
        try {
            const newAccessToken = await tryRefreshToken();
            // Повторяем исходный запрос с новым токеном
            return apiRequest({ path, method, token: newAccessToken, body, _retry: true });
        } catch {
            // Refresh не прошёл — очищаем токены и перезагружаем страницу
            // App.jsx поймёт что token=null и покажет экран логина
            clearTokens();
            window.location.reload();
            return null;
        }
    }

    return parseResponse(response);
}
