import asyncio
import os
import sys
import logging
import traceback
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.append(os.getcwd())

from src.mcp.client import MCPClient

async def test_mcp_flow():
    print("\n=== Testing Backend -> MCP -> Tableau Flow ===\n")
    
    client = MCPClient()
    
    try:
        print("Step 1: Connecting to MCP Server...")
        async with client as mcp:
            session_id = await mcp._initialize_session()
            print(f"✅ Connected! Session ID: {session_id}")
            
            print("\nStep 2: Listing Datasources (Tool Call)...")
            try:
                result = await mcp.call_tool("list_datasources", {})
                print("✅ Tool Call Successful!")
                print(result)
            except Exception as e:
                print(f"❌ Tool Call Failed Type: {type(e)}")
                print(f"❌ Tool Call Failed Repr: {repr(e)}")
                print(f"❌ Tool Call Failed Str: {str(e)}")
                traceback.print_exc()
                
    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_mcp_flow())
