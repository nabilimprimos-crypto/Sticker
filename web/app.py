import sqlite3
import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for

app = Flask(__name__)
DB = os.path.join(os.path.dirname(__file__), 'sticker.db')

STAGES = [
    {'id': 1, 'name': 'Nouvelle commande',   'color': '#6c757d'},
    {'id': 2, 'name': 'Validation artwork',  'color': '#fd7e14'},
    {'id': 3, 'name': 'Impression',          'color': '#0d6efd'},
    {'id': 4, 'name': 'Découpe / Finition',  'color': '#6f42c1'},
    {'id': 5, 'name': 'Contrôle qualité',    'color': '#ffc107'},
    {'id': 6, 'name': 'Expédié',             'color': '#198754'},
]

ARTWORK_STATES = {
    'pending':  ('En attente', 'secondary'),
    'received': ('Reçu',       'warning'),
    'approved': ('Validé',     'success'),
    'rejected': ('Rejeté',     'danger'),
}


# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                reference     TEXT    NOT NULL UNIQUE,
                client        TEXT    NOT NULL,
                product       TEXT    NOT NULL,
                quantity      INTEGER NOT NULL DEFAULT 1,
                material      TEXT    DEFAULT 'vinyl',
                finish        TEXT    DEFAULT 'glossy',
                cut_type      TEXT    DEFAULT 'square',
                width_mm      REAL    DEFAULT 0,
                height_mm     REAL    DEFAULT 0,
                stage_id      INTEGER NOT NULL DEFAULT 1,
                artwork_state TEXT    NOT NULL DEFAULT 'pending',
                priority      INTEGER NOT NULL DEFAULT 0,
                notes         TEXT    DEFAULT '',
                date_created  TEXT    NOT NULL,
                date_deadline TEXT,
                date_updated  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id    INTEGER NOT NULL,
                action      TEXT    NOT NULL,
                detail      TEXT,
                date        TEXT    NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id)
            );
        """)


def log(conn, order_id: int, action: str, detail: str = ''):
    conn.execute(
        "INSERT INTO history (order_id, action, detail, date) VALUES (?,?,?,?)",
        (order_id, action, detail, now())
    )


def now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def stage_name(stage_id: int) -> str:
    return next((s['name'] for s in STAGES if s['id'] == stage_id), '—')


def auto_ref() -> str:
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) as n FROM orders").fetchone()
        year = datetime.now().year
        return f"STK/{year}/{(row['n'] + 1):04d}"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    with get_db() as conn:
        if q:
            rows = conn.execute(
                "SELECT * FROM orders WHERE reference LIKE ? OR client LIKE ? ORDER BY priority DESC, date_created DESC",
                (f'%{q}%', f'%{q}%')
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM orders ORDER BY priority DESC, date_created DESC"
            ).fetchall()

    orders = [dict(r) for r in rows]
    for o in orders:
        o['stage_name']    = stage_name(o['stage_id'])
        o['artwork_label'] = ARTWORK_STATES.get(o['artwork_state'], ('—', 'secondary'))
        o['stage_pct']     = round((o['stage_id'] / len(STAGES)) * 100)

    # Group by stage for Kanban
    kanban = {s['id']: {'stage': s, 'orders': []} for s in STAGES}
    for o in orders:
        sid = o['stage_id']
        if sid in kanban:
            kanban[sid]['orders'].append(o)

    return render_template('index.html',
        orders=orders,
        kanban=list(kanban.values()),
        stages=STAGES,
        artwork_states=ARTWORK_STATES,
        q=q,
        total=len(orders),
    )


@app.route('/order/new', methods=['GET', 'POST'])
def new_order():
    if request.method == 'POST':
        ref = request.form.get('reference', '').strip() or auto_ref()
        with get_db() as conn:
            conn.execute("""
                INSERT INTO orders
                  (reference, client, product, quantity, material, finish, cut_type,
                   width_mm, height_mm, date_deadline, notes, date_created, date_updated)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                ref,
                request.form['client'],
                request.form['product'],
                int(request.form.get('quantity', 1)),
                request.form.get('material', 'vinyl'),
                request.form.get('finish', 'glossy'),
                request.form.get('cut_type', 'square'),
                float(request.form.get('width_mm', 0) or 0),
                float(request.form.get('height_mm', 0) or 0),
                request.form.get('date_deadline') or None,
                request.form.get('notes', ''),
                now(), now(),
            ))
            order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            log(conn, order_id, 'Création', f'Commande créée — {ref}')
        return redirect(url_for('order_detail', ref=ref))
    return render_template('new_order.html', stages=STAGES, ref=auto_ref())


