import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest } from "../api";
import { DealModal } from "../components/DealModal";
import { Icon } from "../components/Icon";
import { KanbanBoard } from "../components/KanbanBoard";
import { Modal } from "../components/Modal";
import { ICONS } from "../constants/icons";
import { CURRENCIES, DEFAULT_CURRENCY, STAGE_KIND_COLORS, formatDate, formatMoney, formatTotals, sumByCurrency } from "../constants/crm";
import { userName, useUsersMap } from "../hooks/useUsersMap";

const byPosition = (a, b) => a.position - b.position || a.id - b.id;

// Все сделки (постранично, по 100) — доска показывает колонки целиком.
async function fetchAllDeals(token, clientId) {
    const all = [];
    let page = 1;
    let pages = 1;
    do {
        const qs = new URLSearchParams({ page, size: 100 });
        if (clientId) qs.set("client_id", clientId);
        const data = await apiRequest({ path: `/deals?${qs}`, token });
        all.push(...(data?.items ?? []));
        pages = data?.pages ?? 1;
        page += 1;
    } while (page <= pages && page <= 10);
    return all;
}

/**
 * Воронка сделок: канбан по стадиям. clientId — только сделки этого клиента (вкладка в карточке клиента)
 * и возможность создать сделку; без clientId — все сделки компании.
 * Перетаскивание: между колонками и внутри колонки (порядок карточек сохраняется на сервере).
 */
