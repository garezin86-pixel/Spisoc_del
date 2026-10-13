import { GENDERS, todayInput } from "../constants/crm";

// Поля частного лица (B2C): дата рождения и пол. Показываются, только когда выбран тип «Человек».
export function PersonFields({ form, set }) {
    return (
        <div className="form-two-col">
            <div className="form-group">
                <label className="form-label">Дата рождения</label>
                <input type="date" max={todayInput()} min="1900-01-01" value={form.birth_date} onChange={set("birth_date")} />
            </div>
            <div className="form-group">
                <label className="form-label">Пол</label>
                <select value={form.gender} onChange={set("gender")}>
                    <option value="">Не указан</option>
                    {GENDERS.map(g => <option key={g.key} value={g.key}>{g.label}</option>)}
                </select>
            </div>
        </div>
    );
}
