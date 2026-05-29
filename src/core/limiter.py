# src/core/limiter.py
# Единственный экземпляр лимитера — импортируется во всех роутерах
from slowapi import Limiter

limiter = Limiter(key_func=lambda request: request.client.host)
