"""Database models. Every id is a 36-character UUID string."""

import uuid
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import false as sa_false
from sqlalchemy import true as sa_true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db_config import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Role(str, Enum):
    """Roles in a home, lowest to highest."""

    MEMBER = "member"  # uses devices
    OPERATOR = "operator"  # also adds, edits and removes devices
    ADMIN = "admin"  # everything; the old "owner" role became admin


class Home(Base):
    __tablename__ = "homes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20), default="residential")
    address: Mapped[str | None] = mapped_column(Text)
    # Owner setting: every member must use two-factor login to use this home.
    # Devices page: False (default) shows a group as one tile in its room and
    # hides its devices there; True also lists them and shows groups apart.
    show_grouped_devices: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    require_two_factor: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    memberships: Mapped[list["HomeMembership"]] = relationship(
        back_populates="home", cascade="all, delete-orphan"
    )
    devices: Mapped[list["Device"]] = relationship(
        back_populates="home", cascade="all, delete-orphan"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(512))  # Argon2id
    name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Failed logins in a row, and a lockout's end (app/login_failures.py).
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[str | None] = mapped_column(String(128))  # base32
    is_totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Last accepted TOTP time step; codes from this step or earlier are refused.
    totp_last_step: Mapped[int | None] = mapped_column(Integer)
    # New secret during an authenticator reset, until a code from it is confirmed.
    pending_totp_secret: Mapped[str | None] = mapped_column(String(128))
    # Colour scheme for the web app: "system", "light", "dark", "red" (black
    # and red) or "violet" (purple and black).
    theme: Mapped[str] = mapped_column(
        String(10), default="system", server_default="system"
    )
    # JSON list of Argon2id hashes; a used code is replaced by null.
    recovery_codes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    memberships: Mapped[list["HomeMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class HomeMembership(Base):
    __tablename__ = "home_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    home_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("homes.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # a Role value

    user: Mapped[User] = relationship(back_populates="memberships")
    home: Mapped[Home] = relationship(back_populates="memberships")


class Session(Base):
    """Server-side login session. Logout deletes the row (SEC-03)."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # SHA-256 of the session token; the token itself is never stored.
    hash_token: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_activity: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    ip_address: Mapped[str | None] = mapped_column(String(45))
    # "Keep me logged in": lasts KEEP_LOGGED_IN_SECONDS with no idle timeout.
    keep: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )

    user: Mapped[User] = relationship(back_populates="sessions")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    home_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("homes.id", ondelete="SET NULL")
    )
    ip_address: Mapped[str | None] = mapped_column(String(45))
    details: Mapped[str | None] = mapped_column(Text)  # JSON, secrets redacted
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    home_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("homes.id", ondelete="CASCADE"), index=True
    )
    integration: Mapped[str] = mapped_column(String(50))
    # The integration's own id for the device (Rheem: serial number).
    external_id: Mapped[str | None] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    room: Mapped[str | None] = mapped_column(String(50))
    capabilities: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    state: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    # This device's own safety limits (thermostats, water heaters): they can
    # only narrow the home's limits for the type. None = use the type's.
    min_temperature: Mapped[float | None] = mapped_column(Float)
    max_temperature: Mapped[float | None] = mapped_column(Float)
    # active_history: the old value is loaded when it changes, so verbose
    # logging can tell a real online/offline change (app/verbose.py).
    online: Mapped[bool] = mapped_column(Boolean, default=False, active_history=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    home: Mapped[Home] = relationship(back_populates="devices")


class DeviceSafetyLimits(Base):
    """Per-home temperature limits for one device type. Thermostat and
    water-heater control stays off until an enabled row exists (SEC-42).
    Temperatures are in `unit` ("F" or "C")."""

    __tablename__ = "device_safety_limits"
    __table_args__ = (
        UniqueConstraint("home_id", "device_type", name="uq_safety_limits_home_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    home_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("homes.id", ondelete="CASCADE"), index=True
    )
    device_type: Mapped[str] = mapped_column(String(20))
    unit: Mapped[str] = mapped_column(String(1), default="F", server_default="F")
    min_temperature: Mapped[float | None] = mapped_column(Float)
    max_temperature: Mapped[float | None] = mapped_column(Float)
    # Target given to a new device of this type; within min and max.
    default_target: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class Enrollment(Base):
    """One-time code an owner creates to add a household member. Only the
    SHA-256 of the code is stored; it expires and works once."""

    __tablename__ = "enrollments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    home_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("homes.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # TOTP secret offered by /enroll/start, confirmed by /enroll/finish.
    pending_totp_secret: Mapped[str | None] = mapped_column(String(128))
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HomeIntegration(Base):
    """Whether one integration (device brand) is turned on for a home. A
    missing row means the integration's default (see app/features.py)."""

    __tablename__ = "home_integrations"
    __table_args__ = (
        UniqueConstraint("home_id", "integration", name="uq_home_integration"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    home_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("homes.id", ondelete="CASCADE"), index=True
    )
    integration: Mapped[str] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IntegrationCredential(Base):
    """A home's login for one integration, encrypted with SECRETS_KEY
    (app/vault.py). `label` is the non-secret part shown in the app (email)."""

    __tablename__ = "integration_credentials"
    __table_args__ = (
        UniqueConstraint(
            "home_id", "integration", name="uq_credential_home_integration"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    home_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("homes.id", ondelete="CASCADE"), index=True
    )
    integration: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(255))
    secret: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SystemSettings(Base):
    """Login rules for every account (one row, id 1). Accounts are not tied to
    one home, so these apply across the whole installation."""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    require_email: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=sa_true()
    )
    allow_recovery: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    password_min_length: Mapped[int] = mapped_column(
        Integer, default=12, server_default="12"
    )
    password_upper: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    password_lower: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    password_digit: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    password_special: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    # HTTPS (scripts/serve.py reads these when the server starts). The key is
    # encrypted with the vault (SECRETS_KEY); the certificate is public.
    https_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    tls_certificate: Mapped[str | None] = mapped_column(Text)
    tls_private_key: Mapped[str | None] = mapped_column(Text)
    # Email server for sending recovery codes (optional). The password is
    # encrypted with the vault.
    smtp_host: Mapped[str | None] = mapped_column(String(255))
    smtp_port: Mapped[int] = mapped_column(Integer, default=587, server_default="587")
    smtp_security: Mapped[str] = mapped_column(
        String(10), default="starttls", server_default="starttls"
    )
    smtp_username: Mapped[str | None] = mapped_column(String(255))
    smtp_password: Mapped[str | None] = mapped_column(Text)
    smtp_from: Mapped[str | None] = mapped_column(String(255))
    # How long the login page's choices last (Settings > Admin > Login times).
    # Each: days; 0 = never expires; None = turned off (its checkbox hidden).
    # "Keep me logged in": how long a kept session lasts.
    keep_logged_in_days: Mapped[int | None] = mapped_column(
        Integer, default=30, server_default="30", nullable=True
    )
    # "Remember me": how long the login name stays filled in.
    remember_me_days: Mapped[int | None] = mapped_column(
        Integer, default=365, server_default="365", nullable=True
    )
    # "Remember this device": how long an approved device skips the code.
    remember_device_days: Mapped[int | None] = mapped_column(
        Integer, default=0, server_default="0", nullable=True
    )
    # After repeated failed logins (app/login_failures.py): "none", "lockout"
    # (blocked for a time, or until the password is reset) or "lockdown"
    # (account turned off until an admin turns it on again).
    login_failure_action: Mapped[str] = mapped_column(
        String(10), default="none", server_default="none"
    )
    # Failures in a row before it applies; None (blank) = the rule is off.
    login_failure_limit: Mapped[int | None] = mapped_column(
        Integer, default=10, server_default="10", nullable=True
    )
    # Lockout length in minutes; 0 = until the password is reset; None = off.
    login_lockout_minutes: Mapped[int | None] = mapped_column(
        Integer, default=15, server_default="15", nullable=True
    )
    # Settings > Activity log: also record integration detail (app/verbose.py).
    verbose_logging: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PasswordReset(Base):
    """A one-time code an owner gives a member who forgot their password.
    Only the SHA-256 of the code is stored; it expires and works once."""

    __tablename__ = "password_resets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeviceGroup(Base):
    """Devices controlled together (for example the ceiling lights). Made in
    this app or imported from a Cync room or group; after import it is this
    app's to edit (changes are not sent back to Cync). A deleted imported
    group is kept as `deleted` so the next sync does not bring it back."""

    __tablename__ = "device_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    home_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("homes.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(20), default="app")  # app | cync
    external_id: Mapped[str | None] = mapped_column(String(100))
    room: Mapped[str | None] = mapped_column(String(50))
    device_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Room(Base):
    """A room of a home, so rooms can exist before any device is in them.
    Devices and groups name their room (Device.room, DeviceGroup.room)."""

    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("home_id", "name", name="uq_rooms_home_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    home_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("homes.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))