@app.route('/order/<path:ref>')
def order_detail(ref):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE reference=?", (ref,)).fetchone()
        if not row:
            return "Commande introuvable", 404
        order = dict(row)
        history = conn.execute(
            "SELECT * FROM history WHERE order_id=? ORDER BY date DESC", (order['id'],)
        ).fetchall()

    order['stage_name']    = stage_name(order['stage_id'])
    order['artwork_label'] = ARTWORK_STATES.get(order['artwork_state'], ('—', 'secondary'))
    order['stage_pct']     = round((order['stage_id'] / len(STAGES)) * 100)

    return render_template('order.html',
        order=order,
        stages=STAGES,
        artwork_states=ARTWORK_STATES,
        history=[dict(h) for h in history],
    )


# ── API JSON ──────────────────────────────────────────────────────────────────

@app.route('/api/order/<path:ref>/next', methods=['POST'])
def api_next_stage(ref):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE reference=?", (ref,)).fetchone()
        if not row:
            return jsonify({'error': 'not found'}), 404
        order = dict(row)
        if order['stage_id'] >= len(STAGES):
            return jsonify({'error': 'Déjà à la dernière étape'}), 400
        new_stage = order['stage_id'] + 1
        conn.execute(
            "UPDATE orders SET stage_id=?, date_updated=? WHERE reference=?",
            (new_stage, now(), ref)
        )
        log(conn, order['id'], 'Étape avancée',
            f"{stage_name(order['stage_id'])} → {stage_name(new_stage)}")
    return jsonify({'stage_id': new_stage, 'stage_name': stage_name(new_stage)})


@app.route('/api/order/<path:ref>/stage', methods=['POST'])
def api_set_stage(ref):
    data = request.get_json()
    new_stage = int(data.get('stage_id', 1))
    if not 1 <= new_stage <= len(STAGES):
        return jsonify({'error': 'Étape invalide'}), 400
    with get_db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE reference=?", (ref,)).fetchone()
        if not row:
            return jsonify({'error': 'not found'}), 404
        order = dict(row)
        conn.execute(
            "UPDATE orders SET stage_id=?, date_updated=? WHERE reference=?",
            (new_stage, now(), ref)
        )
        log(conn, order['id'], 'Étape modifiée',
            f"{stage_name(order['stage_id'])} → {stage_name(new_stage)}")
    return jsonify({'stage_id': new_stage, 'stage_name': stage_name(new_stage)})


@app.route('/api/order/<path:ref>/artwork', methods=['POST'])
def api_set_artwork(ref):
    data = request.get_json()
    state = data.get('state', 'pending')
    if state not in ARTWORK_STATES:
        return jsonify({'error': 'État invalide'}), 400
    with get_db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE reference=?", (ref,)).fetchone()
        if not row:
            return jsonify({'error': 'not found'}), 404
        conn.execute(
            "UPDATE orders SET artwork_state=?, date_updated=? WHERE reference=?",
            (state, now(), ref)
        )
        log(conn, row['id'], 'Artwork', f"→ {ARTWORK_STATES[state][0]}")
    return jsonify({'artwork_state': state, 'label': ARTWORK_STATES[state][0]})


@app.route('/api/order/<path:ref>/priority', methods=['POST'])
def api_toggle_priority(ref):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE reference=?", (ref,)).fetchone()
        if not row:
            return jsonify({'error': 'not found'}), 404
        new_prio = 0 if row['priority'] else 1
        conn.execute(
            "UPDATE orders SET priority=?, date_updated=? WHERE reference=?",
            (new_prio, now(), ref)
        )
        log(conn, row['id'], 'Priorité', 'Urgent' if new_prio else 'Normal')
    return jsonify({'priority': new_prio})


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print("Sticker Workflow — http://localhost:5000")
    app.run(debug=True, port=5000)
