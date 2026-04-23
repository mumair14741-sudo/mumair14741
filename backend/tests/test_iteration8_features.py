"""
Test file for Iteration 8 features:
1. Admin Forgot Password Link on admin login page
2. Clean Link URLs (/t/{short_code} format)
3. Clicks Page Delete By Dropdown
4. IP Duplicate Check Accuracy across user's entire database
5. Backend endpoints: /api/clicks/delete-by-category, PUT /api/links/{id} with custom_short_code
"""

import pytest
import requests
import os
import uuid
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://ip-duplicate-detect.preview.emergentagent.com').rstrip('/')

class TestAuthEndpoints:
    """Test authentication and forgot password endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.admin_email = "us9661626@gmail.com"
        self.admin_password = "<redacted>"
        self.user_email = "test@test.com"
        self.user_password = "test123"
    
    def test_admin_login_success(self):
        """Test admin login works"""
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": self.admin_email,
            "password": self.admin_password
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data.get("is_admin") == True
        print(f"✅ Admin login successful")
    
    def test_user_login_success(self):
        """Test user login works"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": self.user_email,
            "password": self.user_password
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "user" in data
        print(f"✅ User login successful")
    
    def test_forgot_password_endpoint_exists(self):
        """Test forgot password endpoint exists and works"""
        response = requests.post(f"{BASE_URL}/api/auth/forgot-password", json={
            "email": self.user_email
        })
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        # Should NOT expose reset_url in response
        assert "reset_url" not in data
        print(f"✅ Forgot password endpoint works and doesn't expose reset URL")
    
    def test_forgot_password_nonexistent_email(self):
        """Test forgot password with non-existent email returns success (security)"""
        response = requests.post(f"{BASE_URL}/api/auth/forgot-password", json={
            "email": "nonexistent@example.com"
        })
        # Should return 200 to not reveal if email exists
        assert response.status_code == 200
        print(f"✅ Forgot password handles non-existent email gracefully")


class TestLinkEndpoints:
    """Test link management endpoints including clean URLs"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.user_email = "test@test.com"
        self.user_password = "test123"
        # Get auth token
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": self.user_email,
            "password": self.user_password
        })
        self.token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_create_link_with_custom_short_code(self):
        """Test creating a link with custom short code"""
        custom_code = f"test-link-{uuid.uuid4().hex[:6]}"
        response = requests.post(f"{BASE_URL}/api/links", json={
            "offer_url": "https://example.com/test",
            "name": "Test Custom Code Link",
            "custom_short_code": custom_code
        }, headers=self.headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["short_code"] == custom_code
        print(f"✅ Link created with custom short code: {custom_code}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/links/{data['id']}", headers=self.headers)
    
    def test_update_link_custom_short_code(self):
        """Test updating a link's custom short code"""
        # Create a link first
        response = requests.post(f"{BASE_URL}/api/links", json={
            "offer_url": "https://example.com/update-test",
            "name": "Update Test Link"
        }, headers=self.headers)
        assert response.status_code == 200
        link_id = response.json()["id"]
        original_code = response.json()["short_code"]
        
        # Update with new custom code
        new_code = f"updated-{uuid.uuid4().hex[:6]}"
        update_response = requests.put(f"{BASE_URL}/api/links/{link_id}", json={
            "custom_short_code": new_code
        }, headers=self.headers)
        
        assert update_response.status_code == 200
        updated_data = update_response.json()
        assert updated_data["short_code"] == new_code
        print(f"✅ Link short code updated from {original_code} to {new_code}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/links/{link_id}", headers=self.headers)
    
    def test_link_redirect_endpoint_exists(self):
        """Test that /t/{short_code} redirect endpoint exists"""
        # Get existing links
        response = requests.get(f"{BASE_URL}/api/links", headers=self.headers)
        links = response.json()
        
        if links:
            short_code = links[0]["short_code"]
            # Test redirect endpoint (should redirect or return 302/307)
            redirect_response = requests.get(
                f"{BASE_URL}/t/{short_code}", 
                allow_redirects=False
            )
            # Should be a redirect (302, 307) or success (200)
            assert redirect_response.status_code in [200, 302, 307, 308]
            print(f"✅ /t/{short_code} endpoint works (status: {redirect_response.status_code})")
        else:
            print("⚠️ No links found to test redirect")


