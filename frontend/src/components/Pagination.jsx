import { Icon } from "./Icon";
import { ICONS } from "../constants/icons";

export function Pagination({ page, totalPages, onPage }) {
    if (totalPages <= 1) return null;
    return (
        <div className="pagination">
            <button className="btn btn-ghost btn-sm" onClick={() => onPage(page - 1)} disabled={page <= 1}>
                <Icon d={ICONS.chevronL} />
            </button>
            <span className="page-info">{page} / {totalPages}</span>
            <button className="btn btn-ghost btn-sm" onClick={() => onPage(page + 1)} disabled={page >= totalPages}>
                <Icon d={ICONS.chevronR} />
            </button>
        </div>
    );
}

// ─── Comments panel ───────────────────────────────────────
// ─── AuditPanel ──────────────────────────────────────────