class TrustedDevice(Base):
    """A browser a user approved at login ("Remember this device"): logging
    in there needs the password but not the two-factor code. The browser
    holds a random token in an HttpOnly cookie; only its SHA-256 is stored.
    It lasts SystemSettings.remember_device_days from created_at (0 =
    forever) and ends when the user or an admin removes it, the password
    changes, the authenticator is reset or the account is turned off."""

    __tablename__ = "trusted_devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))  # "Chrome on Windows"
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RoomLayout(Base):
    """One user's order of the rooms on a home's Devices page (a JSON list
    of room names; THERMOSTATS_ROOM stands for the thermostats' own room).
    Rooms not in the list follow in name order."""

    __tablename__ = "room_layouts"
    __table_args__ = (
        UniqueConstraint("user_id", "home_id", name="uq_room_layout_user_home"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    home_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("homes.id", ondelete="CASCADE"), index=True
    )
    room_order: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


GUEST_ROLE = "guest"  # below member; not in Role, so require_role refuses it


class GuestAccess(Base):
    """What one guest may do in one home (Settings > Admin > Users, the
    guest's Access window). Guests reach devices only through the guest
    routes (app/guest_access.py); every other home route refuses them."""

    __tablename__ = "guest_access"
    __table_args__ = (
        UniqueConstraint("home_id", "user_id", name="uq_guest_access_home_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    home_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("homes.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    light_power: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    light_settings: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    cameras: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    water_heater: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    # Devices they may not use: shown greyed out (True) or hidden (False).
    show_blocked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    thermostat_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
