import asyncio
import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

# Load environment variables
load_dotenv()

from src.tableau.client import TableauConnectedAppAuth
import httpx
import jwt
import uuid
import time

async def verify_credentials():
    print("\n=== Verifying Tableau Credentials ===\n")
    
    # 1. Check if variables verify
    server = os.getenv("TABLEAU_SERVER")
    site = os.getenv("TABLEAU_SITE_NAME")
    client_id = os.getenv("TABLEAU_CONNECTED_APP_CLIENT_ID")
    secret_id = os.getenv("TABLEAU_CONNECTED_APP_SECRET_ID")
    secret_value = os.getenv("TABLEAU_CONNECTED_APP_SECRET_VALUE")
    username = os.getenv("TABLEAU_USERNAME")

    print(f"Server:     {server}")
    print(f"Site:       {site}")
    print(f"Username:   {username}")
    print(f"Client ID:  {client_id}")
    print(f"Secret ID:  {secret_id}")
    print(f"Secret Val: {'*' * 10 if secret_value else 'MISSING'}")
    
    if not all([server, site, client_id, secret_id, secret_value, username]):
        print("\n❌ Missing configuration! Please check your .env file.")
        return

    print("\nStep 1: Generating JWT...")
    try:
        # Create JWT manually to verify the process
        now = int(time.time())
        payload = {
            "iss": client_id,
            "sub": username,
            "aud": "tableau",
            "exp": now + 300,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "scp": ["tableau:views:embed", "tableau:metrics:embed"] # Standard scopes
        }
        headers = {
            "kid": secret_id,
            "iss": client_id
        }
        token = jwt.encode(payload, secret_value, algorithm="HS256", headers=headers)
        print("✅ JWT Generated successfully")
    except Exception as e:
        print(f"❌ JWT Generation Failed: {e}")
        return

    print("\nStep 2: Authenticating with Tableau REST API...")
    auth_url = f"{server.rstrip('/')}/api/3.24/auth/signin"
    
    req_payload = {
        "credentials": {
            "jwt": token,
            "site": {
                "contentUrl": site
            }
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(auth_url, json=req_payload, headers=headers)
            
            if response.status_code == 200:
                print("✅ Authentication SUCCESSFUL!")
                data = response.json()
                user_id = data['credentials']['user']['id']
                site_id = data['credentials']['site']['id']
                print(f"   User ID: {user_id}")
                print(f"   Site ID: {site_id}")
                print("\n🎉 Your credentials are correct!")
            else:
                print(f"❌ Authentication FAILED (Status {response.status_code})")
                print(f"   Response: {response.text}")
                
                # Help diagnose
                if response.status_code == 404:
                    print("\n   Tip: Check your TABLEAU_SERVER URL. It shouldn't have extra paths.")
                elif response.status_code == 401:
                    print("\n   Tip: 401 usually means:")
                    print("   1. Invalid Secret Value")
                    print("   2. Invalid Secret ID or Client ID")
                    print("   3. User does not exist on this specific site")
                    print("   4. Connected App is not enabled in Tableau settings")
        except Exception as e:
            print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    asyncio.run(verify_credentials())
