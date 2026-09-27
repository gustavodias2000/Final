"""Fluxos HTTP críticos: autenticação, isolamento por tenant e revisão."""

import unittest
from uuid import UUID, uuid4
from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from openpyxl import Workbook

from app.api.dependencies import get_db
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
