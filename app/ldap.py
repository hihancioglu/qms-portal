import os
from dataclasses import dataclass

from ldap3 import ALL, Connection, Server
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars


LDAP_PASSWORD_HASH = "ldap:$external"
LDAP_SYNC_ATTRIBUTES = [
    "sAMAccountName",
    "displayName",
    "givenName",
    "sn",
    "mail",
    "department",
]


@dataclass(frozen=True)
class LDAPSettings:
    server: str
    domain: str
    bind_user: str
    bind_password: str
    base_dn: str
    search_filter: str

    @property
    def bind_username(self) -> str:
        if "\\" in self.bind_user or "@" in self.bind_user:
            return self.bind_user
        return f"{self.domain}\\{self.bind_user}" if self.domain else self.bind_user

    def user_login_name(self, username: str) -> str:
        if "\\" in username or "@" in username:
            return username
        return f"{self.domain}\\{username}" if self.domain else username


@dataclass(frozen=True)
class LDAPUser:
    username: str
    full_name: str
    department: str | None = None
    email: str | None = None


def get_ldap_settings() -> LDAPSettings | None:
    required = {
        "server": os.getenv("LDAP_SERVER", "").strip(),
        "domain": os.getenv("LDAP_DOMAIN", "").strip(),
        "bind_user": os.getenv("LDAP_USER", "").strip(),
        "bind_password": os.getenv("LDAP_PASSWORD", ""),
        "base_dn": os.getenv("LDAP_BASE_DN", "").strip(),
    }
    if not all(required.values()):
        return None
    return LDAPSettings(
        **required,
        search_filter=os.getenv(
            "LDAP_SEARCH_FILTER",
            "(&(objectClass=user)(objectCategory=person)"
            "(!(userAccountControl:1.2.840.113556.1.4.803:=2)))",
        ).strip(),
    )


def ldap_enabled() -> bool:
    return get_ldap_settings() is not None


def _server(settings: LDAPSettings) -> Server:
    return Server(settings.server, get_info=ALL)


def _service_connection(settings: LDAPSettings) -> Connection:
    conn = Connection(
        _server(settings),
        user=settings.bind_username,
        password=settings.bind_password,
        auto_bind=True,
    )
    return conn


def _entry_value(entry, attribute: str) -> str | None:
    if attribute not in entry:
        return None
    value = entry[attribute].value
    if value is None:
        return None
    return str(value)


def _entry_to_user(entry) -> LDAPUser | None:
    username = _entry_value(entry, "sAMAccountName")
    if not username:
        return None
    display_name = _entry_value(entry, "displayName")
    if not display_name:
        name_parts = [_entry_value(entry, "givenName"), _entry_value(entry, "sn")]
        display_name = " ".join(part for part in name_parts if part).strip()
    return LDAPUser(
        username=username.lower(),
        full_name=display_name or username,
        department=_entry_value(entry, "department"),
        email=_entry_value(entry, "mail"),
    )


def _user_filter(settings: LDAPSettings, username: str) -> str:
    escaped_username = escape_filter_chars(username.split("\\")[-1].split("@")[0])
    return f"(&{settings.search_filter}(sAMAccountName={escaped_username}))"


def find_ldap_user(username: str, settings: LDAPSettings | None = None) -> LDAPUser | None:
    settings = settings or get_ldap_settings()
    if not settings:
        return None
    try:
        with _service_connection(settings) as conn:
            conn.search(
                search_base=settings.base_dn,
                search_filter=_user_filter(settings, username),
                attributes=LDAP_SYNC_ATTRIBUTES,
                size_limit=1,
            )
            if not conn.entries:
                return None
            return _entry_to_user(conn.entries[0])
    except LDAPException:
        return None


def authenticate_ldap_user(username: str, password: str) -> LDAPUser | None:
    settings = get_ldap_settings()
    if not settings or not password:
        return None
    ldap_user = find_ldap_user(username, settings)
    if not ldap_user:
        return None
    try:
        with Connection(
            _server(settings),
            user=settings.user_login_name(ldap_user.username),
            password=password,
            auto_bind=True,
        ):
            return ldap_user
    except LDAPException:
        return None


def list_ldap_users(limit: int = 1000) -> list[LDAPUser]:
    settings = get_ldap_settings()
    if not settings:
        return []
    try:
        with _service_connection(settings) as conn:
            conn.search(
                search_base=settings.base_dn,
                search_filter=settings.search_filter,
                attributes=LDAP_SYNC_ATTRIBUTES,
                size_limit=limit,
            )
            users = [_entry_to_user(entry) for entry in conn.entries]
    except LDAPException:
        return []
    return sorted((user for user in users if user), key=lambda user: user.username)
