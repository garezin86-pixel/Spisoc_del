const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function parseResponse(response) {
    const text = await response.text();
    const data = text ? JSON.parse(text) : null;
    if (!response.ok) {
        const message = data?.detail || data?.message || `Ошибка ${response.status}`;
        throw new Error(message);
    }
    return data;
}

export async function apiRequest({ path, method = "GET", token = null, body = null }) {
    const headers = {};
    if (token) {
        headers.Authorization = `Bearer ${token}`;
    }
    if (body !== null) {
        headers["Content-Type"] = "application/json";
    }

    const response = await fetch(`${API_BASE}${path}`, {
        method,
        headers,
        body: body !== null ? JSON.stringify(body) : null,
    });

    return parseResponse(response);
}
