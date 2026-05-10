from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy import func, case as sql_case
from sqlalchemy.orm import Session
from database import CaseRecord, CaseOutcome, CaseAnalytics, UserFeedback
import hashlib
from collections import Counter
import logging

logger = logging.getLogger(__name__)


class CaseSimilarityCalculator:
    """Calculate similarity between cases for matching and analysis"""
    
    @staticmethod
    def case_similarity_score(
        case1: CaseRecord,
        case2: CaseRecord,
        weights: Optional[Dict[str, float]] = None,
    ) -> float:
        """
        Calculate similarity between two cases (0-100).
        """
        if not weights:
            weights = {
                "case_type": 0.3,
                "jurisdiction": 0.2,
                "plaintiff_type": 0.15,
                "defendant_type": 0.15,
                "case_value": 0.2,
            }
        
        score = 0.0
        
        # Case type match (most important)
        if case1.case_type.lower() == case2.case_type.lower():
            score += weights["case_type"]
        
        # Jurisdiction match
        if case1.jurisdiction.lower() == case2.jurisdiction.lower():
            score += weights["jurisdiction"]
        
        # Plaintiff type match
        if case1.plaintiff_type and case2.plaintiff_type:
            if case1.plaintiff_type.lower() == case2.plaintiff_type.lower():
                score += weights["plaintiff_type"]
        
        # Defendant type match
        if case1.defendant_type and case2.defendant_type:
            if case1.defendant_type.lower() == case2.defendant_type.lower():
                score += weights["defendant_type"]
        
        # Case value match
        if case1.case_value and case2.case_value:
            if case1.case_value == case2.case_value:
                score += weights["case_value"]
        
        return score * 100
    
    @staticmethod
    def find_similar_cases(
        db: Session,
        reference_case: CaseRecord,
        min_similarity: float = 50.0,
        limit: int = 50,
    ) -> List[Tuple[CaseRecord, float]]:
        """Find cases similar to reference case using initial DB-side filtering"""
        # Reduce memory load by pre-filtering on common attributes
        query = db.query(CaseRecord).filter(
            CaseRecord.case_id != reference_case.case_id,
            (CaseRecord.case_type == reference_case.case_type) | (CaseRecord.jurisdiction == reference_case.jurisdiction)
        )
        
        # Limit the search space to the most recent/relevant 1000 cases to prevent OOM
        all_cases = query.limit(1000).all()
        
        similarities = []
        for case in all_cases:
            score = CaseSimilarityCalculator.case_similarity_score(reference_case, case)
            if score >= min_similarity:
                similarities.append((case, score))
        
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:limit]


