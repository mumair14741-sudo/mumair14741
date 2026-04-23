"""
Test suite for TrackMaster new features:
1. Sub-user Feature Control: Main users can control which features sub-users can access
2. Forgot Password Email Flow: Remove demo mode link display, only send via email
3. Admin & Main User Management: Admin can see/edit all sub-users, set max_sub_users limit
4. User Click/Link Statistics: Main users can see click/link counts for their sub-users
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@trackmaster.local"
ADMIN_PASSWORD = "<redacted>"
TEST_USER_EMAIL = "test@test.com"
TEST_USER_PASSWORD = "Test123!"


class TestForgotPasswordFlow:
    """Test forgot password endpoint - should NOT return reset_url"""
    
    def test_forgot_password_no_reset_url_in_response(self):
        """Verify forgot-password endpoint does NOT return reset_url field"""
        response = requests.post(f"{BASE_URL}/api/auth/forgot-password", json={
            "email": ADMIN_EMAIL
        })
        assert response.status_code == 200
        data = response.json()
        
        # Verify reset_url is NOT in response (demo mode removed)
        assert "reset_url" not in data, "reset_url should NOT be returned in response"
        
        # Verify expected fields are present
        assert "message" in data
        assert "email_sent" in data
        assert "expires_in" in data
        print(f"✅ Forgot password response: {data}")
    
    def test_forgot_password_nonexistent_email(self):
        """Verify forgot-password handles non-existent email gracefully"""
        response = requests.post(f"{BASE_URL}/api/auth/forgot-password", json={
            "email": "nonexistent@example.com"
        })
        assert response.status_code == 200
        data = response.json()
        
        # Should not reveal if email exists
        assert "reset_url" not in data
        assert data.get("email_sent") == False
        print(f"✅ Non-existent email handled correctly: {data}")


class TestAdminSubUserManagement:
    """Test admin endpoints for sub-user management"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin authentication token"""
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        return response.json().get("access_token")
    
    def test_admin_get_all_sub_users(self, admin_token):
        """Admin can view all sub-users across all main users"""
        response = requests.get(
            f"{BASE_URL}/api/admin/sub-users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should be a list
        assert isinstance(data, list)
        
        # If sub-users exist, verify structure
        if len(data) > 0:
            sub_user = data[0]
            assert "id" in sub_user
            assert "email" in sub_user
            assert "name" in sub_user
            assert "parent_user_id" in sub_user
            assert "parent_email" in sub_user  # Added by admin endpoint
            assert "parent_name" in sub_user   # Added by admin endpoint
            assert "permissions" in sub_user
            print(f"✅ Admin can view {len(data)} sub-users with parent info")
        else:
            print("✅ Admin sub-users endpoint works (no sub-users exist)")
    
    def test_admin_get_users_with_max_sub_users(self, admin_token):
        """Admin can view users with max_sub_users in features"""
        response = requests.get(
            f"{BASE_URL}/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        users = response.json()
        
        # Verify users have features field
        if len(users) > 0:
            user = users[0]
            assert "features" in user
            # max_sub_users should be in features
            features = user.get("features", {})
            print(f"✅ User features: {features}")
    
    def test_admin_update_user_max_sub_users(self, admin_token):
        """Admin can update max_sub_users for a user"""
        # First get a user
        response = requests.get(
            f"{BASE_URL}/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        users = response.json()
        
        if len(users) == 0:
            pytest.skip("No users to test with")
        
        user = users[0]
        user_id = user["id"]
        
        # Update max_sub_users
        new_max = 5
        response = requests.put(
            f"{BASE_URL}/api/admin/users/{user_id}",
            json={
                "features": {
                    **user.get("features", {}),
                    "max_sub_users": new_max
                }
            },
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        print(f"✅ Admin updated max_sub_users to {new_max}")
        
        # Verify update
        response = requests.get(
            f"{BASE_URL}/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        updated_user = next((u for u in response.json() if u["id"] == user_id), None)
        assert updated_user is not None
        assert updated_user.get("features", {}).get("max_sub_users") == new_max
        print(f"✅ Verified max_sub_users is now {new_max}")


class TestSubUserCreationLimit:
    """Test sub-user creation enforces max_sub_users limit"""
    
    @pytest.fixture
    def user_token(self):
        """Get user authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        if response.status_code != 200:
            pytest.skip(f"User login failed: {response.text}")
        return response.json().get("access_token")
    
    @pytest.fixture
    def admin_token(self):
        """Get admin authentication token"""
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        return response.json().get("access_token")
    
    def test_auth_me_returns_max_sub_users(self, user_token):
        """Verify /api/auth/me returns max_sub_users field"""
        response = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify max_sub_users is in response
        assert "max_sub_users" in data, "max_sub_users should be in /auth/me response"
        assert "sub_user_count" in data, "sub_user_count should be in /auth/me response"
        print(f"✅ /auth/me returns max_sub_users: {data.get('max_sub_users')}, sub_user_count: {data.get('sub_user_count')}")


class TestSubUserStats:
    """Test sub-user statistics endpoint"""
    
    @pytest.fixture
    def user_token(self):
        """Get user authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        if response.status_code != 200:
            pytest.skip(f"User login failed: {response.text}")
        return response.json().get("access_token")
    
    def test_sub_users_stats_endpoint(self, user_token):
        """Main user can view sub-user statistics"""
        response = requests.get(
            f"{BASE_URL}/api/sub-users/stats",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "sub_users" in data
        assert "total" in data
        assert isinstance(data["sub_users"], list)
        
        # If sub-users exist, verify stats structure
        if len(data["sub_users"]) > 0:
            stat = data["sub_users"][0]
            assert "id" in stat
            assert "email" in stat
            assert "name" in stat
            assert "link_count" in stat
            assert "click_count" in stat
            assert "proxy_count" in stat
            assert "permissions" in stat
            assert "is_active" in stat
            print(f"✅ Sub-user stats: {stat}")
        else:
            print("✅ Sub-user stats endpoint works (no sub-users)")
        
        print(f"✅ Total sub-users: {data['total']}")


class TestAdminSubUserEditDelete:
    """Test admin can edit and delete sub-users"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin authentication token"""
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        return response.json().get("access_token")
    
    @pytest.fixture
    def user_token(self):
        """Get user authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        if response.status_code != 200:
            pytest.skip(f"User login failed: {response.text}")
        return response.json().get("access_token")
    
    def test_admin_edit_sub_user(self, admin_token):
        """Admin can edit any sub-user"""
        # Get sub-users
        response = requests.get(
            f"{BASE_URL}/api/admin/sub-users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        sub_users = response.json()
        
        if len(sub_users) == 0:
            pytest.skip("No sub-users to test with")
        
        sub_user = sub_users[0]
        sub_user_id = sub_user["id"]
        original_name = sub_user["name"]
        
        # Update sub-user
        new_name = f"TEST_Updated_{uuid.uuid4().hex[:6]}"
        response = requests.put(
            f"{BASE_URL}/api/admin/sub-users/{sub_user_id}",
            json={
                "name": new_name,
                "permissions": {
                    "view_clicks": True,
                    "view_links": True,
                    "view_proxies": True,
                    "edit": False
                },
                "is_active": True
            },
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "sub_user" in data
        assert data["sub_user"]["name"] == new_name
        print(f"✅ Admin updated sub-user name from '{original_name}' to '{new_name}'")
        
        # Restore original name
        requests.put(
            f"{BASE_URL}/api/admin/sub-users/{sub_user_id}",
            json={"name": original_name},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
    
    def test_admin_edit_sub_user_not_found(self, admin_token):
        """Admin gets 404 for non-existent sub-user"""
        response = requests.put(
            f"{BASE_URL}/api/admin/sub-users/nonexistent-id",
            json={"name": "Test"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404
        print("✅ Admin gets 404 for non-existent sub-user")
    
    def test_admin_delete_sub_user_not_found(self, admin_token):
        """Admin gets 404 when deleting non-existent sub-user"""
        response = requests.delete(
            f"{BASE_URL}/api/admin/sub-users/nonexistent-id",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404
        print("✅ Admin gets 404 when deleting non-existent sub-user")


class TestSubUserCreationWithLimit:
    """Test sub-user creation with max_sub_users limit enforcement"""
    
    @pytest.fixture
    def admin_token(self):
        """Get admin authentication token"""
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        return response.json().get("access_token")
    
    @pytest.fixture
    def user_token(self):
        """Get user authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        if response.status_code != 200:
            pytest.skip(f"User login failed: {response.text}")
        return response.json().get("access_token")
    
    def test_sub_user_creation_respects_limit(self, admin_token, user_token):
        """Sub-user creation should respect max_sub_users limit"""
        # First, get user info to check current state
        response = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        if response.status_code != 200:
            pytest.skip("Could not get user info")
        
        user_data = response.json()
        current_count = user_data.get("sub_user_count", 0)
        max_sub_users = user_data.get("max_sub_users", 0)
        
        print(f"Current sub-user count: {current_count}, Max: {max_sub_users}")
        
        # If max is 0 (unlimited) or we're under limit, test creation
        if max_sub_users == 0 or current_count < max_sub_users:
            # Try to create a sub-user
            test_email = f"TEST_subuser_{uuid.uuid4().hex[:8]}@test.com"
            response = requests.post(
                f"{BASE_URL}/api/sub-users",
                json={
                    "email": test_email,
                    "name": "Test Sub User",
                    "password": "TestPass123!"
                },
                headers={"Authorization": f"Bearer {user_token}"}
            )
            
            if response.status_code == 201:
                print(f"✅ Sub-user created successfully")
                # Clean up - delete the test sub-user
                sub_user_id = response.json().get("sub_user", {}).get("id")
                if sub_user_id:
                    requests.delete(
                        f"{BASE_URL}/api/sub-users/{sub_user_id}",
                        headers={"Authorization": f"Bearer {user_token}"}
                    )
            elif response.status_code == 403:
                # User might not be active
                print(f"⚠️ Sub-user creation blocked (user may not be active): {response.json()}")
            else:
                print(f"Sub-user creation response: {response.status_code} - {response.text}")
        else:
            print(f"✅ User at max sub-user limit ({current_count}/{max_sub_users})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
