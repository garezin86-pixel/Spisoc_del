import hashlib
from typing import Any

from fastapi import Request, Response


def user_scoped_key_builder(
    func,
    namespace: str = "",
    *,
    request: Request | None = None,
    response: Response | None = None,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str:
    """Build stable cache keys for endpoints that depend on the current user."""
    user = kwargs.get("current_user")
    user_id = getattr(user, "id", "anonymous")

    if request is not None:
        raw_key = f"{request.method}:{request.url.path}?{request.url.query}:user={user_id}"
    else:
        raw_key = f"{func.__module__}:{func.__name__}:user={user_id}:{kwargs}"

    digest = hashlib.md5(raw_key.encode()).hexdigest()
    return f"{namespace}:{digest}"
