import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, downloadFile } from "../api";
import { DealModal } from "../components/DealModal";
import { Icon } from "../components/Icon";
import { KanbanBoard } from "../components/KanbanBoard";
import { Modal } from "../components/Modal";
import { PipelineSettings } from "../components/PipelineSettings";
import { PipelineSummary } from "../components/PipelineSummary";
import { ICONS } from "../constants/icons";
import { CURRENCIES, DEFAULT_CURRENCY, clientTypeInfo, formatDate, formatMoney, formatTotals, plural, stageColor, sumByCurrency } from "../constants/crm";
import { userName, useUsersMap } from "../hooks/useUsersMap";

const byPosition = (a, b) => a.position - b.position || a.id - b.id;

// Какая воронка выбрана на общей доске, помним между заходами (в карточке клиента выбор свой)
const PIPELINE_KEY = "spisoc_deals_pipeline";

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
export function DealsBoard({ token, clientId = null, canManage, currentUserId, isAdmin = false }) {
    const { users, usersById } = useUsersMap(token);
    const [pipelines, setPipelines] = useState([]);
    const [selectedId, setSelectedId] = useState(null);
    const [deals, setDeals] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [moveError, setMoveError] = useState(null);
    const [movingId, setMovingId] = useState(null);
    const [openDealId, setOpenDealId] = useState(null);
    const [lostAsk, setLostAsk] = useState(null); // { dealId, toStageId, index }
    const [lostReason, setLostReason] = useState("");
    const [showCreate, setShowCreate] = useState(false);
    const [showSettings, setShowSettings] = useState(false);
    const [showSummary, setShowSummary] = useState(false);
    // Создание воронки прямо рядом с выбором воронки (только admin, общая доска)
    const [addingPipeline, setAddingPipeline] = useState(false);
    const [newPipelineName, setNewPipelineName] = useState("");
    const [copyStages, setCopyStages] = useState(true);
    const [pipelineBusy, setPipelineBusy] = useState(false);
    const [newDeal, setNewDeal] = useState({ title: "", amount: "", currency: DEFAULT_CURRENCY, expected_close_date: "" });
    const [creating, setCreating] = useState(false);
    const [createError, setCreateError] = useState(null);

    const load = useCallback(async (silent = false) => {
        if (!silent) setLoading(true);
        setError(null);
        try {
            const [pipelineList, list] = await Promise.all([
                apiRequest({ path: "/pipelines", token }),
                fetchAllDeals(token, clientId),
            ]);
            setPipelines(pipelineList ?? []);
            setDeals(list);
            // Выбранная воронка остаётся, пока существует. Иначе: на общей доске — запомненная или первая;
            // в карточке клиента — воронка, где у клиента есть сделки, или первая.
            setSelectedId(prev => {
                const exists = id => (pipelineList ?? []).some(p => p.id === id);
                if (prev !== null && exists(prev)) return prev;
                const remembered = clientId ? null : Number(localStorage.getItem(PIPELINE_KEY));
                if (remembered && exists(remembered)) return remembered;
                const withDeals = (pipelineList ?? []).find(p => list.some(d => p.stages.some(s => s.id === d.stage_id)));
                return (clientId ? withDeals : null)?.id ?? pipelineList?.[0]?.id ?? null;
            });
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

    const exportCsv = async () => {
        try {
            const qs = new URLSearchParams();
            if (clientId) qs.set("client_id", clientId);
            await downloadFile({ path: `/deals/export?${qs}`, token, fallbackName: "deals_export.csv" });
        } catch (e) {
            setMoveError(e.message);
        }
    };

    const pipeline = pipelines.find(p => p.id === selectedId) ?? null;
    const stages = useMemo(() => pipeline?.stages ?? [], [pipeline]);
    // сделки выбранной воронки (стадии разных воронок не пересекаются)
    const pipelineDeals = useMemo(() => {
        const ids = new Set(stages.map(s => s.id));
        return deals.filter(d => ids.has(d.stage_id));
    }, [deals, stages]);
    const dealsCountOf = p => deals.filter(d => p.stages.some(s => s.id === d.stage_id)).length;

    const selectPipeline = id => {
        setSelectedId(id);
        if (!clientId) localStorage.setItem(PIPELINE_KEY, String(id));
    };

    const createPipeline = async (e) => {
        e.preventDefault();
        const name = newPipelineName.trim();
        if (!name) return;
        setPipelineBusy(true);
        try {
            const body = { name };
            if (copyStages && pipeline) body.copy_from_id = pipeline.id;
            const created = await apiRequest({ path: "/pipelines", method: "POST", token, body });
            await load(true);
            if (created?.id) selectPipeline(created.id);
            setAddingPipeline(false);
            setNewPipelineName("");
            if (!copyStages) setShowSettings(true); // пустую воронку сразу открываем для настройки стадий
        } catch (err) {
            setMoveError(err.message);
        } finally {
            setPipelineBusy(false);
        }
    };

    const addPipelineControl = isAdmin && !clientId && (addingPipeline ? (
        <form className="dl-addpipe" onSubmit={createPipeline}>
            <input
                className="form-input" autoFocus maxLength={100} required aria-label="Название новой воронки"
                placeholder="Название новой воронки" value={newPipelineName} onChange={e => setNewPipelineName(e.target.value)}
            />
            {pipeline && (
                <label className="cl-check">
                    <input type="checkbox" checked={copyStages} onChange={e => setCopyStages(e.target.checked)} />
                    Скопировать стадии из «{pipeline.name}»
                </label>
            )}
            <button type="submit" className="btn btn-primary" disabled={pipelineBusy || !newPipelineName.trim()}>
                {pipelineBusy ? "Создаю…" : "Создать"}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => { setAddingPipeline(false); setNewPipelineName(""); }}>Отмена</button>
        </form>
    ) : (
        <button type="button" className="btn btn-ghost" onClick={() => setAddingPipeline(true)} title="Создать новую воронку">
            <Icon d={ICONS.plus} /> Воронка
        </button>
    ));

    const columns = useMemo(
        () => stages.map(s => ({ key: s.id, label: s.name, color: stageColor(s), kind: s.kind })),
        [stages],
    );
    const items = useMemo(() => {
        const map = {};
        stages.forEach(s => { map[s.id] = []; });
        [...pipelineDeals].sort(byPosition).forEach(d => { (map[d.stage_id] ??= []).push(d); });
        return map;
    }, [stages, pipelineDeals]);
    const kindOf = useMemo(() => Object.fromEntries(stages.map(s => [s.id, s.kind])), [stages]);
    const openDeal = pipelineDeals.find(d => d.id === openDealId) ?? null;
    // сводка перечитывается, когда изменились сделки на доске (перенос, сумма, валюта, удаление)
    const dealsSignature = deals.map(d => `${d.id}:${d.stage_id}:${d.amount}:${d.currency}:${d.owner_id}`).join("|");

    // Итог «в работе» — отдельно по каждой валюте (разные валюты не складываются)
    const openTotals = formatTotals(sumByCurrency(pipelineDeals.filter(d => kindOf[d.stage_id] === "open")));

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
            if (selectedId) body.pipeline_id = selectedId; // сделка создаётся в выбранной воронке
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
        <div className={clientId ? undefined : "cl-page"}>
            {moveError && (
                <div className="alert" style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <span>{moveError}</span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setMoveError(null)}>✕</button>
                </div>
            )}

            {!clientId ? (
                <>
                    <div className="cl-head">
                        <div>
                            <h1 className="cl-title">Воронка сделок</h1>
                            <div className="cl-sub">
                                {pipelineDeals.length} {plural(pipelineDeals.length, "сделка", "сделки", "сделок")}{openTotals && <> · в работе на {openTotals}</>}
                            </div>
                        </div>
                        <div className="cl-actions">
                            <button className="btn btn-ghost" onClick={() => load()}><Icon d={ICONS.refresh} /> Обновить</button>
                            {canManage && (
                                <button className="btn btn-ghost" onClick={exportCsv} title="Выгрузить сделки в CSV">Экспорт</button>
                            )}
                            <button className="btn btn-ghost" onClick={() => setShowSummary(v => !v)} aria-pressed={showSummary}>Сводка</button>
                            {isAdmin && (
                                <button className="btn btn-ghost" onClick={() => setShowSettings(v => !v)} aria-pressed={showSettings}>Воронки</button>
                            )}
                        </div>
                    </div>
                    <div className="cl-filters">
                        {pipelines.length > 1 && (
                            <select
                                className="form-input dl-select" value={selectedId ?? ""} aria-label="Воронка"
                                onChange={e => selectPipeline(Number(e.target.value))}
                            >
                                {pipelines.map(p => <option key={p.id} value={p.id}>{p.name} ({dealsCountOf(p)})</option>)}
                            </select>
                        )}
                        {addPipelineControl}
                    </div>
                </>
            ) : (
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 14, flexWrap: "wrap" }}>
                {clientId && (
                    <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(v => !v)}>
                        <Icon d={ICONS.plus} /> Сделка
                    </button>
                )}
                <button className="btn btn-ghost btn-sm" onClick={() => load()}>
                    <Icon d={ICONS.refresh} /> Обновить
                </button>
                {canManage && (
                    <button className="btn btn-ghost btn-sm" onClick={exportCsv} title="Выгрузить сделки в CSV">
                        Экспорт
                    </button>
                )}
                {pipelines.length > 1 && (
                    <select
                        value={selectedId ?? ""} onChange={e => selectPipeline(Number(e.target.value))}
                        title="Воронка" style={{ width: "auto", padding: "6px 10px", minWidth: 160 }}
                    >
                        {pipelines.map(p => <option key={p.id} value={p.id}>{p.name} ({dealsCountOf(p)})</option>)}
                    </select>
                )}
                {!clientId && (
                    <button className="btn btn-ghost btn-sm" onClick={() => setShowSummary(v => !v)}>
                        📊 Сводка
                    </button>
                )}
                {isAdmin && !clientId && (
                    <button className="btn btn-ghost btn-sm" onClick={() => setShowSettings(v => !v)}>
                        ⚙ Воронки
                    </button>
                )}
                <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: 13 }}>
                    {pipelineDeals.length} {plural(pipelineDeals.length, "сделка", "сделки", "сделок")}{openTotals && <> · в работе на {openTotals}</>}
                </span>
            </div>
            )}

            {showSummary && !clientId && (
                <PipelineSummary token={token} users={users} pipelineId={selectedId} refreshKey={dealsSignature} onClose={() => setShowSummary(false)} />
            )}

            {showSettings && isAdmin && (
                <PipelineSettings
                    token={token} pipelines={pipelines} selectedId={selectedId} onSelect={selectPipeline}
                    dealsCountOf={dealsCountOf} onChanged={() => load(true)} onClose={() => setShowSettings(false)}
                />
            )}

            {showCreate && (
                <form onSubmit={createDeal} className="card form" style={{ marginBottom: 14 }}>
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
                height="auto"
                colorBar
                onMove={onMove}
                renderColumnExtra={(col, list) => {
                    const totals = formatTotals(sumByCurrency(list)); // по валютам: «15 000 ₴ · 2 500 $»
                    return totals ? <span style={{ fontSize: 12, color: "var(--text-muted)", fontWeight: 500 }}>{totals}</span> : null;
                }}
                renderCard={({ item, col, onDragStart, onDragEnd, isDragging }) => (
                    <DealCard
                        deal={item}
                        col={col}
                        kind={kindOf[item.stage_id]}
                        ownerName={userName(usersById, item.owner_id)}
                        showClient={!clientId}
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

function DealCard({ deal, col, kind, ownerName, showClient, onOpen, onDragStart, onDragEnd, isDragging, isMoving }) {
    const overdue = kind === "open" && deal.expected_close_date && new Date(`${deal.expected_close_date}T23:59:59`) < new Date();
    const cls = `dl-card${isDragging ? " is-dragging" : ""}${isMoving ? " is-moving" : ""}`;
    return (
        <div
            className={cls}
            draggable
            onDragStart={e => onDragStart(e, deal.id, col)}
            onDragEnd={onDragEnd}
            onClick={onOpen}
        >
            <div className="dl-card-title">{deal.title}</div>
            {showClient && deal.client_name && (
                <div className="dl-card-client" title={clientTypeInfo(deal.client_type).label}>
                    {clientTypeInfo(deal.client_type).icon} {deal.client_name}
                </div>
            )}
            {deal.lost_reason && <div className="dl-card-lost">Отказ: {deal.lost_reason}</div>}
            <div className="dl-card-foot">
                <span className="dl-card-amount">{deal.amount != null ? formatMoney(deal.amount, deal.currency) : "Без суммы"}</span>
                <span className="dl-card-owner" title={ownerName}>{(ownerName || "?").trim().charAt(0).toUpperCase()}</span>
            </div>
            <div className="dl-card-meta">
                <span>#{deal.id}</span>
                {deal.expected_close_date && (
                    <span className={overdue ? "dl-overdue" : undefined}>
                        <Icon d={ICONS.clock} size={11} /> {formatDate(deal.expected_close_date)}
                    </span>
                )}
            </div>
        </div>
    );
}
