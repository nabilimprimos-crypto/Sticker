import xmlrpc.client
import os
from dotenv import load_dotenv

load_dotenv()

ODOO_URL = os.getenv("ODOO_URL", "https://www.odoo.com")
EMAIL    = os.getenv("ODOO_EMAIL")
PASSWORD = os.getenv("ODOO_PASSWORD")

def list_databases(url: str) -> list:
    db_endpoint = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/db")
    try:
        return db_endpoint.list()
    except Exception as e:
        return [f"ERROR: {e}"]

def authenticate(url: str, db: str, email: str, password: str) -> int | None:
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, email, password, {})
    return uid if uid else None

def get_server_version(url: str) -> str:
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    return common.version()

if __name__ == "__main__":
    print(f"Connecting to: {ODOO_URL}")
    print(f"User: {EMAIL}\n")

    # Server version
    try:
        version = get_server_version(ODOO_URL)
        print(f"Server version: {version}")
    except Exception as e:
        print(f"Could not fetch server version: {e}")

    # List available databases
    print("\nAvailable databases:")
    dbs = list_databases(ODOO_URL)
    for db in dbs:
        print(f"  - {db}")

    # Try to authenticate on each database
    print("\nTrying authentication...")
    for db in dbs:
        if isinstance(db, str) and not db.startswith("ERROR"):
            uid = authenticate(ODOO_URL, db, EMAIL, PASSWORD)
            if uid:
                print(f"  [OK] Authenticated on '{db}' — uid={uid}")
            else:
                print(f"  [FAIL] Authentication failed on '{db}'")
