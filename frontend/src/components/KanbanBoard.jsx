import { useState } from "react";

/**
 * Общая канбан-доска (задачи и сделки).
 *
 * columns:  [{ key, label, color }]
 * items:    { [column.key]: [{ id, ... }] }
 * renderCard({ item, col, onDragStart, onDragEnd, isDragging }) — карточку рисует вызывающий; чтобы её
 *           можно было тащить, нужно вызвать onDragStart(e, item.id, col) из её onDragStart и onDragEnd из onDragEnd.
 * onMove(itemId, fromCol, toCol, index) — карточку отпустили. index — место в целевой колонке (с нуля,
 *           считая без самой карточки) или null, если порядок не важен / отпустили на пустое место.
 * reorder:  true — порядок карточек в колонке сохраняется (сделки): показывается линия вставки, разрешена
 *           перестановка внутри колонки. false — только перенос между колонками (задачи).
 * renderColumnExtra(col, list) — дополнительный элемент в шапке колонки (например, сумма по колонке).
 */
export function KanbanBoard({
    columns,
    items,
    renderCard,
    onMove,
    reorder = false,
    renderColumnExtra = null,
    height = "calc(100vh - 220px)",
    emptyText = "Пусто",
}) {
    const [dragging, setDragging] = useState(null); // { id, fromCol }
    const [dragOver, setDragOver] = useState(null); // { col, index }

    const onDragStart = (e, id, fromCol) => {
        setDragging({ id, fromCol });
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", String(id));
    };
    const onDragEnd = () => { setDragging(null); setDragOver(null); };

    const hover = (col, index) => setDragOver(prev => (prev && prev.col === col && prev.index === index ? prev : { col, index }));

    const onColumnDragOver = (e, col, count) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        hover(col, reorder ? count : null); // над пустым местом колонки — в конец
    };

    const onCardDragOver = (e, col, i) => {
        if (!reorder) return; // событие дойдёт до колонки
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = "move";
        const rect = e.currentTarget.getBoundingClientRect();
        hover(col, e.clientY > rect.top + rect.height / 2 ? i + 1 : i);
    };

    const onDrop = (e, toCol) => {
        e.preventDefault();
        const target = dragOver;
        const drag = dragging;
        setDragOver(null);
        setDragging(null);
        if (!drag) return;

        let index = reorder && target && target.col === toCol ? target.index : null;
        if (drag.fromCol === toCol) {
            if (!reorder) return;
            // перестановка внутри колонки: сама карточка выпадает из списка, индексы после неё сдвигаются
            const fromIdx = (items[toCol] ?? []).findIndex(x => x.id === drag.id);
            if (index !== null && fromIdx !== -1) {
                if (index > fromIdx) index -= 1;
                if (index === fromIdx) return; // положили туда же
            }
        }
        onMove(drag.id, drag.fromCol, toCol, index);
    };

    return (
        <div style={{
            display: "flex", gap: 12, overflowX: "auto", overflowY: "hidden",
            height, paddingBottom: 8, paddingRight: 16, alignItems: "flex-start",
        }}>
            {columns.map(col => {
                const list = items?.[col.key] ?? [];
                const isOver = dragOver?.col === col.key;
                const indicator = i => reorder && isOver && dragOver.index === i && dragging
                    ? <div style={{ height: 3, borderRadius: 2, background: "var(--accent)", margin: "1px 0" }} />
                    : null;
                return (
                    <div
                        key={col.key}
                        onDragOver={e => onColumnDragOver(e, col.key, list.length)}
                        onDrop={e => onDrop(e, col.key)}
                        onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget)) setDragOver(null); }}
                        style={{
                            minWidth: 260, maxWidth: 300, flexShrink: 0,
                            background: isOver ? "rgba(124,106,240,0.08)" : "var(--surface)",
                            border: `1.5px solid ${isOver ? "var(--accent)" : "var(--border)"}`,
                            borderRadius: "var(--radius)",
                            transition: "border-color 0.15s, background 0.15s",
                            overflowY: "auto", maxHeight: "100%",
                        }}
                    >
                        {/* Шапка колонки */}
                        <div style={{ padding: "12px 14px 10px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: "50%", background: col.color, flexShrink: 0 }} />
                            <span style={{ fontFamily: "Syne, sans-serif", fontWeight: 700, fontSize: 13 }}>{col.label}</span>
                            <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
                                {renderColumnExtra?.(col, list)}
                                <span style={{ background: "var(--surface2)", color: "var(--text-muted)", fontSize: 11, fontWeight: 600, borderRadius: 20, padding: "1px 8px" }}>
                                    {list.length}
                                </span>
                            </span>
                        </div>

                        {/* Карточки */}
                        <div style={{ padding: "8px 8px", display: "flex", flexDirection: "column", gap: 7, minHeight: 60 }}>
                            {list.length === 0 ? (
                                <div style={{ textAlign: "center", color: "var(--text-muted)", fontSize: 12, padding: "24px 0", opacity: isOver ? 0.3 : 0.6 }}>
                                    {isOver ? "Отпустите сюда" : emptyText}
                                </div>
                            ) : list.map((item, i) => (
                                <div key={item.id} onDragOver={e => onCardDragOver(e, col.key, i)}>
                                    {indicator(i)}
                                    {renderCard({ item, col: col.key, onDragStart, onDragEnd, isDragging: dragging?.id === item.id })}
                                </div>
                            ))}
                            {list.length > 0 && indicator(list.length)}
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
