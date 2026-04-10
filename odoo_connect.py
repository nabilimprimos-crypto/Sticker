import xmlrpc.client
import os
from dotenv import load_dotenv

load_dotenv()

URL      = os.getenv("ODOO_URL", "https://sticker.cloud-erp.ma")
DB       = os.getenv("ODOO_DB",  "sticker")
USER     = os.getenv("ODOO_USER", "admin")
PASSWORD = os.getenv("ODOO_PASSWORD")

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")


def get_version() -> dict:
    return common.version()


def authenticate() -> int:
    uid = common.authenticate(DB, USER, PASSWORD, {})
    if not uid:
        raise ValueError("Authentication failed — check your credentials or database name.")
    return uid


def search_read(uid: int, model: str, domain: list, fields: list, limit: int = 10) -> list:
    return models.execute_kw(
        DB, uid, PASSWORD,
        model, "search_read",
        [domain],
        {"fields": fields, "limit": limit},
    )


if __name__ == "__main__":
    print(f"Connecting to : {URL}")
    print(f"Database      : {DB}")
    print(f"User          : {USER}\n")

    # Server version
    try:
        v = get_version()
        print(f"Server version : {v.get('server_version', v)}")
    except Exception as e:
        print(f"Version check failed: {e}")

    # Authentication
    try:
        uid = authenticate()
        print(f"Authentication : OK  (uid={uid})\n")
    except Exception as e:
        print(f"Authentication : FAILED — {e}")
        raise SystemExit(1)

    # Quick smoke-test: list first 5 products
    try:
        products = search_read(uid, "product.template", [], ["name", "list_price", "type"], limit=5)
        print("Sample products:")
        for p in products:
            print(f"  [{p['id']}] {p['name']}  —  price={p['list_price']}  type={p['type']}")
    except Exception as e:
        print(f"Could not fetch products: {e}")