export function DealsBoard({ token, clientId = null, canManage, currentUserId, height }) {
    const { users, usersById } = useUsersMap(token);
    const [stages, setStages] = useState([]);
    const [deals, setDeals] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [moveError, setMoveError] = useState(null);
    const [movingId, setMovingId] = useState(null);
    const [openDealId, setOpenDealId] = useState(null);
    const [lostAsk, setLostAsk] = useState(null); // { dealId, toStageId, index }
    const [lostReason, setLostReason] = useState("");
    const [showCreate, setShowCreate] = useState(false);
    const [newDeal, setNewDeal] = useState({ title: "", amount: "", currency: DEFAULT_CURRENCY, expected_close_date: "" });
    const [creating, setCreating] = useState(false);
    const [createError, setCreateError] = useState(null);

    const load = useCallback(async (silent = false) => {
        if (!silent) setLoading(true);
        setError(null);
        try {
            const [pipeline, list] = await Promise.all([
                apiRequest({ path: "/pipeline", token }),
                fetchAllDeals(token, clientId),
            ]);
            setStages(pipeline?.stages ?? []);
            setDeals(list);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }, [token, clientId]);

    useEffect(() => { if (token) load(); }, [token, load]);

    useEffect(() => {
        if (!moveError) return;
        const timer = setTimeout(() => setMoveError(null), 6000);
        return () => clearTimeout(timer);
    }, [moveError]);

    const columns = useMemo(
        () => stages.map(s => ({ key: s.id, label: s.name, color: STAGE_KIND_COLORS[s.kind] ?? "#6b7280", kind: s.kind })),
        [stages],
    );
    const items = useMemo(() => {
        const map = {};
        stages.forEach(s => { map[s.id] = []; });
        [...deals].sort(byPosition).forEach(d => { (map[d.stage_id] ??= []).push(d); });
        return map;
    }, [stages, deals]);
    const kindOf = useMemo(() => Object.fromEntries(stages.map(s => [s.id, s.kind])), [stages]);
    const openDeal = deals.find(d => d.id === openDealId) ?? null;

    // Итог «в работе» — отдельно по каждой валюте (разные валюты не складываются)
    const openTotals = formatTotals(sumByCurrency(deals.filter(d => kindOf[d.stage_id] === "open")));

    const doMove = async (dealId, toStageId, index, reason) => {
        // Оптимистично: карточка сразу встаёт на место; при ошибке доска перечитывается.
        setDeals(prev => {
            const moving = prev.find(d => d.id === dealId);
            if (!moving) return prev;
            const rest = prev.filter(d => d.id !== dealId);
            const column = rest.filter(d => d.stage_id === toStageId).sort(byPosition);
            const at = index === null || index === undefined ? column.length : Math.min(index, column.length);
            column.splice(at, 0, { ...moving, stage_id: toStageId });
            const order = new Map(column.map((d, i) => [d.id, i]));
            return [
                ...rest.map(d => (order.has(d.id) ? { ...d, position: order.get(d.id) } : d)),
                { ...moving, stage_id: toStageId, position: order.get(dealId) },
            ];
        });
        setMovingId(dealId);
        setMoveError(null);
        try {
            const body = { stage_id: toStageId };
            if (index !== null && index !== undefined) body.position = index;
            if (reason) body.lost_reason = reason;
            await apiRequest({ path: `/deals/${dealId}/stage`, method: "PATCH", token, body });
        } catch (err) {
            // Причина видна пользователю: например, у выигранной сделки нужна сумма, а закрытую вернуть может только менеджер.
            setMoveError(err.message);
        } finally {
            await load(true);
            setMovingId(null);
        }
    };

    const onMove = (dealId, fromStageId, toStageId, index) => {
        if (kindOf[toStageId] === "lost" && fromStageId !== toStageId) {
            setLostReason("");
            setLostAsk({ dealId, toStageId, index });
            return;
        }
        doMove(dealId, toStageId, index);
    };

    const confirmLost = () => {
        const reason = lostReason.trim();
        if (!reason) return;
        const { dealId, toStageId, index } = lostAsk;
        setLostAsk(null);
        doMove(dealId, toStageId, index, reason);
    };

    const createDeal = async e => {
        e.preventDefault();
        setCreating(true);
        setCreateError(null);
        try {
            const body = { title: newDeal.title.trim() };
            if (newDeal.amount !== "") body.amount = Number(newDeal.amount);
            body.currency = newDeal.currency;
            if (newDeal.expected_close_date) body.expected_close_date = newDeal.expected_close_date;
            await apiRequest({ path: `/clients/${clientId}/deals`, method: "POST", token, body });
            setNewDeal({ title: "", amount: "", currency: DEFAULT_CURRENCY, expected_close_date: "" });
            setShowCreate(false);
            await load(true);
        } catch (err) {
            setCreateError(err.message);
        } finally {
            setCreating(false);
        }
    };

    if (loading) return <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>Загрузка воронки…</div>;
    if (error) return <div style={{ padding: 40, textAlign: "center", color: "var(--red)" }}>Ошибка: {error}</div>;

    return (
        <div>
            {moveError && (
                <div className="alert" style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <span>{moveError}</span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setMoveError(null)}>✕</button>
                </div>
            )}

            <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 14, flexWrap: "wrap" }}>
                {clientId && (
                    <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(v => !v)}>
                        <Icon d={ICONS.plus} /> Сделка
                    </button>
                )}
                <button className="btn btn-ghost btn-sm" onClick={() => load()}>
                    <Icon d={ICONS.refresh} /> Обновить
                </button>
                <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: 13 }}>
                    {deals.length} сделок{openTotals && <> · в работе на {openTotals}</>}
                </span>
            </div>

            {showCreate && (
                <form onSubmit={createDeal} className="card" style={{ marginBottom: 14 }}>
                    {createError && <div className="alert" style={{ marginBottom: 10 }}>{createError}</div>}
                    <div className="form-group">
                        <label className="form-label">Название</label>
                        <input className="form-input" value={newDeal.title} maxLength={200} required
                            onChange={e => setNewDeal(f => ({ ...f, title: e.target.value }))} />
                    </div>
                    <div className="form-two-col">
                        <div className="form-group">
                            <label className="form-label">Сумма</label>
                            <input className="form-input" type="number" min="0" step="0.01" value={newDeal.amount}
                                onChange={e => setNewDeal(f => ({ ...f, amount: e.target.value }))} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">Валюта</label>
                            <select className="form-input" value={newDeal.currency}
                                onChange={e => setNewDeal(f => ({ ...f, currency: e.target.value }))}>
                                {CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.symbol} {c.code}</option>)}
                            </select>
                        </div>
                    </div>
                    <div className="form-two-col">
                        <div className="form-group">
                            <label className="form-label">Ожидаемая дата закрытия</label>
                            <input className="form-input" type="date" value={newDeal.expected_close_date}
                                onChange={e => setNewDeal(f => ({ ...f, expected_close_date: e.target.value }))} />
                        </div>
                    </div>
                    <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowCreate(false)}>Отмена</button>
                        <button type="submit" className="btn btn-primary btn-sm" disabled={creating || !newDeal.title.trim()}>Создать</button>
                    </div>
                </form>
            )}

            <KanbanBoard
                columns={columns}
                items={items}
                reorder
                height={height ?? (clientId ? "60vh" : "calc(100vh - 230px)")}
                onMove={onMove}
                renderColumnExtra={(col, list) => {
                    const totals = formatTotals(sumByCurrency(list)); // по валютам: «15 000 ₴ · 2 500 $»
                    return totals ? <span style={{ fontSize: 11, color: "var(--text-dim)", fontWeight: 600, textAlign: "right" }}>{totals}</span> : null;
                }}
                renderCard={({ item, col, onDragStart, onDragEnd, isDragging }) => (
                    <DealCard
                        deal={item}
                        col={col}
                        kind={kindOf[item.stage_id]}
                        ownerName={userName(usersById, item.owner_id)}
                        onOpen={() => setOpenDealId(item.id)}
                        onDragStart={onDragStart}
                        onDragEnd={onDragEnd}
                        isDragging={isDragging}
                        isMoving={movingId === item.id}
                    />
                )}
            />

            {openDeal && (
                <DealModal
                    deal={openDeal}
                    stages={stages}
                    users={users}
                    usersById={usersById}
                    token={token}
                    canManage={canManage}
                    currentUserId={currentUserId}
                    onClose={() => setOpenDealId(null)}
                    onChanged={() => load(true)}
                />
            )}

            {lostAsk && (
                <Modal title="Причина отказа" onClose={() => setLostAsk(null)} width={440}>
                    <div className="form-group">
                        <label className="form-label">Почему сделка проиграна? (обязательно)</label>
                        <textarea className="form-input" rows={3} value={lostReason} maxLength={500} autoFocus
                            onChange={e => setLostReason(e.target.value)} />
                    </div>
                    <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => setLostAsk(null)}>Отмена</button>
                        <button className="btn btn-danger btn-sm" onClick={confirmLost} disabled={!lostReason.trim()}>В «Отказ»</button>
                    </div>
                </Modal>
            )}
        </div>
    );
}

