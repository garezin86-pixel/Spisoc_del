import { useState, useEffect } from "react";
import { API_BASE } from "../api";

const _knownNoAvatar = new Set();


export function UserProfileAvatar({ userId, username, size = 72, version }) {
    const [broken, setBroken] = useState(() => _knownNoAvatar.has(userId));

    // После успешной загрузки нового аватара (см. handleAvatarPick) родитель
    // передаёт свежий version — сбрасываем broken и убираем из чёрного списка,
    // иначе картинка так и останется заглушкой с инициалами до перезагрузки страницы.
    useEffect(() => {
        if (version) {
            _knownNoAvatar.delete(userId);
            setBroken(false);
        }
    }, [version, userId]);

    const initials = (username || "?").trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase()).join("") || "?";

    if (broken || !userId) {
        return (
            <div style={{
                width: size, height: size, borderRadius: "50%", flexShrink: 0,
                background: "var(--accent)", color: "#fff", display: "flex",
                alignItems: "center", justifyContent: "center",
                fontSize: size * 0.36, fontWeight: 700,
            }}>
                {initials}
            </div>
        );
    }
    return (
        <img
            src={`${API_BASE}/users/${userId}/avatar${version ? `?v=${version}` : ""}`}
            alt={username}
            onError={() => { _knownNoAvatar.add(userId); setBroken(true); }}
            style={{ width: size, height: size, borderRadius: "50%", objectFit: "cover", flexShrink: 0, background: "var(--surface2)" }}
        />
    );
}
