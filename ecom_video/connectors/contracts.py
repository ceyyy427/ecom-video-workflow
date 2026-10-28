"""Local connector inputs. No caller-supplied network URL, scope, or command."""

from typing import Literal

from pydantic import Field, SecretStr

from ..operations.contracts import Identifier, Strict


class AccountInput(Strict):
    platform: Literal["douyin", "xiaohongshu"]
    name: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=256)


class OAuthConfig(Strict):
    client_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    client_secret: SecretStr
    callback: str = Field(min_length=1, max_length=240)


class AuthorizeInput(Strict):
    config_id: Identifier
    confirmed: Literal[True]


class ReadInput(Strict):
    account_id: Identifier
    content_ids: list[str] = Field(min_length=1, max_length=10)
    confirmed: Literal[True]


class PackInput(Strict):
    job_id: Identifier
    platform: Literal["douyin", "xiaohongshu"]
    title: str = Field(min_length=1, max_length=100)
    text: str = Field(max_length=3000)


class RegistrationInput(Strict):
    pack_id: Identifier
    account_id: Identifier
    content_id: str = Field(min_length=1, max_length=256)
    reviewer: str = Field(min_length=1, max_length=120)
    confirmed: Literal[True]
