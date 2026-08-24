import { useEffect, useCallback, useRef } from "react";

export function useWebSocket(token, onEvent) {
    const wsRef = useRef(null);
    const reconnectRef = useRef(null);
    const mountedRef = useRef(true);

    const connect = useCallback(() => {
        if (!token || !mountedRef.current) return;

        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const host = window.location.host;
        const url = `${protocol}//${host}/api/ws?token=${token}`;

        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
            console.log("[WS] connected");
            if (reconnectRef.current) {
                clearTimeout(reconnectRef.current);
                reconnectRef.current = null;
            }
        };

        ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                if (msg.event === "pong") return;
                onEvent(msg.event, msg.data);
            } catch { }
        };

        ws.onclose = (e) => {
            console.log("[WS] disconnected, reconnecting in 3s...", e.code);
            if (mountedRef.current && e.code !== 4001) {
                reconnectRef.current = setTimeout(connect, 3000);
            }
        };

        ws.onerror = () => ws.close();
    }, [token, onEvent]);

    useEffect(() => {
        mountedRef.current = true;
        connect();

        // Keepalive ping каждые 25 сек
        const ping = setInterval(() => {
            if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send("ping");
            }
        }, 25000);

        return () => {
            mountedRef.current = false;
            clearTimeout(reconnectRef.current);
            clearInterval(ping);
            wsRef.current?.close();
        };
    }, [connect]);
}

// ─── Helpers ──────────────────────────────────────────────
