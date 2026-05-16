from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator


class SetupStatusResponse(BaseModel):
    needs_setup: bool


class SetupCompleteRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)


class SetupCompleteResponse(BaseModel):
    api_key: str
    message: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: str
    username: str
    roles: list[str]
    llm_nl_enabled: bool = True


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    email: str | None = None
    roles: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def roles_must_be_viewer_or_manager(self) -> Self:
        allowed = {"viewer", "manager"}
        if len(self.roles) != 1:
            raise ValueError("exactly one role is required: viewer or manager")
        if self.roles[0] not in allowed:
            raise ValueError("role must be viewer or manager")
        return self


class UserOut(BaseModel):
    id: str
    username: str
    email: str | None
    is_active: bool
    roles: list[str]


class AuditLogEntry(BaseModel):
    id: int
    ts: str
    actor_kind: str
    actor_username: str | None
    action: str
    target_kind: str | None
    target_id: str | None
    details: dict[str, Any]
    ip: str | None
    user_agent: str | None


class AuditLogListResponse(BaseModel):
    total: int
    items: list[AuditLogEntry]


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class ApiKeyCreateResponse(BaseModel):
    id: str
    name: str
    key: str


class ApiKeyOut(BaseModel):
    id: str
    name: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=512)
    source_url: str | None = None
    breach_date: str | None = None
    type: str | None = None
    notes: str | None = None


class TagPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=512)
    source_url: str | None = None
    breach_date: str | None = None
    type: str | None = None
    notes: str | None = None


class TagOut(BaseModel):
    id: str
    name: str
    source_url: str | None
    breach_date: str | None
    type: str | None
    notes: str | None
    created_at: str


class IndexRequest(BaseModel):
    leads: list[dict] = Field(default_factory=list)
    tag_names: list[str] = Field(default_factory=list)
    batch_name: str | None = None


class QueryRequest(BaseModel):
    dsl: str
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    view: Literal["rows", "merged"] = "rows"


class QueryNlRequest(BaseModel):
    nl: str = Field(min_length=1, max_length=2000)


class QueryNlResponse(BaseModel):
    ok: bool
    dsl: str | None = None
    error: str | None = None
    attempted: str | None = None


class AssistantChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class AssistantChatRequest(BaseModel):
    messages: list[AssistantChatMessage] = Field(min_length=1, max_length=24)


class AssistantChatResponse(BaseModel):
    reply: str


class ExportRequest(BaseModel):
    dsl: str
    format: Literal["csv", "jsonl"] = "csv"


class JobOut(BaseModel):
    id: str
    type: str
    state: str
    batch_id: str | None
    processed_rows: int
    total_rows: int | None
    result_uri: str | None
    error: str | None
    started_at: str | None
    finished_at: str | None
    checkpoint: dict
    batch_name: str | None = None
    source_filename: str | None = None
    accepted_rows: int | None = None
    rejected_rows: int | None = None
    duplicate_rows: int | None = None
    ingest_ts: str | None = None


class BatchOut(BaseModel):
    id: str
    name: str | None
    source_filename: str | None
    accepted_rows: int
    rejected_rows: int
    duplicate_rows: int
    ingest_ts: str


class UploadBrowseEntry(BaseModel):
    key: str
    is_directory: bool
    size: int | None = None
    content_type: str | None = None
    last_modified: str | None = None


class UploadBrowseResponse(BaseModel):
    prefix: str
    entries: list[UploadBrowseEntry]


class UploadPresignResponse(BaseModel):
    url: str
