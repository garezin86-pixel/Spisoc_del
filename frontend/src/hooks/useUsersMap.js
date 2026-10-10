import { useEffect, useMemo, useState } from "react";
import { apiRequest } from "../api";
import { extractItems } from "../utils/extractItems";

// Пользователи компании: список (для выбора ответственного) и словарь id → username.
// Если пользователей нельзя получить (нет прав), хук отдаёт пустой список — интерфейс покажет «#id».
export function useUsersMap(token) {
    const [users, setUsers] = useState([]);

    useEffect(() => {
        if (!token) return;
        let cancelled = false;
        apiRequest({ path: "/users?page=1&size=100", token })
            .then(data => { if (!cancelled) setUsers(extractItems(data)); })
            .catch(() => { if (!cancelled) setUsers([]); });
        return () => { cancelled = true; };
    }, [token]);

    const usersById = useMemo(() => Object.fromEntries(users.map(u => [u.id, u.username])), [users]);
    return { users, usersById };
}

export function userName(usersById, id) {
    if (id === null || id === undefined) return "—";
    return usersById[id] ?? `#${id}`;
}
