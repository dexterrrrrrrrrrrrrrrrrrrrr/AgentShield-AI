from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def trim_email(cls, value):
        return value.strip().casefold() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        # App policy: email identity is case-insensitive, including the local part.
        return value.casefold()


class RegisterInput(LoginInput):
    full_name: str = Field(min_length=2, max_length=100)
    password: SecretStr = Field(min_length=12, max_length=128)
    confirm_password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("full_name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password.get_secret_value() != self.confirm_password.get_secret_value():
            raise ValueError("Passwords must match")
        if self.password.get_secret_value().isspace():
            raise ValueError("Password cannot be only whitespace")
        return self


class UserResponse(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    created_at: datetime
    authenticated: bool = True
    session_expires_at: datetime | None = None
    email_verified: bool = False
    profile_picture: str | None = None
    authentication_provider: str = "password"
    google_connected: bool = False
    last_login_at: datetime | None = None


def public_user(
    user: dict, authenticated: bool = True, session_expires_at: datetime | None = None
) -> UserResponse:
    return UserResponse(
        id=user["_id"],
        full_name=user["full_name"],
        email=user["email"],
        created_at=user["created_at"],
        authenticated=authenticated,
        session_expires_at=session_expires_at,
        email_verified=bool(user.get("email_verified", False)),
        profile_picture=user.get("profile_picture"),
        authentication_provider=(
            "password+google" if user.get("password_hash") else "google"
        )
        if user.get("google_sub")
        else "password",
        google_connected=bool(user.get("google_sub")),
        last_login_at=user.get("last_login_at"),
    )
