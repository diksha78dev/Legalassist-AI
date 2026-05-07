import sys
import os
from unittest.mock import MagicMock, patch

# Add the project directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from analytics_engine import AnalyticsAggregator, AnalyticsCalculator, AppealProbabilityEstimator

def test_analytics_aggregates():
    print("Testing Analytics Aggregates Optimization...")
    db = MagicMock()
    
    # Mocking a dashboard summary response
    mock_stats = MagicMock()
    mock_stats.total = 100
    mock_stats.appeals = 20
    mock_stats.p_wins = 40
    mock_stats.d_wins = 30
    mock_stats.settlements = 20
    mock_stats.dismissals = 10
    
    db.query().join().first.return_value = mock_stats
    
    summary = AnalyticsAggregator.get_dashboard_summary(db)
    print(f"Dashboard Summary: {summary}")
    assert summary["total_cases_processed"] == 100
    assert summary["appeals_filed"] == 20
    assert summary["appeal_rate_percent"] == 20.0
    
    # Mocking judge stats
    mock_judge_row = MagicMock()
    mock_judge_row.judge_name = "Justice Smith"
    mock_judge_row.total = 10
    mock_judge_row.wins = 5
    mock_judge_row.appeal_wins = 2
    mock_judge_row.appeals = 4
    
    db.query().join().filter().group_by().having().all.return_value = [mock_judge_row]
    
    top_judges = AnalyticsAggregator.get_top_judges(db, "Delhi")
    print(f"Top Judges: {top_judges}")
    assert len(top_judges) == 1
    assert top_judges[0]["judge"] == "Justice Smith"
    assert top_judges[0]["win_rate"] == 50.0
    assert top_judges[0]["appeal_success_rate"] == 50.0

    print("SUCCESS: Analytics engine optimized and verified!")

if __name__ == "__main__":
    test_analytics_aggregates()
