from flask import Flask, request, jsonify, redirect, send_file, render_template
import sqlite3
import random
import string
import qrcode
import io

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect('links.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_url TEXT NOT NULL,
            short_code TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )
    ''')
    # This line force-adds expires_at if it's missing from old database
    try:
        cursor.execute('ALTER TABLE links ADD COLUMN expires_at TIMESTAMP')
    except:
       pass
    try:
        cursor.execute('ALTER TABLE links ADD COLUMN password TEXT')
    except:
       pass
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            short_code TEXT NOT NULL,
            clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def generate_short_code():
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=6))



@app.route('/shorten', methods=['POST'])
def shorten_url():
    data = request.get_json()
    original_url = data['url']
    days = data.get('expires_in_days', None)
    custom_alias = data.get('custom_alias', None)
    password = data.get('password', None)

    short_code = custom_alias if custom_alias else generate_short_code()

    expires_at = None
    if days:
        from datetime import datetime, timedelta
        expires_at = datetime.now() + timedelta(days=int(days))

    conn = sqlite3.connect('links.db')
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO links (original_url, short_code, expires_at, password) VALUES (?, ?, ?, ?)',
                       (original_url, short_code, expires_at, password))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'This alias is already taken, try another!'}), 400
    conn.close()

    return jsonify({
        'original_url': original_url,
        'short_url': f'http://127.0.0.1:5000/{short_code}',
        'expires_at': str(expires_at) if expires_at else 'Never',
        'password_protected': True if password else False
    })
@app.route('/<short_code>')
def redirect_url(short_code):
    from datetime import datetime
    conn = sqlite3.connect('links.db')
    cursor = conn.cursor()
    cursor.execute('SELECT original_url, expires_at, password FROM links WHERE short_code = ?', (short_code,))
    result = cursor.fetchone()

    if result:
        original_url, expires_at, password = result

        if expires_at:
            expires_at = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S.%f')
            if datetime.now() > expires_at:
                conn.close()
                return jsonify({'error': 'This link has expired'}), 410

        if password:
            provided = request.args.get('password')
            if provided != password:
                conn.close()
                return jsonify({'error': 'Password required', 'hint': 'Add ?password=yourpassword to the URL'}), 401

        cursor.execute('INSERT INTO clicks (short_code) VALUES (?)', (short_code,))
        conn.commit()
        conn.close()
        return redirect(original_url)
    else:
        conn.close()
        return jsonify({'error': 'Link not found'}), 404
    
@app.route('/analytics/<short_code>')
def analytics(short_code):
    conn = sqlite3.connect('links.db')
    cursor = conn.cursor()
    cursor.execute('SELECT original_url FROM links WHERE short_code = ?', (short_code,))
    link = cursor.fetchone()

    cursor.execute('SELECT COUNT(*) FROM clicks WHERE short_code = ?', (short_code,))
    total_clicks = cursor.fetchone()[0]
    conn.close()

    if request.headers.get('Accept', '').find('text/html') != -1:
        return render_template('analytics.html')

    if link:
        return jsonify({
            'short_code': short_code,
            'original_url': link[0],
            'total_clicks': total_clicks
        })
    else:
        return jsonify({'error': 'Link not found'}), 404 
    
@app.route('/qr/<short_code>')
def generate_qr(short_code):
    short_url = f'http://127.0.0.1:5000/{short_code}'
    
    qr = qrcode.make(short_url)
    buf = io.BytesIO()
    qr.save(buf, format='PNG')
    buf.seek(0)
    
    return send_file(buf, mimetype='image/png')
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/all-links')
def all_links():
    conn = sqlite3.connect('links.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT l.short_code, l.original_url, l.expires_at, l.password,
               COUNT(c.id) as total_clicks
        FROM links l
        LEFT JOIN clicks c ON l.short_code = c.short_code
        GROUP BY l.short_code
        ORDER BY l.created_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()

    return jsonify([{
        'short_code': r[0],
        'original_url': r[1],
        'expires_at': r[2],
        'password': r[3],
        'total_clicks': r[4]
    } for r in rows])

@app.route('/delete/<short_code>', methods=['DELETE'])
def delete_link(short_code):
    conn = sqlite3.connect('links.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM links WHERE short_code = ?', (short_code,))
    cursor.execute('DELETE FROM clicks WHERE short_code = ?', (short_code,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})
  
if __name__ == '__main__':
    init_db()
    app.run(debug=True)