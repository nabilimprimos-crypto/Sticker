"""
Client XML-RPC pour le module sticker_workflow.
Usage : python odoo_connect.py [commande]

Commandes disponibles :
  list          — Liste toutes les commandes en cours
  kanban        — Affiche le tableau Kanban par étape
  create        — Crée une nouvelle commande (interactif)
  next <ref>    — Passe une commande à l'étape suivante
  ship <ref>    — Marque une commande comme expédiée
"""

import os
import sys
import xmlrpc.client
from dotenv import load_dotenv

load_dotenv()

URL      = os.getenv("ODOO_URL",      "https://sticker.cloud-erp.ma")
DB       = os.getenv("ODOO_DB",       "sticker")
USER     = os.getenv("ODOO_USER",     "admin")
PASSWORD = os.getenv("ODOO_PASSWORD")

_common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
_models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
_uid    = None


# ── Auth ──────────────────────────────────────────────────────────────────────

def uid() -> int:
    global _uid
    if _uid is None:
        _uid = _common.authenticate(DB, USER, PASSWORD, {})
        if not _uid:
            raise SystemExit("Authentication failed — vérifiez vos identifiants dans .env")
    return _uid


def call(model: str, method: str, args: list, kwargs: dict = None) -> object:
    return _models.execute_kw(DB, uid(), PASSWORD, model, method, args, kwargs or {})


# ── Helpers ───────────────────────────────────────────────────────────────────

KANBAN_LABEL = {'normal': '●', 'done': '✔', 'blocked': '✖'}
ARTWORK_LABEL = {
    'pending':  '⏳ En attente',
    'received': '📥 Reçu',
    'approved': '✅ Validé',
    'rejected': '❌ Rejeté',
}


def get_stages() -> list:
    return call('sticker.stage', 'search_read', [[]], {
        'fields': ['name', 'sequence'],
        'order': 'sequence',
    })


def get_orders(domain=None) -> list:
    return call('sticker.order', 'search_read', [domain or []], {
        'fields': [
            'name', 'partner_id', 'product_name', 'quantity',
            'stage_id', 'kanban_state', 'artwork_state',
            'priority', 'date_deadline', 'user_id',
        ],
        'order': 'priority desc, date_order desc',
    })


# ── Commandes CLI ─────────────────────────────────────────────────────────────

def cmd_list():
    orders = get_orders()
    if not orders:
        print("Aucune commande trouvée.")
        return
    print(f"\n{'REF':<18} {'CLIENT':<25} {'PRODUIT':<22} {'QTÉ':>5}  {'ÉTAPE':<22} {'ART':<14} {'KAN'}")
    print("─" * 115)
    for o in orders:
        ks   = KANBAN_LABEL.get(o['kanban_state'], '?')
        art  = ARTWORK_LABEL.get(o['artwork_state'], o['artwork_state'])
        stage = o['stage_id'][1] if o['stage_id'] else '—'
        client = o['partner_id'][1] if o['partner_id'] else '—'
        prio = '🔴 ' if o['priority'] == '1' else '   '
        print(f"{prio}{o['name']:<16} {client:<25} {o['product_name']:<22} {o['quantity']:>5}  {stage:<22} {art:<14} {ks}")
    print()


def cmd_kanban():
    stages = get_stages()
    orders = get_orders()
    by_stage = {s['id']: [] for s in stages}
    for o in orders:
        sid = o['stage_id'][0] if o['stage_id'] else None
        if sid in by_stage:
            by_stage[sid].append(o)

    print()
    for s in stages:
        col = by_stage[s['id']]
        print(f"┌─── {s['name'].upper()} ({len(col)}) {'─' * max(0, 40 - len(s['name']))}")
        if not col:
            print("│   (vide)")
        for o in col:
            ks  = KANBAN_LABEL.get(o['kanban_state'], '?')
            art = '✅' if o['artwork_state'] == 'approved' else ('❌' if o['artwork_state'] == 'rejected' else '⏳')
            client = o['partner_id'][1] if o['partner_id'] else '—'
            prio = '🔴' if o['priority'] == '1' else '  '
            print(f"│  {prio} {o['name']}  {client:<20}  {o['product_name'][:20]:<20}  art:{art} {ks}")
        print("│")
    print()


def cmd_create():
    print("\n── Nouvelle commande sticker ──")
    partners = call('res.partner', 'search_read', [[('customer_rank', '>', 0)]], {
        'fields': ['id', 'name'], 'limit': 20, 'order': 'name'})

    print("\nClients disponibles :")
    for i, p in enumerate(partners):
        print(f"  {i+1}. {p['name']}")
    idx = int(input("Choisir un client (numéro) : ")) - 1
    partner_id = partners[idx]['id']

    product_name = input("Désignation sticker : ")
    quantity     = int(input("Quantité : "))

    new_id = call('sticker.order', 'create', [{
        'partner_id':   partner_id,
        'product_name': product_name,
        'quantity':     quantity,
    }])
    order = call('sticker.order', 'read', [[new_id]], {'fields': ['name']})[0]
    print(f"\nCommande créée : {order['name']}  (id={new_id})\n")


def cmd_next(ref: str):
    ids = call('sticker.order', 'search', [[['name', '=', ref]]])
    if not ids:
        print(f"Commande '{ref}' introuvable.")
        return
    call('sticker.order', 'action_next_stage', [ids])
    order = call('sticker.order', 'read', [ids], {'fields': ['name', 'stage_id']})[0]
    print(f"'{order['name']}' → {order['stage_id'][1]}")


def cmd_ship(ref: str):
    ids = call('sticker.order', 'search', [[['name', '=', ref]]])
    if not ids:
        print(f"Commande '{ref}' introuvable.")
        return
    call('sticker.order', 'action_ship', [ids])
    print(f"'{ref}' marquée comme expédiée ✔")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    cmd  = args[0] if args else 'kanban'

    try:
        if cmd == 'list':
            cmd_list()
        elif cmd == 'kanban':
            cmd_kanban()
        elif cmd == 'create':
            cmd_create()
        elif cmd == 'next' and len(args) > 1:
            cmd_next(args[1])
        elif cmd == 'ship' and len(args) > 1:
            cmd_ship(args[1])
        else:
            print(__doc__)
    except Exception as e:
        print(f"Erreur : {e}")
        raise SystemExit(1)


if __name__ == '__main__':
    main()
