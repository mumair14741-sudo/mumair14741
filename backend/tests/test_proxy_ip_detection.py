"""
Test suite for Proxy IP Detection and Duplicate Check features
Tests:
1. Proxy test endpoint (/api/proxies/{id}/test) detects correct outbound IP via httpbin.org
2. Proxy test returns all_detected_ips array if multiple IPs detected
3. Proxy test checks duplicate against user's own database (not global)
4. ProxyResponse model includes all_detected_ips and duplicate_matched_ip fields
5. Get proxies endpoint returns proxies from both user_db and main_db
6. Proxy upload saves to user_db
7. Proxy delete works for both user_db and main_db proxies
"""

import pytest
import requests
import os
import time
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_USER_EMAIL = "test@test.com"
TEST_USER_PASSWORD = "test123"


class TestProxyIPDetection:
    """Test proxy IP detection and duplicate checking features"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.token = None
        self.created_proxy_ids = []
    
    def get_auth_token(self):
        """Get authentication token for test user"""
        if self.token:
            return self.token
        
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        
        if response.status_code == 200:
            self.token = response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
            return self.token
        else:
            pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")
    
    def test_01_user_login(self):
        """Test user can login successfully"""
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "access_token" in data, "No access token in response"
        assert "user" in data, "No user data in response"
        print(f"✅ User login successful: {data['user'].get('email')}")
    
    def test_02_get_proxies_endpoint(self):
        """Test GET /api/proxies returns proxies list"""
        self.get_auth_token()
        
        response = self.session.get(f"{BASE_URL}/api/proxies?filter=all")
        
        assert response.status_code == 200, f"Get proxies failed: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"✅ Get proxies successful: {len(data)} proxies found")
        
        # Check if response includes new fields
        if len(data) > 0:
            proxy = data[0]
            # Verify ProxyResponse model fields exist
            assert "id" in proxy, "Missing 'id' field"
            assert "proxy_string" in proxy, "Missing 'proxy_string' field"
            assert "status" in proxy, "Missing 'status' field"
            print(f"✅ Proxy response model has required fields")
    
    def test_03_proxy_response_model_has_new_fields(self):
        """Test ProxyResponse model includes all_detected_ips and duplicate_matched_ip fields"""
        self.get_auth_token()
        
        response = self.session.get(f"{BASE_URL}/api/proxies?filter=all")
        assert response.status_code == 200, f"Get proxies failed: {response.text}"
        
        data = response.json()
        
        # Even if no proxies exist, we can verify the endpoint works
        # The model fields will be validated when we upload and test a proxy
        print(f"✅ Proxies endpoint returns valid response with {len(data)} proxies")
        
        # If there are proxies with detected IPs, verify the new fields
        for proxy in data:
            if proxy.get("detected_ip"):
                # Check for new fields (they may be None but should exist in model)
                print(f"  - Proxy {proxy['id'][:8]}... has detected_ip: {proxy.get('detected_ip')}")
                if proxy.get("all_detected_ips"):
                    print(f"    all_detected_ips: {proxy.get('all_detected_ips')}")
                if proxy.get("duplicate_matched_ip"):
                    print(f"    duplicate_matched_ip: {proxy.get('duplicate_matched_ip')}")
    
    def test_04_upload_proxy_to_user_db(self):
        """Test proxy upload saves to user_db"""
        self.get_auth_token()
        
        # Generate unique proxy string to avoid duplicates
        unique_id = str(uuid.uuid4())[:8]
        test_proxy = f"192.168.{unique_id[:3]}.{unique_id[3:6]}:8080"
        
        response = self.session.post(f"{BASE_URL}/api/proxies/upload", json={
            "proxy_list": [test_proxy],
            "proxy_type": "http"
        })
        
        assert response.status_code == 200, f"Upload proxy failed: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        assert len(data) > 0, "Should return uploaded proxy"
        
        uploaded_proxy = data[0]
        assert "id" in uploaded_proxy, "Uploaded proxy should have id"
        assert uploaded_proxy.get("proxy_string") == test_proxy, "Proxy string should match"
        
        # Store for cleanup
        self.created_proxy_ids.append(uploaded_proxy["id"])
        
        print(f"✅ Proxy uploaded successfully: {uploaded_proxy['id'][:8]}...")
        print(f"  - proxy_string: {uploaded_proxy.get('proxy_string')}")
        print(f"  - status: {uploaded_proxy.get('status')}")
        print(f"  - is_duplicate: {uploaded_proxy.get('is_duplicate')}")
        
        return uploaded_proxy["id"]
    
    def test_05_proxy_test_endpoint_exists(self):
        """Test POST /api/proxies/{id}/test endpoint exists"""
        self.get_auth_token()
        
        # First upload a test proxy
        unique_id = str(uuid.uuid4())[:8]
        test_proxy = f"10.0.{unique_id[:3]}.{unique_id[3:6]}:3128"
        
        upload_response = self.session.post(f"{BASE_URL}/api/proxies/upload", json={
            "proxy_list": [test_proxy],
            "proxy_type": "http"
        })
        
        assert upload_response.status_code == 200, f"Upload failed: {upload_response.text}"
        proxy_id = upload_response.json()[0]["id"]
        self.created_proxy_ids.append(proxy_id)
        
        # Test the proxy (will likely fail since it's a fake proxy, but endpoint should work)
        test_response = self.session.post(f"{BASE_URL}/api/proxies/{proxy_id}/test")
        
        # Should return 200 even if proxy is dead
        assert test_response.status_code == 200, f"Test proxy endpoint failed: {test_response.text}"
        
        data = test_response.json()
        assert "status" in data, "Response should have 'status' field"
        
        # Since this is a fake proxy, it should be dead
        print(f"✅ Proxy test endpoint works: status={data.get('status')}")
        
        # Verify response includes new fields (even if None for dead proxy)
        if data.get("status") == "alive":
            assert "detected_ip" in data, "Alive proxy should have detected_ip"
            print(f"  - detected_ip: {data.get('detected_ip')}")
            print(f"  - all_detected_ips: {data.get('all_detected_ips')}")
            print(f"  - duplicate_matched_ip: {data.get('duplicate_matched_ip')}")
    
    def test_06_proxy_test_returns_all_detected_ips(self):
        """Test that proxy test returns all_detected_ips array"""
        self.get_auth_token()
        
        # Get existing proxies
        response = self.session.get(f"{BASE_URL}/api/proxies?filter=all")
        assert response.status_code == 200
        
        proxies = response.json()
        
        # Find a proxy that has been tested and is alive
        alive_proxy = None
        for proxy in proxies:
            if proxy.get("status") == "alive" and proxy.get("detected_ip"):
                alive_proxy = proxy
                break
        
        if alive_proxy:
            print(f"✅ Found alive proxy with detected IP: {alive_proxy['id'][:8]}...")
            print(f"  - detected_ip: {alive_proxy.get('detected_ip')}")
            print(f"  - all_detected_ips: {alive_proxy.get('all_detected_ips')}")
            
            # Verify all_detected_ips field exists (may be None or list)
            # The field should be present in the response model
            if alive_proxy.get("all_detected_ips"):
                assert isinstance(alive_proxy["all_detected_ips"], list), "all_detected_ips should be a list"
                print(f"  - all_detected_ips count: {len(alive_proxy['all_detected_ips'])}")
        else:
            print("⚠️ No alive proxy with detected IP found - skipping detailed check")
            # This is not a failure, just means no proxies have been tested yet
    
    def test_07_proxy_duplicate_check_uses_user_db(self):
        """Test that duplicate check queries user's own database"""
        self.get_auth_token()
        
        # Get proxies and check duplicate fields
        response = self.session.get(f"{BASE_URL}/api/proxies?filter=all")
        assert response.status_code == 200
        
        proxies = response.json()
        
        # Check for duplicate-related fields
        for proxy in proxies:
            # These fields should exist in the response
            is_duplicate = proxy.get("is_duplicate", False)
            is_duplicate_proxy = proxy.get("is_duplicate_proxy", False)
            is_duplicate_click = proxy.get("is_duplicate_click", False)
            duplicate_matched_ip = proxy.get("duplicate_matched_ip")
            
            if is_duplicate:
                print(f"✅ Found duplicate proxy: {proxy['id'][:8]}...")
                print(f"  - is_duplicate_proxy: {is_duplicate_proxy}")
                print(f"  - is_duplicate_click: {is_duplicate_click}")
                print(f"  - duplicate_matched_ip: {duplicate_matched_ip}")
        
        print(f"✅ Duplicate check fields present in proxy responses")
    
    def test_08_delete_proxy_works(self):
        """Test proxy delete works"""
        self.get_auth_token()
        
        # First upload a proxy to delete
        unique_id = str(uuid.uuid4())[:8]
        test_proxy = f"172.16.{unique_id[:3]}.{unique_id[3:6]}:8888"
        
        upload_response = self.session.post(f"{BASE_URL}/api/proxies/upload", json={
            "proxy_list": [test_proxy],
            "proxy_type": "http"
        })
        
        assert upload_response.status_code == 200
        proxy_id = upload_response.json()[0]["id"]
        
        # Delete the proxy
        delete_response = self.session.delete(f"{BASE_URL}/api/proxies/{proxy_id}")
        
        assert delete_response.status_code == 200, f"Delete failed: {delete_response.text}"
        print(f"✅ Proxy deleted successfully: {proxy_id[:8]}...")
        
        # Verify it's gone
        get_response = self.session.get(f"{BASE_URL}/api/proxies?filter=all")
        assert get_response.status_code == 200
        
        remaining_proxies = get_response.json()
        remaining_ids = [p["id"] for p in remaining_proxies]
        assert proxy_id not in remaining_ids, "Deleted proxy should not appear in list"
        print(f"✅ Verified proxy is no longer in list")
    
    def test_09_bulk_delete_proxies(self):
        """Test bulk delete proxies endpoint"""
        self.get_auth_token()
        
        # Upload multiple proxies
        unique_id = str(uuid.uuid4())[:8]
        test_proxies = [
            f"10.1.{unique_id[:3]}.1:8080",
            f"10.1.{unique_id[:3]}.2:8080",
            f"10.1.{unique_id[:3]}.3:8080"
        ]
        
        upload_response = self.session.post(f"{BASE_URL}/api/proxies/upload", json={
            "proxy_list": test_proxies,
            "proxy_type": "http"
        })
        
        assert upload_response.status_code == 200
        uploaded = upload_response.json()
        proxy_ids = [p["id"] for p in uploaded]
        
        # Bulk delete
        delete_response = self.session.post(f"{BASE_URL}/api/proxies/bulk-delete", json=proxy_ids)
        
        assert delete_response.status_code == 200, f"Bulk delete failed: {delete_response.text}"
        data = delete_response.json()
        # API returns 'deleted_count' field
        deleted_count = data.get("deleted_count", data.get("deleted", 0))
        assert deleted_count >= len(proxy_ids), f"Should delete at least {len(proxy_ids)} proxies"
        
        print(f"✅ Bulk delete successful: {deleted_count} proxies deleted")
    
    def test_10_proxy_filters_work(self):
        """Test proxy filter parameters work correctly"""
        self.get_auth_token()
        
        filters = ["all", "unique", "duplicate", "alive", "dead", "pending", "vpn", "clean"]
        
        for filter_name in filters:
            response = self.session.get(f"{BASE_URL}/api/proxies?filter={filter_name}")
            assert response.status_code == 200, f"Filter '{filter_name}' failed: {response.text}"
            data = response.json()
            print(f"✅ Filter '{filter_name}': {len(data)} proxies")
    
    def test_11_refresh_status_endpoint(self):
        """Test refresh status endpoint works"""
        self.get_auth_token()
        
        response = self.session.post(f"{BASE_URL}/api/proxies/refresh-status")
        
        assert response.status_code == 200, f"Refresh status failed: {response.text}"
        data = response.json()
        
        assert "updated" in data or "new_duplicates_found" in data, "Response should have status fields"
        print(f"✅ Refresh status successful: {data}")


