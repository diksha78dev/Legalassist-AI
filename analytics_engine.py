from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy import func, case as sql_case
from sqlalchemy.orm import Session, joinedload
from database import CaseRecord, CaseOutcome, CaseAnalytics, UserFeedback, SimilarityFeedback
import hashlib
import hmac
import os
import re
from collections import Counter
import logging

logger = logging.getLogger(__name__)


def _normalize_text(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _token_set(value: Optional[str]) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", _normalize_text(value))
    return {token for token in tokens if len(token) > 2}


def _summary_overlap(reference: Optional[str], candidate: Optional[str]) -> float:
    reference_tokens = _token_set(reference)
    candidate_tokens = _token_set(candidate)
    if not reference_tokens or not candidate_tokens:
        return 0.0
    union = reference_tokens | candidate_tokens
    if not union:
        return 0.0
    return len(reference_tokens & candidate_tokens) / len(union)


def _parse_cost_value(cost_text: Optional[str]) -> Optional[float]:
    if not cost_text:
        return None

    numbers = [int(match.replace(",", "")) for match in re.findall(r"\d[\d,]*", cost_text)]
    if not numbers:
        return None

    return float(sum(numbers) / len(numbers))


def _confidence_from_samples(sample_count: int) -> str:
    if sample_count >= 25:
        return "high"
    if sample_count >= 12:
        return "medium"
    if sample_count >= 5:
        return "low"
    return "very_low"


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

        # Judgment summary overlap helps surface cases with similar reasoning.
        if case1.judgment_summary and case2.judgment_summary:
            summary_overlap = _summary_overlap(case1.judgment_summary, case2.judgment_summary)
            score += weights.get("judgment_summary", 0.0) * summary_overlap
        
        return score * 100
    
    @staticmethod
    def find_similar_cases(
        db: Session,
        reference_case: CaseRecord,
        min_similarity: float = 50.0,
        limit: int = 50,
    ) -> List[Tuple[CaseRecord, float]]:
        """Find cases similar to reference case using initial DB-side filtering.

        Fix: Exclusion filter now correctly references CaseRecord.id (the actual
        primary key column) instead of the non-existent CaseRecord.case_id field.
        Previously, the wrong field reference caused the reference case to remain
        in similarity results, producing self-matching records.
        """
        # Reduce memory load by pre-filtering on common attributes.
        # FIX: Use CaseRecord.id (primary key) — not case_id — to reliably
        # exclude the reference case from results.
        query = db.query(CaseRecord).filter(
            CaseRecord.id != reference_case.id,  # corrected from case_id
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

    @staticmethod
    def get_feedback_adjustment(
        db: Session,
        candidate_case: CaseRecord,
        user_id: Optional[str] = None,
        query_signature: Optional[str] = None,
    ) -> float:
        """Return a small ranking adjustment from historical similarity feedback."""
        query = db.query(SimilarityFeedback).filter(
            SimilarityFeedback.candidate_case_id == candidate_case.id,
        )

        if user_id is not None:
            query = query.filter(SimilarityFeedback.user_id == str(user_id))
        if query_signature is not None:
            query = query.filter(SimilarityFeedback.query_signature == query_signature)

        feedback_rows = query.limit(50).all()
        if not feedback_rows:
            return 0.0

        positive_count = sum(1 for row in feedback_rows if row.relevance)
        negative_count = len(feedback_rows) - positive_count
        raw_delta = (positive_count - negative_count) / max(len(feedback_rows), 1)
        return max(-0.03, min(0.03, raw_delta * 0.03))


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
            func.sum(sql_case((CaseRecord.outcome == winning_outcome, 1), else_=0)).label('wins'),
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
        Calculate the aggregate appeal success rate from a list of CaseRecord objects.
        Cases without outcome_data or with appeal_filed=False are safely ignored.
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


class PredictiveAnalyticsEngine:
    """Generate actionable predictions from historical case data."""

    DEFAULT_APPEAL_WINDOW_DAYS = {
        "civil": 30,
        "criminal": 30,
        "family": 45,
        "commercial": 45,
        "labor": 30,
        "general": 30,
    }

    DEFAULT_COST_RANGE = {
        "civil": (12000, 25000),
        "criminal": (5000, 15000),
        "family": (8000, 20000),
        "commercial": (20000, 50000),
        "labor": (7000, 18000),
        "general": (10000, 30000),
    }

    DEFAULT_TIMELINE_DAYS = {
        "civil": 180,
        "criminal": 120,
        "family": 150,
        "commercial": 240,
        "labor": 120,
        "general": 180,
    }

    @staticmethod
    def _normalized_case_type(case_type: Optional[str]) -> str:
        normalized = _normalize_text(case_type)
        return normalized if normalized else "general"

    @staticmethod
    def _candidate_query(
        db: Session,
        case_type: Optional[str],
        jurisdiction: Optional[str],
        court_name: Optional[str] = None,
        judge_name: Optional[str] = None,
        plaintiff_type: Optional[str] = None,
        defendant_type: Optional[str] = None,
        limit: int = 1000,
    ):
        query = db.query(CaseRecord).options(joinedload(CaseRecord.outcome_data))

        normalized_case_type = _normalize_text(case_type)
        if normalized_case_type and normalized_case_type != "general":
            query = query.filter(func.lower(CaseRecord.case_type) == normalized_case_type)

        if jurisdiction:
            query = query.filter(func.lower(CaseRecord.jurisdiction) == _normalize_text(jurisdiction))
        if court_name:
            query = query.filter(func.lower(CaseRecord.court_name) == _normalize_text(court_name))
        if judge_name:
            query = query.filter(func.lower(CaseRecord.judge_name) == _normalize_text(judge_name))
        if plaintiff_type:
            query = query.filter(func.lower(CaseRecord.plaintiff_type) == _normalize_text(plaintiff_type))
        if defendant_type:
            query = query.filter(func.lower(CaseRecord.defendant_type) == _normalize_text(defendant_type))

        return query.order_by(CaseRecord.created_at.desc()).limit(limit).all()

    @staticmethod
    def _score_case_profile(
        reference_case: CaseRecord,
        candidate_case: CaseRecord,
        case_summary: Optional[str] = None,
    ) -> float:
        base_score = CaseSimilarityCalculator.case_similarity_score(reference_case, candidate_case)
        summary_source = case_summary or reference_case.judgment_summary
        summary_bonus = 0.0
        if summary_source:
            summary_bonus = _summary_overlap(summary_source, candidate_case.judgment_summary) * 15.0
        return min(100.0, base_score + summary_bonus)

    @staticmethod
    def find_similar_cases_for_profile(
        db: Session,
        case_type: str,
        jurisdiction: str,
        court_name: Optional[str] = None,
        judge_name: Optional[str] = None,
        plaintiff_type: Optional[str] = None,
        defendant_type: Optional[str] = None,
        case_value: Optional[str] = None,
        case_summary: Optional[str] = None,
        min_similarity: float = 50.0,
        limit: int = 10,
    ) -> List[Tuple[CaseRecord, float]]:
        """Find similar cases for a user-provided case profile."""
        reference_case = CaseRecord(
            hashed_case_id="prediction-profile",
            case_type=case_type,
            jurisdiction=jurisdiction,
            court_name=court_name,
            judge_name=judge_name,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
            case_value=case_value,
            outcome="pending",
            judgment_summary=case_summary,
        )

        candidates = PredictiveAnalyticsEngine._candidate_query(
            db,
            case_type=case_type,
            jurisdiction=jurisdiction,
            court_name=court_name,
            judge_name=judge_name,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
        )

        scored: List[Tuple[CaseRecord, float]] = []
        for candidate in candidates:
            score = PredictiveAnalyticsEngine._score_case_profile(reference_case, candidate, case_summary)
            if score >= min_similarity:
                scored.append((candidate, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    @staticmethod
    def _scope_metrics(cases: List[CaseRecord]) -> Dict[str, Optional[float]]:
        total_cases = len(cases)
        appealed_cases = 0
        appeal_successes = 0
        plaintiff_wins = 0
        defendant_wins = 0
        cost_values: List[float] = []
        duration_values: List[int] = []

        for case in cases:
            if _normalize_text(case.outcome) == "plaintiff_won":
                plaintiff_wins += 1
            elif _normalize_text(case.outcome) == "defendant_won":
                defendant_wins += 1

            outcome = case.outcome_data
            if not outcome or not outcome.appeal_filed:
                continue

            appealed_cases += 1
            if outcome.appeal_success:
                appeal_successes += 1

            parsed_cost = _parse_cost_value(outcome.appeal_cost)
            if parsed_cost is not None:
                cost_values.append(parsed_cost)
            if outcome.time_to_appeal_verdict:
                duration_values.append(outcome.time_to_appeal_verdict)

        appeal_success_rate = None
        if appealed_cases:
            appeal_success_rate = round((appeal_successes / appealed_cases) * 100, 1)

        plaintiff_win_rate = round((plaintiff_wins / total_cases) * 100, 1) if total_cases else 0.0
        avg_cost = round(sum(cost_values) / len(cost_values), 0) if cost_values else None
        avg_duration = round(sum(duration_values) / len(duration_values), 0) if duration_values else None

        return {
            "total_cases": total_cases,
            "appealed_cases": appealed_cases,
            "appeal_success_rate": appeal_success_rate,
            "plaintiff_win_rate": plaintiff_win_rate,
            "avg_cost": avg_cost,
            "avg_duration": avg_duration,
        }

    @staticmethod
    def _scope_rate(
        db: Session,
        case_type: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        court_name: Optional[str] = None,
        judge_name: Optional[str] = None,
        plaintiff_type: Optional[str] = None,
        defendant_type: Optional[str] = None,
    ) -> Dict[str, Optional[float]]:
        cases = PredictiveAnalyticsEngine._candidate_query(
            db,
            case_type=case_type,
            jurisdiction=jurisdiction,
            court_name=court_name,
            judge_name=judge_name,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
        )
        return PredictiveAnalyticsEngine._scope_metrics(cases)

    @staticmethod
    def predict_appeal_success(
        db: Session,
        case_type: str,
        jurisdiction: str,
        court_name: Optional[str] = None,
        judge_name: Optional[str] = None,
        plaintiff_type: Optional[str] = None,
        defendant_type: Optional[str] = None,
        case_value: Optional[str] = None,
        case_summary: Optional[str] = None,
        similar_cases_limit: int = 10,
    ) -> Dict:
        similar_cases = PredictiveAnalyticsEngine.find_similar_cases_for_profile(
            db,
            case_type=case_type,
            jurisdiction=jurisdiction,
            court_name=court_name,
            judge_name=judge_name,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
            case_value=case_value,
            case_summary=case_summary,
            min_similarity=45.0,
            limit=similar_cases_limit,
        )

        similar_with_appeals = [case for case, _ in similar_cases if case.outcome_data and case.outcome_data.appeal_filed]
        similar_stats = PredictiveAnalyticsEngine._scope_metrics(similar_with_appeals)

        judge_stats = PredictiveAnalyticsEngine._scope_rate(
            db,
            case_type=case_type,
            jurisdiction=jurisdiction,
            court_name=court_name,
            judge_name=judge_name,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
        ) if judge_name else {"total_cases": 0, "appeal_success_rate": None}

        court_stats = PredictiveAnalyticsEngine._scope_rate(
            db,
            case_type=case_type,
            jurisdiction=jurisdiction,
            court_name=court_name,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
        ) if court_name else {"total_cases": 0, "appeal_success_rate": None}

        jurisdiction_stats = PredictiveAnalyticsEngine._scope_rate(
            db,
            case_type=case_type,
            jurisdiction=jurisdiction,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
        )

        global_case_stats = PredictiveAnalyticsEngine._scope_rate(
            db,
            case_type=case_type,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
        )

        components: List[Tuple[float, float, int, str]] = []

        if similar_stats["appeal_success_rate"] is not None:
            components.append((similar_stats["appeal_success_rate"], 0.45, int(similar_stats["appealed_cases"] or 0), "similar_cases"))
        if judge_stats.get("appeal_success_rate") is not None:
            components.append((judge_stats["appeal_success_rate"], 0.2, int(judge_stats.get("appealed_cases") or 0), "judge_history"))
        if court_stats.get("appeal_success_rate") is not None:
            components.append((court_stats["appeal_success_rate"], 0.15, int(court_stats.get("appealed_cases") or 0), "court_history"))
        if jurisdiction_stats.get("appeal_success_rate") is not None:
            components.append((jurisdiction_stats["appeal_success_rate"], 0.12, int(jurisdiction_stats.get("appealed_cases") or 0), "jurisdiction_history"))
        if global_case_stats.get("appeal_success_rate") is not None:
            components.append((global_case_stats["appeal_success_rate"], 0.08, int(global_case_stats.get("appealed_cases") or 0), "case_type_history"))

        if not components:
            predicted_rate = 50.0
            dominant_source = "fallback"
        else:
            weighted_total = 0.0
            weight_sum = 0.0
            dominant_source = components[0][3]

            for rate, weight, sample_count, source_name in components:
                adjusted_weight = weight * min(1.0, max(sample_count, 1) / 15.0)
                weighted_total += rate * adjusted_weight
                weight_sum += adjusted_weight
                if adjusted_weight > 0 and source_name == "similar_cases":
                    dominant_source = source_name

            predicted_rate = round(weighted_total / weight_sum, 1) if weight_sum else 50.0

        sample_count = sum(
            int(scope.get("appealed_cases") or 0)
            for scope in [similar_stats, judge_stats, court_stats, jurisdiction_stats, global_case_stats]
        )

        confidence = _confidence_from_samples(sample_count)

        reasoning_parts = []
        if similar_stats["appealed_cases"]:
            reasoning_parts.append(
                f"Similar cases: {similar_stats['appeal_success_rate']:.1f}% success across {similar_stats['appealed_cases']} appealed cases"
            )
        if judge_stats.get("appealed_cases"):
            reasoning_parts.append(
                f"Judge history: {judge_stats['appeal_success_rate']:.1f}% success across {int(judge_stats['appealed_cases'])} appealed cases"
            )
        if court_stats.get("appealed_cases"):
            reasoning_parts.append(
                f"Court history: {court_stats['appeal_success_rate']:.1f}% success across {int(court_stats['appealed_cases'])} appealed cases"
            )
        if not reasoning_parts:
            reasoning_parts.append("Historical appeal data is sparse, so the estimate falls back to case-type baselines.")

        return {
            "predicted_success_rate": predicted_rate,
            "confidence": confidence,
            "source": dominant_source,
            "sample_count": sample_count,
            "similar_cases_found": len(similar_cases),
            "similar_cases_success_rate": similar_stats["appeal_success_rate"],
            "judge_success_rate": judge_stats.get("appeal_success_rate"),
            "court_success_rate": court_stats.get("appeal_success_rate"),
            "jurisdiction_success_rate": jurisdiction_stats.get("appeal_success_rate"),
            "reasoning": "; ".join(reasoning_parts),
            "similar_cases": [
                {
                    "case_id": case.id,
                    "case_number": case.hashed_case_id,
                    "title": case.judge_name or case.court_name or "Precedent",
                    "jurisdiction": case.jurisdiction,
                    "case_type": case.case_type,
                    "relevance_score": round(score / 100.0, 4),
                    "appeal_filed": bool(case.outcome_data.appeal_filed) if case.outcome_data else False,
                    "appeal_success": case.outcome_data.appeal_success if case.outcome_data else None,
                }
                for case, score in similar_cases
            ],
        }

    @staticmethod
    def estimate_judgment_timeline(
        db: Session,
        case_type: str,
        jurisdiction: str,
        court_name: Optional[str] = None,
        judge_name: Optional[str] = None,
        plaintiff_type: Optional[str] = None,
        defendant_type: Optional[str] = None,
        case_summary: Optional[str] = None,
    ) -> Dict:
        similar_cases = PredictiveAnalyticsEngine.find_similar_cases_for_profile(
            db,
            case_type=case_type,
            jurisdiction=jurisdiction,
            court_name=court_name,
            judge_name=judge_name,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
            case_summary=case_summary,
            min_similarity=40.0,
            limit=20,
        )

        durations = []
        for case, _ in similar_cases:
            outcome = case.outcome_data
            if not outcome or not outcome.appeal_filed:
                continue
            if outcome.time_to_appeal_verdict:
                durations.append(outcome.time_to_appeal_verdict)

        average_duration = round(sum(durations) / len(durations), 0) if durations else None
        if average_duration is None:
            average_duration = float(PredictiveAnalyticsEngine.DEFAULT_TIMELINE_DAYS.get(PredictiveAnalyticsEngine._normalized_case_type(case_type), 180))

        appeal_window_days = PredictiveAnalyticsEngine.DEFAULT_APPEAL_WINDOW_DAYS.get(
            PredictiveAnalyticsEngine._normalized_case_type(case_type),
            30,
        )

        filing_stage = max(7, int(round(average_duration * 0.15)))
        admission_stage = max(10, int(round(average_duration * 0.25)))
        hearing_stage = max(14, int(round(average_duration * 0.35)))
        decision_stage = max(7, int(round(max(average_duration - (filing_stage + admission_stage + hearing_stage), 0))))
        estimated_total_days = filing_stage + admission_stage + hearing_stage + decision_stage

        if estimated_total_days >= appeal_window_days:
            deadline_risk = "high"
        elif estimated_total_days >= appeal_window_days * 0.8:
            deadline_risk = "medium"
        elif estimated_total_days >= appeal_window_days * 0.6:
            deadline_risk = "low"
        else:
            deadline_risk = "very_low"

        return {
            "estimated_total_days": int(estimated_total_days),
            "average_duration_days": int(round(average_duration, 0)),
            "deadline_window_days": appeal_window_days,
            "deadline_risk": deadline_risk,
            "stages": {
                "filing_preparation_days": filing_stage,
                "admission_days": admission_stage,
                "hearing_days": hearing_stage,
                "decision_days": decision_stage,
            },
            "sample_count": len(durations),
            "confidence": _confidence_from_samples(len(durations)),
            "reasoning": (
                f"Estimated from {len(durations)} similar appeal timelines. "
                if durations
                else "No matching duration data found, so this uses case-type baselines."
            ),
        }

    @staticmethod
    def predict_cost(
        db: Session,
        case_type: str,
        jurisdiction: str,
        court_name: Optional[str] = None,
        judge_name: Optional[str] = None,
        plaintiff_type: Optional[str] = None,
        defendant_type: Optional[str] = None,
        case_summary: Optional[str] = None,
    ) -> Dict:
        similar_cases = PredictiveAnalyticsEngine.find_similar_cases_for_profile(
            db,
            case_type=case_type,
            jurisdiction=jurisdiction,
            court_name=court_name,
            judge_name=judge_name,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
            case_summary=case_summary,
            min_similarity=40.0,
            limit=20,
        )

        costs: List[float] = []
        for case, _ in similar_cases:
            outcome = case.outcome_data
            if not outcome or not outcome.appeal_filed:
                continue
            parsed_cost = _parse_cost_value(outcome.appeal_cost)
            if parsed_cost is not None:
                costs.append(parsed_cost)

        if costs:
            average_cost = sum(costs) / len(costs)
            lower = int(round(average_cost * 0.8, 0))
            upper = int(round(average_cost * 1.2, 0))
            source = "historical_cases"
        else:
            default_low, default_high = PredictiveAnalyticsEngine.DEFAULT_COST_RANGE.get(
                PredictiveAnalyticsEngine._normalized_case_type(case_type),
                PredictiveAnalyticsEngine.DEFAULT_COST_RANGE["general"],
            )
            lower = default_low
            upper = default_high
            average_cost = (lower + upper) / 2
            source = "case_type_baseline"

        return {
            "estimated_cost_range": f"₹{lower:,.0f} - ₹{upper:,.0f}",
            "average_cost": int(round(average_cost, 0)),
            "sample_count": len(costs),
            "confidence": _confidence_from_samples(len(costs)),
            "source": source,
            "reasoning": (
                f"Based on {len(costs)} similar appeal cost records."
                if costs
                else "No local cost records were found, so this uses a case-type baseline."
            ),
        }

    @staticmethod
    def recommend_judge_and_court(
        db: Session,
        case_type: str,
        jurisdiction: str,
        limit: int = 5,
    ) -> Dict:
        judge_rows = db.query(
            CaseRecord.judge_name,
            func.count(CaseRecord.id).label("total_cases"),
            func.sum(sql_case((CaseRecord.outcome.ilike("plaintiff_won"), 1), else_=0)).label("plaintiff_wins"),
            func.sum(sql_case(((CaseOutcome.appeal_filed == True) & (CaseOutcome.appeal_success == True), 1), else_=0)).label("appeal_successes"),
            func.sum(sql_case((CaseOutcome.appeal_filed == True, 1), else_=0)).label("appeals"),
        ).join(CaseOutcome, CaseRecord.id == CaseOutcome.case_id, isouter=True).filter(
            func.lower(CaseRecord.case_type) == _normalize_text(case_type),
            func.lower(CaseRecord.jurisdiction) == _normalize_text(jurisdiction),
            CaseRecord.judge_name.isnot(None),
        ).group_by(CaseRecord.judge_name).having(func.count(CaseRecord.id) >= 3).all()

        court_rows = db.query(
            CaseRecord.court_name,
            func.count(CaseRecord.id).label("total_cases"),
            func.sum(sql_case((CaseRecord.outcome.ilike("plaintiff_won"), 1), else_=0)).label("plaintiff_wins"),
            func.sum(sql_case(((CaseOutcome.appeal_filed == True) & (CaseOutcome.appeal_success == True), 1), else_=0)).label("appeal_successes"),
            func.sum(sql_case((CaseOutcome.appeal_filed == True, 1), else_=0)).label("appeals"),
        ).join(CaseOutcome, CaseRecord.id == CaseOutcome.case_id, isouter=True).filter(
            func.lower(CaseRecord.case_type) == _normalize_text(case_type),
            func.lower(CaseRecord.jurisdiction) == _normalize_text(jurisdiction),
            CaseRecord.court_name.isnot(None),
        ).group_by(CaseRecord.court_name).having(func.count(CaseRecord.id) >= 3).all()

        def _build_rankings(rows, label_key: str) -> List[Dict]:
            rankings = []
            for row in rows:
                appeals = row.appeals or 0
                appeal_rate = round((row.appeal_successes / appeals) * 100, 1) if appeals else 0.0
                total_cases = row.total_cases or 0
                win_rate = round((row.plaintiff_wins / total_cases) * 100, 1) if total_cases else 0.0
                rankings.append(
                    {
                        label_key: getattr(row, label_key),
                        "total_cases": total_cases,
                        "win_rate": win_rate,
                        "appeal_success_rate": appeal_rate,
                        "appeals": appeals,
                    }
                )

            rankings.sort(key=lambda item: (item["appeal_success_rate"], item["total_cases"]), reverse=True)
            return rankings[:limit]

        judge_rankings = _build_rankings(judge_rows, "judge_name")
        court_rankings = _build_rankings(court_rows, "court_name")

        return {
            "top_judges": judge_rankings,
            "top_courts": court_rankings,
            "recommended_judge": judge_rankings[0]["judge_name"] if judge_rankings else None,
            "recommended_court": court_rankings[0]["court_name"] if court_rankings else None,
        }

    @staticmethod
    def build_case_prediction_pack(
        db: Session,
        case_type: str,
        jurisdiction: str,
        court_name: Optional[str] = None,
        judge_name: Optional[str] = None,
        plaintiff_type: Optional[str] = None,
        defendant_type: Optional[str] = None,
        case_value: Optional[str] = None,
        case_summary: Optional[str] = None,
    ) -> Dict:
        appeal_success = PredictiveAnalyticsEngine.predict_appeal_success(
            db,
            case_type=case_type,
            jurisdiction=jurisdiction,
            court_name=court_name,
            judge_name=judge_name,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
            case_value=case_value,
            case_summary=case_summary,
        )
        timeline = PredictiveAnalyticsEngine.estimate_judgment_timeline(
            db,
            case_type=case_type,
            jurisdiction=jurisdiction,
            court_name=court_name,
            judge_name=judge_name,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
            case_summary=case_summary,
        )
        cost = PredictiveAnalyticsEngine.predict_cost(
            db,
            case_type=case_type,
            jurisdiction=jurisdiction,
            court_name=court_name,
            judge_name=judge_name,
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
            case_summary=case_summary,
        )
        recommendations = PredictiveAnalyticsEngine.recommend_judge_and_court(
            db,
            case_type=case_type,
            jurisdiction=jurisdiction,
        )

        return {
            "appeal_success": appeal_success,
            "timeline": timeline,
            "cost": cost,
            "recommendations": recommendations,
            "similar_cases": appeal_success["similar_cases"],
        }


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
    """Generate an anonymous case ID from case data using HMAC-SHA256.

    Raw SHA-256 without a secret key is deterministic and vulnerable to
    precomputation and correlation attacks.  HMAC-SHA256 binds the output
    to a server-side secret so identical inputs produce unpredictable
    identifiers across environments.

    The secret is read from the CASE_ANONYMIZATION_SECRET environment
    variable (same source used by case_manager._get_case_anonymization_secret).
    Raises RuntimeError if the secret is not configured, consistent with the
    project-wide policy of failing loudly rather than silently degrading
    anonymization strength.
    """
    secret = os.getenv("CASE_ANONYMIZATION_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "CASE_ANONYMIZATION_SECRET is not configured. "
            "Set this environment variable to a strong random value before "
            "generating anonymous case identifiers."
        )
    return hmac.new(
        secret.encode("utf-8"),
        case_data.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
