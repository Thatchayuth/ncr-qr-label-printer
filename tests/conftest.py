import pytest

from qrlabel.app.defaults import default_asset_profile, default_asset_template
from qrlabel.infrastructure.storage.database import Database


@pytest.fixture
def profile():
    return default_asset_profile()


@pytest.fixture
def template():
    return default_asset_template()


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.sqlite3")
