import os
import unittest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_trend.db")
os.environ.setdefault("READ_API_KEY", "")
os.environ.setdefault("WRITE_API_KEY", "")
os.environ.setdefault("ALLOWED_ORIGINS", "http://127.0.0.1:8899")

from fastapi import HTTPException

import main


class ApiConfigAndAuthTests(unittest.TestCase):
    def test_parse_allowed_origins(self):
        parsed = main.parse_allowed_origins("http://a.test, http://b.test")
        self.assertEqual(parsed, ["http://a.test", "http://b.test"])

    def test_parse_allowed_origins_rejects_mixed_wildcard(self):
        with self.assertRaises(RuntimeError):
            main.parse_allowed_origins("*,http://a.test")

    def test_validate_environment_rejects_invalid_env(self):
        old_env = main.APP_ENV
        try:
            main.APP_ENV = "invalid"
            with self.assertRaises(RuntimeError):
                main.validate_environment()
        finally:
            main.APP_ENV = old_env

    def test_validate_environment_rejects_production_without_keys(self):
        old_env = main.APP_ENV
        old_read_key = main.READ_API_KEY
        old_write_key = main.WRITE_API_KEY
        old_db = main.DATABASE_URL
        old_origins = main.ALLOWED_ORIGINS
        try:
            main.APP_ENV = "production"
            main.READ_API_KEY = ""
            main.WRITE_API_KEY = ""
            main.DATABASE_URL = "postgresql+psycopg2://x:y@localhost:5432/z"
            main.ALLOWED_ORIGINS = ["https://app.example.com"]
            with self.assertRaises(RuntimeError):
                main.validate_environment()
        finally:
            main.APP_ENV = old_env
            main.READ_API_KEY = old_read_key
            main.WRITE_API_KEY = old_write_key
            main.DATABASE_URL = old_db
            main.ALLOWED_ORIGINS = old_origins

    def test_validate_environment_rejects_production_wildcard_cors(self):
        old_env = main.APP_ENV
        old_read_key = main.READ_API_KEY
        old_write_key = main.WRITE_API_KEY
        old_db = main.DATABASE_URL
        old_origins = main.ALLOWED_ORIGINS
        try:
            main.APP_ENV = "production"
            main.READ_API_KEY = "read-key-long-enough"
            main.WRITE_API_KEY = "write-key-long-enough"
            main.DATABASE_URL = "postgresql+psycopg2://x:y@localhost:5432/z"
            main.ALLOWED_ORIGINS = ["*"]
            with self.assertRaises(RuntimeError):
                main.validate_environment()
        finally:
            main.APP_ENV = old_env
            main.READ_API_KEY = old_read_key
            main.WRITE_API_KEY = old_write_key
            main.DATABASE_URL = old_db
            main.ALLOWED_ORIGINS = old_origins

    def test_require_read_api_key_rejects_missing_or_invalid_key(self):
        old_key = main.READ_API_KEY
        try:
            main.READ_API_KEY = "read-test-key"
            with self.assertRaises(HTTPException):
                main.require_read_api_key(None)
            with self.assertRaises(HTTPException):
                main.require_read_api_key("wrong")
            main.require_read_api_key("read-test-key")
        finally:
            main.READ_API_KEY = old_key

    def test_require_write_api_key_rejects_missing_or_invalid_key(self):
        old_key = main.WRITE_API_KEY
        try:
            main.WRITE_API_KEY = "write-test-key"
            with self.assertRaises(HTTPException):
                main.require_write_api_key(None)
            with self.assertRaises(HTTPException):
                main.require_write_api_key("wrong")
            main.require_write_api_key("write-test-key")
        finally:
            main.WRITE_API_KEY = old_key

    def test_routes_protected_in_p15_scope(self):
        read_routes = {
            "/prices/latest",
            "/prices/recent",
            "/summary",
            "/trend/summary",
            "/predict",
            "/signals/recent",
            "/signals/stats",
            "/signals/performance",
            "/reads/multi",
            "/backtest/report",
        }
        write_routes = {"/prices", "/prices/reset"}

        route_deps = {}
        for route in main.app.routes:
            path = getattr(route, "path", None)
            if path in read_routes | write_routes:
                route_deps[path] = {dep.call.__name__ for dep in route.dependant.dependencies if dep.call is not None}

        for path in read_routes:
            self.assertIn("require_read_api_key", route_deps[path])

        for path in write_routes:
            self.assertIn("require_write_api_key", route_deps[path])


if __name__ == "__main__":
    unittest.main()
