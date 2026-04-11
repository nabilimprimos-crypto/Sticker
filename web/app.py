import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ── Database abstraction (SQLite local / PostgreSQL production) ───────────────

DATABASE_URL = os.getenv('DATABASE_URL')  # set by Render in production
SQLITE_PATH  = os.path.join(os.path.dirname(__file__), 'sticker.db')

# Render gives postgres:// but psycopg2 needs postgresql://
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras
    PH = '%s'   # PostgreSQL placeholder
else:
    PH = '?'    # SQLite placeholder


@contextmanager
def get_db():
    if USE_PG:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def fetchall(cursor):
    """Return list of dicts regardless of DB backend."""
    if USE_PG:
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    return [dict(r) for r in cursor.fetchall()]


def fetchone(cursor):
    """Return single dict or None."""
    if USE_PG:
        row = cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))
    row = cursor.fetchone()
    return dict(row) if row else None


def insert_returning_id(conn, sql, params):
    """INSERT and return new row id."""
    cur = conn.cursor()
    if USE_PG:
        cur.execute(sql + ' RETURNING id', params)
        return cur.fetchone()[0]
    else:
        cur.execute(sql, params)
        return cur.lastrowid


# ── Constants ────────────────────────────────────────────────────────────────

STAGES = [
    {'id': 1, 'name': 'Nouvelle commande',  'color': '#6c757d'},
    {'id': 2, 'name': 'Validation artwork', 'color': '#fd7e14'},
    {'id': 3, 'name': 'Impression',         'color': '#0d6efd'},
    {'id': 4, 'name': 'Découpe / Finition', 'color': '#6f42c1'},
    {'id': 5, 'name': 'Contrôle qualité',   'color': '#ffc107'},
    {'id': 6, 'name': 'Expédié',            'color': '#198754'},
]

ARTWORK_STATES = {
    'pending':  ('En attente', 'secondary'),
    'received': ('Reçu',       'warning'),
    'approved': ('Validé',     'success'),
    'rejected': ('Rejeté',     'danger'),
}


# ── DB init ───────────────────────────────────────────────────────────────────

def init_db():
    serial = 'SERIAL' if USE_PG else 'INTEGER'
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS orders (
                id            {serial} PRIMARY KEY,
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
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS history (
                id          {serial} PRIMARY KEY,
                order_id    INTEGER NOT NULL,
                action      TEXT    NOT NULL,
                detail      TEXT,
                date        TEXT    NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id)
            )
        """)


# ── Helpers ───────────────────────────────────────────────────────────────────

def now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def stage_name(stage_id: int) -> str:
    return next((s['name'] for s in STAGES if s['id'] == stage_id), '—')


def auto_ref() -> str:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM orders")
        n = cur.fetchone()[0]
        year = datetime.now().year
        return f"STK/{year}/{(n + 1):04d}"


def log(conn, order_id: int, action: str, detail: str = ''):
    conn.cursor().execute(
        f"INSERT INTO history (order_id, action, detail, date) VALUES ({PH},{PH},{PH},{PH})",
        (order_id, action, detail, now())
    )


def enrich(order: dict) -> dict:
    order['stage_name']    = stage_name(order['stage_id'])
    order['artwork_label'] = ARTWORK_STATES.get(order['artwork_state'], ('—', 'secondary'))
    order['stage_pct']     = round((order['stage_id'] / len(STAGES)) * 100)
    return order


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    with get_db() as conn:
        cur = conn.cursor()
        if q:
            like = f'%{q}%'
            cur.execute(
                f"SELECT * FROM orders WHERE reference LIKE {PH} OR client LIKE {PH} ORDER BY priority DESC, date_created DESC",
                (like, like)
            )
        else:
            cur.execute("SELECT * FROM orders ORDER BY priority DESC, date_created DESC")
        orders = [enrich(r) for r in fetchall(cur)]

    kanban = {s['id']: {'stage': s, 'orders': []} for s in STAGES}
    for o in orders:
        if o['stage_id'] in kanban:
            kanban[o['stage_id']]['orders'].append(o)

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
            order_id = insert_returning_id(conn,
                f"""INSERT INTO orders
                  (reference, client, product, quantity, material, finish, cut_type,
                   width_mm, height_mm, date_deadline, notes, date_created, date_updated)
                VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})""",
                (
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
                )
            )
            log(conn, order_id, 'Création', f'Commande créée — {ref}')
        return redirect(url_for('order_detail', ref=ref))
    return render_template('new_order.html', stages=STAGES, ref=auto_ref())


@app.route('/order/<path:ref>')
def order_detail(ref):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM orders WHERE reference={PH}", (ref,))
        row = fetchone(cur)
        if not row:
            return "Commande introuvable", 404
        order = enrich(row)
        cur.execute(
            f"SELECT * FROM history WHERE order_id={PH} ORDER BY date DESC",
            (order['id'],)
        )
        history = fetchall(cur)

    return render_template('order.html',
        order=order,
        stages=STAGES,
        artwork_states=ARTWORK_STATES,
        history=history,
    )


# ── API JSON ──────────────────────────────────────────────────────────────────

@app.route('/api/order/<path:ref>/next', methods=['POST'])
def api_next_stage(ref):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM orders WHERE reference={PH}", (ref,))
        order = fetchone(cur)
        if not order:
            return jsonify({'error': 'not found'}), 404
        if order['stage_id'] >= len(STAGES):
            return jsonify({'error': 'Déjà à la dernière étape'}), 400
        new_stage = order['stage_id'] + 1
        conn.cursor().execute(
            f"UPDATE orders SET stage_id={PH}, date_updated={PH} WHERE reference={PH}",
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
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM orders WHERE reference={PH}", (ref,))
        order = fetchone(cur)
        if not order:
            return jsonify({'error': 'not found'}), 404
        conn.cursor().execute(
            f"UPDATE orders SET stage_id={PH}, date_updated={PH} WHERE reference={PH}",
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
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM orders WHERE reference={PH}", (ref,))
        order = fetchone(cur)
        if not order:
            return jsonify({'error': 'not found'}), 404
        conn.cursor().execute(
            f"UPDATE orders SET artwork_state={PH}, date_updated={PH} WHERE reference={PH}",
            (state, now(), ref)
        )
        log(conn, order['id'], 'Artwork', f"→ {ARTWORK_STATES[state][0]}")
    return jsonify({'artwork_state': state, 'label': ARTWORK_STATES[state][0]})


@app.route('/api/order/<path:ref>/priority', methods=['POST'])
def api_toggle_priority(ref):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM orders WHERE reference={PH}", (ref,))
        order = fetchone(cur)
        if not order:
            return jsonify({'error': 'not found'}), 404
        new_prio = 0 if order['priority'] else 1
        conn.cursor().execute(
            f"UPDATE orders SET priority={PH}, date_updated={PH} WHERE reference={PH}",
            (new_prio, now(), ref)
        )
        log(conn, order['id'], 'Priorité', 'Urgent' if new_prio else 'Normal')
    return jsonify({'priority': new_prio})


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    port = int(os.getenv('PORT', 5000))
    debug = not USE_PG
    print(f"Sticker Workflow — http://localhost:{port}  [{'PostgreSQL' if USE_PG else 'SQLite'}]")
    app.run(debug=debug, port=port, host='0.0.0.0')
