"""
Test Suite for Sub-User Management, User Settings, and Admin Subscription Features
Tests the following features:
1. Sub-user CRUD operations (create, read, update, delete)
2. User profile update (name, password change)
3. Admin user editing (email, password, subscription type, expiration)
4. Subscription management
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials — read from env; fall back to local defaults
ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@trackmaster.local")
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "admin123")
TEST_USER_EMAIL = os.environ.get("TEST_USER_EMAIL", "vpntest@example.com")
TEST_USER_PASSWORD = os.environ.get("TEST_USER_PASSWORD", "vpntest123")
SUB_USER_DEFAULT_PASSWORD = os.environ.get("TEST_SUB_USER_PASSWORD", "subuser123")
MAIN_USER_DEFAULT_PASSWORD = os.environ.get("TEST_MAIN_USER_PASSWORD", "test123")


class TestSubUserManagement:
    """Test sub-user CRUD operations"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup - login as test user"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as test user
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        self.token = response.json()["access_token"]
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        self.user_id = response.json()["user"]["id"]
        
        yield
        
        # Cleanup - delete any test sub-users created
        try:
            sub_users = self.session.get(f"{BASE_URL}/api/sub-users").json()
            for sub_user in sub_users:
                if sub_user.get("email", "").startswith("TEST_"):
                    self.session.delete(f"{BASE_URL}/api/sub-users/{sub_user['id']}")
        except:
            pass
    
    def test_create_sub_user(self):
        """Test creating a sub-user"""
        unique_id = str(uuid.uuid4())[:8]
        sub_user_data = {
            "email": f"TEST_subuser_{unique_id}@example.com",
            "password": "subuser123",
            "name": f"Test SubUser {unique_id}",
            "permissions": {
                "view_clicks": True,
                "view_links": True,
                "view_proxies": False,
                "edit": False
            }
        }
        
        response = self.session.post(f"{BASE_URL}/api/sub-users", json=sub_user_data)
        assert response.status_code == 200, f"Create sub-user failed: {response.text}"
        
        data = response.json()
        assert "sub_user" in data
        assert data["sub_user"]["email"] == sub_user_data["email"]
        assert data["sub_user"]["name"] == sub_user_data["name"]
        assert data["sub_user"]["permissions"]["view_clicks"] == True
        assert data["sub_user"]["permissions"]["view_links"] == True
        assert "id" in data["sub_user"]
        
        # Cleanup
        self.session.delete(f"{BASE_URL}/api/sub-users/{data['sub_user']['id']}")
        print("✅ Create sub-user works correctly")
    
    def test_get_sub_users(self):
        """Test getting list of sub-users"""
        # First create a sub-user
        unique_id = str(uuid.uuid4())[:8]
        create_response = self.session.post(f"{BASE_URL}/api/sub-users", json={
            "email": f"TEST_list_{unique_id}@example.com",
            "password": "test123",
            "name": f"Test List {unique_id}"
        })
        assert create_response.status_code == 200
        sub_user_id = create_response.json()["sub_user"]["id"]
        
        # Get sub-users list
        response = self.session.get(f"{BASE_URL}/api/sub-users")
        assert response.status_code == 200, f"Get sub-users failed: {response.text}"
        
        data = response.json()
        assert isinstance(data, list)
        
        # Verify our created sub-user is in the list
        found = any(su["id"] == sub_user_id for su in data)
        assert found, "Created sub-user not found in list"
        
        # Cleanup
        self.session.delete(f"{BASE_URL}/api/sub-users/{sub_user_id}")
        print("✅ Get sub-users list works correctly")
    
    def test_update_sub_user(self):
        """Test updating a sub-user"""
        # Create sub-user first
        unique_id = str(uuid.uuid4())[:8]
        create_response = self.session.post(f"{BASE_URL}/api/sub-users", json={
            "email": f"TEST_update_{unique_id}@example.com",
            "password": "test123",
            "name": f"Original Name {unique_id}"
        })
        assert create_response.status_code == 200
        sub_user_id = create_response.json()["sub_user"]["id"]
        
        # Update sub-user
        update_data = {
            "name": f"Updated Name {unique_id}",
            "permissions": {
                "view_clicks": True,
                "view_links": True,
                "view_proxies": True,
                "edit": True
            },
            "is_active": False
        }
        
        response = self.session.put(f"{BASE_URL}/api/sub-users/{sub_user_id}", json=update_data)
        assert response.status_code == 200, f"Update sub-user failed: {response.text}"
        
        data = response.json()
        assert data["sub_user"]["name"] == update_data["name"]
        assert data["sub_user"]["permissions"]["view_proxies"] == True
        assert data["sub_user"]["is_active"] == False
        
        # Cleanup
        self.session.delete(f"{BASE_URL}/api/sub-users/{sub_user_id}")
        print("✅ Update sub-user works correctly")
    
    def test_delete_sub_user(self):
        """Test deleting a sub-user"""
        # Create sub-user first
        unique_id = str(uuid.uuid4())[:8]
        create_response = self.session.post(f"{BASE_URL}/api/sub-users", json={
            "email": f"TEST_delete_{unique_id}@example.com",
            "password": "test123",
            "name": f"To Delete {unique_id}"
        })
        assert create_response.status_code == 200
        sub_user_id = create_response.json()["sub_user"]["id"]
        
        # Delete sub-user
        response = self.session.delete(f"{BASE_URL}/api/sub-users/{sub_user_id}")
        assert response.status_code == 200, f"Delete sub-user failed: {response.text}"
        
        # Verify deletion - should not be in list
        list_response = self.session.get(f"{BASE_URL}/api/sub-users")
        sub_users = list_response.json()
        found = any(su["id"] == sub_user_id for su in sub_users)
        assert not found, "Deleted sub-user still in list"
        
        print("✅ Delete sub-user works correctly")
    
    def test_sub_user_duplicate_email_rejected(self):
        """Test that duplicate email is rejected for sub-users"""
        unique_id = str(uuid.uuid4())[:8]
        email = f"TEST_dup_{unique_id}@example.com"
        
        # Create first sub-user
        response1 = self.session.post(f"{BASE_URL}/api/sub-users", json={
            "email": email,
            "password": "test123",
            "name": "First SubUser"
        })
        assert response1.status_code == 200
        sub_user_id = response1.json()["sub_user"]["id"]
        
        # Try to create second with same email
        response2 = self.session.post(f"{BASE_URL}/api/sub-users", json={
            "email": email,
            "password": "test456",
            "name": "Second SubUser"
        })
        assert response2.status_code == 400, "Duplicate email should be rejected"
        
        # Cleanup
        self.session.delete(f"{BASE_URL}/api/sub-users/{sub_user_id}")
        print("✅ Duplicate sub-user email correctly rejected")


