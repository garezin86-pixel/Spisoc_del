import { useEffect, useState } from "react";
import { apiRequest } from "../api";

/**
 * Выбор клиента с поиском: «— без клиента —» / чип выбранного клиента с крестиком.
 * onChange(id | null, name) — id null означает «отвязать».
 */
export function ClientPicker({ token, value, name, onChange }) {
    const [search, setSearch] = useState("");
    const [found, setFound] = useState([]);
    const [open, setOpen] = useState(false);

    // поиск с задержкой; пока клиент выбран, не ищем
    useEffect(() => {
        if (value || !open) return undefined;
        const timer = setTimeout(() => {
            const qs = new URLSearchParams({ page: 1, size: 8 });
            if (search.trim()) qs.set("search", search.trim());
            apiRequest({ path: `/clients?${qs}`, token }).then(r => setFound(r?.items ?? [])).catch(() => setFound([]));
        }, 250);
        return () => clearTimeout(timer);
    }, [value, open, search, token]);

    if (value) {
        return (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="meta-chip">👤 {name || `#${value}`}</span>
                <button type="button" className="btn btn-ghost btn-sm" title="Отвязать клиента" onClick={() => onChange(null, "")}>✕</button>
            </div>
        );
    }
    return (
        <div>
            <input
                placeholder="— без клиента — (начните вводить название)"
                value={search}
                onFocus={() => setOpen(true)}
                onChange={e => { setSearch(e.target.value); setOpen(true); }}
            />
            {open && (
                <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 6, maxHeight: 180, overflowY: "auto" }}>
                    {found.map(c => (
                        <button
                            key={c.id} type="button" className="home-row"
                            onClick={() => { onChange(c.id, c.name); setSearch(""); setOpen(false); }}
                        >
                            <span className="home-row-main"><span className="home-row-title">{c.name}</span></span>
                        </button>
                    ))}
                    {found.length === 0 && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Ничего не найдено</div>}
                </div>
            )}
        </div>
    );
}
