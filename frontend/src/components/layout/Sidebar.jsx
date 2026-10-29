import { useState } from "react";
import { APP_DESCRIPTION, APP_LOGO, APP_NAME } from "../../constants/branding";
import { ICONS } from "../../constants/icons";
import { FOOTER_ITEMS, NAV_GROUPS } from "../../constants/navigation";
import { Icon } from "../Icon";
import { ChevronIcon, CloseIcon, MoonIcon, SunIcon } from "./shellIcons";

function NavItem({ item, active, count, onClick }) {
    const path = item.path ?? ICONS[item.icon];
    return (
        <button type="button" className={`sh-nav-item${active ? " active" : ""}`}
            aria-current={active ? "page" : undefined} onClick={() => onClick(item.tab)}>
            {path && <Icon d={path} size={18} />}
            <span className="sh-nav-label">{item.label}</span>
            {count > 0 && <span className="sh-count">{count}</span>}
        </button>
    );
}

// variant="side"   — десктоп: страницы только активной группы.
// variant="drawer" — мобильное меню: все группы раскрывающимися списками.
export function Sidebar({ variant = "side", activeGroup, tab, counts, onNavigate, onClose, theme, onToggleTheme }) {
    const [openGroup, setOpenGroup] = useState(activeGroup);
    const group = NAV_GROUPS.find(g => g.id === activeGroup) ?? NAV_GROUPS[0];
    const go = (t) => { onNavigate(t); if (variant === "drawer") onClose?.(); };

    const brand = (
        <div className="sh-brand">
            <div className="sh-logo">{APP_LOGO}</div>
            <div className="sh-brand-text">
                <div className="sh-brand-name">{APP_NAME}</div>
                {APP_DESCRIPTION && <div className="sh-brand-tag">{APP_DESCRIPTION}</div>}
            </div>
            {variant === "drawer" && (
                <button type="button" className="sh-icon-btn" onClick={onClose} aria-label="Закрыть меню"><CloseIcon /></button>
            )}
        </div>
    );

    const footer = (
        <div className="sh-side-footer">
            {FOOTER_ITEMS.map(i => (
                <NavItem key={i.tab} item={i} count={counts[i.count]} onClick={go}
                    active={tab === i.tab} />
            ))}
            {variant === "drawer" && (
                <button type="button" className="sh-nav-item" onClick={onToggleTheme}>
                    {theme === "dark" ? <SunIcon size={18} /> : <MoonIcon size={18} />}
                    <span className="sh-nav-label">{theme === "dark" ? "Светлая тема" : "Тёмная тема"}</span>
                </button>
            )}
        </div>
    );

    if (variant === "side") {
        return (
            <aside className="sh-side sh-side--desktop" aria-label="Разделы">
                {brand}
                <div className="sh-group-label">{group.label}</div>
                <nav className="sh-nav">
                    {group.items.map(i => (
                        <NavItem key={i.tab} item={i} active={tab === i.tab} count={counts[i.count]} onClick={go} />
                    ))}
                </nav>
                {footer}
            </aside>
        );
    }

    return (
        <div className="sh-drawer-wrap">
            <div className="sh-scrim" onClick={onClose} />
            <aside className="sh-side sh-side--drawer" role="dialog" aria-modal="true" aria-label="Меню">
                {brand}
                <nav className="sh-nav">
                    {NAV_GROUPS.map(g => {
                        const open = openGroup === g.id;
                        return (
                            <div key={g.id}>
                                <button type="button" className={`sh-acc-head${g.id === activeGroup ? " current" : ""}`}
                                    aria-expanded={open} onClick={() => setOpenGroup(open ? null : g.id)}>
                                    <span>{g.label}</span>
                                    <span className={`sh-chev${open ? " open" : ""}`}><ChevronIcon size={16} /></span>
                                </button>
                                {open && (
                                    <div className="sh-acc-body">
                                        {g.items.map(i => (
                                            <NavItem key={i.tab} item={i} active={tab === i.tab} count={counts[i.count]} onClick={go} />
                                        ))}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </nav>
                {footer}
            </aside>
        </div>
    );
}
