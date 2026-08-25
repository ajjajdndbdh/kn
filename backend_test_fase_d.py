"""
FASE D — Backend API Testing for Design Requests
Testing all backend requirements from the review request
"""
import requests
import sys
from datetime import datetime, timedelta

# Public endpoint from frontend/.env
BASE_URL = "https://sales-roles-next.preview.emergentagent.com/api"

class DesignRequestTester:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tokens = {}
        self.entity_id = "ent_ksc"
        
    def log(self, msg, success=None):
        if success is True:
            print(f"✅ {msg}")
            self.tests_passed += 1
        elif success is False:
            print(f"❌ {msg}")
        else:
            print(f"ℹ️  {msg}")
        self.tests_run += 1 if success is not None else 0
    
    def login(self, email, password="demo12345"):
        """Login and store token"""
        try:
            resp = requests.post(f"{BASE_URL}/auth/login", 
                               json={"email": email, "password": password},
                               timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("token") or data.get("access_token")
                if token:
                    self.tokens[email] = token
                    self.log(f"Login berhasil: {email}", True)
                    return token
            self.log(f"Login gagal {email}: {resp.status_code}", False)
            return None
        except Exception as e:
            self.log(f"Login error {email}: {str(e)}", False)
            return None
    
    def headers(self, email):
        """Get headers with token and entity"""
        token = self.tokens.get(email)
        if not token:
            return {}
        return {
            "Authorization": f"Bearer {token}",
            "X-Entity-Id": self.entity_id,
            "Content-Type": "application/json"
        }
    
    def test_get_list(self, email, expected_status=200, page_size=1):
        """Test GET /api/design-requests with pagination"""
        try:
            resp = requests.get(
                f"{BASE_URL}/design-requests",
                headers=self.headers(email),
                params={"page": 1, "page_size": page_size},
                timeout=10
            )
            if resp.status_code == expected_status:
                if expected_status == 200:
                    data = resp.json()
                    summary = data.get("summary", {})
                    total = summary.get("total", 0)
                    self.log(f"GET list ({email}): {resp.status_code}, total={total}, summary={summary}", True)
                    return data
                else:
                    self.log(f"GET list ({email}): {resp.status_code} (expected)", True)
                    return None
            else:
                self.log(f"GET list ({email}): expected {expected_status}, got {resp.status_code}", False)
                return None
        except Exception as e:
            self.log(f"GET list error ({email}): {str(e)}", False)
            return None
    
    def test_create_invalid_brief(self, email):
        """Test POST with brief < 5 characters (should be 400)"""
        try:
            resp = requests.post(
                f"{BASE_URL}/design-requests",
                headers=self.headers(email),
                json={
                    "brief": "abc",  # Too short
                    "target_type": "motif",
                    "source": "internal"
                },
                timeout=10
            )
            if resp.status_code == 400:
                self.log(f"Brief < 5 huruf ditolak 400: {resp.json().get('detail', '')}", True)
                return True
            else:
                self.log(f"Brief < 5 huruf: expected 400, got {resp.status_code}", False)
                return False
        except Exception as e:
            self.log(f"Create invalid brief error: {str(e)}", False)
            return False
    
    def test_create_source_so_without_so_id(self, email):
        """Test POST with source=so but no so_id (should be 400)"""
        try:
            resp = requests.post(
                f"{BASE_URL}/design-requests",
                headers=self.headers(email),
                json={
                    "brief": "Test design request for SO",
                    "target_type": "motif",
                    "source": "so"
                    # Missing so_id
                },
                timeout=10
            )
            if resp.status_code == 400:
                detail = resp.json().get('detail', '')
                if 'pesanan' in detail.lower():
                    self.log(f"source=so tanpa so_id ditolak 400: {detail}", True)
                    return True
            self.log(f"source=so tanpa so_id: expected 400, got {resp.status_code}", False)
            return False
        except Exception as e:
            self.log(f"Create source=so error: {str(e)}", False)
            return False
    
    def test_create_all_entity_mode(self, email):
        """Test POST with X-Entity-Id: all (should be 409)"""
        try:
            headers = self.headers(email)
            headers["X-Entity-Id"] = "all"
            resp = requests.post(
                f"{BASE_URL}/design-requests",
                headers=headers,
                json={
                    "brief": "Test design request in all mode",
                    "target_type": "motif",
                    "source": "internal"
                },
                timeout=10
            )
            if resp.status_code == 409:
                detail = resp.json().get('detail', '')
                self.log(f"Mode 'Semua Entitas' ditolak 409: {detail}", True)
                return True
            else:
                self.log(f"Mode 'all': expected 409, got {resp.status_code}", False)
                return False
        except Exception as e:
            self.log(f"Create all mode error: {str(e)}", False)
            return False
    
    def test_create_valid(self, email):
        """Create a valid design request"""
        try:
            resp = requests.post(
                f"{BASE_URL}/design-requests",
                headers=self.headers(email),
                json={
                    "brief": "Test design request - valid brief for testing",
                    "target_type": "motif",
                    "source": "internal",
                    "submit_now": True
                },
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                req_id = data.get("id")
                number = data.get("number")
                status = data.get("status")
                self.log(f"Create valid ({email}): {number}, status={status}", True)
                return data
            else:
                self.log(f"Create valid failed: {resp.status_code}", False)
                return None
        except Exception as e:
            self.log(f"Create valid error: {str(e)}", False)
            return None
    
    def test_state_machine_invalid_transition(self, req_id, email, action, expected_status=400):
        """Test invalid state transitions"""
        try:
            resp = requests.post(
                f"{BASE_URL}/design-requests/{req_id}/{action}",
                headers=self.headers(email),
                json={},
                timeout=10
            )
            if resp.status_code == expected_status:
                self.log(f"Invalid transition /{action} ditolak {expected_status}", True)
                return True
            else:
                self.log(f"Invalid transition /{action}: expected {expected_status}, got {resp.status_code}", False)
                return False
        except Exception as e:
            self.log(f"State machine error: {str(e)}", False)
            return False
    
    def test_reject_without_reason(self, req_id, email):
        """Test reject without reason (should be 400)"""
        try:
            resp = requests.post(
                f"{BASE_URL}/design-requests/{req_id}/reject",
                headers=self.headers(email),
                json={"reason": ""},  # Empty reason
                timeout=10
            )
            if resp.status_code == 400:
                detail = resp.json().get('detail', '')
                if 'alasan' in detail.lower():
                    self.log(f"Reject tanpa alasan ditolak 400: {detail}", True)
                    return True
            self.log(f"Reject tanpa alasan: expected 400, got {resp.status_code}", False)
            return False
        except Exception as e:
            self.log(f"Reject without reason error: {str(e)}", False)
            return False
    
    def test_cancel_without_reason(self, req_id, email):
        """Test cancel without reason (should be 400)"""
        try:
            resp = requests.post(
                f"{BASE_URL}/design-requests/{req_id}/cancel",
                headers=self.headers(email),
                json={"reason": "ab"},  # Too short
                timeout=10
            )
            if resp.status_code == 400:
                detail = resp.json().get('detail', '')
                if 'alasan' in detail.lower():
                    self.log(f"Cancel dengan alasan < 3 huruf ditolak 400: {detail}", True)
                    return True
            self.log(f"Cancel tanpa alasan: expected 400, got {resp.status_code}", False)
            return False
        except Exception as e:
            self.log(f"Cancel without reason error: {str(e)}", False)
            return False
    
    def test_designer_permissions(self):
        """Test designer role permissions (403 on create/assign/approve/reject)"""
        designer_email = "designer@kainnusantara.id"
        
        # Designer should NOT be able to create
        try:
            resp = requests.post(
                f"{BASE_URL}/design-requests",
                headers=self.headers(designer_email),
                json={
                    "brief": "Designer trying to create",
                    "target_type": "motif",
                    "source": "internal"
                },
                timeout=10
            )
            if resp.status_code == 403:
                self.log(f"Designer POST /design-requests: 403 (correct)", True)
            else:
                self.log(f"Designer POST: expected 403, got {resp.status_code}", False)
        except Exception as e:
            self.log(f"Designer create test error: {str(e)}", False)
    
    def test_sales_permissions(self):
        """Test sales role permissions (403 on all design-requests)"""
        sales_email = "sales@kainnusantara.id"
        
        try:
            resp = requests.get(
                f"{BASE_URL}/design-requests",
                headers=self.headers(sales_email),
                timeout=10
            )
            if resp.status_code == 403:
                self.log(f"Sales GET /design-requests: 403 (correct)", True)
            else:
                self.log(f"Sales GET: expected 403, got {resp.status_code}", False)
        except Exception as e:
            self.log(f"Sales permissions test error: {str(e)}", False)
    
    def test_report_by_designer_permissions(self):
        """Test /design/reports/by-designer permissions"""
        # Admin/Manager should have access
        admin_email = "admin@kainnusantara.id"
        try:
            resp = requests.get(
                f"{BASE_URL}/design/reports/by-designer",
                headers=self.headers(admin_email),
                timeout=10
            )
            if resp.status_code == 200:
                self.log(f"Admin GET /design/reports/by-designer: 200", True)
            else:
                self.log(f"Admin report: expected 200, got {resp.status_code}", False)
        except Exception as e:
            self.log(f"Admin report test error: {str(e)}", False)
        
        # Designer should get 403
        designer_email = "designer@kainnusantara.id"
        try:
            resp = requests.get(
                f"{BASE_URL}/design/reports/by-designer",
                headers=self.headers(designer_email),
                timeout=10
            )
            if resp.status_code == 403:
                self.log(f"Designer GET /design/reports/by-designer: 403 (correct)", True)
            else:
                self.log(f"Designer report: expected 403, got {resp.status_code}", False)
        except Exception as e:
            self.log(f"Designer report test error: {str(e)}", False)
    
    def test_report_mine_endpoint(self):
        """Test /design/reports/mine endpoint (NEW)"""
        designer_email = "designer@kainnusantara.id"
        try:
            resp = requests.get(
                f"{BASE_URL}/design/reports/mine",
                headers=self.headers(designer_email),
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                # Should NOT have 'items' key (only 'me' and 'team')
                if 'items' in data:
                    self.log(f"Designer /reports/mine: FAIL - contains 'items' key (leaking other designers)", False)
                elif 'me' in data and 'team' in data:
                    self.log(f"Designer /reports/mine: 200, only 'me' and 'team' (correct)", True)
                else:
                    self.log(f"Designer /reports/mine: unexpected structure", False)
            else:
                self.log(f"Designer /reports/mine: expected 200, got {resp.status_code}", False)
        except Exception as e:
            self.log(f"Designer /reports/mine error: {str(e)}", False)
    
    def test_roles_endpoint(self):
        """Test GET /api/roles includes designer"""
        admin_email = "admin@kainnusantara.id"
        try:
            resp = requests.get(
                f"{BASE_URL}/roles",
                headers=self.headers(admin_email),
                timeout=10
            )
            if resp.status_code == 200:
                roles = resp.json()
                designer_role = next((r for r in roles if r.get('id') == 'designer'), None)
                if designer_role and designer_role.get('label') == 'Desainer':
                    self.log(f"GET /api/roles: includes 'designer' with label 'Desainer'", True)
                else:
                    self.log(f"GET /api/roles: designer role not found or incorrect label", False)
            else:
                self.log(f"GET /api/roles: {resp.status_code}", False)
        except Exception as e:
            self.log(f"Roles endpoint error: {str(e)}", False)
    
    def test_summary_calculation(self):
        """Test that summary is calculated from ALL filtered results, not just page"""
        admin_email = "admin@kainnusantara.id"
        
        # Get with page_size=1
        data1 = self.test_get_list(admin_email, page_size=1)
        if not data1:
            return
        
        summary1 = data1.get("summary", {})
        total1 = summary1.get("total", 0)
        
        # Get with page_size=100
        try:
            resp = requests.get(
                f"{BASE_URL}/design-requests",
                headers=self.headers(admin_email),
                params={"page": 1, "page_size": 100},
                timeout=10
            )
            if resp.status_code == 200:
                data2 = resp.json()
                summary2 = data2.get("summary", {})
                total2 = summary2.get("total", 0)
                
                if total1 == total2 and total1 > 0:
                    self.log(f"Summary calculation: consistent across page sizes (total={total1})", True)
                elif total1 == total2 == 0:
                    self.log(f"Summary calculation: no data to test", None)
                else:
                    self.log(f"Summary calculation: INCONSISTENT (page_size=1: {total1}, page_size=100: {total2})", False)
        except Exception as e:
            self.log(f"Summary calculation error: {str(e)}", False)

def main():
    print("=" * 80)
    print("FASE D — Backend API Testing for Design Requests")
    print("=" * 80)
    print()
    
    tester = DesignRequestTester()
    
    # Login all users
    print("🔐 Logging in users...")
    tester.login("admin@kainnusantara.id")
    tester.login("manager@kainnusantara.id")
    tester.login("designer@kainnusantara.id")
    tester.login("salesadmin@kainnusantara.id")
    tester.login("sales@kainnusantara.id")
    print()
    
    # Test 1: GET list with summary
    print("📋 Test 1: GET /api/design-requests with summary")
    tester.test_get_list("admin@kainnusantara.id")
    tester.test_summary_calculation()
    print()
    
    # Test 2: POST validations
    print("📋 Test 2: POST /api/design-requests validations")
    tester.test_create_invalid_brief("admin@kainnusantara.id")
    tester.test_create_source_so_without_so_id("admin@kainnusantara.id")
    tester.test_create_all_entity_mode("admin@kainnusantara.id")
    print()
    
    # Test 3: Create valid request
    print("📋 Test 3: Create valid design request")
    req = tester.test_create_valid("manager@kainnusantara.id")
    print()
    
    # Test 4: Reason validations
    if req:
        print("📋 Test 4: Reject/Cancel reason validations")
        req_id = req.get("id")
        # These will fail because status is 'submitted', not 'delivered'
        # But we're testing the reason validation
        tester.test_reject_without_reason(req_id, "manager@kainnusantara.id")
        tester.test_cancel_without_reason(req_id, "manager@kainnusantara.id")
        print()
    
    # Test 5: Designer permissions
    print("📋 Test 5: Designer role permissions (NARROW)")
    tester.test_designer_permissions()
    tester.test_report_by_designer_permissions()
    tester.test_report_mine_endpoint()
    print()
    
    # Test 6: Sales permissions
    print("📋 Test 6: Sales role permissions (403 on design-requests)")
    tester.test_sales_permissions()
    print()
    
    # Test 7: Roles endpoint
    print("📋 Test 7: GET /api/roles includes designer")
    tester.test_roles_endpoint()
    print()
    
    # Summary
    print("=" * 80)
    print(f"📊 HASIL: {tester.tests_passed}/{tester.tests_run} tests passed")
    print("=" * 80)
    
    return 0 if tester.tests_passed == tester.tests_run else 1

if __name__ == "__main__":
    sys.exit(main())
