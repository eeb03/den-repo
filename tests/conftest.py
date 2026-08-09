"""
Shared test configuration.

WHY THIS EXISTS. Authentication arrived after most of this suite was written.
Those tests exercise conversion, provenance, view resolution, overlays and the
thin client -- none of which is about who is signed in -- and rewriting eighty
of them to register a user first would bury what each one is actually asserting
under login boilerplate.

So by default the auth dependencies are overridden with a fixed test identity
and dataset authorisation is allowed through. That is a deliberate trade with
one condition attached: **authorisation is then not covered by those tests at
all**, and must be covered somewhere. It is, exhaustively, in
`tests/test_auth_and_ownership.py`, including a route-enumerating guard that
fails when a new dataset route appears without protection.

A test that wants the REAL stack -- every one in that file -- marks itself:

    @pytest.mark.real_auth

and gets no overrides. The marker is opt-in rather than opt-out on purpose: a
new security test cannot accidentally inherit a bypass, because it has to ask
for the real thing by name and would fail loudly if it did not.
"""
import pytest

from api.main import app
from auth.dependencies import (
    get_current_user,
    get_optional_user,
    require_dataset_access,
    require_owned_dataset,
)
from database.models import User


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_auth: run against the real authentication stack, with no dependency overrides",
    )


#: Not persisted. Only ever returned by the override below, so nothing in the
#: database depends on it existing.
TEST_USER = User(
    id="00000000-0000-4000-8000-00000000test",
    email="tests@subterra.invalid",
    display_name="test runner",
    is_active=True,
)


@pytest.fixture(autouse=True)
def _default_test_identity(request, monkeypatch):
    """Authenticate every test except those marked `real_auth`."""
    if "real_auth" in request.keywords:
        yield
        return

    # Two routes take their dataset id from the request BODY, so the check runs
    # inside the handler where a dependency override cannot reach it. They call
    # it through the module (`access.dataset_or_404`) precisely so it can be
    # neutralised here for tests that are not about authorisation.
    from auth import dependencies as access

    monkeypatch.setattr(access, "dataset_or_404", lambda db, user, dataset_id: None)

    overrides = {
        get_current_user: lambda: TEST_USER,
        get_optional_user: lambda: TEST_USER,
        # Dataset authorisation is allowed through: these tests seed rows
        # directly and are not about ownership. The handlers ignore the
        # returned value -- it is bound to `_dataset` purely to run the check.
        require_dataset_access: lambda: None,
        require_owned_dataset: lambda: None,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield
    finally:
        for key in overrides:
            app.dependency_overrides.pop(key, None)
