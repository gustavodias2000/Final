"""Fluxos HTTP críticos: autenticação, isolamento por tenant e revisão."""

import unittest
from datetime import datetime, timezone
from uuid import UUID, uuid4
from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from openpyxl import Workbook

from app.api.dependencies import get_db
from app.core.login_throttle import login_throttle
from app.core.security import hash_password
from app.db.models import Audit, AuditItem, Tenant, User
from app.db.session import Base
from app.main import app


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        login_throttle.clear()
        self.addCleanup(login_throttle.clear)
        self.client = TestClient(app)
        self.addCleanup(self._cleanup)
        self._seed_data()

    def _cleanup(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _seed_data(self) -> None:
        db = self.Session()
        try:
            self.tenant_a = Tenant(id=uuid4(), nome="Empresa A")
            self.tenant_b = Tenant(id=uuid4(), nome="Empresa B")
            self.user_a = User(
                id=uuid4(),
                tenant_id=self.tenant_a.id,
                username="auditor-a",
                password_hash=hash_password("senha-segura"),
            )
            self.user_b = User(
                id=uuid4(),
                tenant_id=self.tenant_b.id,
                username="auditor-b",
                password_hash=hash_password("senha-segura"),
            )
            self.audit_a = Audit(
                id=uuid4(),
                tenant_id=self.tenant_a.id,
                source_filename="cadastro.xlsx",
                source_file_sha256="a" * 64,
                source_file_size_bytes=128,
                status="completed",
                total_produtos=1,
                processados=1,
                errors=[],
            )
            self.item_a = AuditItem(
                id=uuid4(),
                audit_id=self.audit_a.id,
                codigo_produto="SKU-1",
                descricao="Produto de teste",
                ncm_atual="00000000",
                ncm_sugerido="01012100",
                cest_atual=None,
                cest_sugerido=None,
                score=92.0,
                status="suggested",
                motivo="Correspondência de referência.",
                fonte_referencia="https://example.test/ncm",
                versao_referencia="test-v1",
            )
            db.add_all([self.tenant_a, self.tenant_b, self.user_a, self.user_b, self.audit_a, self.item_a])
            db.commit()
        finally:
            db.close()

    def _token_for(self, username: str) -> str:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "senha-segura"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["access_token"]

    def _headers_for(self, username: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token_for(username)}"}

    def test_database_health_check_queries_the_database(self) -> None:
        response = self.client.get("/health/db")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})

    def test_database_health_check_reports_unreachable_database(self) -> None:
        class BrokenSession:
            def execute(self, *_args, **_kwargs):
                raise OperationalError("SELECT 1", {}, Exception("banco pausado"))

        app.dependency_overrides[get_db] = lambda: BrokenSession()

        response = self.client.get("/health/db")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["database"], "unreachable")

    def test_login_is_blocked_after_repeated_failures_even_with_the_right_password(self) -> None:
        for _ in range(5):
            response = self.client.post("/api/v1/auth/login", json={"username": "auditor-a", "password": "errada"})
            self.assertEqual(response.status_code, 401)

        blocked = self.client.post("/api/v1/auth/login", json={"username": "Auditor-A ", "password": "senha-segura"})
        other_user = self.client.post("/api/v1/auth/login", json={"username": "auditor-b", "password": "senha-segura"})

        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Muitas tentativas", blocked.json()["detail"])
        self.assertGreater(int(blocked.headers["Retry-After"]), 0)
        self.assertEqual(other_user.status_code, 200)

    def test_successful_login_resets_the_failure_count(self) -> None:
        for _ in range(4):
            self.client.post("/api/v1/auth/login", json={"username": "auditor-a", "password": "errada"})
        self._token_for("auditor-a")
        for _ in range(4):
            response = self.client.post("/api/v1/auth/login", json={"username": "auditor-a", "password": "errada"})

        self.assertEqual(response.status_code, 401)

    def test_large_responses_are_compressed(self) -> None:
        response = self.client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("content-encoding"), "gzip")

    def test_audit_history_lists_tenant_audits_newest_first_with_decision_counts(self) -> None:
        db = self.Session()
        try:
            older = Audit(
                id=uuid4(), tenant_id=self.tenant_a.id, source_filename="antiga.xlsx", source_file_sha256="b" * 64,
                source_file_size_bytes=64, status="completed", total_produtos=2, processados=2, errors=[],
                created_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
            )
            other_tenant = Audit(
                id=uuid4(), tenant_id=self.tenant_b.id, source_filename="outra-empresa.xlsx", source_file_sha256="c" * 64,
                source_file_size_bytes=64, status="completed", total_produtos=1, processados=1, errors=[],
            )
            db.query(Audit).filter(Audit.id == self.audit_a.id).update({Audit.created_at: datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)})
            base = dict(audit_id=older.id, descricao="Item", score=90.0, motivo="Teste.")
            db.add_all([
                older,
                other_tenant,
                AuditItem(id=uuid4(), codigo_produto="A1", status="approved", **base),
                AuditItem(id=uuid4(), codigo_produto="A2", status="rejected", **base),
            ])
            db.commit()
        finally:
            db.close()

        response = self.client.get("/api/v1/audits", headers=self._headers_for("auditor-a"))
        limited = self.client.get("/api/v1/audits?limit=1", headers=self._headers_for("auditor-a"))
        unauthenticated = self.client.get("/api/v1/audits")

        self.assertEqual(response.status_code, 200)
        history = response.json()
        self.assertEqual([entry["arquivo"] for entry in history], ["cadastro.xlsx", "antiga.xlsx"])
        self.assertEqual(history[0]["pendentes"], 1)
        self.assertEqual((history[1]["aprovados"], history[1]["rejeitados"], history[1]["pendentes"]), (1, 1, 0))
        self.assertNotIn("data", history[0])
        self.assertEqual(len(limited.json()), 1)
        self.assertEqual(unauthenticated.status_code, 401)

    def test_login_rejects_invalid_credentials(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "auditor-a", "password": "incorreta"},
        )

        self.assertEqual(response.status_code, 401)

    def test_audit_contract_requires_authentication_and_includes_item_id(self) -> None:
        unauthenticated = self.client.get(f"/api/v1/audits/{self.audit_a.id}")
        response = self.client.get(
            f"/api/v1/audits/{self.audit_a.id}",
            headers=self._headers_for("auditor-a"),
        )

        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["data"][0]["id"], str(self.item_a.id))
        self.assertEqual(payload["data"][0]["status"], "suggested")

    def test_tenant_cannot_read_or_review_another_tenants_audit(self) -> None:
        headers = self._headers_for("auditor-b")
        read_response = self.client.get(f"/api/v1/audits/{self.audit_a.id}", headers=headers)
        review_response = self.client.post(
            f"/api/v1/audits/{self.audit_a.id}/items/{self.item_a.id}/review",
            headers=headers,
            json={"decision": "approved"},
        )

        self.assertEqual(read_response.status_code, 404)
        self.assertEqual(review_response.status_code, 404)

    def test_latest_audit_is_limited_to_the_authenticated_tenant(self) -> None:
        own_response = self.client.get("/api/v1/audits/latest", headers=self._headers_for("auditor-a"))
        other_response = self.client.get("/api/v1/audits/latest", headers=self._headers_for("auditor-b"))

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(own_response.json()["audit_id"], str(self.audit_a.id))
        self.assertEqual(other_response.status_code, 404)

    def _set_cest_candidates(self) -> str:
        db = self.Session()
        try:
            item = db.get(AuditItem, self.item_a.id)
            item.status = "pending_review"
            item.cest_status = "catalog_multiple"
            item.cest_candidates = [
                {"cest": "20.063.00", "descricao": "Opção A", "score": 40.0},
                {"cest": "28.033.00", "descricao": "Opção B", "score": 35.0},
            ]
            db.commit()
        finally:
            db.close()
        return f"/api/v1/audits/{self.audit_a.id}/items/{self.item_a.id}/review"

    def test_approval_records_the_chosen_cest_among_eligible_options(self) -> None:
        endpoint = self._set_cest_candidates()
        headers = self._headers_for("auditor-a")

        listed = self.client.get(f"/api/v1/audits/{self.audit_a.id}", headers=headers).json()["data"][0]
        approved = self.client.post(
            endpoint, headers=headers, json={"decision": "approved", "cest_escolhido": "28.033.00"}
        )

        self.assertEqual([option["cest"] for option in listed["cest_candidates"]], ["20.063.00", "28.033.00"])
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(approved.json()["cest_escolhido"], "28.033.00")
        db = self.Session()
        try:
            self.assertEqual(db.get(AuditItem, self.item_a.id).cest_escolhido, "28.033.00")
        finally:
            db.close()

    def test_review_rejects_a_cest_outside_the_options_or_with_rejection(self) -> None:
        endpoint = self._set_cest_candidates()
        headers = self._headers_for("auditor-a")

        outside = self.client.post(
            endpoint, headers=headers, json={"decision": "approved", "cest_escolhido": "01.001.00"}
        )
        with_rejection = self.client.post(
            endpoint, headers=headers, json={"decision": "rejected", "cest_escolhido": "20.063.00"}
        )

        self.assertEqual(outside.status_code, 422)
        self.assertEqual(with_rejection.status_code, 422)
        db = self.Session()
        try:
            item = db.get(AuditItem, self.item_a.id)
            self.assertEqual(item.status, "pending_review")
            self.assertIsNone(item.cest_escolhido)
        finally:
            db.close()

    def test_review_is_persisted_and_cannot_be_repeated(self) -> None:
        headers = self._headers_for("auditor-a")
        endpoint = f"/api/v1/audits/{self.audit_a.id}/items/{self.item_a.id}/review"

        approved = self.client.post(endpoint, headers=headers, json={"decision": "approved"})
        repeated = self.client.post(endpoint, headers=headers, json={"decision": "rejected"})

        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(repeated.status_code, 409)

        db = self.Session()
        try:
            item = db.get(AuditItem, self.item_a.id)
            self.assertEqual(item.status, "approved")
            self.assertEqual(item.reviewed_by_user_id, self.user_a.id)
            self.assertIsNotNone(item.reviewed_at)
        finally:
            db.close()

    def test_upload_rejects_an_unsupported_extension_before_creating_an_audit(self) -> None:
        response = self.client.post(
            "/api/v1/audits/upload",
            headers=self._headers_for("auditor-a"),
            files={"file": ("cadastro.csv", b"codigo_produto,descricao", "text/csv")},
        )

        self.assertEqual(response.status_code, 415)
        db = self.Session()
        try:
            self.assertEqual(db.query(Audit).count(), 1)
        finally:
            db.close()

    def test_upload_persists_normalized_input_for_the_separate_worker(self) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["codigo_produto", "descricao", "ncm_atual", "cest_atual"])
        worksheet.append(["SKU-2", "Produto para worker", "", ""])
        content = BytesIO()
        workbook.save(content)

        response = self.client.post(
            "/api/v1/audits/upload",
            headers=self._headers_for("auditor-a"),
            files={
                "file": (
                    "cadastro.xlsx",
                    content.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["status"], "processing")
        db = self.Session()
        try:
            persisted_audit = db.get(Audit, UUID(payload["audit_id"]))
            self.assertEqual(persisted_audit.total_produtos, 1)
            self.assertEqual(len(persisted_audit.input_items), 1)
            self.assertEqual(persisted_audit.input_items[0].codigo_produto, "SKU-2")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
