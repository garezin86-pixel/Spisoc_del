import { useState, useEffect, useRef } from "react";
import { STATUS_LIST, STATUS_META } from "../constants/status";

export function StatusMenu({ status, onChange, disabled }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const current = STATUS_META[status] ?? STATUS_LIST[1];

    useEffect(() => {
        if (!open) return;
        function handleClickOutside(e) {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        }
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, [open]);

    return (
        <div ref={ref} style={{ position: "relative", display: "inline-block" }}>
            <button
                type="button"
                className="btn btn-sm"
                disabled={disabled}
                onClick={() => setOpen(v => !v)}
                style={{
                    background: current.color + "22",
                    color: current.color,
                    border: `1px solid ${current.color}55`,
                    fontWeight: 600,
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                }}
            >
                <span style={{
                    display: "inline-block", width: 8, height: 8,
                    borderRadius: "50%", background: current.color, flexShrink: 0,
                }} />
                {current.icon} {current.label}
                <span style={{ fontSize: 10, opacity: 0.8 }}>▾</span>
            </button>

            {open && (
                <div style={{
                    position: "absolute",
                    top: "calc(100% + 4px)",
                    left: 0,
                    zIndex: 30,
                    minWidth: 170,
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    boxShadow: "var(--shadow-sm)",
                    overflow: "hidden",
                }}>
                    {STATUS_LIST.map(s => (
                        <div
                            key={s.key}
                            onClick={() => { if (s.key !== status) onChange(s.key); setOpen(false); }}
                            style={{
                                padding: "9px 12px",
                                fontSize: 13,
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                                cursor: "pointer",
                                color: "var(--text)",
                                background: s.key === status ? "var(--surface2)" : "transparent",
                            }}
                            onMouseEnter={e => { e.currentTarget.style.background = "var(--surface2)"; }}
                            onMouseLeave={e => { e.currentTarget.style.background = s.key === status ? "var(--surface2)" : "transparent"; }}
                        >
                            <span style={{
                                display: "inline-block", width: 8, height: 8,
                                borderRadius: "50%", background: s.color, flexShrink: 0,
                            }} />
                            {s.icon} {s.label}
                            {s.key === status && <span style={{ marginLeft: "auto", color: "var(--accent)" }}>✓</span>}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

// ─── DependenciesPanel ─────────────────────────────────────
