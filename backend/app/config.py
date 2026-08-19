import secrets
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache

logger = logging.getLogger(__name__)


def _auto_jwt_secret() -> str:
    logger.warning("JWT_SECRET not set — auto-generated (sessions invalidate on restart)")
    return secrets.token_hex(32)


class Settings(BaseSettings):
    # Telegram
    telegram_api_id: int
    telegram_api_hash: str
    telegram_bot_token: str

    telegram_helper_bot_tokens_str: str = Field("", alias="TELEGRAM_HELPER_BOT_TOKENS")
    telegram_bot_session_strings_str: str = Field("", alias="TELEGRAM_BOT_SESSION_STRINGS")

    auth_users_str: str = Field("", alias="AUTH_USERS")
    admin_ids_str: str = Field("", alias="ADMIN_IDS")

    @property
    def auth_users(self) -> list[int]:
        v = self.auth_users_str
        if not v:
            return []
        try:
            return [int(u.strip()) for u in v.split(",") if u.strip()]
        except ValueError:
            return []

    @property
    def admin_ids(self) -> set[int]:
        v = self.admin_ids_str
        if not v:
            return set()
        try:
            return {int(u.strip()) for u in v.split(",") if u.strip()}
        except ValueError:
            return set()

    @property
    def telegram_helper_bot_tokens(self) -> list[str]:
        v = self.telegram_helper_bot_tokens_str
        if not v:
            return []
        return [t.strip() for t in v.split(",") if t.strip()]

    @property
    def all_bot_tokens(self) -> list[str]:
        return [self.telegram_bot_token] + self.telegram_helper_bot_tokens

    @property
    def telegram_bot_session_strings(self) -> list[str]:
        v = self.telegram_bot_session_strings_str
        if not v:
            return []
        return [s.strip() for s in v.split(",") if s.strip()]

    telegram_storage_channel_id: int

    # Database — set DATABASE_URL in .env for PostgreSQL (Supabase)
    database_url: str = "sqlite+aiosqlite:///./data/teleplay.db"

    # JWT — set JWT_SECRET for persistent sessions across restarts
    # Generate with: openssl rand -hex 32
    jwt_secret: str = Field(default_factory=_auto_jwt_secret)
    jwt_expiry_minutes: int = 10080

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = Field(24696, alias="SERVER_PORT")

    # Concurrency — gates both the Kurigram get/save-file semaphores and the
    # per-client stream semaphores in streaming.py. 8 = more pipelined chunk
    # fetches per bot; raise further only while "Batch ... timed out" stays absent.
    telegram_client_concurrency: int = 8

    # Timeouts (Telegram-Drive inspired)
    telegram_connect_timeout: int = 30
    telegram_timeout: int = 60

    # Optional MTProto proxy (socks5:// or http://). Empty = direct connection (TOS-compliant on HF Spaces)
    mt_proxy_url: str = Field("", alias="MT_PROXY_URL")

    # Subtitles (internet subtitle search)
    # Comma-separated two-letter/Alpha3 language codes, e.g. "en,ta"
    subtitle_languages_str: str = Field("en", alias="SUBTITLE_LANGUAGES")
    # Comma-separated provider list; keyless-first. OpenSubtitles.com requires
    # OPENSUBTITLES_USERNAME/PASSWORD/API_KEY.
    subtitle_providers_str: str = Field(
        "podnapisi,tvsubtitles,addic7ed", alias="SUBTITLE_PROVIDERS"
    )
    opensubtitles_username: str = Field("", alias="OPENSUBTITLES_USERNAME")
    opensubtitles_password: str = Field("", alias="OPENSUBTITLES_PASSWORD")
    opensubtitles_api_key: str = Field("", alias="OPENSUBTITLES_API_KEY")

    @property
    def subtitle_languages(self) -> list[str]:
        return [c.strip() for c in self.subtitle_languages_str.split(",") if c.strip()]

    @property
    def subtitle_providers(self) -> list[str]:
        return [p.strip() for p in self.subtitle_providers_str.split(",") if p.strip()]

    # Cloudflare API (tunnel/DNS management)
    cloudflare_api_token: str = Field("", alias="CLOUDFLARE_API_TOKEN")

    # Google Drive
    gdrive_client_id: str = ""
    gdrive_client_secret: str = ""
    gdrive_redirect_uri: str = "https://your-domain.com/api/gdrive/auth/callback"

    # Debug
    debug_password: str = ""  # Set via .env: DEBUG_PASSWORD=yourpass

    # Web
    web_base_url: str = "https://REDACTED_DOMAIN"

    # Grab / movie search
    grab_group_username: str = ""  # e.g. "AutoFilterGroup"
    grab_bot_username: str = ""    # e.g. "FileBot"
    grab_session_string: str = ""  # single dedicated Ivy session (legacy)

    # Multi-group search: comma-separated list of groups (GRAB_GROUP_USERNAMES)
    # takes precedence over GRAB_GROUP_USERNAME. GRAB_BOT_USERNAMES maps a bot to
    # each group positionally; an empty entry means auto-detect the replying bot.
    grab_group_usernames_str: str = Field("", alias="GRAB_GROUP_USERNAMES")
    grab_bot_usernames_str: str = Field("", alias="GRAB_BOT_USERNAMES")

    # Comma-separated list of Ivy session strings for the grabber pool.
    # When multiple are configured, N grab operations run concurrently.
    # Falls back to GRAB_SESSION_STRING, then TELEGRAM_BOT_SESSION_STRINGS.
    grab_session_strings_str: str = Field("", alias="GRAB_SESSION_STRINGS")

    @property
    def grab_session_strings(self) -> list[str]:
        v = self.grab_session_strings_str
        if not v:
            return []
        return [s.strip() for s in v.split(",") if s.strip()]

    @property
    def grab_groups(self) -> list[str]:
        v = self.grab_group_usernames_str
        if not v:
            return [self.grab_group_username] if self.grab_group_username else []
        return [g.strip() for g in v.split(",") if g.strip()]

    @property
    def grab_group_bots(self) -> list[str]:
        """Bots positionally parallel to grab_groups ('' = auto-detect the bot)."""
        groups = self.grab_groups
        if not groups:
            return []
        v = self.grab_bot_usernames_str
        if not v:
            return [self.grab_bot_username] * len(groups)
        bots = [b.strip() for b in v.split(",")]
        while len(bots) < len(groups):
            bots.append(self.grab_bot_username)
        return bots[: len(groups)]

    @property
    def grab_group_bot_pairs(self) -> list[tuple[str, str]]:
        return list(zip(self.grab_groups, self.grab_group_bots))

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
