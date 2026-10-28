from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TimestampType = DateTime().with_variant(MySQLDateTime(fsp=6), 'mysql')


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Timestamp:
    created_at: Mapped[datetime] = mapped_column(TimestampType, default=now)
    updated_at: Mapped[datetime] = mapped_column(TimestampType, default=now, onupdate=now)


class Knowledge(Timestamp):
    dataset_version: Mapped[str] = mapped_column(String(64), default='demo-v1')


class Source(Knowledge, Base):
    __tablename__ = 'sources'
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(2048))
    local_path: Mapped[str | None] = mapped_column(String(512))
    publisher: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(24))
    language: Mapped[str] = mapped_column(String(16), default='zh-Hans')
    license_note: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default='pending')


class Entity(Knowledge, Base):
    __tablename__ = 'entities'
    entity_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(24), index=True)
    name_zh: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(ForeignKey('sources.source_id'))
    status: Mapped[str] = mapped_column(String(16), default='active')


class Alias(Knowledge, Base):
    __tablename__ = 'entity_aliases'
    __table_args__ = (UniqueConstraint('entity_id', 'normalized_alias', 'language'),)
    alias_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey('entities.entity_id'))
    alias: Mapped[str] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(16))
    normalized_alias: Mapped[str] = mapped_column(String(255), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey('sources.source_id'))


class Attraction(Knowledge, Base):
    __tablename__ = 'attractions'
    entity_id: Mapped[str] = mapped_column(ForeignKey('entities.entity_id'), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    address_zh: Mapped[str] = mapped_column(String(512))
    address_en: Mapped[str | None] = mapped_column(String(512))
    latitude: Mapped[float] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float] = mapped_column(Numeric(10, 6))
    summary: Mapped[str] = mapped_column(Text)
    story: Mapped[str | None] = mapped_column(Text)
    setting: Mapped[str] = mapped_column(String(16), index=True)
    visit_minutes: Mapped[int | None] = mapped_column(Integer)
    ticket_price_min_hkd: Mapped[float | None] = mapped_column(Numeric(10, 2))
    ticket_price_max_hkd: Mapped[float | None] = mapped_column(Numeric(10, 2))
    ticket_note: Mapped[str | None] = mapped_column(Text)
    opening_hours: Mapped[dict | None] = mapped_column(JSON)
    official_url: Mapped[str | None] = mapped_column(String(2048))
    primary_source_id: Mapped[str] = mapped_column(ForeignKey('sources.source_id'))
    field_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Relation(Knowledge, Base):
    __tablename__ = 'relations'
    __table_args__ = (UniqueConstraint('subject_id', 'predicate', 'object_id'),)
    relation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_id: Mapped[str] = mapped_column(ForeignKey('entities.entity_id'), index=True)
    predicate: Mapped[str] = mapped_column(String(32), index=True)
    object_id: Mapped[str] = mapped_column(ForeignKey('entities.entity_id'), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey('sources.source_id'))
    evidence: Mapped[str] = mapped_column(Text)
    distance_m: Mapped[int | None] = mapped_column(Integer)
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    status: Mapped[str] = mapped_column(String(16), default='active')


class Image(Knowledge, Base):
    __tablename__ = 'images'
    image_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attraction_id: Mapped[str] = mapped_column(ForeignKey('attractions.entity_id'))
    asset_path: Mapped[str | None] = mapped_column(String(512))
    remote_url: Mapped[str | None] = mapped_column(String(2048))
    caption: Mapped[str] = mapped_column(String(512))
    source_id: Mapped[str] = mapped_column(ForeignKey('sources.source_id'))
    author: Mapped[str | None] = mapped_column(String(255))
    license_note: Mapped[str] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Document(Knowledge, Base):
    __tablename__ = 'documents'
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attraction_id: Mapped[str | None] = mapped_column(ForeignKey('attractions.entity_id'))
    source_id: Mapped[str] = mapped_column(ForeignKey('sources.source_id'))
    title: Mapped[str] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(16))
    raw_path: Mapped[str | None] = mapped_column(String(512))
    clean_text: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT, 'mysql'))
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default='active')


class Chunk(Knowledge, Base):
    __tablename__ = 'chunks'
    __table_args__ = (UniqueConstraint('document_id', 'splitter_version', 'chunk_index'),)
    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.document_id'))
    attraction_id: Mapped[str | None] = mapped_column(ForeignKey('attractions.entity_id'))
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    locator: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    splitter_version: Mapped[str] = mapped_column(String(64), default='chars-500-overlap-80-v1')


class User(Timestamp, Base):
    __tablename__ = 'users'
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    auth_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(100))
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default='active')


class Conversation(Timestamp, Base):
    __tablename__ = 'sessions'
    session_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.user_id'), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    checkpoint: Mapped[dict | None] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=0)
    active_run_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(24), default='active')


class Message(Timestamp, Base):
    __tablename__ = 'messages'
    message_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey('sessions.session_id'), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT, 'mysql'))
    status: Mapped[str] = mapped_column(String(24))
    citations: Mapped[list] = mapped_column(JSON, default=list)
    memory_processed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Run(Timestamp, Base):
    __tablename__ = 'runs'
    __table_args__ = (UniqueConstraint('session_id', 'request_id'),)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey('sessions.session_id'), index=True)
    request_id: Mapped[str] = mapped_column(String(64))
    input_message_id: Mapped[str] = mapped_column(ForeignKey('messages.message_id'))
    session_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default='queued')
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    index_version: Mapped[str | None] = mapped_column(String(64))
    trace: Mapped[list] = mapped_column(JSON, default=list)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))


class Preference(Timestamp, Base):
    __tablename__ = 'user_preferences'
    __table_args__ = (UniqueConstraint('user_id', 'preference_key'),)
    preference_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.user_id'))
    preference_key: Mapped[str] = mapped_column(String(64))
    value: Mapped[object | None] = mapped_column(JSON)
    source_message_id: Mapped[str | None] = mapped_column(ForeignKey('messages.message_id'))
    origin: Mapped[str] = mapped_column(String(24))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default='active')
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