class AnalyticsCalculator:
    """Calculate various analytics metrics using SQL aggregates"""
    
    @staticmethod
    def calculate_judge_win_rate(
        db: Session,
        judge_name: str,
        jurisdiction: str,
        winning_outcome: str = "plaintiff_won",
    ) -> Dict:
        """Calculate judge-specific statistics using aggregates"""
        stats = db.query(
            func.count(CaseRecord.id).label('total'),
            func.sum(sql_case((CaseRecord.outcome.ilike(winning_outcome), 1), else_=0)).label('wins'),
            func.sum(sql_case((CaseOutcome.appeal_filed == True, 1), else_=0)).label('appeals'),
            func.sum(sql_case(((CaseOutcome.appeal_filed == True) & (CaseOutcome.appeal_success == True), 1), else_=0)).label('appeal_wins')
        ).join(CaseOutcome, CaseRecord.id == CaseOutcome.case_id, isouter=True).filter(
            CaseRecord.judge_name == judge_name,
            CaseRecord.jurisdiction == jurisdiction,
        ).first()
        
        total = stats.total or 0
        if total == 0:
            return {
                "judge": judge_name,
                "jurisdiction": jurisdiction,
                "total_cases": 0,
                "win_rate": 0.0,
                "appeal_success_rate": 0.0,
            }
            
        wins = stats.wins or 0
        appeals = stats.appeals or 0
        appeal_wins = stats.appeal_wins or 0
        
        return {
            "judge": judge_name,
            "jurisdiction": jurisdiction,
            "total_cases": total,
            "win_rate": round((wins / total) * 100, 1),
            "appeal_success_rate": round((appeal_wins / appeals * 100), 1) if appeals > 0 else 0.0,
        }
    
    @staticmethod
    def calculate_court_statistics(
        db: Session,
        court_name: str,
        case_type: Optional[str] = None,
    ) -> Dict:
        """Calculate statistics for a specific court using aggregates"""
        query = db.query(
            func.count(CaseRecord.id).label('total'),
            func.sum(sql_case((CaseRecord.outcome.ilike('plaintiff_won'), 1), else_=0)).label('p_wins'),
            func.sum(sql_case((CaseRecord.outcome.ilike('defendant_won'), 1), else_=0)).label('d_wins'),
            func.sum(sql_case((CaseRecord.outcome.ilike('settlement'), 1), else_=0)).label('settlements'),
            func.sum(sql_case((CaseRecord.outcome.ilike('dismissal'), 1), else_=0)).label('dismissals'),
            func.sum(sql_case((CaseOutcome.appeal_filed == True, 1), else_=0)).label('appeals')
        ).join(CaseOutcome, CaseRecord.id == CaseOutcome.case_id, isouter=True).filter(
            CaseRecord.court_name == court_name
        )
        
        if case_type:
            query = query.filter(CaseRecord.case_type == case_type)
            
        stats = query.first()
        total = stats.total or 0
        
        if total == 0:
            return {
                "court": court_name,
                "case_type": case_type,
                "total_cases": 0,
            }
            
        appeals_filed = stats.appeals or 0
        
        return {
            "court": court_name,
            "case_type": case_type,
            "total_cases": total,
            "plaintiff_wins": stats.p_wins or 0,
            "defendant_wins": stats.d_wins or 0,
            "settlements": stats.settlements or 0,
            "dismissals": stats.dismissals or 0,
            "appeals_filed": appeals_filed,
            "appeal_rate": round((appeals_filed / total) * 100, 1),
        }
    
    @staticmethod
    def calculate_jurisdiction_trends(
        db: Session,
        jurisdiction: str,
    ) -> Dict:
        """Get trends for a jurisdiction using grouped aggregates"""
        total = db.query(func.count(CaseRecord.id)).filter(CaseRecord.jurisdiction == jurisdiction).scalar() or 0
        
        if total == 0:
            return {"jurisdiction": jurisdiction, "total_cases": 0}
            
        stats_by_type = db.query(
            CaseRecord.case_type,
            func.count(CaseRecord.id).label('count'),
            func.sum(sql_case((CaseRecord.outcome.ilike('plaintiff_won'), 1), else_=0)).label('wins')
        ).filter(CaseRecord.jurisdiction == jurisdiction).group_by(CaseRecord.case_type).all()
        
        type_stats = {}
        for row in stats_by_type:
            type_stats[row.case_type] = {
                "count": row.count,
                "plaintiff_win_rate": round((row.wins / row.count * 100), 1) if row.count > 0 else 0.0,
            }
            
        return {
            "jurisdiction": jurisdiction,
            "total_cases": total,
            "case_type_stats": type_stats,
        }


    @staticmethod
    def calculate_appeal_success_rate(cases: list) -> float:
        """
        Calculate the appeal success rate from a list of CaseRecord objects.
        Cases without outcome_data or with appeal_filed=False are ignored.
        Returns a percentage (0.0–100.0), or 0.0 if no qualifying cases.
        """
        appeals_filed = 0
        appeals_won = 0
        for case in cases:
            outcome_data = getattr(case, "outcome_data", None)
            if outcome_data is None:
                continue
            if not getattr(outcome_data, "appeal_filed", False):
                continue
            appeals_filed += 1
            if getattr(outcome_data, "appeal_success", False):
                appeals_won += 1
        if appeals_filed == 0:
            return 0.0
        return round((appeals_won / appeals_filed) * 100, 1)


