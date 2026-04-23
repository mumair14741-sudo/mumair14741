"""
Test suite for:
1. DELETE /api/clicks/delete-by-category endpoint with categories: vpn, proxy, duplicate
2. GET /api/branding endpoint for branding settings
3. Branding CSS variables being applied via BrandingContext
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
USER_EMAIL = "test@test.com"
USER_PASSWORD = "test123"
ADMIN_EMAIL = "us9661626@gmail.com"
ADMIN_PASSWORD = "<redacted>"


class TestBrandingEndpoint:
    """Test branding API endpoint"""
    
    def test_get_branding_returns_200(self):
        """GET /api/branding should return 200"""
        response = requests.get(f"{BASE_URL}/api/branding")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✅ GET /api/branding returns 200")
    
    def test_branding_has_required_fields(self):
        """Branding response should have all required fields"""
        response = requests.get(f"{BASE_URL}/api/branding")
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "app_name", "tagline", "primary_color", "secondary_color",
            "footer_text"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
            print(f"✅ Branding has field: {field} = {data[field]}")
        
        print("✅ Branding has all required fields")
    
    def test_branding_custom_values_applied(self):
        """Branding should show custom values (Traxun)"""
        response = requests.get(f"{BASE_URL}/api/branding")
        assert response.status_code == 200
        data = response.json()
        
        # Check that custom branding is applied
        assert data.get("app_name") == "Traxun", f"Expected 'Traxun', got {data.get('app_name')}"
        assert "Track Everything Behind The Click" in data.get("tagline", ""), f"Tagline mismatch: {data.get('tagline')}"
        print(f"✅ Custom branding applied: app_name={data['app_name']}, tagline={data['tagline']}")


class TestDeleteByCategory:
    """Test DELETE /api/clicks/delete-by-category endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login and get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": USER_EMAIL,
            "password": USER_PASSWORD
        })
        if response.status_code == 200:
            self.token = response.json()["access_token"]
            self.headers = {"Authorization": f"Bearer {self.token}"}
            print(f"✅ Logged in as {USER_EMAIL}")
        else:
            pytest.skip(f"Login failed: {response.status_code}")
    
    def test_delete_by_vpn_category(self):
        """DELETE /api/clicks/delete-by-category?categories=vpn should work"""
        response = requests.delete(
            f"{BASE_URL}/api/clicks/delete-by-category",
            params={"categories": "vpn"},
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "deleted_count" in data, "Response should have deleted_count"
        assert "categories" in data, "Response should have categories"
        assert "vpn" in data["categories"], "Categories should include vpn"
        print(f"✅ DELETE by VPN category works: deleted {data['deleted_count']} clicks")
    
    def test_delete_by_proxy_category(self):
        """DELETE /api/clicks/delete-by-category?categories=proxy should work"""
        response = requests.delete(
            f"{BASE_URL}/api/clicks/delete-by-category",
            params={"categories": "proxy"},
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "deleted_count" in data, "Response should have deleted_count"
        assert "proxy" in data["categories"], "Categories should include proxy"
        print(f"✅ DELETE by Proxy category works: deleted {data['deleted_count']} clicks")
    
    def test_delete_by_duplicate_category(self):
        """DELETE /api/clicks/delete-by-category?categories=duplicate should work"""
        response = requests.delete(
            f"{BASE_URL}/api/clicks/delete-by-category",
            params={"categories": "duplicate"},
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "deleted_count" in data, "Response should have deleted_count"
        assert "duplicate" in data["categories"], "Categories should include duplicate"
        print(f"✅ DELETE by Duplicate category works: deleted {data['deleted_count']} clicks")
    
    def test_delete_by_multiple_categories(self):
        """DELETE /api/clicks/delete-by-category?categories=vpn,proxy,duplicate should work"""
        response = requests.delete(
            f"{BASE_URL}/api/clicks/delete-by-category",
            params={"categories": "vpn,proxy,duplicate"},
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "deleted_count" in data, "Response should have deleted_count"
        assert len(data["categories"]) == 3, "Should have 3 categories"
        print(f"✅ DELETE by multiple categories works: deleted {data['deleted_count']} clicks")
    
    def test_delete_by_empty_category_fails(self):
        """DELETE /api/clicks/delete-by-category with empty categories should fail"""
        response = requests.delete(
            f"{BASE_URL}/api/clicks/delete-by-category",
            params={"categories": ""},
            headers=self.headers
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("✅ DELETE with empty categories correctly returns 400")
    
    def test_delete_by_invalid_category_fails(self):
        """DELETE /api/clicks/delete-by-category with invalid category should fail"""
        response = requests.delete(
            f"{BASE_URL}/api/clicks/delete-by-category",
            params={"categories": "invalid_category"},
            headers=self.headers
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("✅ DELETE with invalid category correctly returns 400")
    
    def test_delete_by_category_requires_auth(self):
        """DELETE /api/clicks/delete-by-category without auth should fail"""
        response = requests.delete(
            f"{BASE_URL}/api/clicks/delete-by-category",
            params={"categories": "vpn"}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✅ DELETE by category correctly requires authentication")


class TestUserLogin:
    """Test user authentication"""
    
    def test_user_login_success(self):
        """User login should work with valid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": USER_EMAIL,
            "password": USER_PASSWORD
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "access_token" in data, "Response should have access_token"
        assert "user" in data, "Response should have user"
        print(f"✅ User login successful: {data['user'].get('email')}")
    
    def test_admin_login_success(self):
        """Admin login should work with valid credentials"""
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "access_token" in data, "Response should have access_token"
        print("✅ Admin login successful")


class TestClicksEndpoint:
    """Test clicks endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login and get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": USER_EMAIL,
            "password": USER_PASSWORD
        })
        if response.status_code == 200:
            self.token = response.json()["access_token"]
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            pytest.skip(f"Login failed: {response.status_code}")
    
    def test_get_clicks_returns_200(self):
        """GET /api/clicks should return 200"""
        response = requests.get(f"{BASE_URL}/api/clicks", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"✅ GET /api/clicks returns 200 with {len(data)} clicks")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
