from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse
from typing import NoReturn


def not_found(detail: str = "Not found") -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def task_not_found(detail: str = "Task not found") -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def unauthorized(detail: str = "Invalid or expired token"):
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def invalid_credentials(detail: str = "Invalid credentials"):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def user_already_exists(detail: str = "User already exists"):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def current_admin(detail: str = "For administrator only"):
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="For administrator only"
    )


def no_access(detail: str = "No access"):
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def incorrect_request(detail: str = "Incorrect request"):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def group_already_exists(detail: str = "Group already exists"):
    raise HTTPException(status_code=400, detail="Group already exists")


def invalid_id_response():
    return HTMLResponse("Неверный ID", status_code=400)


def user_not_found_response():
    return HTMLResponse("Пользователь не найден", status_code=404)


def incorrect_valueerror(detail: str = "Incorrect request"):
    raise ValueError(detail)


def user_not_found(detail: str = "User not found"):
    raise HTTPException(status_code=404, detail=detail)


def unauthorized_user(detail: str = "This is not your task"):
    raise HTTPException(status_code=403, detail=detail)
