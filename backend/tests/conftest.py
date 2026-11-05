import os

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-0123456789abcdef0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://growos:growos@localhost:5432/growos_test")
os.environ.setdefault("ARTIFACTS_DIR", "/tmp/growos-test-artifacts")
