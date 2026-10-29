import { useEffect, useRef, useState } from "react";
import { NAV_GROUPS } from "../../constants/navigation";
import { ROLE_LABELS } from "../../constants/roles";
import { NotificationBell } from "../NotificationBell";
import { UserProfileAvatar } from "../UserProfileAvatar";
import { ChatIcon, ChevronIcon, MenuIcon, MoonIcon, SearchIcon, SunIcon } from "./shellIcons";

// Закрывает всплывающее меню по клику снаружи и по Escape.
function useDismiss(open, close) {
    const ref = useRef(null);
    useEffect(() => {
        if (!open) return undefined;
        const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) close(); };
        const onKey = (e) => { if (e.key === "Escape") close(); };
        document.addEventListener("mousedown", onDown);
        document.addEventListener("keydown", onKey);
        return () => {
            document.removeEventListener("mousedown", onDown);
            document.removeEventListener("keydown", onKey);
        };
    }, [open, close]);
    return ref;
}

function GroupChip({ group, active, onNavigate }) {
    const [open, setOpen] = useState(false);
    const close = () => setOpen(false);
    const ref = useDismiss(open, close);
    return (
        <div className="sh-pop" ref={ref}>
            <button type="button" className={`sh-chip${active ? " active" : ""}`}
                aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(o => !o)}>
                {group.label} <ChevronIcon size={14} />
            </button>
            {open && (
                <div className="sh-menu" role="menu">
                    {group.items.map(i => (
                        <button key={i.tab} type="button" role="menuitem" className="sh-menu-item"
                            onClick={() => { close(); onNavigate(i.tab); }}>
                            {i.label}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

export function TopBar({
    token, activeGroup, onNavigate, onOpenPalette, onOpenMenu, theme, onToggleTheme,
    chatUnread, onToggleChat, currentUserId, currentUsername, currentRole,
    onOpenProfile, adminUrl, onLogout, onOpenTask,
}) {
    const [userMenu, setUserMenu] = useState(false);
    const userRef = useDismiss(userMenu, () => setUserMenu(false));
    return (
        <header className="sh-top">
            <button type="button" className="sh-icon-btn sh-hamburger" onClick={onOpenMenu} aria-label="Открыть меню">
                <MenuIcon />
            </button>
            <button type="button" className="sh-search" onClick={onOpenPalette} aria-label="Поиск (Ctrl K)">
                <SearchIcon size={18} /> <span>Поиск</span> <kbd>Ctrl K</kbd>
            </button>
            <nav className="sh-groups" aria-label="Группы разделов">
                {NAV_GROUPS.map(g => (
                    <GroupChip key={g.id} group={g} active={g.id === activeGroup} onNavigate={onNavigate} />
                ))}
            </nav>
            <div className="sh-spacer" />
            <button type="button" className="sh-icon-btn" onClick={onToggleTheme}
                aria-label={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"}>
                {theme === "dark" ? <SunIcon /> : <MoonIcon />}
            </button>
            <button type="button" className="sh-icon-btn sh-badge-host" onClick={onToggleChat}
                aria-label={chatUnread > 0 ? `Чат, непрочитанных: ${chatUnread}` : "Чат"}>
                <ChatIcon />
                {chatUnread > 0 && <span className="sh-badge sh-badge--red">{chatUnread > 99 ? "99+" : chatUnread}</span>}
            </button>
            <NotificationBell token={token} onOpenTask={onOpenTask} />
            <div className="sh-pop" ref={userRef}>
                <button type="button" className="sh-user" aria-haspopup="menu" aria-expanded={userMenu}
                    onClick={() => setUserMenu(o => !o)}>
                    {currentUserId != null && <UserProfileAvatar userId={currentUserId} username={currentUsername} size={32} />}
                    <span className="sh-user-text">
                        <span className="sh-user-name">{currentUsername}</span>
                        <span className="sh-user-role">{ROLE_LABELS[currentRole] ?? currentRole}</span>
                    </span>
                    <ChevronIcon size={14} />
                </button>
                {userMenu && (
                    <div className="sh-menu sh-menu--right" role="menu">
                        {currentUserId != null && (
                            <button type="button" role="menuitem" className="sh-menu-item"
                                onClick={() => { setUserMenu(false); onOpenProfile(currentUserId); }}>Мой профиль</button>
                        )}
                        {currentRole === "admin" && (
                            <a role="menuitem" className="sh-menu-item" href={adminUrl} target="_blank" rel="noopener noreferrer">Админка</a>
                        )}
                        <button type="button" role="menuitem" className="sh-menu-item" onClick={() => { setUserMenu(false); onLogout(); }}>Выйти</button>
                    </div>
                )}
            </div>
        </header>
    );
}
