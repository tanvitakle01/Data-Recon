from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1)
    organization_name: str = Field(min_length=1)


class SignInRequest(BaseModel):
    email: EmailStr
    password: str


class PasswordResetRequestBody(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    access_token: str
    new_password: str = Field(min_length=8)


class CurrentUserResponse(BaseModel):
    email: str
    full_name: str | None
    organization_name: str
