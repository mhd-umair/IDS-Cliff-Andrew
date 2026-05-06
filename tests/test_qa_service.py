from __future__ import annotations

from src.db import default_db_path, get_connection
from src.llm_client import LLMResult
from src.qa_service import QAContext, answer_question


class FakeLLM:
    def generate(self, system_prompt: str, user_prompt: str) -> LLMResult:
        return LLMResult(
            text="Grounded response generated for user question.",
            used_model="fake-model",
            provider="fake-provider",
        )


def test_current_value_question_returns_schema():
    conn = get_connection(default_db_path())
    ctx = QAContext(start_date="2025-01-01", end_date="2025-03-31", overhead_target=350000.0)
    result = answer_question(conn, "What is our dead stock ratio?", ctx, llm_client=FakeLLM())
    assert "answer" in result
    assert "evidence" in result
    assert "period" in result
    assert "confidence" in result
    assert result["period"]["start_date"] == "2025-01-01"


def test_comparison_question_returns_previous_period_evidence():
    conn = get_connection(default_db_path())
    ctx = QAContext(start_date="2025-01-01", end_date="2025-03-31", overhead_target=350000.0)
    result = answer_question(conn, "How did tech efficiency change versus previous period?", ctx, llm_client=FakeLLM())
    assert result["meta"]["intent"] == "period_comparison"
    assert any("comparison_period" in e for e in result["evidence"])


def test_unsupported_question_fallback():
    conn = get_connection(default_db_path())
    ctx = QAContext(start_date="2025-01-01", end_date="2025-03-31", overhead_target=350000.0)
    result = answer_question(conn, "Write a SQL join for every table in this database", ctx, llm_client=FakeLLM())
    assert result["confidence"] == "low"
    assert "supported-intent" in result["assumptions"][0].lower() or "outside supported intent" in result["assumptions"][0].lower()
