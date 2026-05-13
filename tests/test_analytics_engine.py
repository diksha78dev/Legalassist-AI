"""Regression tests for analytics engine null-safety and predictive insights."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from analytics_engine import AnalyticsCalculator, PredictiveAnalyticsEngine
from database import Base, CaseRecord, CaseOutcome


def _create_test_case(db, hashed_case_id, case_type, jurisdiction, judge_name, court_name, outcome, summary, appeal_filed, appeal_success, appeal_cost, appeal_days):
    case = CaseRecord(
        hashed_case_id=hashed_case_id,
        case_type=case_type,
        jurisdiction=jurisdiction,
        judge_name=judge_name,
        court_name=court_name,
        outcome=outcome,
        judgment_summary=summary,
    )
    db.add(case)
    db.flush()

    outcome_row = CaseOutcome(
        case_id=case.id,
        appeal_filed=appeal_filed,
        appeal_success=appeal_success,
        appeal_cost=appeal_cost,
        time_to_appeal_verdict=appeal_days,
    )
    db.add(outcome_row)
    db.commit()
    return case


@pytest.fixture()
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = testing_session()
    try:
        yield db
    finally:
        db.close()


class TestAnalyticsCalculator:
    """Test analytics calculations with defensive None handling."""

    def test_calculate_appeal_success_rate_ignores_missing_outcome_data(self):
        """Cases without outcome data should be ignored, not crash the calculation."""
        cases = [
            CaseRecord(
                hashed_case_id="case-none",
                case_type="civil",
                jurisdiction="Delhi",
                outcome="plaintiff_won",
            ),
            CaseRecord(
                hashed_case_id="case-success",
                case_type="civil",
                jurisdiction="Delhi",
                outcome="plaintiff_won",
            ),
            CaseRecord(
                hashed_case_id="case-failure",
                case_type="civil",
                jurisdiction="Delhi",
                outcome="defendant_won",
            ),
        ]

        cases[1].outcome_data = CaseOutcome(
            appeal_filed=True,
            appeal_success=True,
        )
        cases[2].outcome_data = CaseOutcome(
            appeal_filed=True,
            appeal_success=False,
        )

        assert AnalyticsCalculator.calculate_appeal_success_rate(cases) == 50.0


class TestPredictiveAnalyticsEngine:
    def test_build_case_prediction_pack_uses_similar_cases(self, test_db):
        _create_test_case(
            test_db,
            "case-1",
            "civil",
            "Delhi",
            "Judge A",
            "High Court",
            "plaintiff_won",
            "contract interpretation and injunction",
            True,
            True,
            "₹12,000 - ₹18,000",
            120,
        )
        _create_test_case(
            test_db,
            "case-2",
            "civil",
            "Delhi",
            "Judge A",
            "High Court",
            "plaintiff_won",
            "contract interpretation and damages",
            True,
            True,
            "₹10,000 - ₹16,000",
            110,
        )
        _create_test_case(
            test_db,
            "case-3",
            "civil",
            "Delhi",
            "Judge A",
            "High Court",
            "defendant_won",
            "contract interpretation and relief",
            True,
            False,
            "₹15,000 - ₹20,000",
            150,
        )
        _create_test_case(
            test_db,
            "case-4",
            "civil",
            "Delhi",
            "Judge A",
            "High Court",
            "plaintiff_won",
            "contract interpretation and precedent",
            True,
            True,
            "₹11,000 - ₹17,000",
            130,
        )
        _create_test_case(
            test_db,
            "case-5",
            "civil",
            "Delhi",
            "Judge A",
            "High Court",
            "plaintiff_won",
            "contract interpretation and precedent",
            False,
            None,
            None,
            None,
        )

        prediction = PredictiveAnalyticsEngine.build_case_prediction_pack(
            test_db,
            case_type="civil",
            jurisdiction="Delhi",
            court_name="High Court",
            judge_name="Judge A",
            case_summary="contract interpretation and precedent",
        )

        assert prediction["appeal_success"]["predicted_success_rate"] >= 70.0
        assert prediction["timeline"]["estimated_total_days"] > 0
        assert prediction["cost"]["estimated_cost_range"].startswith("₹")
        assert prediction["recommendations"]["recommended_judge"] == "Judge A"
        assert prediction["similar_cases"]
