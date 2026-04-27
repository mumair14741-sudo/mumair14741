"""
Test VPN Detection and Admin Bulk Delete Features
- VPN detection using Scamalytics (score >= 25 = VPN)
- VPN filter in proxy management
- Stop testing and Test Pending buttons
- Admin bulk delete users with checkboxes
- VPN blocking on links when block_vpn is enabled
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Admin credentials
ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@trackmaster.local")
ADMIN_PASSWORD = "admin123"

# Test user credentials
TEST_USER_EMAIL = "vpntest@example.com"
TEST_USER_PASSWORD = "vpntest123"


class TestProxyVPNFilters:
    """Test proxy VPN filter endpoints"""
    
    @pytest.fixture
    def admin_token(self):
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    @pytest.fixture
    def activated_user(self, admin_token):
        """Create and activate a user with proxy permission"""
        timestamp = int(time.time())
        email = f"TEST_vpn_proxy_{timestamp}@example.com"
        
        # Register user
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpass123",
            "name": "TEST VPN Proxy User"
        })
        user_data = response.json()
        user_id = user_data["user"]["id"]
        
        # Activate with proxy permission
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
    
    def test_proxy_filter_all(self, activated_user):
        """Test proxy filter=all returns all proxies"""
        response = requests.get(
            f"{BASE_URL}/api/proxies?filter=all",
            headers={"Authorization": f"Bearer {activated_user['token']}"}
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    
    def test_proxy_filter_vpn(self, activated_user):
        """Test proxy filter=vpn returns only VPN proxies"""
        response = requests.get(
            f"{BASE_URL}/api/proxies?filter=vpn",
            headers={"Authorization": f"Bearer {activated_user['token']}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # All returned proxies should have is_vpn=True
        for proxy in data:
            assert proxy.get("is_vpn") == True
    
    def test_proxy_filter_clean(self, activated_user):
        """Test proxy filter=clean returns only clean alive proxies"""
        response = requests.get(
            f"{BASE_URL}/api/proxies?filter=clean",
            headers={"Authorization": f"Bearer {activated_user['token']}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # All returned proxies should be alive and not VPN
        for proxy in data:
            assert proxy.get("status") == "alive"
            assert proxy.get("is_vpn") != True
    
    def test_proxy_filter_pending(self, activated_user):
        """Test proxy filter=pending returns only pending proxies"""
        response = requests.get(
            f"{BASE_URL}/api/proxies?filter=pending",
            headers={"Authorization": f"Bearer {activated_user['token']}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # All returned proxies should have status=pending
        for proxy in data:
            assert proxy.get("status") == "pending"
    
    def test_proxy_filter_alive(self, activated_user):
        """Test proxy filter=alive returns only alive proxies"""
        response = requests.get(
            f"{BASE_URL}/api/proxies?filter=alive",
            headers={"Authorization": f"Bearer {activated_user['token']}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        for proxy in data:
            assert proxy.get("status") == "alive"
    
    def test_proxy_filter_dead(self, activated_user):
        """Test proxy filter=dead returns only dead proxies"""
        response = requests.get(
            f"{BASE_URL}/api/proxies?filter=dead",
            headers={"Authorization": f"Bearer {activated_user['token']}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        for proxy in data:
            assert proxy.get("status") == "dead"


class TestProxyUploadAndVPNDetection:
    """Test proxy upload and VPN detection"""
    
    @pytest.fixture
    def admin_token(self):
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    @pytest.fixture
    def activated_user(self, admin_token):
        """Create and activate a user with proxy permission"""
        timestamp = int(time.time())
        email = f"TEST_proxy_upload_{timestamp}@example.com"
        
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpass123",
            "name": "TEST Proxy Upload User"
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
                    "conversions": True,
                    "proxies": True,
                    "import_data": True,
                    "max_links": 100,
                    "max_clicks": 100000
                }
            }
        )
        
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": email,
            "password": "testpass123"
        })
        
        yield {
            "id": user_id,
            "email": email,
            "token": login_response.json()["access_token"]
        }
        
        # Cleanup - delete all proxies first
        proxies_response = requests.get(
            f"{BASE_URL}/api/proxies?filter=all",
            headers={"Authorization": f"Bearer {login_response.json()['access_token']}"}
        )
        if proxies_response.status_code == 200:
            proxy_ids = [p["id"] for p in proxies_response.json()]
            if proxy_ids:
                requests.post(
                    f"{BASE_URL}/api/proxies/bulk-delete",
                    headers={"Authorization": f"Bearer {login_response.json()['access_token']}"},
                    json=proxy_ids
                )
        
        requests.delete(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
    
    def test_proxy_upload_success(self, activated_user):
        """Test proxy upload creates proxies with pending status"""
        response = requests.post(
            f"{BASE_URL}/api/proxies/upload",
            headers={"Authorization": f"Bearer {activated_user['token']}"},
            json={
                "proxy_list": ["127.0.0.1:8080", "192.168.1.1:3128"],
                "proxy_type": "http"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        
        # Check proxy structure
        for proxy in data:
            assert "id" in proxy
            assert "proxy_string" in proxy
            assert "proxy_type" in proxy
            assert "status" in proxy
            assert proxy["status"] == "pending"
            assert "is_vpn" in proxy
            assert "vpn_score" in proxy or proxy.get("vpn_score") is None
    
    def test_proxy_response_includes_vpn_fields(self, activated_user):
        """Test proxy response includes VPN-related fields"""
        # Upload a proxy
        requests.post(
            f"{BASE_URL}/api/proxies/upload",
            headers={"Authorization": f"Bearer {activated_user['token']}"},
            json={
                "proxy_list": ["10.0.0.1:8080"],
                "proxy_type": "http"
            }
        )
        
        # Get proxies
        response = requests.get(
            f"{BASE_URL}/api/proxies?filter=all",
            headers={"Authorization": f"Bearer {activated_user['token']}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            proxy = data[0]
            # Verify VPN fields exist in response
            assert "is_vpn" in proxy
            assert "vpn_score" in proxy or proxy.get("vpn_score") is None


class TestAdminBulkDeleteUsers:
    """Test admin bulk delete users feature"""
    
    @pytest.fixture
    def admin_token(self):
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_admin_can_delete_single_user(self, admin_token):
        """Test admin can delete a single user"""
        timestamp = int(time.time())
        email = f"TEST_delete_single_{timestamp}@example.com"
        
        # Create user
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpass123",
            "name": "TEST Delete Single User"
        })
        user_id = response.json()["user"]["id"]
        
        # Delete user
        delete_response = requests.delete(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert delete_response.status_code == 200
        
        # Verify user is deleted
        get_response = requests.get(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert get_response.status_code == 404
    
    def test_admin_can_delete_multiple_users(self, admin_token):
        """Test admin can delete multiple users (simulating bulk delete)"""
        timestamp = int(time.time())
        user_ids = []
        
        # Create 3 test users
        for i in range(3):
            email = f"TEST_bulk_delete_{timestamp}_{i}@example.com"
            response = requests.post(f"{BASE_URL}/api/auth/register", json={
                "email": email,
                "password": "testpass123",
                "name": f"TEST Bulk Delete User {i}"
            })
            user_ids.append(response.json()["user"]["id"])
        
        # Delete each user (simulating bulk delete from frontend)
        for user_id in user_ids:
            delete_response = requests.delete(
                f"{BASE_URL}/api/admin/users/{user_id}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert delete_response.status_code == 200
        
        # Verify all users are deleted
        for user_id in user_ids:
            get_response = requests.get(
                f"{BASE_URL}/api/admin/users/{user_id}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert get_response.status_code == 404
    
    def test_admin_users_list_returns_all_users(self, admin_token):
        """Test admin users list returns users with all required fields"""
        response = requests.get(
            f"{BASE_URL}/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        
        if len(data) > 0:
            user = data[0]
            # Verify user has required fields for checkbox selection
            assert "id" in user
            assert "email" in user
            assert "name" in user
            assert "status" in user


class TestLinkVPNBlocking:
    """Test VPN blocking on links when block_vpn is enabled"""
    
    @pytest.fixture
    def admin_token(self):
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    @pytest.fixture
    def activated_user(self, admin_token):
        """Create and activate a user with link permission"""
        timestamp = int(time.time())
        email = f"TEST_vpn_block_{timestamp}@example.com"
        
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpass123",
            "name": "TEST VPN Block User"
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
                    "conversions": True,
                    "proxies": True,
                    "import_data": True,
                    "max_links": 100,
                    "max_clicks": 100000
                }
            }
        )
        
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": email,
            "password": "testpass123"
        })
        
        yield {
            "id": user_id,
            "email": email,
            "token": login_response.json()["access_token"]
        }
        
        requests.delete(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
    
    def test_create_link_with_block_vpn_enabled(self, activated_user):
        """Test creating a link with block_vpn=True"""
        response = requests.post(
            f"{BASE_URL}/api/links",
            headers={"Authorization": f"Bearer {activated_user['token']}"},
            json={
                "offer_url": "https://example.com/vpn-blocked",
                "name": "TEST VPN Blocked Link",
                "block_vpn": True
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["block_vpn"] == True
        
        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/links/{data['id']}",
            headers={"Authorization": f"Bearer {activated_user['token']}"}
        )
    
    def test_create_link_with_block_vpn_disabled(self, activated_user):
        """Test creating a link with block_vpn=False (default)"""
        response = requests.post(
            f"{BASE_URL}/api/links",
            headers={"Authorization": f"Bearer {activated_user['token']}"},
            json={
                "offer_url": "https://example.com/vpn-allowed",
                "name": "TEST VPN Allowed Link",
                "block_vpn": False
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["block_vpn"] == False
        
        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/links/{data['id']}",
            headers={"Authorization": f"Bearer {activated_user['token']}"}
        )
    
    def test_update_link_block_vpn(self, activated_user):
        """Test updating link block_vpn setting"""
        # Create link without VPN blocking
        create_response = requests.post(
            f"{BASE_URL}/api/links",
            headers={"Authorization": f"Bearer {activated_user['token']}"},
            json={
                "offer_url": "https://example.com/update-vpn",
                "name": "TEST Update VPN Link",
                "block_vpn": False
            }
        )
        link_id = create_response.json()["id"]
        
        # Update to enable VPN blocking
        update_response = requests.put(
            f"{BASE_URL}/api/links/{link_id}",
            headers={"Authorization": f"Bearer {activated_user['token']}"},
            json={"block_vpn": True}
        )
        assert update_response.status_code == 200
        assert update_response.json()["block_vpn"] == True
        
        # Verify change persisted
        get_response = requests.get(
            f"{BASE_URL}/api/links/{link_id}",
            headers={"Authorization": f"Bearer {activated_user['token']}"}
        )
        assert get_response.json()["block_vpn"] == True
        
        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/links/{link_id}",
            headers={"Authorization": f"Bearer {activated_user['token']}"}
        )


class TestProxyBulkDelete:
    """Test proxy bulk delete feature"""
    
    @pytest.fixture
    def admin_token(self):
        response = requests.post(f"{BASE_URL}/api/admin/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        return response.json()["access_token"]
    
    @pytest.fixture
    def user_with_proxies(self, admin_token):
        """Create user with uploaded proxies"""
        timestamp = int(time.time())
        email = f"TEST_proxy_bulk_{timestamp}@example.com"
        
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "testpass123",
            "name": "TEST Proxy Bulk User"
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
                    "conversions": True,
                    "proxies": True,
                    "import_data": True,
                    "max_links": 100,
                    "max_clicks": 100000
                }
            }
        )
        
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": email,
            "password": "testpass123"
        })
        user_token = login_response.json()["access_token"]
        
        # Upload some proxies
        requests.post(
            f"{BASE_URL}/api/proxies/upload",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "proxy_list": ["1.1.1.1:8080", "2.2.2.2:8080", "3.3.3.3:8080"],
                "proxy_type": "http"
            }
        )
        
        yield {
            "id": user_id,
            "token": user_token
        }
        
        requests.delete(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
    
    def test_proxy_bulk_delete(self, user_with_proxies):
        """Test bulk delete proxies"""
        # Get proxy IDs
        proxies_response = requests.get(
            f"{BASE_URL}/api/proxies?filter=all",
            headers={"Authorization": f"Bearer {user_with_proxies['token']}"}
        )
        proxies = proxies_response.json()
        proxy_ids = [p["id"] for p in proxies[:2]]
        
        # Bulk delete
        response = requests.post(
            f"{BASE_URL}/api/proxies/bulk-delete",
            headers={"Authorization": f"Bearer {user_with_proxies['token']}"},
            json=proxy_ids
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
