"""The Google OAuth callback must stay reachable without a session: Google redirects the browser there.

This broke once when router-level authentication was introduced, so it is pinned by a test.
"""
from app.api.router import api_router

CALLBACK = "/api/integrations/google/oauth/callback"


def _dependency_names(path: str) -> list[set[str]]:
    """Dependency names for every route registered at this path (one entry per HTTP method)."""
    return [{getattr(d.call, "__name__", "") for d in r.dependant.dependencies}
            for r in api_router.routes if getattr(r, "path", None) == path]


def test_callback_is_public():
    deps = _dependency_names(CALLBACK)
    assert deps, "the OAuth callback route is missing"
    for names in deps:
        assert "get_principal" not in names, "the callback must not require a signed-in session"


def test_protected_integration_routes_still_require_auth():
    for path in ("/api/integrations/connections", "/api/integrations/google/connect", "/api/integrations/providers"):
        deps = _dependency_names(path)
        assert deps, f"{path} is missing"
        for names in deps:
            assert "get_principal" in names, f"{path} must require authentication"


def test_health_and_login_stay_public():
    for path in ("/api/health", "/api/auth/login"):
        for names in _dependency_names(path):
            assert "get_principal" not in names
