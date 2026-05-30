from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CollectionVariable:
    key: str
    value: str
    type: str = "string"


@dataclass
class AuthConfig:
    type: str
    params: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, "params": self.params}


@dataclass
class QueryParam:
    key: str
    value: str
    disabled: bool = False


@dataclass
class RequestBody:
    mode: str
    content: str | dict | list = ""
    content_type: str = ""

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "content": self.content,
            "content_type": self.content_type,
        }


@dataclass
class ParsedRequest:
    name: str
    method: str
    url_raw: str
    headers: dict[str, str] = field(default_factory=dict)
    body: RequestBody = field(default_factory=lambda: RequestBody(mode="none"))
    auth: AuthConfig | None = None
    query_params: list[QueryParam] = field(default_factory=list)
    folder_path: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "method": self.method,
            "url_raw": self.url_raw,
            "headers": self.headers,
            "body": self.body.to_dict(),
            "auth": self.auth.to_dict() if self.auth else None,
            "query_params": [
                {"key": q.key, "value": q.value, "disabled": q.disabled}
                for q in self.query_params
            ],
            "folder_path": self.folder_path,
        }


@dataclass
class ParsedCollection:
    name: str
    description: str
    requests: list[ParsedRequest] = field(default_factory=list)
    variables: list[CollectionVariable] = field(default_factory=list)
    auth: AuthConfig | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "requests": [r.to_dict() for r in self.requests],
            "variables": [
                {"key": v.key, "value": v.value, "type": v.type}
                for v in self.variables
            ],
            "auth": self.auth.to_dict() if self.auth else None,
        }
