from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

StorageStore = Literal["uploads", "exports"]


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


class ColumnMapSuggestRequest(BaseModel):
    format: Literal["csv"] = "csv"
    inner_name: str | None = None
    headers: list[str] = Field(min_length=1, max_length=200)
    sample_rows: list[dict[str, str]] = Field(default_factory=list, max_length=20)


class ColumnMapSuggestResponse(BaseModel):
    column_map: dict[str, str]
    canonical_fields: list[str]


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
    family: str | None = None
    notes: str | None = None

    @field_validator("family", mode="before")
    @classmethod
    def validate_family_code(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise TypeError("tag family must be a string or null")
        s = v.strip()
        return s.upper() if s else None


class TagPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=512)
    source_url: str | None = None
    breach_date: str | None = None
    family: str | None = None
    notes: str | None = None

    @field_validator("family", mode="before")
    @classmethod
    def validate_family_code(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise TypeError("tag family must be a string or null")
        s = v.strip()
        return s.upper() if s else None


class TagTaxonomyFamilyItem(BaseModel):
    code: str


class TagTaxonomyOut(BaseModel):
    families: list[TagTaxonomyFamilyItem]


class TagOut(BaseModel):
    id: str
    name: str
    source_url: str | None
    breach_date: str | None
    family: str | None
    notes: str | None
    created_at: str

    @classmethod
    def from_tag(cls, t: object, *, family_code: str | None = None) -> Self:
        """Build TagOut from a Tag ORM row (avoids circular imports on Tag model)."""
        breach = getattr(t, "breach_date", None)
        return cls(
            id=str(getattr(t, "id")),
            name=str(getattr(t, "name")),
            source_url=getattr(t, "source_url", None),
            breach_date=breach.isoformat() if breach else None,
            family=family_code,
            notes=getattr(t, "notes", None),
            created_at=getattr(t, "created_at").isoformat(),
        )


class TagFamilyCreate(BaseModel):
    code: str = Field(min_length=1, max_length=128)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, v: object) -> str:
        if not isinstance(v, str):
            raise TypeError("family code must be a string")
        s = v.strip()
        if not s:
            raise ValueError("family code is required")
        return s.upper()


class TagFamilyPatch(BaseModel):
    code: str = Field(min_length=1, max_length=128)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, v: object) -> str:
        if not isinstance(v, str):
            raise TypeError("family code must be a string")
        s = v.strip()
        if not s:
            raise ValueError("family code is required")
        return s.upper()


class TagFamilyOut(BaseModel):
    id: str
    code: str
    created_at: str

    @classmethod
    def from_family(cls, row: object) -> Self:
        return cls(
            id=str(getattr(row, "id")),
            code=str(getattr(row, "code")),
            created_at=getattr(row, "created_at").isoformat(),
        )


class IndexRequest(BaseModel):
    leads: list[dict] = Field(default_factory=list)
    tag_names: list[str] = Field(default_factory=list)
    batch_name: str | None = None


class QueryRequest(BaseModel):
    dsl: str
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    view: Literal["rows", "related"] = "rows"


class SavedViewCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    dsl: str = Field(min_length=1)
    view: Literal["rows", "related"] = "rows"


class SavedViewPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    dsl: str | None = Field(default=None, min_length=1)
    view: Literal["rows", "related"] | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if not any(field in self.model_fields_set for field in ("name", "dsl", "view")):
            raise ValueError("at least one field is required")
        return self


class SavedViewOut(BaseModel):
    id: str
    name: str
    dsl: str
    view: Literal["rows", "related"]
    created_at: str
    updated_at: str

    @classmethod
    def from_saved_view(cls, row: object) -> Self:
        return cls(
            id=str(getattr(row, "id")),
            name=str(getattr(row, "name")),
            dsl=str(getattr(row, "dsl")),
            view=getattr(row, "view"),
            created_at=getattr(row, "created_at").isoformat(),
            updated_at=getattr(row, "updated_at").isoformat(),
        )


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
    row_limit: int | None = Field(default=None, ge=1)


class IngestQueuedUploadRequest(BaseModel):
    upload_id: str = Field(min_length=1)
    selected_files: list[str] = Field(default_factory=list)
    tag_names: str = ""
    batch_name: str | None = None
    column_map_by_file_json: str | None = None
    merge_archive: bool = False


class IngestDuplicateMatch(BaseModel):
    source_sha256: str
    existing_batch_id: str
    existing_filename: str | None = None
    existing_batch_name: str | None = None
    ingest_ts: str


class IngestPreviewFile(BaseModel):
    inner_name: str
    format: str
    format_confidence: float
    csv_delimiter: str | None = None
    headers: list[str] | None = None
    column_guesses: dict[str, list[dict[str, Any]]] | None = None
    recommended_column_map: dict[str, str] | None = None
    sample_rows: list[dict[str, str]] = Field(default_factory=list)
    size: int
    duplicate_match: IngestDuplicateMatch | None = None


class IngestPreviewResponse(BaseModel):
    upload_id: str
    outer_filename: str
    merge_archive: bool
    file_count: int
    canonical_fields: list[str]
    files: list[IngestPreviewFile]


class IngestQueuedItemResponse(BaseModel):
    batch_id: str
    job_id: str
    inner_name: str
    format: str
    detect_confidence: float | None = None
    duplicate_match: IngestDuplicateMatch | None = None


class IngestQueuedResponse(BaseModel):
    batch_id: str | None = None
    job_id: str | None = None
    items: list[IngestQueuedItemResponse]


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


class StorageFolderContext(BaseModel):
    kind: Literal["none", "ingest_batch", "export_job"] = "none"
    batch_id: str | None = None
    batch_name: str | None = None
    source_filename: str | None = None
    tag_names: list[str] = Field(default_factory=list)
    job_id: str | None = None
    job_type: str | None = None
    job_state: str | None = None
    export_dsl: str | None = None
    export_rows: int | None = None


class StorageBrowseResponse(BaseModel):
    store: StorageStore
    prefix: str
    entries: list[UploadBrowseEntry]
    folder: StorageFolderContext = Field(default_factory=StorageFolderContext)


class StoragePresignResponse(BaseModel):
    url: str