class TestUserProfileUpdate:
    """Test user profile update functionality"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup - login as test user"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as test user
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        self.token = response.json()["access_token"]
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        
        yield
    
    def test_update_profile_name(self):
        """Test updating user's name"""
        # Get current user info
        me_response = self.session.get(f"{BASE_URL}/api/auth/me")
        original_name = me_response.json()["name"]
        
        # Update name
        new_name = f"Updated Name {str(uuid.uuid4())[:4]}"
        response = self.session.put(f"{BASE_URL}/api/auth/profile", json={
            "name": new_name
        })
        assert response.status_code == 200, f"Update profile failed: {response.text}"
        
        # Verify update
        data = response.json()
        assert data["user"]["name"] == new_name
        
        # Restore original name
        self.session.put(f"{BASE_URL}/api/auth/profile", json={"name": original_name})
        print("✅ Update profile name works correctly")
    
    def test_update_password_requires_current(self):
        """Test that password change requires current password"""
        response = self.session.put(f"{BASE_URL}/api/auth/profile", json={
            "new_password": "newpassword123"
        })
        assert response.status_code == 400, "Should require current password"
        assert "current password" in response.json().get("detail", "").lower()
        print("✅ Password change correctly requires current password")
    
    def test_update_password_wrong_current(self):
        """Test that wrong current password is rejected"""
        response = self.session.put(f"{BASE_URL}/api/auth/profile", json={
            "current_password": "wrongpassword",
            "new_password": "newpassword123"
        })
        assert response.status_code == 400, "Wrong current password should be rejected"
        print("✅ Wrong current password correctly rejected")
    
    def test_get_me_returns_subscription_info(self):
        """Test that /auth/me returns subscription info"""
        response = self.session.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200
        
        data = response.json()
        assert "subscription_type" in data
        assert "subscription_expires" in data or data.get("subscription_expires") is None
        assert "sub_user_count" in data
        assert "admin_contact" in data
        print("✅ /auth/me returns subscription info correctly")


