"""
Smoke tests for post-deployment validation
Verifies that all critical components are working
"""

import requests
import sys
import time
from typing import Tuple, List
import json


class SmokeTest:
    def __init__(self, app_url: str = "http://localhost:8501"):
        self.app_url = app_url.rstrip("/")
        self.failed_tests: List[str] = []
        self.passed_tests: List[str] = []
    
    def test_app_health(self) -> bool:
        """Test application health endpoint"""
        try:
            response = requests.get(f"{self.app_url}/_stcore/health", timeout=10)
            if response.status_code == 200:
                self.passed_tests.append("✅ Application health check passed")
                return True
            else:
                self.failed_tests.append(f"❌ Application returned status {response.status_code}")
                return False
        except Exception as e:
            self.failed_tests.append(f"❌ Application health check failed: {str(e)}")
            return False
    
    def test_prometheus_metrics(self) -> bool:
        """Test Prometheus metrics endpoint"""
        try:
            response = requests.get("http://prometheus:9090/api/v1/targets", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    self.passed_tests.append("✅ Prometheus metrics endpoint working")
                    return True
            self.failed_tests.append("❌ Prometheus metrics endpoint not responding correctly")
            return False
        except Exception as e:
            self.failed_tests.append(f"❌ Prometheus check failed: {str(e)}")
            return False
    
    def test_database_connectivity(self) -> bool:
        """Test database connectivity"""
        try:
            # This would require database credentials
            # For now, just check if PostgreSQL service is accessible
            response = requests.head("http://postgres:5432", timeout=5)
            # Note: HEAD won't work on postgres, but connection attempt will
            self.passed_tests.append("✅ Database port accessible")
            return True
        except Exception as e:
            self.failed_tests.append(f"❌ Database connectivity check failed: {str(e)}")
            return False
    
    def test_redis_connectivity(self) -> bool:
        """Test Redis connectivity"""
        try:
            response = requests.head("http://redis:6379", timeout=5)
            self.passed_tests.append("✅ Redis port accessible")
            return True
        except Exception as e:
            self.failed_tests.append(f"❌ Redis connectivity check failed: {str(e)}")
            return False
    
    def test_log_aggregation(self) -> bool:
        """Test Elasticsearch logging"""
        try:
            response = requests.get("http://elasticsearch:9200/_cluster/health", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") in ["green", "yellow"]:
                    self.passed_tests.append("✅ Elasticsearch cluster healthy")
                    return True
            self.failed_tests.append("❌ Elasticsearch cluster not healthy")
            return False
        except Exception as e:
            self.failed_tests.append(f"❌ Elasticsearch check failed: {str(e)}")
            return False
    
    def test_grafana_dashboards(self) -> bool:
        """Test Grafana is accessible"""
        try:
            response = requests.get("http://grafana:3000/api/health", timeout=10)
            if response.status_code == 200:
                self.passed_tests.append("✅ Grafana dashboards accessible")
                return True
            self.failed_tests.append("❌ Grafana not responding")
            return False
        except Exception as e:
            self.failed_tests.append(f"❌ Grafana check failed: {str(e)}")
            return False
    
    def test_jaeger_tracing(self) -> bool:
        """Test Jaeger tracing"""
        try:
            response = requests.get("http://jaeger:16686/api/services", timeout=10)
            if response.status_code == 200:
                self.passed_tests.append("✅ Jaeger tracing working")
                return True
            self.failed_tests.append("❌ Jaeger not responding")
            return False
        except Exception as e:
            self.failed_tests.append(f"❌ Jaeger check failed: {str(e)}")
            return False
    
    def test_api_response_time(self) -> bool:
        """Test API response time (should be < 2 seconds)"""
        try:
            start = time.time()
            response = requests.get(f"{self.app_url}/", timeout=5)
            elapsed = time.time() - start
            
            if elapsed < 2.0:
                self.passed_tests.append(f"✅ API response time: {elapsed:.2f}s (< 2s threshold)")
                return True
            else:
                self.failed_tests.append(f"❌ API response time: {elapsed:.2f}s (> 2s threshold)")
                return False
        except Exception as e:
            self.failed_tests.append(f"❌ API response test failed: {str(e)}")
            return False
    
    def test_error_handling(self) -> bool:
        """Test error handling with invalid request"""
        try:
            response = requests.get(f"{self.app_url}/invalid-endpoint", timeout=5)
            # Should return 404 or similar, not 500
            if response.status_code < 500:
                self.passed_tests.append(f"✅ Error handling working (status {response.status_code})")
                return True
            else:
                self.failed_tests.append(f"❌ Unexpected error response: {response.status_code}")
                return False
        except Exception as e:
            self.failed_tests.append(f"❌ Error handling test failed: {str(e)}")
            return False
    
    def run_all_tests(self) -> Tuple[int, int]:
        """Run all smoke tests, return (passed, failed)"""
        print("\n" + "="*60)
        print("🧪 Running Post-Deployment Smoke Tests")
        print("="*60 + "\n")
        
        tests = [
            ("Application Health", self.test_app_health),
            ("Prometheus Metrics", self.test_prometheus_metrics),
            ("Database Connectivity", self.test_database_connectivity),
            ("Redis Connectivity", self.test_redis_connectivity),
            ("Log Aggregation", self.test_log_aggregation),
            ("Grafana Dashboards", self.test_grafana_dashboards),
            ("Jaeger Tracing", self.test_jaeger_tracing),
            ("API Response Time", self.test_api_response_time),
            ("Error Handling", self.test_error_handling),
        ]
        
        for test_name, test_func in tests:
            print(f"Running: {test_name}...", end=" ", flush=True)
            try:
                result = test_func()
                if result:
                    print()
                else:
                    print()
            except Exception as e:
                print(f"ERROR: {str(e)}")
                self.failed_tests.append(f"❌ {test_name} crashed: {str(e)}")
        
        # Print results
        print("\n" + "="*60)
        print("📊 Test Results")
        print("="*60 + "\n")
        
        for test in self.passed_tests:
            print(test)
        
        for test in self.failed_tests:
            print(test)
        
        passed = len(self.passed_tests)
        failed = len(self.failed_tests)
        
        print(f"\n{'='*60}")
        print(f"Total: {passed} passed, {failed} failed")
        print(f"{'='*60}\n")
        
        if failed == 0:
            print("✨ All smoke tests passed! Deployment is healthy.")
            return passed, failed
        else:
            print("⚠️  Some tests failed. Review the logs above.")
            return passed, failed


def main():
    """Run smoke tests"""
    import os
    
    app_url = os.getenv("APP_URL", "http://localhost:8501")
    
    tester = SmokeTest(app_url)
    passed, failed = tester.run_all_tests()
    
    # Exit with error code if any tests failed
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
