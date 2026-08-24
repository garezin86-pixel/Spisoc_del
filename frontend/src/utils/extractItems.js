export function extractItems(data) {
    if (!data) return [];
    let items;
    if (Array.isArray(data)) items = data;
    else if (Array.isArray(data.items)) items = data.items;
    else return [];
    // Дедупликация по id — защита от двойного вызова (StrictMode, race conditions)
    const seen = new Set();
    return items.filter(item => {
        if (item?.id == null) return true;
        if (seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
    });
}
