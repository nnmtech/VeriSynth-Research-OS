"""Test configuration and fixtures."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """Test client fixture."""
    return TestClient(app)
