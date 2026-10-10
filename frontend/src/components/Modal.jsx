import { useEffect } from "react";

// Простое модальное окно: затемнение + карточка. Закрывается по Esc и клику на фон.
export function Modal({ title, onClose, children, width = 560 }) {
    useEffect(() => {
        const onKey = e => { if (e.key === "Escape") onClose(); };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onClose]);

    return (
        <div
            onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}
            style={{
                position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000,
                display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "6vh 16px", overflowY: "auto",
            }}
        >
            <div className="card" style={{ width: "100%", maxWidth: width, margin: 0 }}>
                <div className="section-header" style={{ marginBottom: 12 }}>
                    <div className="section-title">{title}</div>
                    <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Закрыть">✕</button>
                </div>
                {children}
            </div>
        </div>
    );
}