class TestAdminUserEditing:
    """Test admin user editing functionality"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup - login as admin"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as admin
        response = self.session.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        self.token = response.json()["access_token"]
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        
        yield
    
    def test_admin_can_update_user_email(self):
        """Test admin can update user email"""
        # First create a test user
        unique_id = str(uuid.uuid4())[:8]
        original_email = f"TEST_email_{unique_id}@example.com"
        
        # Register user
        reg_session = requests.Session()
        reg_response = reg_session.post(f"{BASE_URL}/api/auth/register", json={
            "email": original_email,
            "password": "test123",
            "name": f"Test User {unique_id}"
        })
        assert reg_response.status_code == 200
        user_id = reg_response.json()["user"]["id"]
        
        # Admin updates email
        new_email = f"TEST_newemail_{unique_id}@example.com"
        response = self.session.put(f"{BASE_URL}/api/admin/users/{user_id}", json={
            "email": new_email
        })
        assert response.status_code == 200, f"Admin update email failed: {response.text}"
        
        # Verify email was updated
        data = response.json()
        assert data["user"]["email"] == new_email
        
        # Cleanup - delete test user
        self.session.delete(f"{BASE_URL}/api/admin/users/{user_id}")
        print("✅ Admin can update user email")
    
    def test_admin_can_update_user_password(self):
        """Test admin can update user password"""
        # Create test user
        unique_id = str(uuid.uuid4())[:8]
        email = f"TEST_pwd_{unique_id}@example.com"
        
        reg_session = requests.Session()
        reg_response = reg_session.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "oldpassword123",
            "name": f"Test User {unique_id}"
        })
        assert reg_response.status_code == 200
        user_id = reg_response.json()["user"]["id"]
        
        # Admin updates password
        new_password = "newpassword456"
        response = self.session.put(f"{BASE_URL}/api/admin/users/{user_id}", json={
            "password": new_password,
            "status": "active"  # Activate so we can test login
        })
        assert response.status_code == 200, f"Admin update password failed: {response.text}"
        
        # Verify new password works
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": email,
            "password": new_password
        })
        assert login_response.status_code == 200, "Login with new password should work"
        
        # Cleanup
        self.session.delete(f"{BASE_URL}/api/admin/users/{user_id}")
        print("✅ Admin can update user password")
    
    def test_admin_can_set_subscription_type(self):
        """Test admin can set subscription type"""
        # Create test user
        unique_id = str(uuid.uuid4())[:8]
        email = f"TEST_sub_{unique_id}@example.com"
        
        reg_session = requests.Session()
        reg_response = reg_session.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "test123",
            "name": f"Test User {unique_id}"
        })
        assert reg_response.status_code == 200
        user_id = reg_response.json()["user"]["id"]
        
        # Admin sets subscription type
        response = self.session.put(f"{BASE_URL}/api/admin/users/{user_id}", json={
            "subscription_type": "monthly"
        })
        assert response.status_code == 200, f"Admin set subscription failed: {response.text}"
        
        # Verify subscription type
        data = response.json()
        assert data["user"]["subscription_type"] == "monthly"
        
        # Cleanup
        self.session.delete(f"{BASE_URL}/api/admin/users/{user_id}")
        print("✅ Admin can set subscription type")
    
    def test_admin_can_set_subscription_expiration(self):
        """Test admin can set subscription expiration date"""
        # Create test user
        unique_id = str(uuid.uuid4())[:8]
        email = f"TEST_exp_{unique_id}@example.com"
        
        reg_session = requests.Session()
        reg_response = reg_session.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "test123",
            "name": f"Test User {unique_id}"
        })
        assert reg_response.status_code == 200
        user_id = reg_response.json()["user"]["id"]
        
        # Admin sets subscription expiration
        expiration_date = "2026-12-31"
        response = self.session.put(f"{BASE_URL}/api/admin/users/{user_id}", json={
            "subscription_type": "yearly",
            "subscription_expires": expiration_date
        })
        assert response.status_code == 200, f"Admin set expiration failed: {response.text}"
        
        # Verify expiration
        data = response.json()
        assert data["user"]["subscription_expires"] == expiration_date
        assert data["user"]["subscription_type"] == "yearly"
        
        # Cleanup
        self.session.delete(f"{BASE_URL}/api/admin/users/{user_id}")
        print("✅ Admin can set subscription expiration")
    
    def test_admin_users_list_includes_sub_user_count(self):
        """Test admin users list includes sub_user_count"""
        response = self.session.get(f"{BASE_URL}/api/admin/users")
        assert response.status_code == 200
        
        users = response.json()
        assert len(users) > 0
        
        # Check that sub_user_count field exists
        for user in users:
            assert "sub_user_count" in user, f"User {user.get('email')} missing sub_user_count"
        
        print("✅ Admin users list includes sub_user_count")
    
    def test_admin_stats_includes_sub_user_stats(self):
        """Test admin stats includes sub-user statistics"""
        response = self.session.get(f"{BASE_URL}/api/admin/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert "total_sub_users" in data
        assert "users_with_sub_users" in data
        
        print("✅ Admin stats includes sub-user statistics")
    
    def test_admin_duplicate_email_rejected(self):
        """Test admin cannot set duplicate email"""
        # Get existing user
        users_response = self.session.get(f"{BASE_URL}/api/admin/users")
        users = users_response.json()
        
        if len(users) < 2:
            pytest.skip("Need at least 2 users to test duplicate email")
        
        # Try to set user1's email to user2's email
        user1 = users[0]
        user2 = users[1]
        
        response = self.session.put(f"{BASE_URL}/api/admin/users/{user1['id']}", json={
            "email": user2["email"]
        })
        assert response.status_code == 400, "Duplicate email should be rejected"
        
        print("✅ Admin duplicate email correctly rejected")


class TestSubUserLogin:
    """Test sub-user login functionality"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup - login as test user and create a sub-user"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as test user
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        assert response.status_code == 200
        self.token = response.json()["access_token"]
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        
        # Create a sub-user for testing
        self.unique_id = str(uuid.uuid4())[:8]
        self.sub_user_email = f"TEST_login_{self.unique_id}@example.com"
        self.sub_user_password = "subuser123"
        
        create_response = self.session.post(f"{BASE_URL}/api/sub-users", json={
            "email": self.sub_user_email,
            "password": self.sub_user_password,
            "name": f"Login Test {self.unique_id}"
        })
        assert create_response.status_code == 200
        self.sub_user_id = create_response.json()["sub_user"]["id"]
        
        yield
        
        # Cleanup
        try:
            self.session.delete(f"{BASE_URL}/api/sub-users/{self.sub_user_id}")
        except:
            pass
    
    def test_sub_user_can_login(self):
        """Test sub-user can login with their credentials"""
        response = requests.post(f"{BASE_URL}/api/sub-users/login", json={
            "email": self.sub_user_email,
            "password": self.sub_user_password
        })
        assert response.status_code == 200, f"Sub-user login failed: {response.text}"
        
        data = response.json()
        assert "access_token" in data
        assert data["user"]["is_sub_user"] == True
        assert "parent_user_id" in data["user"]
        assert "permissions" in data["user"]
        
        print("✅ Sub-user can login successfully")
    
    def test_sub_user_wrong_password_rejected(self):
        """Test sub-user login with wrong password is rejected"""
        response = requests.post(f"{BASE_URL}/api/sub-users/login", json={
            "email": self.sub_user_email,
            "password": "wrongpassword"
        })
        assert response.status_code == 401, "Wrong password should be rejected"
        
        print("✅ Sub-user wrong password correctly rejected")
    
    def test_deactivated_sub_user_cannot_login(self):
        """Test deactivated sub-user cannot login"""
        # Deactivate sub-user
        self.session.put(f"{BASE_URL}/api/sub-users/{self.sub_user_id}", json={
            "is_active": False
        })
        
        # Try to login
        response = requests.post(f"{BASE_URL}/api/sub-users/login", json={
            "email": self.sub_user_email,
            "password": self.sub_user_password
        })
        assert response.status_code == 403, "Deactivated sub-user should not be able to login"
        
        print("✅ Deactivated sub-user correctly cannot login")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