function DealCard({ deal, col, kind, ownerName, onOpen, onDragStart, onDragEnd, isDragging, isMoving }) {
    const overdue = kind === "open" && deal.expected_close_date && new Date(`${deal.expected_close_date}T23:59:59`) < new Date();
    return (
        <div
            draggable
            onDragStart={e => onDragStart(e, deal.id, col)}
            onDragEnd={onDragEnd}
            onClick={onOpen}
            style={{
                background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
                padding: "10px 12px", cursor: isDragging ? "grabbing" : "grab", userSelect: "none",
                opacity: isDragging ? 0.4 : isMoving ? 0.7 : 1, boxShadow: isDragging ? "none" : "var(--shadow-sm)",
                transition: "opacity 0.15s, box-shadow 0.15s",
            }}
        >
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>#{deal.id}</span>
                {deal.amount != null && (
                    <span style={{ marginLeft: "auto", fontSize: 13, fontWeight: 700, color: "var(--text)" }}>{formatMoney(deal.amount, deal.currency)}</span>
                )}
            </div>
            <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.4, wordBreak: "break-word", marginBottom: 6 }}>{deal.title}</div>
            {deal.lost_reason && (
                <div style={{ fontSize: 11, color: "var(--red)", marginBottom: 6 }}>Отказ: {deal.lost_reason}</div>
            )}
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
                {deal.expected_close_date && (
                    <span style={{ color: overdue ? "var(--red)" : "var(--text-muted)", display: "flex", alignItems: "center", gap: 3 }}>
                        <Icon d={ICONS.clock} size={11} />{formatDate(deal.expected_close_date)}
                    </span>
                )}
                <span style={{ marginLeft: "auto", color: "var(--text-dim)" }}>{ownerName}</span>
            </div>
        </div>
    );
}