class AppealProbabilityEstimator:
    """Estimate appeal success probability for new cases using aggregates"""
    
    @staticmethod
    def estimate_appeal_success(
        db: Session,
        case_type: str,
        jurisdiction: str,
        court_name: Optional[str] = None,
        judge_name: Optional[str] = None,
        outcome_magnitude: str = "moderate",
        similar_cases_limit: int = 1000,
    ) -> Dict:
        """Estimate appeal success probability using SQL aggregates on a limited dataset"""
        # First, get the IDs of the most recent matching cases up to the limit
        matching_ids_query = db.query(CaseRecord.id).filter(
            CaseRecord.case_type == case_type,
            CaseRecord.jurisdiction == jurisdiction,
        )
        
        if court_name:
            matching_ids_query = matching_ids_query.filter(CaseRecord.court_name == court_name)
        if judge_name:
            matching_ids_query = matching_ids_query.filter(CaseRecord.judge_name == judge_name)
            
        # Apply the workload limit
        subquery = matching_ids_query.order_by(CaseRecord.created_at.desc()).limit(similar_cases_limit).subquery()
        
        # Aggregate over this limited subset
        query = db.query(
            func.count(CaseRecord.id).label('total'),
            func.sum(sql_case(((CaseOutcome.appeal_filed == True) & (CaseOutcome.appeal_success == True), 1), else_=0)).label('appeal_wins'),
            func.sum(sql_case((CaseOutcome.appeal_filed == True, 1), else_=0)).label('appeals')
        ).join(CaseOutcome, CaseRecord.id == CaseOutcome.case_id, isouter=True).filter(
            CaseRecord.id.in_(subquery)
        )
        
        stats = query.first()
        total_similar = stats.total or 0
        
        if total_similar == 0:
            return {
                "estimated_success_rate": None,
                "confidence": "very_low",
                "similar_cases_found": 0,
                "reasoning": f"No similar cases found in {jurisdiction} for {case_type} cases.",
            }
            
        appeals = stats.appeals or 0
        appeal_wins = stats.appeal_wins or 0
        appeal_success_rate = (appeal_wins / appeals * 100) if appeals > 0 else 0.0
        
        # Adjust based on outcome magnitude
        adjustment = {"low": 0.95, "moderate": 1.0, "high": 1.05}.get(outcome_magnitude.lower(), 1.0)
        adjusted_rate = min(100, max(0, appeal_success_rate * adjustment))
        
        # Confidence logic
        if total_similar >= 50: confidence = "high"
        elif total_similar >= 20: confidence = "medium"
        elif total_similar >= 10: confidence = "low"
        else: confidence = "very_low"
        
        reasoning = f"Based on {total_similar} similar {case_type} cases in {jurisdiction}. "
        reasoning += f"Appeal success rate in similar cases: {appeal_success_rate:.1f}%"
        
        return {
            "estimated_success_rate": round(adjusted_rate, 1),
            "confidence": confidence,
            "similar_cases_found": total_similar,
            "appeal_success_rate_from_similar": round(appeal_success_rate, 1),
            "reasoning": reasoning,
        }

    @staticmethod
    def estimate_appeal_cost_and_time(
        db: Session,
        case_type: str,
        jurisdiction: str,
    ) -> Dict:
        """Estimate typical appeal cost and time using aggregates"""
        # Fetch only necessary columns
        res = db.query(
            CaseOutcome.appeal_cost,
            CaseOutcome.time_to_appeal_verdict
        ).join(CaseRecord, CaseRecord.id == CaseOutcome.case_id).filter(
            CaseRecord.case_type == case_type,
            CaseRecord.jurisdiction == jurisdiction,
            CaseOutcome.appeal_filed == True
        ).all()
        
        if not res:
            # Fallback
            default_costs = {"civil": "₹12,000 - ₹25,000", "criminal": "₹5,000 - ₹15,000", "family": "₹8,000 - ₹20,000", "commercial": "₹20,000 - ₹50,000"}
            default_time = {"civil": "12-24 months", "criminal": "12-30 months", "family": "12-24 months", "commercial": "18-36 months"}
            return {
                "avg_cost": default_costs.get(case_type.lower(), "₹10,000 - ₹30,000"),
                "avg_time": default_time.get(case_type.lower(), "12-24 months"),
                "note": "Generic estimates - not based on local data",
            }
            
        costs = []
        times = []
        for row in res:
            if row.appeal_cost:
                import re
                numbers = re.findall(r'\d+', row.appeal_cost)
                if numbers: costs.append(int(numbers[0]))
            if row.time_to_appeal_verdict:
                times.append(row.time_to_appeal_verdict)
                
        avg_cost = sum(costs) / len(costs) if costs else None
        avg_time_days = sum(times) / len(times) if times else None
        
        cost_str = f"₹{int(avg_cost * 0.8):.0f} - ₹{int(avg_cost * 1.2):.0f}" if avg_cost else "Unknown"
        time_str = f"{int(avg_time_days/30 * 0.8)}-{int(avg_time_days/30 * 1.2)} months" if avg_time_days else "12-24 months"
        
        return {"avg_cost": cost_str, "avg_time": time_str, "similar_cases": len(res)}


