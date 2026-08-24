import React from "react";

export function renderCommentText(text) {
    if (!text) return null;
    const parts = text.split(/(@\S+)/g);
    return parts.map((part, i) =>
        part.startsWith("@") && part.length > 1
            ? <span key={i} className="comment-mention">{part}</span>
            : <React.Fragment key={i}>{part}</React.Fragment>
    );
}
