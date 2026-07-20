"""Tests for the connection module."""
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

from dpp_webhook.connection import (
    ConnectionConfig,
    ConnectionResult,
    DppConnectionError,
    OAuthConfig,
    extract_connection_id_from_url,
    update_dotenv_file,
    generate_connection_name,
)


class TestConnectionConfig(unittest.TestCase):
    """Test ConnectionConfig dataclass."""
    
    def test_connection_config_creation(self):
        config = ConnectionConfig(
            product_id="01KQYD3G8PB93P4BRD4GFDWXC5",
            name="Test Connection",
            description="Test description",
            provider_type_id="01KS593JNR3AG9ECWFV7Q0K8HH",
            unit_identifier_field_id="01KQWAPJFEVGK2F5SMDD3S1PGS",
        )
        self.assertEqual(config.product_id, "01KQYD3G8PB93P4BRD4GFDWXC5")
        self.assertEqual(config.name, "Test Connection")


class TestConnectionResult(unittest.TestCase):
    """Test ConnectionResult dataclass and properties."""
    
    def test_webhook_url_property(self):
        result = ConnectionResult(
            id="01KV62G32NV20A9XK9R2ZJ9J0T",
            webhook_secret="test-secret",
            endpoint_url="/api/webhooks/dpps/01KV62G32NV20A9XK9R2ZJ9J0T",
            unit_identifier_path="data.identifierAndProductData.fields.uniqueBatteryIdentifier",
            name="Test Connection",
            base_url="https://cleantron-api.digiprodpass.com/api",
        )
        self.assertEqual(
            result.webhook_url,
            "https://cleantron-api.digiprodpass.com/api/webhooks/dpps/01KV62G32NV20A9XK9R2ZJ9J0T",
        )
    
    def test_activate_url_property(self):
        result = ConnectionResult(
            id="01KV62G32NV20A9XK9R2ZJ9J0T",
            webhook_secret="test-secret",
            endpoint_url="/api/webhooks/dpps/01KV62G32NV20A9XK9R2ZJ9J0T",
            unit_identifier_path="data.identifierAndProductData.fields.uniqueBatteryIdentifier",
            name="Test Connection",
            base_url="https://cleantron-api.digiprodpass.com/api",
        )
        self.assertEqual(
            result.activate_url,
            "https://cleantron-api.digiprodpass.com/api/webhooks/dpps/01KV62G32NV20A9XK9R2ZJ9J0T/activate",
        )


class TestOAuthConfig(unittest.TestCase):
    """Test OAuthConfig dataclass."""
    
    def test_oauth_config_creation(self):
        config = OAuthConfig(
            sso_url="https://cleantron-sso.digiprodpass.com",
            realm="01KP7KHVPH6NSYC8ZDE6REEX8N",
            client_id="client.frontend",
            client_secret="test-secret",
            username="test@example.com",
            password="test-password",
        )
        self.assertEqual(config.sso_url, "https://cleantron-sso.digiprodpass.com")
        self.assertEqual(config.realm, "01KP7KHVPH6NSYC8ZDE6REEX8N")


class TestUpdateDotenvFile(unittest.TestCase):
    """Test .env file update logic."""
    
    def test_update_existing_keys(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("EXISTING_KEY=old_value\n")
            f.write("OTHER_KEY=other_value\n")
            env_path = Path(f.name)
        
        try:
            updates = {"EXISTING_KEY": "new_value"}
            updated = update_dotenv_file(env_path, updates)
            
            self.assertEqual(updated, ["EXISTING_KEY"])
            
            content = env_path.read_text()
            self.assertIn("EXISTING_KEY=new_value", content)
            self.assertIn("OTHER_KEY=other_value", content)
        finally:
            env_path.unlink()
    
    def test_add_new_keys(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("EXISTING_KEY=value\n")
            env_path = Path(f.name)
        
        try:
            updates = {"NEW_KEY": "new_value"}
            updated = update_dotenv_file(env_path, updates)
            
            self.assertEqual(updated, ["NEW_KEY"])
            
            content = env_path.read_text()
            self.assertIn("EXISTING_KEY=value", content)
            self.assertIn("NEW_KEY=new_value", content)
        finally:
            env_path.unlink()
    
    def test_preserves_comments(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("# This is a comment\n")
            f.write("EXISTING_KEY=value\n")
            env_path = Path(f.name)
        
        try:
            updates = {"NEW_KEY": "new_value"}
            update_dotenv_file(env_path, updates)
            
            content = env_path.read_text()
            self.assertIn("# This is a comment", content)
        finally:
            env_path.unlink()
    
    @patch.dict(os.environ, {"EXISTING_KEY": "shell_value"})
    def test_does_not_override_shell_env(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("EXISTING_KEY=old_value\n")
            env_path = Path(f.name)
        
        try:
            updates = {"EXISTING_KEY": "new_value"}
            updated = update_dotenv_file(env_path, updates)
            
            # Should not update because it's set in shell
            self.assertEqual(updated, [])
            
            content = env_path.read_text()
            self.assertIn("EXISTING_KEY=old_value", content)
        finally:
            env_path.unlink()


class TestGenerateConnectionName(unittest.TestCase):
    """Test connection name generation."""
    
    def test_generates_name_with_timestamp(self):
        name = generate_connection_name()
        self.assertTrue(name.startswith("DPP Webhook - "))
        self.assertIn("T", name)  # ISO format timestamp
        self.assertIn("Z", name)  # UTC timezone


class TestExtractConnectionId(unittest.TestCase):
    """Test connection ID extraction from URLs."""
    
    def test_extracts_id_from_url(self):
        url = "https://cleantron-api.digiprodpass.com/api/webhooks/dpps/01KV62G32NV20A9XK9R2ZJ9J0T"
        self.assertEqual(
            extract_connection_id_from_url(url),
            "01KV62G32NV20A9XK9R2ZJ9J0T",
        )
    
    def test_handles_trailing_slash(self):
        url = "https://cleantron-api.digiprodpass.com/api/webhooks/dpps/01KV62G32NV20A9XK9R2ZJ9J0T/"
        self.assertEqual(
            extract_connection_id_from_url(url),
            "01KV62G32NV20A9XK9R2ZJ9J0T",
        )
    
    def test_returns_empty_for_empty_url(self):
        self.assertEqual(extract_connection_id_from_url(""), "")
    
    def test_returns_last_segment_for_single_path(self):
        self.assertEqual(extract_connection_id_from_url("ABC123"), "ABC123")


if __name__ == "__main__":
    unittest.main()