class AnalyticsAggregator:
    """Generate aggregated analytics for dashboard using SQL aggregates"""
    
    @staticmethod
    def get_dashboard_summary(db: Session) -> Dict:
        """Get overall dashboard summary using aggregates"""
        stats = db.query(
            func.count(CaseRecord.id).label('total'),
            func.sum(sql_case((CaseOutcome.appeal_filed == True, 1), else_=0)).label('appeals'),
            func.sum(sql_case((CaseRecord.outcome.ilike('plaintiff_won'), 1), else_=0)).label('p_wins'),
            func.sum(sql_case((CaseRecord.outcome.ilike('defendant_won'), 1), else_=0)).label('d_wins'),
            func.sum(sql_case((CaseRecord.outcome.ilike('settlement'), 1), else_=0)).label('settlements'),
            func.sum(sql_case((CaseRecord.outcome.ilike('dismissal'), 1), else_=0)).label('dismissals')
        ).join(CaseOutcome, CaseRecord.id == CaseOutcome.case_id, isouter=True).first()
        
        total = stats.total or 0
        appeals = stats.appeals or 0
        
        return {
            "total_cases_processed": total,
            "appeals_filed": appeals,
            "appeal_rate_percent": round((appeals / total * 100), 1) if total > 0 else 0,
            "plaintiff_wins": stats.p_wins or 0,
            "defendant_wins": stats.d_wins or 0,
            "settlements": stats.settlements or 0,
            "dismissals": stats.dismissals or 0,
        }
    
    @staticmethod
    def get_top_judges(db: Session, jurisdiction: str, limit: int = 10) -> List[Dict]:
        """Get top judges by appeal success rate using grouped aggregates"""
        judge_stats = db.query(
            CaseRecord.judge_name,
            func.count(CaseRecord.id).label('total'),
            func.sum(sql_case((CaseRecord.outcome.ilike('plaintiff_won'), 1), else_=0)).label('wins'),
            func.sum(sql_case(((CaseOutcome.appeal_filed == True) & (CaseOutcome.appeal_success == True), 1), else_=0)).label('appeal_wins'),
            func.sum(sql_case((CaseOutcome.appeal_filed == True, 1), else_=0)).label('appeals')
        ).join(CaseOutcome, CaseRecord.id == CaseOutcome.case_id, isouter=True).filter(
            CaseRecord.jurisdiction == jurisdiction,
            CaseRecord.judge_name != None
        ).group_by(CaseRecord.judge_name).having(func.count(CaseRecord.id) >= 5).all()
        
        results = []
        for row in judge_stats:
            results.append({
                "judge": row.judge_name,
                "jurisdiction": jurisdiction,
                "total_cases": row.total,
                "win_rate": round((row.wins / row.total * 100), 1),
                "appeal_success_rate": round((row.appeal_wins / row.appeals * 100), 1) if row.appeals > 0 else 0.0
            })
            
        results.sort(key=lambda x: x["appeal_success_rate"], reverse=True)
        return results[:limit]
    
    @staticmethod
    def get_regional_trends(db: Session) -> List[Dict]:
        """Get trends by jurisdiction using grouped aggregates"""
        trends_stats = db.query(
            CaseRecord.jurisdiction,
            func.count(CaseRecord.id).label('total'),
            func.sum(sql_case(((CaseOutcome.appeal_filed == True) & (CaseOutcome.appeal_success == True), 1), else_=0)).label('appeal_wins'),
            func.sum(sql_case((CaseOutcome.appeal_filed == True, 1), else_=0)).label('appeals')
        ).join(CaseOutcome, CaseRecord.id == CaseOutcome.case_id, isouter=True).filter(
            CaseRecord.jurisdiction != None
        ).group_by(CaseRecord.jurisdiction).all()
        
        results = []
        for row in trends_stats:
            results.append({
                "jurisdiction": row.jurisdiction,
                "total_cases": row.total,
                "appeal_success_rate": round((row.appeal_wins / row.appeals * 100), 1) if row.appeals > 0 else 0.0
            })
            
        results.sort(key=lambda x: x["total_cases"], reverse=True)
        return results


# Utility function to anonymize case ID
def generate_anonymous_case_id(case_data: str) -> str:
    """Generate anonymous case ID from case data"""
    return hashlib.sha256(case_data.encode()).hexdigest()[:16]