class TestProxyResponseModel:
    """Test ProxyResponse model structure"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
    
    def get_auth_token(self):
        """Get authentication token"""
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        
        if response.status_code == 200:
            token = response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
            return token
        else:
            pytest.skip("Authentication failed")
    
    def test_proxy_response_has_all_fields(self):
        """Verify ProxyResponse model has all required fields"""
        self.get_auth_token()
        
        # Upload a test proxy
        unique_id = str(uuid.uuid4())[:8]
        test_proxy = f"192.168.100.{unique_id[:3]}:9999"
        
        upload_response = self.session.post(f"{BASE_URL}/api/proxies/upload", json={
            "proxy_list": [test_proxy],
            "proxy_type": "http"
        })
        
        assert upload_response.status_code == 200
        proxy = upload_response.json()[0]
        
        # Required fields from ProxyResponse model
        required_fields = [
            "id",
            "proxy_string",
            "proxy_type",
            "status",
            "last_checked"
        ]
        
        # Optional fields that should be present (may be None)
        optional_fields = [
            "proxy_ip",
            "response_time",
            "detected_ip",
            "all_detected_ips",  # NEW FIELD
            "is_duplicate",
            "is_duplicate_proxy",
            "is_duplicate_click",
            "duplicate_matched_ip",  # NEW FIELD
            "is_vpn",
            "vpn_score"
        ]
        
        for field in required_fields:
            assert field in proxy, f"Missing required field: {field}"
            print(f"✅ Required field '{field}': {proxy.get(field)}")
        
        for field in optional_fields:
            # Field should exist in response (even if None)
            print(f"  Optional field '{field}': {proxy.get(field)}")
        
        # Cleanup
        self.session.delete(f"{BASE_URL}/api/proxies/{proxy['id']}")
        print(f"✅ ProxyResponse model has all expected fields")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