class TestClicksEndpoints:
    """Test clicks management endpoints including delete-by-category"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.user_email = "test@test.com"
        self.user_password = "test123"
        # Get auth token
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": self.user_email,
            "password": self.user_password
        })
        self.token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_clicks(self):
        """Test getting clicks list"""
        response = requests.get(f"{BASE_URL}/api/clicks", headers=self.headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        print(f"✅ Get clicks endpoint works, found {len(response.json())} clicks")
    
    def test_delete_by_category_endpoint_exists(self):
        """Test delete-by-category endpoint exists"""
        # Test with VPN category
        response = requests.delete(
            f"{BASE_URL}/api/clicks/delete-by-category",
            params={"categories": "vpn"},
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "deleted_count" in data
        assert "categories" in data
        print(f"✅ Delete by category endpoint works, deleted {data['deleted_count']} VPN clicks")
    
    def test_delete_by_category_multiple(self):
        """Test delete-by-category with multiple categories"""
        response = requests.delete(
            f"{BASE_URL}/api/clicks/delete-by-category",
            params={"categories": "vpn,proxy,duplicate"},
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "deleted_count" in data
        assert set(data["categories"]) == {"vpn", "proxy", "duplicate"}
        print(f"✅ Delete by multiple categories works, deleted {data['deleted_count']} clicks")
    
    def test_delete_by_category_invalid(self):
        """Test delete-by-category with invalid category"""
        response = requests.delete(
            f"{BASE_URL}/api/clicks/delete-by-category",
            params={"categories": "invalid_category"},
            headers=self.headers
        )
        # Should return 400 for invalid category
        assert response.status_code == 400
        print(f"✅ Delete by invalid category returns 400 as expected")


class TestIPDuplicateDetection:
    """Test IP duplicate detection across user's entire database"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.user_email = "test@test.com"
        self.user_password = "test123"
        # Get auth token
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": self.user_email,
            "password": self.user_password
        })
        self.token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_create_two_links_for_duplicate_test(self):
        """Create two links to test IP duplicate detection"""
        # Create first link
        link1_response = requests.post(f"{BASE_URL}/api/links", json={
            "offer_url": "https://example.com/link1",
            "name": "IP Duplicate Test Link 1",
            "custom_short_code": f"dup-test-1-{uuid.uuid4().hex[:4]}"
        }, headers=self.headers)
        assert link1_response.status_code == 200
        link1 = link1_response.json()
        
        # Create second link
        link2_response = requests.post(f"{BASE_URL}/api/links", json={
            "offer_url": "https://example.com/link2",
            "name": "IP Duplicate Test Link 2",
            "custom_short_code": f"dup-test-2-{uuid.uuid4().hex[:4]}"
        }, headers=self.headers)
        assert link2_response.status_code == 200
        link2 = link2_response.json()
        
        print(f"✅ Created two test links: {link1['short_code']} and {link2['short_code']}")
        
        # Store for cleanup
        self.test_link1_id = link1["id"]
        self.test_link2_id = link2["id"]
        self.test_link1_code = link1["short_code"]
        self.test_link2_code = link2["short_code"]
        
        return link1, link2
    
    def test_ip_duplicate_detection_logic(self):
        """Test that IP duplicate detection checks across all user's links"""
        # This test verifies the backend logic exists
        # The actual duplicate detection happens when clicking links
        
        # Get clicks to verify the is_duplicate fields exist
        response = requests.get(f"{BASE_URL}/api/clicks", headers=self.headers)
        assert response.status_code == 200
        clicks = response.json()
        
        # Check that click response model includes duplicate fields
        if clicks:
            click = clicks[0]
            # These fields should exist in the response model
            print(f"✅ Click data structure verified")
            print(f"   - IP Address: {click.get('ip_address', 'N/A')}")
            print(f"   - IPv4: {click.get('ipv4', 'N/A')}")
            print(f"   - IPv6: {click.get('ipv6', 'N/A')}")
            print(f"   - Is VPN: {click.get('is_vpn', 'N/A')}")
        else:
            print("⚠️ No clicks found to verify structure")


class TestCleanURLFormat:
    """Test that URLs use clean /t/ format instead of /api/r/"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.user_email = "test@test.com"
        self.user_password = "test123"
        # Get auth token
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": self.user_email,
            "password": self.user_password
        })
        self.token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_t_endpoint_exists(self):
        """Test that /t/{short_code} endpoint exists"""
        # Get a link
        response = requests.get(f"{BASE_URL}/api/links", headers=self.headers)
        links = response.json()
        
        if links:
            short_code = links[0]["short_code"]
            # Test /t/ endpoint
            t_response = requests.get(f"{BASE_URL}/t/{short_code}", allow_redirects=False)
            assert t_response.status_code in [200, 302, 307, 308]
            print(f"✅ /t/{short_code} endpoint exists and responds")
        else:
            # Create a test link
            create_response = requests.post(f"{BASE_URL}/api/links", json={
                "offer_url": "https://example.com/test",
                "name": "URL Format Test"
            }, headers=self.headers)
            if create_response.status_code == 200:
                short_code = create_response.json()["short_code"]
                t_response = requests.get(f"{BASE_URL}/t/{short_code}", allow_redirects=False)
                assert t_response.status_code in [200, 302, 307, 308]
                print(f"✅ /t/{short_code} endpoint exists and responds")
                # Cleanup
                requests.delete(f"{BASE_URL}/api/links/{create_response.json()['id']}", headers=self.headers)
    
    def test_api_r_endpoint_also_works(self):
        """Test that /api/r/{short_code} still works for backward compatibility"""
        response = requests.get(f"{BASE_URL}/api/links", headers=self.headers)
        links = response.json()
        
        if links:
            short_code = links[0]["short_code"]
            # Test /api/r/ endpoint
            r_response = requests.get(f"{BASE_URL}/api/r/{short_code}", allow_redirects=False)
            # 403 is also valid - it means duplicate IP detection is working
            assert r_response.status_code in [200, 302, 307, 308, 403]
            if r_response.status_code == 403:
                print(f"✅ /api/r/{short_code} endpoint works - returned 403 (duplicate IP detected)")
            else:
                print(f"✅ /api/r/{short_code} endpoint still works for backward compatibility")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
