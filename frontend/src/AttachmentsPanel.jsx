// AttachmentsPanel.jsx
// Панель вложений к задаче с дропзоной для загрузки файлов.
//
// Бэкенд:
//   POST   /api/attachments/tasks/{taskId}   — загрузить (multipart)
//   GET    /api/attachments/tasks/{taskId}   — список
//   GET    /api/attachments/{id}/download    — скачать
//   DELETE /api/attachments/{id}             — удалить

import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest, API_BASE } from "./api";

const MAX_SIZE = 20 * 1024 * 1024; // 20 МБ

const ATTACH_ICONS = {
    paperclip: "M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z",
    download:  "M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z",
    trash:     "M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z",
    file:      "M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z",
    image:     "M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z",
    video:     "M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z",
    audio:     "M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z",
};

function Icon({ d, size = 18 }) {
    return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
            <path d={d} />
        </svg>
    );
}

function fileIcon(mimeType) {
    if (!mimeType) return ATTACH_ICONS.file;
    if (mimeType.startsWith("image/")) return ATTACH_ICONS.image;
    if (mimeType.startsWith("video/")) return ATTACH_ICONS.video;
    if (mimeType.startsWith("audio/")) return ATTACH_ICONS.audio;
    return ATTACH_ICONS.file;
}

function formatSize(bytes) {
    if (!bytes) return "—";
    if (bytes < 1024) return `${bytes} Б`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

function formatDate(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleString("ru-RU", {
        day: "2-digit", month: "short",
        hour: "2-digit", minute: "2-digit",
    });
}

// ─── Дропзона ────────────────────────────────────────────────────────────────

function DropZone({ onFiles, uploading }) {
    const [dragOver, setDragOver] = useState(false);
    const inputRef = useRef(null);

    function handleDrop(e) {
        e.preventDefault();
        setDragOver(false);
        const files = Array.from(e.dataTransfer.files);
        if (files.length) onFiles(files);
    }

    function handleChange(e) {
        const files = Array.from(e.target.files);
        if (files.length) onFiles(files);
        e.target.value = "";            // сбрасываем input чтобы можно было выбрать тот же файл снова
    }

    return (
        <div
            className={`dropzone ${dragOver ? "dropzone--over" : ""} ${uploading ? "dropzone--uploading" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => !uploading && inputRef.current?.click()}
        >
            <input
                ref={inputRef}
                type="file"
                multiple
                style={{ display: "none" }}
                onChange={handleChange}
            />
            <Icon d={ATTACH_ICONS.paperclip} size={20} />
            {uploading ? (
                <span>Загрузка…</span>
            ) : dragOver ? (
                <span>Отпустите файл</span>
            ) : (
                <span>
                    Перетащите файлы или <u>нажмите</u>
                    <br />
                    <small>Максимум 20 МБ на файл</small>
                </span>
            )}
        </div>
    );
}

// ─── Прогресс-бар загружаемых файлов ─────────────────────────────────────────

function UploadQueue({ queue }) {
    if (!queue.length) return null;
    return (
        <div className="upload-queue">
            {queue.map((item) => (
                <div key={item.id} className="upload-queue-item">
                    <span className="upload-queue-name" title={item.name}>
                        {item.name}
                    </span>
                    {item.error ? (
                        <span className="upload-queue-error">{item.error}</span>
                    ) : item.done ? (
                        <span className="upload-queue-done">✓</span>
                    ) : (
                        <div className="upload-progress">
                            <div
                                className="upload-progress-bar"
                                style={{ width: `${item.progress}%` }}
                            />
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
}

// ─── Основной компонент ───────────────────────────────────────────────────────

export default function AttachmentsPanel({ taskId, token, currentUserId, canDelete }) {
    const [items, setItems]           = useState([]);
    const [total, setTotal]           = useState(0);
    const [loading, setLoading]       = useState(false);
    const [deletingId, setDeletingId] = useState(null);
    const [error, setError]           = useState(null);
    const [queue, setQueue]           = useState([]);   // [{id, name, progress, done, error}]

    const inflightRef = useRef(false);

    // ── Загрузка списка ───────────────────────────────────────────────────────
    const load = useCallback(async () => {
        if (inflightRef.current) return;
        inflightRef.current = true;
        setLoading(true);
        setError(null);
        try {
            const data = await apiRequest({ path: `/attachments/tasks/${taskId}`, token });
            setItems(data?.items ?? []);
            setTotal(data?.total ?? 0);
        } catch {
            setError("Не удалось загрузить вложения");
        } finally {
            setLoading(false);
            inflightRef.current = false;
        }
    }, [taskId, token]);

    useEffect(() => { load(); }, [load]);

    // ── Загрузка файлов через XMLHttpRequest (нужен прогресс) ─────────────────
    async function uploadFile(file, queueId) {
        return new Promise((resolve, reject) => {
            if (file.size > MAX_SIZE) {
                reject(new Error(`Файл слишком большой: ${formatSize(file.size)}. Макс. 20 МБ`));
                return;
            }

            const fd = new FormData();
            fd.append("file", file);

            const xhr = new XMLHttpRequest();
            xhr.open("POST", `${API_BASE}/attachments/tasks/${taskId}`);
            xhr.setRequestHeader("Authorization", `Bearer ${token}`);

            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) {
                    const pct = Math.round((e.loaded / e.total) * 100);
                    setQueue((q) =>
                        q.map((item) => item.id === queueId ? { ...item, progress: pct } : item)
                    );
                }
            };

            xhr.onload = () => {
                if (xhr.status === 201) {
                    const newAtt = JSON.parse(xhr.responseText);
                    resolve(newAtt);
                } else {
                    try {
                        const err = JSON.parse(xhr.responseText);
                        reject(new Error(err.detail || `Ошибка ${xhr.status}`));
                    } catch {
                        reject(new Error(`Ошибка ${xhr.status}`));
                    }
                }
            };

            xhr.onerror = () => reject(new Error("Сетевая ошибка"));
            xhr.send(fd);
        });
    }

    async function handleFiles(files) {
        setError(null);

        // Добавляем файлы в очередь
        const newItems = files.map((f) => ({
            id: `${f.name}-${Date.now()}-${Math.random()}`,
            name: f.name,
            progress: 0,
            done: false,
            error: null,
        }));
        setQueue((q) => [...q, ...newItems]);

        // Загружаем параллельно
        await Promise.all(
            files.map(async (file, i) => {
                const queueId = newItems[i].id;
                try {
                    const att = await uploadFile(file, queueId);
                    // Добавляем в список
                    setItems((prev) => [att, ...prev]);
                    setTotal((n) => n + 1);
                    setQueue((q) =>
                        q.map((item) => item.id === queueId ? { ...item, done: true, progress: 100 } : item)
                    );
                } catch (e) {
                    setQueue((q) =>
                        q.map((item) => item.id === queueId ? { ...item, error: e.message } : item)
                    );
                }
            })
        );

        // Через 3 секунды убираем завершённые из очереди (только успешные)
        setTimeout(() => {
            setQueue((q) => q.filter((item) => !item.done));
        }, 3000);
    }

    // ── Скачивание ────────────────────────────────────────────────────────────
    async function handleDownload(attachmentId, filename, mimeType) {
        try {
            const res = await fetch(`${API_BASE}/attachments/${attachmentId}/download`, {
                headers: { Authorization: `Bearer ${token}` },
                redirect: "follow",
            });
            if (!res.ok) {
                setError(
                    res.status === 404
                        ? `Файл доступен только в Telegram-боте: /getfile ${attachmentId}`
                        : "Не удалось скачать файл"
                );
                return;
            }
            const blob = await res.blob();

            // Восстанавливаем правильный Content-Type из известного mime_type
            // (StaticFiles может отдавать application/octet-stream)
            const typedBlob = (mimeType && blob.type === "application/octet-stream")
                ? new Blob([blob], { type: mimeType })
                : blob;

            const url = URL.createObjectURL(typedBlob);

            // Изображения открываем в новой вкладке, остальное скачиваем
            if (typedBlob.type.startsWith("image/")) {
                const win = window.open(url, "_blank", "noopener,noreferrer");
                // Если попап заблокирован — скачиваем как fallback
                if (!win) {
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = filename || "file";
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                }
            } else {
                const a = document.createElement("a");
                a.href = url;
                a.download = filename || "file";
                document.body.appendChild(a);
                a.click();
                a.remove();
            }

            setTimeout(() => URL.revokeObjectURL(url), 10000);
        } catch {
            setError("Не удалось скачать файл");
        }
    }

    // ── Удаление ──────────────────────────────────────────────────────────────
    async function handleDelete(attachmentId) {
        if (!window.confirm("Удалить вложение?")) return;
        setDeletingId(attachmentId);
        try {
            await apiRequest({ path: `/attachments/${attachmentId}`, method: "DELETE", token });
            setItems((prev) => prev.filter((a) => a.id !== attachmentId));
            setTotal((n) => n - 1);
        } catch {
            setError("Не удалось удалить вложение");
        } finally {
            setDeletingId(null);
        }
    }

    const isUploading = queue.some((item) => !item.done && !item.error);

    // ── Рендер ────────────────────────────────────────────────────────────────
    return (
        <div className="attachments-panel">
            {/* Заголовок */}
            <div className="attachments-title">
                <Icon d={ATTACH_ICONS.paperclip} />
                Вложения
                {total > 0 && <span className="count-badge">{total}</span>}
            </div>

            {/* Ошибка */}
            {error && (
                <div className="attachments-error" onClick={() => setError(null)}>
                    {error}
                </div>
            )}

            {/* Дропзона */}
            <DropZone onFiles={handleFiles} uploading={isUploading} />

            {/* Очередь загрузки */}
            <UploadQueue queue={queue} />

            {/* Список файлов */}
            {loading ? (
                <div className="attachments-empty">Загрузка…</div>
            ) : items.length === 0 ? (
                <div className="attachments-empty">
                    Вложений пока нет
                </div>
            ) : (
                <div className="attachment-list">
                    {items.map((att) => (
                        <div key={att.id} className="attachment-item">
                            <div className="attachment-icon">
                                <Icon d={fileIcon(att.mime_type)} size={20} />
                            </div>
                            <div className="attachment-info">
                                <div className="attachment-filename" title={att.filename}>
                                    {att.filename}
                                </div>
                                <div className="attachment-meta">
                                    {formatSize(att.file_size)} · {att.uploader?.username ?? "—"} · {formatDate(att.created_at)}
                                </div>
                            </div>
                            <div className="attachment-actions">
                                <button
                                    className="btn-icon"
                                    title="Скачать"
                                    onClick={() => handleDownload(att.id, att.filename, att.mime_type)}
                                >
                                    <Icon d={ATTACH_ICONS.download} size={16} />
                                </button>
                                {(canDelete || att.uploader?.id === currentUserId) && (
                                    <button
                                        className="btn-icon btn-icon-danger"
                                        title="Удалить"
                                        disabled={deletingId === att.id}
                                        onClick={() => handleDelete(att.id)}
                                    >
                                        <Icon d={ATTACH_ICONS.trash} size={16} />
                                    </button>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
