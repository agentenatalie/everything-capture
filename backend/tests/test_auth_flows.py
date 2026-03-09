import os
import sys
import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth import attach_session_cookie, issue_auth_session, resolve_auth_session  # noqa: E402
from database import Base  # noqa: E402
from models import AppConfig, AuthSession, User  # noqa: E402
from routers.auth import (  # noqa: E402
    _consume_verification_code,
    _create_or_claim_user,
    _providers_payload,
    _store_verification_code,
    logout,
)
from tenant import DEFAULT_USER_EMAIL, DEFAULT_USER_ID, DEFAULT_USER_NAME  # noqa: E402


class AuthFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _insert_default_user(self) -> None:
        with self.Session() as db:
            db.add(
                User(
                    id=DEFAULT_USER_ID,
                    email=DEFAULT_USER_EMAIL,
                    display_name=DEFAULT_USER_NAME,
                    is_default=True,
                )
            )
            db.commit()

    def test_create_or_claim_user_claims_default_local_user(self) -> None:
        self._insert_default_user()
        with self.Session() as db:
            user = _create_or_claim_user(
                db,
                email="alice@example.com",
                display_name="Alice",
            )
            db.commit()

            self.assertEqual(user.id, DEFAULT_USER_ID)
            self.assertFalse(user.is_default)
            self.assertEqual(user.email, "alice@example.com")
            self.assertEqual(user.display_name, "Alice")
            self.assertIsNotNone(user.email_verified_at)
            self.assertIsNotNone(user.last_login_at)

    def test_issue_auth_session_can_be_resolved_from_raw_token(self) -> None:
        with self.Session() as db:
            user = User(email="reader@example.com", display_name="Reader")
            db.add(user)
            db.commit()
            db.refresh(user)

            request = SimpleNamespace(
                headers={"user-agent": "pytest"},
                client=SimpleNamespace(host="127.0.0.1"),
            )
            auth_session, raw_token = issue_auth_session(db, user, "email_code", request)
            db.commit()

            resolved_session, resolved_user = resolve_auth_session(db, raw_token)

            self.assertEqual(resolved_session.id, auth_session.id)
            self.assertEqual(resolved_user.id, user.id)
            self.assertEqual(resolved_session.provider, "email_code")

    def test_newly_created_user_can_issue_session_before_commit(self) -> None:
        with self.Session() as db:
            user = _create_or_claim_user(
                db,
                email="fresh@example.com",
                display_name="Fresh User",
            )
            self.assertIsNotNone(user.id)

            auth_session, raw_token = issue_auth_session(
                db,
                user,
                "email_code",
                SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1")),
            )
            db.commit()

            resolved_session, resolved_user = resolve_auth_session(db, raw_token)
            self.assertEqual(resolved_session.id, auth_session.id)
            self.assertEqual(resolved_user.id, user.id)

    def test_attach_session_cookie_accepts_naive_utc_expiry(self) -> None:
        response = JSONResponse({"status": "ok"})
        with self.Session() as db:
            user = User(email="cookie@example.com", display_name="Cookie User")
            db.add(user)
            db.commit()
            db.refresh(user)

            auth_session, raw_token = issue_auth_session(
                db,
                user,
                "email_code",
                SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1")),
            )

        attach_session_cookie(response, raw_token, auth_session.expires_at)
        self.assertIn("everything_grabber_session=", response.headers.get("set-cookie", ""))

    def test_verification_code_cannot_be_reused_after_consumption(self) -> None:
        with self.Session() as db:
            code = _store_verification_code(
                db,
                channel="email",
                target="reader@example.com",
            )

            _consume_verification_code(
                db,
                channel="email",
                target="reader@example.com",
                code=code,
            )

            with self.assertRaises(HTTPException) as excinfo:
                _consume_verification_code(
                    db,
                    channel="email",
                    target="reader@example.com",
                    code=code,
                )

            self.assertEqual(excinfo.exception.status_code, 400)
            self.assertEqual(excinfo.exception.detail, "No active verification code")

    def test_providers_payload_enables_google_when_app_config_is_saved(self) -> None:
        with self.Session() as db:
            db.add(
                AppConfig(
                    google_oauth_client_id="google-client-id",
                    google_oauth_client_secret="plain-secret",
                )
            )
            db.commit()

            providers = _providers_payload(
                SimpleNamespace(url_for=lambda name: "http://127.0.0.1:8000/api/auth/google/callback"),
                db,
            )

            self.assertTrue(providers.google_enabled)
            self.assertTrue(providers.email_enabled)
            self.assertTrue(providers.phone_enabled)

    def test_logout_revokes_session_even_when_request_session_is_detached(self) -> None:
        with self.Session() as writer_db:
            user = User(email="logout@example.com", display_name="Logout User")
            writer_db.add(user)
            writer_db.commit()
            writer_db.refresh(user)

            auth_session, _ = issue_auth_session(
                writer_db,
                user,
                "google_oauth",
                SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1")),
            )
            writer_db.commit()
            writer_db.refresh(auth_session)
            writer_db.expunge(auth_session)

        request = SimpleNamespace(state=SimpleNamespace(auth_session=auth_session))

        with self.Session() as reader_db:
            response = logout(request, reader_db)
            self.assertEqual(response.status_code, 200)

            session_record = reader_db.query(AuthSession).filter(AuthSession.id == auth_session.id).first()
            self.assertIsNotNone(session_record.revoked_at)


if __name__ == "__main__":
    unittest.main()
