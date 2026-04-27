"""
Test Admin Panel and IP Import Features
- Admin login/authentication
- Admin stats endpoint
- Admin user management (list, activate, block, edit)
- IP import feature
- Bulk delete clicks
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Admin credentials from .env
ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@trackmaster.local")
ADMIN_PASSWORD = "admin123"


class TestAdminAuthentication:
    """Test admin login and authentication"""
    
    def test_admin_login_success(self):
        """Test admin login with valid credentials"""
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["is_admin"] == True
    
    def test_admin_login_invalid_credentials(self):
        """Test admin login with invalid credentials"""
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": "wrong@example.com",
            "password": "wrongpass"
        })
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data
        assert "Invalid admin credentials" in data["detail"]
    
    def test_admin_stats_without_auth(self):
        """Test admin stats endpoint without authentication"""
        response = requests.get(f"{BASE_URL}/api/admin/stats")
        assert response.status_code == 401
    
    def test_admin_users_without_auth(self):
        """Test admin users endpoint without authentication"""
        response = requests.get(f"{BASE_URL}/api/admin/users")
        assert response.status_code == 401


class TestAdminStats:
    """Test admin statistics endpoint"""
    
    @pytest.fixture
    def admin_token(self):
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_admin_stats_returns_correct_structure(self, admin_token):
        """Test admin stats returns all required fields"""
        response = requests.get(
            f"{BASE_URL}/api/admin/stats",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify all required fields exist
        assert "total_users" in data
        assert "active_users" in data
        assert "pending_users" in data
        assert "blocked_users" in data
        assert "total_links" in data
        assert "total_clicks" in data
        assert "total_conversions" in data
        
        # Verify data types
        assert isinstance(data["total_users"], int)
        assert isinstance(data["active_users"], int)
        assert isinstance(data["pending_users"], int)
        assert isinstance(data["blocked_users"], int)


class TestAdminUserManagement:
    """Test admin user management features"""
    
    @pytest.fixture
    def admin_token(self):
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    @pytest.fixture
    def test_user(self, admin_token):
        """Create a test user for admin operations"""
        timestamp = int(time.time())
        email = f"TEST_admin_user_{timestamp}@example.com"
        
        # Register user
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpass123",
            "name": "TEST Admin Test User"
        })
        user_data = response.json()
        
        yield {
            "id": user_data["user"]["id"],
            "email": email,
            "token": user_data["access_token"]
        }
        
        # Cleanup - delete user after test
        requests.delete(
            f"{BASE_URL}/api/admin/users/{user_data['user']['id']}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
    
    def test_get_all_users(self, admin_token):
        """Test getting all users list"""
        response = requests.get(
            f"{BASE_URL}/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        
        if len(data) > 0:
            user = data[0]
            assert "id" in user
            assert "email" in user
            assert "name" in user
            assert "status" in user
            assert "features" in user
    
    def test_new_user_has_pending_status(self, test_user, admin_token):
        """Test that new users start with pending status"""
        response = requests.get(
            f"{BASE_URL}/api/admin/users/{test_user['id']}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["features"]["links"] == False
        assert data["features"]["clicks"] == False
    
    def test_activate_user(self, test_user, admin_token):
        """Test activating a user with full features"""
        response = requests.put(
            f"{BASE_URL}/api/admin/users/{test_user['id']}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "status": "active",
                "features": {
                    "links": True,
                    "clicks": True,
                    "conversions": True,
                    "proxies": True,
                    "import_data": True,
                    "max_links": 100,
                    "max_clicks": 100000
                }
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "User updated successfully"
        assert data["user"]["status"] == "active"
        assert data["user"]["features"]["links"] == True
        assert data["user"]["features"]["import_data"] == True
    
    def test_block_user(self, test_user, admin_token):
        """Test blocking a user"""
        response = requests.put(
            f"{BASE_URL}/api/admin/users/{test_user['id']}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"status": "blocked"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["status"] == "blocked"
    
    def test_blocked_user_cannot_login(self, test_user, admin_token):
        """Test that blocked users cannot login"""
        # First block the user
        requests.put(
            f"{BASE_URL}/api/admin/users/{test_user['id']}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"status": "blocked"}
        )
        
        # Try to login
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": test_user["email"],
            "password": "testpass123"
        })
        assert response.status_code == 403
        assert "blocked" in response.json()["detail"].lower()
    
    def test_update_user_features(self, test_user, admin_token):
        """Test updating specific user features"""
        response = requests.put(
            f"{BASE_URL}/api/admin/users/{test_user['id']}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "features": {
                    "links": True,
                    "clicks": True,
                    "conversions": False,
                    "proxies": False,
                    "import_data": False,
                    "max_links": 50,
                    "max_clicks": 5000
                }
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["features"]["links"] == True
        assert data["user"]["features"]["conversions"] == False
        assert data["user"]["features"]["max_links"] == 50
    
    def test_add_subscription_note(self, test_user, admin_token):
        """Test adding subscription note to user"""
        response = requests.put(
            f"{BASE_URL}/api/admin/users/{test_user['id']}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"subscription_note": "Premium user - paid via PayPal"}
        )
        assert response.status_code == 200
        
        # Verify note was saved
        get_response = requests.get(
            f"{BASE_URL}/api/admin/users/{test_user['id']}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert get_response.json()["subscription_note"] == "Premium user - paid via PayPal"


class TestIPImport:
    """Test IP list import feature"""
    
    @pytest.fixture
    def admin_token(self):
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    @pytest.fixture
    def activated_user(self, admin_token):
        """Create and activate a user with import permission"""
        timestamp = int(time.time())
        email = f"TEST_import_user_{timestamp}@example.com"
        
        # Register user
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpass123",
            "name": "TEST Import User"
        })
        user_data = response.json()
        user_id = user_data["user"]["id"]
        
        # Activate with import permission
        requests.put(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "status": "active",
                "features": {
                    "links": True,
                    "clicks": True,
                    "conversions": True,
                    "proxies": True,
                    "import_data": True,
                    "max_links": 100,
                    "max_clicks": 100000
                }
            }
        )
        
        # Login to get fresh token
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": email,
            "password": "testpass123"
        })
        
        yield {
            "id": user_id,
            "email": email,
            "token": login_response.json()["access_token"]
        }
        
        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
    
    @pytest.fixture
    def test_link(self, activated_user):
        """Create a test link for IP import"""
        response = requests.post(
            f"{BASE_URL}/api/links",
            headers={"Authorization": f"Bearer {activated_user['token']}"},
            json={
                "offer_url": "https://example.com/test-offer",
                "name": "TEST IP Import Link"
            }
        )
        link_data = response.json()
        
        yield link_data
        
        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/links/{link_data['id']}",
            headers={"Authorization": f"Bearer {activated_user['token']}"}
        )
    
    def test_import_ips_success(self, activated_user, test_link):
        """Test successful IP import"""
        response = requests.post(
            f"{BASE_URL}/api/clicks/import-ips",
            headers={"Authorization": f"Bearer {activated_user['token']}"},
            json={
                "link_id": test_link["id"],
                "ip_list": ["192.168.1.1", "10.0.0.1", "172.16.0.1"],
                "country": "United States"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["imported"] == 3
        assert "Successfully imported" in data["message"]
    
    def test_import_ips_without_permission(self, admin_token):
        """Test IP import fails for user without permission"""
        # Create user without import permission
        timestamp = int(time.time())
        email = f"TEST_no_import_{timestamp}@example.com"
        
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpass123",
            "name": "TEST No Import User"
        })
        user_data = response.json()
        user_token = user_data["access_token"]
        user_id = user_data["user"]["id"]
        
        # Try to import without permission
        import_response = requests.post(
            f"{BASE_URL}/api/clicks/import-ips",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "link_id": "some-link-id",
                "ip_list": ["192.168.1.1"],
                "country": "US"
            }
        )
        assert import_response.status_code == 403
        
        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
    
    def test_import_ips_invalid_link(self, activated_user):
        """Test IP import fails for invalid link"""
        response = requests.post(
            f"{BASE_URL}/api/clicks/import-ips",
            headers={"Authorization": f"Bearer {activated_user['token']}"},
            json={
                "link_id": "invalid-link-id",
                "ip_list": ["192.168.1.1"],
                "country": "US"
            }
        )
        assert response.status_code == 404


class TestBulkDeleteClicks:
    """Test bulk delete clicks feature"""
    
    @pytest.fixture
    def admin_token(self):
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    @pytest.fixture
    def user_with_clicks(self, admin_token):
        """Create user with link and imported clicks"""
        timestamp = int(time.time())
        email = f"TEST_bulk_delete_{timestamp}@example.com"
        
        # Register and activate user
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpass123",
            "name": "TEST Bulk Delete User"
        })
        user_data = response.json()
        user_id = user_data["user"]["id"]
        
        requests.put(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "status": "active",
                "features": {
                    "links": True,
                    "clicks": True,
                    "import_data": True,
                    "max_links": 100,
                    "max_clicks": 100000
                }
            }
        )
        
        # Login
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": email,
            "password": "testpass123"
        })
        user_token = login_response.json()["access_token"]
        
        # Create link
        link_response = requests.post(
            f"{BASE_URL}/api/links",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"offer_url": "https://example.com/bulk-test", "name": "TEST Bulk Delete Link"}
        )
        link_id = link_response.json()["id"]
        
        # Import some clicks
        requests.post(
            f"{BASE_URL}/api/clicks/import-ips",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "link_id": link_id,
                "ip_list": ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"],
                "country": "Test Country"
            }
        )
        
        yield {
            "id": user_id,
            "token": user_token,
            "link_id": link_id
        }
        
        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
    
    def test_bulk_delete_clicks(self, user_with_clicks):
        """Test bulk delete clicks"""
        # Get click IDs
        clicks_response = requests.get(
            f"{BASE_URL}/api/clicks?limit=10",
            headers={"Authorization": f"Bearer {user_with_clicks['token']}"}
        )
        clicks = clicks_response.json()
        click_ids = [c["id"] for c in clicks[:2]]
        
        # Bulk delete
        response = requests.post(
            f"{BASE_URL}/api/clicks/bulk-delete",
            headers={"Authorization": f"Bearer {user_with_clicks['token']}"},
            json=click_ids
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 2
    
    def test_bulk_delete_empty_list(self, user_with_clicks):
        """Test bulk delete with empty list"""
        response = requests.post(
            f"{BASE_URL}/api/clicks/bulk-delete",
            headers={"Authorization": f"Bearer {user_with_clicks['token']}"},
            json=[]
        )
        assert response.status_code == 200
        assert response.json()["deleted_count"] == 0


class TestUserRegistrationFlow:
    """Test user registration creates pending user"""
    
    @pytest.fixture
    def admin_token(self):
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_registration_creates_pending_user(self, admin_token):
        """Test that new registration creates user with pending status"""
        timestamp = int(time.time())
        email = f"TEST_pending_{timestamp}@example.com"
        
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpass123",
            "name": "TEST Pending User"
        })
        assert response.status_code == 200
        data = response.json()
        
        # Verify user status is pending
        assert data["user"]["status"] == "pending"
        
        # Verify features are all disabled
        features = data["user"]["features"]
        assert features["links"] == False
        assert features["clicks"] == False
        assert features["conversions"] == False
        assert features["proxies"] == False
        assert features.get("import", False) == False
        
        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/admin/users/{data['user']['id']}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
    
    def test_auth_me_returns_admin_contact(self, admin_token):
        """Test that /auth/me returns admin contact email"""
        timestamp = int(time.time())
        email = f"TEST_contact_{timestamp}@example.com"
        
        # Register user
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpass123",
            "name": "TEST Contact User"
        })
        user_token = response.json()["access_token"]
        user_id = response.json()["user"]["id"]
        
        # Get user profile
        me_response = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert me_response.status_code == 200
        data = me_response.json()
        assert "admin_contact" in data
        assert data["admin_contact"] == os.environ.get("TEST_ADMIN_EMAIL", "admin@trackmaster.local")
        
        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
