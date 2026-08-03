# src/admin/utils/url_helpers.py

from starlette.requests import Request

ADMIN_PREFIX = "/admin"

URLS = {
    "template": {
        "list": f"{ADMIN_PREFIX}/task-template-model/list",
        "details": f"{ADMIN_PREFIX}/task-template-model/details/",
        "edit": f"{ADMIN_PREFIX}/task-template-model/edit/",
        "apply": f"{ADMIN_PREFIX}/task-template-model/apply/",
    },
    "user": {
        "list": f"{ADMIN_PREFIX}/user-model/list",
        "details": f"{ADMIN_PREFIX}/user-model/details/",
        "edit": f"{ADMIN_PREFIX}/user-model/edit/",
        "toggle": f"{ADMIN_PREFIX}/user-model/toggle-active/",
        "stats": f"{ADMIN_PREFIX}/user-model/stats/",
    },
    "task": {
        "list": f"{ADMIN_PREFIX}/spisok-model/list",
        "details": f"{ADMIN_PREFIX}/spisok-model/details/",
        "edit": f"{ADMIN_PREFIX}/spisok-model/edit/",
        "create": f"{ADMIN_PREFIX}/spisok-model/comment/create?task_id=",
    },
}


def admin_url(request: Request, path: str) -> str:
    """Строит абсолютный URL для админки"""
    base = str(request.base_url).rstrip("/")
    return f"{base}/admin/{path.lstrip('/')}"


def user_urls(request: Request, user_id: int) -> dict:
    """Все URL для пользователя"""
    return {
        "list": admin_url(request, "user-model/list"),
        "details": admin_url(request, f"user-model/details/{user_id}"),
        "edit": admin_url(request, f"user-model/edit/{user_id}"),
        "toggle": admin_url(request, f"user-model/toggle-active/{user_id}"),
        "stats": admin_url(request, f"user-model/stats/{user_id}"),
    }


def task_urls(request: Request) -> dict:
    """Все URL для задачи"""
    return {
        "list": admin_url(request, "spisok-model/list"),
        "details": admin_url(request, "spisok-model/details/"),
        "edit": admin_url(request, "spisok-model/edit/"),
    }


# Справочник маршрутов sqladmin (для навигации по коду, не используется рантаймом):
#   statics                              → /statics
#   index                                → /
#   list                                 → /{identity}/list
#   details                              → /{identity}/details/{pk:path}
#   delete                                → /{identity}/delete
#   create                                → /{identity}/create
#   edit                                  → /{identity}/edit/{pk:path}
#   export                                → /{identity}/export/{export_type}
#   ajax_lookup                           → /{identity}/ajax/lookup
#   login                                 → /login
#   logout                                → /logout
#   view-user-model-user_stats           → /user-model/stats/{pk}
#   view-user-model-toggle_active        → /user-model/toggle-active/{pk}
#   view-spisok-model-create_comment     → /spisok-model/comment/create
#
# В шаблонах Jinja2 статичные ссылки строятся через словарь urls (см. функции
# выше), динамические — через base + admin_url() в цикле:
#   <a href="{{ urls.list }}">← Назад</a>
#   {% for t in tasks %}<a href="{{ base }}/admin/spisok-model/details/{{ t.id }}">{{ t.title }}</a>{% endfor %}
