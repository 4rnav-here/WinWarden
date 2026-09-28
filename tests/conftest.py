import pytest
from optimizer import journal


@pytest.fixture
def tmp_journal(tmp_path):
    """Isolated SQLite journal for each test that requests it."""
    journal.init(tmp_path / "journal.db")
    yield
    journal.init()  # reset to default path; close connection
