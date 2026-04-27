"""
Test Sub-User Data Access and Feature Restrictions
Tests:
1. Sub-user login and data access (should see parent's links, clicks, proxies)
2. Sub-user can create links (stored under parent's account)
3. Main user can see links created by sub-user
4. Links page - create with OS restriction, country restriction, VPN block
5. Clicks page - date filters
6. Forgot Password flow - request reset, verify token, reset password
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001')

# Test credentials — read from env; fall back to local defaults
MAIN_USER_EMAIL = os.environ.get("TEST_MAIN_USER_EMAIL", "linktest@example.com")
MAIN_USER_PASSWORD = os.environ.get("TEST_MAIN_USER_PASSWORD", "test123")
SUB_USER_EMAIL = os.environ.get("TEST_SUB_USER_EMAIL", "subuser1@example.com")
SUB_USER_PASSWORD = os.environ.get("TEST_SUB_USER_PASSWORD", "sub123")
ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@trackmaster.local")
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "admin123")


class TestSubUserDataAccess:
    """Test sub-user login and data access"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
    def get_main_user_token(self):
        """Get main user token"""
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": MAIN_USER_EMAIL,
            "password": MAIN_USER_PASSWORD
        })
        assert response.status_code == 200, f"Main user login failed: {response.text}"
        return response.json()["access_token"]
    
    def get_sub_user_token(self):
        """Get sub-user token"""
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": SUB_USER_EMAIL,
            "password": SUB_USER_PASSWORD
        })
        assert response.status_code == 200, f"Sub-user login failed: {response.text}"
        return response.json()["access_token"]
    
    def test_sub_user_login_returns_correct_flags(self):
        """Test that sub-user login returns is_sub_user=True and parent_user_id"""
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": SUB_USER_EMAIL,
            "password": SUB_USER_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        
        # Verify sub-user flags
        assert data["user"]["is_sub_user"] == True, "is_sub_user should be True"
        assert "parent_user_id" in data["user"], "parent_user_id should be present"
        assert data["user"]["parent_user_id"] is not None, "parent_user_id should not be None"
        
        # Verify sub-user inherits parent's features
        assert "features" in data["user"], "features should be inherited from parent"
        print(f"✅ Sub-user login returns correct flags: is_sub_user={data['user']['is_sub_user']}, parent_user_id={data['user']['parent_user_id']}")
    
    def test_sub_user_can_access_links(self):
        """Test that sub-user can access parent's links"""
        token = self.get_sub_user_token()
        
        response = self.session.get(f"{BASE_URL}/api/links", headers={
            "Authorization": f"Bearer {token}"
        })
        assert response.status_code == 200, f"Sub-user should be able to access links: {response.text}"
        links = response.json()
        print(f"✅ Sub-user can access links: {len(links)} links found")
    
    def test_sub_user_can_access_clicks(self):
        """Test that sub-user can access parent's clicks"""
        token = self.get_sub_user_token()
        
        response = self.session.get(f"{BASE_URL}/api/clicks", headers={
            "Authorization": f"Bearer {token}"
        })
        assert response.status_code == 200, f"Sub-user should be able to access clicks: {response.text}"
        clicks = response.json()
        print(f"✅ Sub-user can access clicks: {len(clicks)} clicks found")
    
    def test_sub_user_can_access_proxies(self):
        """Test that sub-user can access parent's proxies"""
        token = self.get_sub_user_token()
        
        response = self.session.get(f"{BASE_URL}/api/proxies", headers={
            "Authorization": f"Bearer {token}"
        })
        assert response.status_code == 200, f"Sub-user should be able to access proxies: {response.text}"
        proxies = response.json()
        print(f"✅ Sub-user can access proxies: {len(proxies)} proxies found")


