"""Provider adapter contract.

Every external integration implements ProviderAdapter so business logic never depends on a vendor SDK.
Adapters receive decrypted credentials + non-secret config at construction time only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class CredentialField:
    key: str
    label: str
    secret: bool = True
    required: bool = True
    help: str = ""


@dataclass
class ConfigField:
    key: str
    label: str
    type: str = "string"  # string|number|boolean|select|textarea
    default: Any = None
    options: list[str] = field(default_factory=list)
    help: str = ""
    # Show this field only when another field holds one of these values, e.g. {"capability": ["mentions"]}. Lets one
    # provider that does several things ask only for the fields the chosen job needs, instead of one long form in
    # which most of the boxes are irrelevant and nothing says which.
    show_if: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthResult:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class UsageEstimate:
    requests: int = 0
    tokens: int = 0
    unit_type: str = "requests"
    note: str = ""


@dataclass
class Capabilities:
    category: str
    features: list[str] = field(default_factory=list)
    measurement_type: str = "observed"  # first_party | observed | estimated | lab | field
    notes: str = ""


@dataclass
class CollectResult:
    """Raw payload (stored as artifact) + metadata about the request."""
    raw: Any
    meta: dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    """Raised for provider failures (auth, quota, invalid response)."""


class ProviderAdapter:
    key: ClassVar[str] = "base"
    category: ClassVar[str] = "base"
    # Who you buy or get this from. Several adapters share one vendor — one SerpApi key serves six of them — so the
    # Integrations page groups by this and lists each adapter's capabilities underneath, rather than showing the same
    # vendor six times under six category headings where no two rows look related.
    vendor: ClassVar[str] = ""
    vendor_url: ClassVar[str] = ""
    display_name: ClassVar[str] = "Base"
    description: ClassVar[str] = ""
    docs_url: ClassVar[str] = ""
    credential_fields: ClassVar[list[CredentialField]] = []
    config_fields: ClassVar[list[ConfigField]] = []
    # Adapters that need no stored credentials (e.g. bundled crawler, public APIs) can be used without a connection.
    requires_connection: ClassVar[bool] = True

    def __init__(self, credentials: dict[str, Any] | None = None, config: dict[str, Any] | None = None):
        self.credentials = credentials or {}
        self.config = {**{f.key: f.default for f in self.config_fields}, **(config or {})}

    def health_check(self) -> HealthResult:
        raise NotImplementedError

    def collect(self, request: dict[str, Any]) -> CollectResult:
        raise NotImplementedError

    def normalize(self, result: CollectResult) -> Any:
        raise NotImplementedError

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate()

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category=self.category)

    @classmethod
    def category_for_config(cls, config: dict[str, Any] | None = None) -> str:
        """Which category a connection with this config belongs to.

        Fixed for a real vendor, because the API does what it does. Overridden by the providers that are a blank
        slate — a custom JSON endpoint is whatever you point it at — so the connection is filed under the job it
        was configured for and the right collection task finds it.
        """
        return cls.category

    @classmethod
    def declared_features(cls) -> list[str]:
        """What this provider says it can do, read from an un-credentialed instance.

        Construction only merges config defaults and never touches the network, so this is safe to call for any
        provider whether or not it is connected. Tasks use it to pick a provider by capability instead of by
        category — several providers share a category while covering different parts of it.
        """
        try:
            return sorted(cls().get_capabilities().features)
        except Exception:  # noqa: BLE001 — a provider that cannot describe itself must not break the registry
            return []

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {
            "key": cls.key, "category": cls.category, "display_name": cls.display_name,
            "description": cls.description, "docs_url": cls.docs_url, "requires_connection": cls.requires_connection,
            "vendor": cls.vendor or cls.display_name, "vendor_url": cls.vendor_url,
            "features": cls.declared_features(),
            "credential_fields": [f.__dict__ for f in cls.credential_fields],
            "config_fields": [f.__dict__ for f in cls.config_fields],
        }
