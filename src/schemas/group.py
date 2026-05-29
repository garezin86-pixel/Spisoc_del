from pydantic import BaseModel, ConfigDict, Field

from src.schemas.user import UserSchema


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class GroupSchema(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class GroupWithUsersSchema(BaseModel):
    id: int
    name: str
    users: list[UserSchema] = []

    model_config = ConfigDict(from_attributes=True)