class TestSubUserLinkCreation:
    """Test sub-user can create links stored under parent's account"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.created_link_id = None
        
    def teardown_method(self, method):
        """Cleanup created test links"""
        if self.created_link_id:
            try:
                # Use main user to delete the link
                response = self.session.post(f"{BASE_URL}/api/auth/login", json={
                    "email": MAIN_USER_EMAIL,
                    "password": MAIN_USER_PASSWORD
                })
                if response.status_code == 200:
                    token = response.json()["access_token"]
                    self.session.delete(f"{BASE_URL}/api/links/{self.created_link_id}", headers={
                        "Authorization": f"Bearer {token}"
                    })
            except:
                pass
    
    def get_main_user_token(self):
        """Get main user token"""
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": MAIN_USER_EMAIL,
            "password": MAIN_USER_PASSWORD
        })
        return response.json()["access_token"]
    
    def get_sub_user_token(self):
        """Get sub-user token"""
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": SUB_USER_EMAIL,
            "password": SUB_USER_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_sub_user_can_create_link(self):
        """Test that sub-user can create a link"""
        token = self.get_sub_user_token()
        
        unique_name = f"TEST_SubUserLink_{uuid.uuid4().hex[:8]}"
        response = self.session.post(f"{BASE_URL}/api/links", json={
            "offer_url": "https://example.com/subuser-test",
            "name": unique_name,
            "status": "active"
        }, headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert response.status_code == 200, f"Sub-user should be able to create link: {response.text}"
        link = response.json()
        self.created_link_id = link["id"]
        
        assert link["name"] == unique_name
        assert link["offer_url"] == "https://example.com/subuser-test"
        print(f"✅ Sub-user created link: {link['id']} with name {link['name']}")
        
        return link["id"], unique_name
    
    def test_main_user_can_see_subuser_created_link(self):
        """Test that main user can see links created by sub-user"""
        # First create a link as sub-user
        sub_token = self.get_sub_user_token()
        unique_name = f"TEST_SubUserLink_{uuid.uuid4().hex[:8]}"
        
        create_response = self.session.post(f"{BASE_URL}/api/links", json={
            "offer_url": "https://example.com/subuser-visible-test",
            "name": unique_name,
            "status": "active"
        }, headers={
            "Authorization": f"Bearer {sub_token}"
        })
        
        assert create_response.status_code == 200
        created_link = create_response.json()
        self.created_link_id = created_link["id"]
        
        # Now check as main user
        main_token = self.get_main_user_token()
        response = self.session.get(f"{BASE_URL}/api/links", headers={
            "Authorization": f"Bearer {main_token}"
        })
        
        assert response.status_code == 200
        links = response.json()
        
        # Find the link created by sub-user
        found_link = next((l for l in links if l["id"] == created_link["id"]), None)
        assert found_link is not None, f"Main user should see link created by sub-user: {created_link['id']}"
        print(f"✅ Main user can see sub-user created link: {found_link['name']}")


class TestLinkRestrictions:
    """Test link creation with OS, country, and VPN restrictions"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.created_link_ids = []
        
    def teardown_method(self, method):
        """Cleanup created test links"""
        try:
            response = self.session.post(f"{BASE_URL}/api/auth/login", json={
                "email": MAIN_USER_EMAIL,
                "password": MAIN_USER_PASSWORD
            })
            if response.status_code == 200:
                token = response.json()["access_token"]
                for link_id in self.created_link_ids:
                    self.session.delete(f"{BASE_URL}/api/links/{link_id}", headers={
                        "Authorization": f"Bearer {token}"
                    })
        except:
            pass
    
    def get_token(self):
        """Get main user token"""
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": MAIN_USER_EMAIL,
            "password": MAIN_USER_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_create_link_with_os_restriction(self):
        """Test creating link with OS restriction"""
        token = self.get_token()
        
        response = self.session.post(f"{BASE_URL}/api/links", json={
            "offer_url": "https://example.com/ios-only",
            "name": f"TEST_OSRestricted_{uuid.uuid4().hex[:8]}",
            "status": "active",
            "allowed_os": ["iOS", "Android"]
        }, headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert response.status_code == 200, f"Failed to create link with OS restriction: {response.text}"
        link = response.json()
        self.created_link_ids.append(link["id"])
        
        assert link["allowed_os"] == ["iOS", "Android"], f"OS restriction not saved: {link['allowed_os']}"
        print(f"✅ Created link with OS restriction: {link['allowed_os']}")
    
    def test_create_link_with_country_restriction(self):
        """Test creating link with country restriction"""
        token = self.get_token()
        
        response = self.session.post(f"{BASE_URL}/api/links", json={
            "offer_url": "https://example.com/us-only",
            "name": f"TEST_CountryRestricted_{uuid.uuid4().hex[:8]}",
            "status": "active",
            "allowed_countries": ["United States", "Canada"]
        }, headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert response.status_code == 200, f"Failed to create link with country restriction: {response.text}"
        link = response.json()
        self.created_link_ids.append(link["id"])
        
        assert link["allowed_countries"] == ["United States", "Canada"], f"Country restriction not saved: {link['allowed_countries']}"
        print(f"✅ Created link with country restriction: {link['allowed_countries']}")
    
    def test_create_link_with_vpn_block(self):
        """Test creating link with VPN blocking enabled"""
        token = self.get_token()
        
        response = self.session.post(f"{BASE_URL}/api/links", json={
            "offer_url": "https://example.com/no-vpn",
            "name": f"TEST_VPNBlocked_{uuid.uuid4().hex[:8]}",
            "status": "active",
            "block_vpn": True
        }, headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert response.status_code == 200, f"Failed to create link with VPN block: {response.text}"
        link = response.json()
        self.created_link_ids.append(link["id"])
        
        assert link["block_vpn"] == True, f"VPN block not saved: {link['block_vpn']}"
        print(f"✅ Created link with VPN block: block_vpn={link['block_vpn']}")
    
    def test_create_link_with_all_restrictions(self):
        """Test creating link with all restrictions combined"""
        token = self.get_token()
        
        response = self.session.post(f"{BASE_URL}/api/links", json={
            "offer_url": "https://example.com/restricted",
            "name": f"TEST_AllRestrictions_{uuid.uuid4().hex[:8]}",
            "status": "active",
            "allowed_os": ["iOS"],
            "allowed_countries": ["United States"],
            "block_vpn": True
        }, headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert response.status_code == 200, f"Failed to create link with all restrictions: {response.text}"
        link = response.json()
        self.created_link_ids.append(link["id"])
        
        assert link["allowed_os"] == ["iOS"]
        assert link["allowed_countries"] == ["United States"]
        assert link["block_vpn"] == True
        print(f"✅ Created link with all restrictions: OS={link['allowed_os']}, Countries={link['allowed_countries']}, VPN Block={link['block_vpn']}")


class TestClicksDateFilters:
    """Test clicks page date filters"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
    def get_token(self):
        """Get main user token"""
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": MAIN_USER_EMAIL,
            "password": MAIN_USER_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_clicks_filter_today(self):
        """Test clicks filter for today"""
        token = self.get_token()
        
        response = self.session.get(f"{BASE_URL}/api/clicks?filter_type=today", headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert response.status_code == 200, f"Failed to get today's clicks: {response.text}"
        clicks = response.json()
        print(f"✅ Today filter works: {len(clicks)} clicks")
    
    def test_clicks_filter_yesterday(self):
        """Test clicks filter for yesterday"""
        token = self.get_token()
        
        response = self.session.get(f"{BASE_URL}/api/clicks?filter_type=yesterday", headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert response.status_code == 200, f"Failed to get yesterday's clicks: {response.text}"
        clicks = response.json()
        print(f"✅ Yesterday filter works: {len(clicks)} clicks")
    
    def test_clicks_filter_week(self):
        """Test clicks filter for this week"""
        token = self.get_token()
        
        response = self.session.get(f"{BASE_URL}/api/clicks?filter_type=week", headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert response.status_code == 200, f"Failed to get this week's clicks: {response.text}"
        clicks = response.json()
        print(f"✅ Week filter works: {len(clicks)} clicks")
    
    def test_clicks_filter_month(self):
        """Test clicks filter for this month"""
        token = self.get_token()
        
        response = self.session.get(f"{BASE_URL}/api/clicks?filter_type=month", headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert response.status_code == 200, f"Failed to get this month's clicks: {response.text}"
        clicks = response.json()
        print(f"✅ Month filter works: {len(clicks)} clicks")
    
    def test_clicks_custom_date_range(self):
        """Test clicks with custom date range"""
        token = self.get_token()
        
        response = self.session.get(
            f"{BASE_URL}/api/clicks?start_date=2024-01-01T00:00:00Z&end_date=2025-12-31T23:59:59Z", 
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200, f"Failed to get clicks with custom date range: {response.text}"
        clicks = response.json()
        print(f"✅ Custom date range filter works: {len(clicks)} clicks")


class TestForgotPasswordFlow:
    """Test forgot password flow"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
    
    def test_forgot_password_request(self):
        """Test forgot password request generates token"""
        response = self.session.post(f"{BASE_URL}/api/auth/forgot-password", json={
            "email": MAIN_USER_EMAIL
        })
        
        assert response.status_code == 200, f"Forgot password request failed: {response.text}"
        data = response.json()
        
        assert "reset_token" in data, "Reset token should be returned"
        assert "reset_url" in data, "Reset URL should be returned"
        print(f"✅ Forgot password request works: token generated")
        
        return data["reset_token"]
    
    def test_verify_reset_token(self):
        """Test verify reset token endpoint"""
        # First get a reset token
        response = self.session.post(f"{BASE_URL}/api/auth/forgot-password", json={
            "email": MAIN_USER_EMAIL
        })
        assert response.status_code == 200
        token = response.json()["reset_token"]
        
        # Verify the token
        verify_response = self.session.get(f"{BASE_URL}/api/auth/verify-reset-token/{token}")
        
        assert verify_response.status_code == 200, f"Token verification failed: {verify_response.text}"
        data = verify_response.json()
        
        assert data["valid"] == True, "Token should be valid"
        assert data["email"] == MAIN_USER_EMAIL, "Email should match"
        print(f"✅ Token verification works: valid={data['valid']}, email={data['email']}")
    
    def test_invalid_reset_token(self):
        """Test that invalid reset token is rejected"""
        response = self.session.get(f"{BASE_URL}/api/auth/verify-reset-token/invalid-token-12345")
        
        assert response.status_code == 400, f"Invalid token should be rejected: {response.text}"
        print(f"✅ Invalid token correctly rejected")
    
    def test_reset_password_with_valid_token(self):
        """Test reset password with valid token"""
        # First get a reset token
        response = self.session.post(f"{BASE_URL}/api/auth/forgot-password", json={
            "email": MAIN_USER_EMAIL
        })
        assert response.status_code == 200
        token = response.json()["reset_token"]
        
        # Reset password (use same password to not break other tests)
        reset_response = self.session.post(f"{BASE_URL}/api/auth/reset-password", json={
            "token": token,
            "new_password": MAIN_USER_PASSWORD  # Keep same password
        })
        
        assert reset_response.status_code == 200, f"Password reset failed: {reset_response.text}"
        data = reset_response.json()
        
        assert "message" in data
        print(f"✅ Password reset works: {data['message']}")
    
    def test_reset_password_with_used_token(self):
        """Test that used token cannot be reused"""
        # First get a reset token
        response = self.session.post(f"{BASE_URL}/api/auth/forgot-password", json={
            "email": MAIN_USER_EMAIL
        })
        assert response.status_code == 200
        token = response.json()["reset_token"]
        
        # Use the token
        self.session.post(f"{BASE_URL}/api/auth/reset-password", json={
            "token": token,
            "new_password": MAIN_USER_PASSWORD
        })
        
        # Try to use it again
        reuse_response = self.session.post(f"{BASE_URL}/api/auth/reset-password", json={
            "token": token,
            "new_password": "newpassword123"
        })
        
        assert reuse_response.status_code == 400, f"Used token should be rejected: {reuse_response.text}"
        print(f"✅ Used token correctly rejected on reuse")


class TestPageAccessibility:
    """Test all pages are accessible for both main user and sub-user"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
    
    def get_main_user_token(self):
        """Get main user token"""
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": MAIN_USER_EMAIL,
            "password": MAIN_USER_PASSWORD
        })
        return response.json()["access_token"]
    
    def get_sub_user_token(self):
        """Get sub-user token"""
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": SUB_USER_EMAIL,
            "password": SUB_USER_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_main_user_can_access_all_endpoints(self):
        """Test main user can access all API endpoints"""
        token = self.get_main_user_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        endpoints = [
            ("/api/links", "Links"),
            ("/api/clicks", "Clicks"),
            ("/api/conversions", "Conversions"),
            ("/api/proxies", "Proxies"),
            ("/api/dashboard/stats", "Dashboard Stats"),
            ("/api/auth/me", "User Profile"),
            ("/api/sub-users", "Sub-Users"),
        ]
        
        for endpoint, name in endpoints:
            response = self.session.get(f"{BASE_URL}{endpoint}", headers=headers)
            assert response.status_code == 200, f"Main user should access {name}: {response.text}"
            print(f"✅ Main user can access {name}")
    
    def test_sub_user_can_access_data_endpoints(self):
        """Test sub-user can access data endpoints"""
        token = self.get_sub_user_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        endpoints = [
            ("/api/links", "Links"),
            ("/api/clicks", "Clicks"),
            ("/api/conversions", "Conversions"),
            ("/api/proxies", "Proxies"),
            ("/api/dashboard/stats", "Dashboard Stats"),
        ]
        
        for endpoint, name in endpoints:
            response = self.session.get(f"{BASE_URL}{endpoint}", headers=headers)
            assert response.status_code == 200, f"Sub-user should access {name}: {response.text}"
            print(f"✅ Sub-user can access {name}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
