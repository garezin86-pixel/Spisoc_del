# src/schemas/calendar.py
from pydantic import BaseModel


class CalendarFeedResponse(BaseModel):
    feed_url: str
