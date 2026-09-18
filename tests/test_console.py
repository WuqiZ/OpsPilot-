"""Console endpoints are read-only on page load; these tests never call an LLM."""

import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from api import main
from core.skill_loader import SkillManager
from rag.knowledge_base import KnowledgeBase


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        # No context manager: skip the production lifespan and external services.
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()

    def test_console_assets_do_not_shadow_api_routes(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('lang="zh-CN"', response.text)
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)
        self.assertEqual(self.client.get("/assets/styles.css").status_code, 200)
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)
        self.assertEqual(self.client.get("/assets/%2E%2E/.env").status_code, 404)

    def test_saved_report_is_read_without_running_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = pathlib.Path(directory) / "report.json"
            with patch.dict(os.environ, {"EVAL_BASELINE_PATH": str(report_path)}):
                self.assertEqual(self.client.get("/eval/latest").status_code, 404)
                report = {"total": 1, "passed": 0, "results": [{"test_id": "failed_0", "passed": False}]}
                report_path.write_text(json.dumps(report), encoding="utf-8")
                self.assertEqual(self.client.get("/eval/latest").json(), report)
                report_path.write_text("not json", encoding="utf-8")
                self.assertEqual(self.client.get("/eval/latest").status_code, 503)

    def test_skills_are_looked_up_by_registered_name(self):
        manager = SkillManager(str(pathlib.Path(__file__).parents[1] / "skills"))
        manager.load()
        with patch.object(main, "_skills", manager):
            name = manager.skills[0].name
            response = self.client.get(f"/skills/{name}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["content"], manager.skills[0].content)
            self.assertEqual(self.client.get("/skills/not-registered").status_code, 404)

    def test_document_listing_validates_and_preserves_source(self):
        kb = KnowledgeBase.__new__(KnowledgeBase)
        knowledge, incident = Mock(), Mock()
        knowledge.get.return_value = {
            "ids": ["k1"], "documents": ["knowledge body"],
            "metadatas": [{"title": "Knowledge", "chunk": 0}],
        }
        incident.get.return_value = {
            "ids": ["i1"], "documents": ["incident body"], "metadatas": [{"title": "Incident"}],
        }
        kb._collections = {"knowledge": knowledge, "incident": incident}
        result = kb.list_documents(limit=2)
        self.assertEqual([item["source"] for item in result], ["knowledge", "incident"])
        incident.get.assert_called_with(limit=1, include=["documents", "metadatas"])
        incident.reset_mock()
        self.assertEqual(len(kb.list_documents(limit=1)), 1)
        incident.get.assert_not_called()
        with patch.object(main, "_knowledge_base", Mock()):
            self.assertEqual(self.client.get("/knowledge/documents?source=wrong").status_code, 422)
            self.assertEqual(self.client.get("/knowledge/documents?limit=201").status_code, 422)


if __name__ == "__main__":
    unittest.main()
