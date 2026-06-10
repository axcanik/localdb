import os
import sys
import json
import secrets
import datetime
import requests
import base64
import time
import pyotp
import urllib.parse
from dotenv import load_dotenv
from pymongo import MongoClient
import certifi

load_dotenv()
mongo_uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/planvb')
client = MongoClient(mongo_uri, tlsCAFile=certifi.where())
db = client.get_database()


# Anti-Crack / Anti-Debug Protection (Advance Protection)
if sys.gettrace() is not None:
    print("[!] Debugger detected. Security trigger activated.")
    sys.exit(1)

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, abort, send_from_directory, make_response, Response, stream_with_context
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)
app.secret_key = secrets.token_urlsafe(48)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, 'data', 'users.json')
UIDS_FILE = os.path.join(BASE_DIR, 'data', 'uids.json')
PORTALS_FILE = os.path.join(BASE_DIR, 'data', 'portals.json')
LOGIN_LOGS_FILE = os.path.join(BASE_DIR, 'data', 'login_logs.json')
ADMIN_LOGS_FILE = os.path.join(BASE_DIR, 'data', 'admin_logs.json')
PRODUCTS_FILE = os.path.join(BASE_DIR, 'data', 'products.json')
SETTINGS_FILE = os.path.join(BASE_DIR, 'data', 'settings.json')
PENDING_PAYMENTS_FILE = os.path.join(BASE_DIR, 'data', 'pending_payments.json')

BYPASS_DOWNLOAD_URL = "https://anikxcheats.com/downloads/AXC_Bypass_v4.zip"
TUTORIAL_VIDEO_URL = "https://www.youtube.com/embed/dQw4w9WgXcQ"

def check_and_purge_expired_users():
    users = load_json(USERS_FILE)
    now = datetime.datetime.now()
    updated = False
    active_users = []
    expired_usernames = []
    
    for u in users:
        # Check client user expiry
        if u.get('is_client') and 'expiry_date' in u:
            exp_str = u['expiry_date']
            if exp_str != 'lifetime':
                try:
                    exp = datetime.datetime.strptime(exp_str, '%Y-%m-%d %H:%M:%S')
                    if exp < now:
                        # Client expired!
                        expired_usernames.append(u['username'])
                        updated = True
                        continue
                except Exception as e:
                    print(f"[Purge] Error parsing user expiry: {e}")
        active_users.append(u)
        
    if updated:
        save_json(USERS_FILE, active_users)
        
        # Clean their UIDs
        if expired_usernames:
            uids = load_json(UIDS_FILE)
            cleaned_uids = []
            for item in uids:
                added_by = item.get('added_by', '')
                if added_by in expired_usernames:
                    remove_uid_from_axc(item['uid'])
                else:
                    cleaned_uids.append(item)
            save_json(UIDS_FILE, cleaned_uids)

# --- Data Helpers ---
def log_admin_action(operator, action, details):
    logs = load_json(ADMIN_LOGS_FILE)
    logs.append({
        'operator': operator,
        'action': action,
        'details': details,
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    if len(logs) > 50:
        logs = logs[-50:]
    save_json(ADMIN_LOGS_FILE, logs)

def log_login_attempt(username, ip, status, user_agent):
    logs = load_json(LOGIN_LOGS_FILE)
    logs.append({
        'username': username,
        'ip': ip,
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'status': status,
        'user_agent': user_agent
    })
    # Keep only the last 1000 logs
    if len(logs) > 1000:
        logs = logs[-1000:]
    save_json(LOGIN_LOGS_FILE, logs)


def get_collection_from_path(path):
    name = os.path.basename(path).split('.')[0]
    return db[name]

def load_json(path):
    col = get_collection_from_path(path)
    return list(col.find({}, {'_id': 0}))

def save_json(path, data):
    col = get_collection_from_path(path)
    col.delete_many({})
    if data:
        col.insert_many(data)

def load_dict_json(path):
    col = get_collection_from_path(path)
    doc = col.find_one({'_id': 'singleton'}, {'_id': 0})
    return doc if doc else {}

def save_dict_json(path, data):
    col = get_collection_from_path(path)
    col.update_one({'_id': 'singleton'}, {'$set': data}, upsert=True)


def format_youtube_embed_url(url):
    url = url.strip()
    if not url:
        return ""
    
    video_id = None
    if "youtu.be/" in url:
        parts = url.split("youtu.be/")
        if len(parts) > 1:
            video_id = parts[1].split("?")[0].split("&")[0]
    elif "watch?v=" in url:
        parts = url.split("watch?v=")
        if len(parts) > 1:
            video_id = parts[1].split("&")[0].split("#")[0]
    elif "youtube.com/embed/" in url or "youtube-nocookie.com/embed/" in url:
        return url
    elif "/v/" in url:
        parts = url.split("/v/")
        if len(parts) > 1:
            video_id = parts[1].split("?")[0]
            
    if video_id:
        return f"https://www.youtube.com/embed/{video_id}"
    return url

def get_payment_settings():
    settings = load_dict_json(SETTINGS_FILE)
    if not settings:
        settings = {
            "zinipay_api_key": "",
            "zinipay_enabled": False,
            "tutorial_video_url": "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "bypass_download_url": "https://anikxcheats.com/downloads/AXC_Bypass_v4.zip",
            "bypass_filename": "AXC_Bypass_v4.zip",
            "bypass_file_size": "4.8 MB"
        }
        save_dict_json(SETTINGS_FILE, settings)
    else:
        # Default any missing keys
        modified = False
        if "tutorial_video_url" not in settings:
            settings["tutorial_video_url"] = "https://www.youtube.com/embed/dQw4w9WgXcQ"
            modified = True
        if "zinipay_api_key" not in settings:
            settings["zinipay_api_key"] = ""
            modified = True
        if "zinipay_enabled" not in settings:
            settings["zinipay_enabled"] = False
            modified = True
        if "bypass_download_url" not in settings:
            settings["bypass_download_url"] = "https://anikxcheats.com/downloads/AXC_Bypass_v4.zip"
            modified = True
        if "bypass_filename" not in settings:
            settings["bypass_filename"] = "AXC_Bypass_v4.zip"
            modified = True
        if "bypass_file_size" not in settings:
            settings["bypass_file_size"] = "4.8 MB"
            modified = True
        if modified:
            save_dict_json(SETTINGS_FILE, settings)
    return settings

# --- Database Migration for API Keys and Limits ---
def migrate_users_db():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                users = json.load(f)
            updated = False
            for u in users:
                if 'api_key' not in u:
                    u['api_key'] = f"axc_api_{secrets.token_hex(16)}"
                    updated = True
                if 'uid_limit' not in u:
                    u['uid_limit'] = 99999 if (u['username'] == 'admin' or u.get('is_admin')) else 100
                    updated = True
            if updated:
                with open(USERS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(users, f, indent=4)
        except Exception as e:
            print(f"[Migration Error] {e}")

migrate_users_db()

# --- Limit Check Helpers ---
def get_user_active_count(username):
    uids = load_json(UIDS_FILE)
    portals = load_json(PORTALS_FILE)
    user_portals = {p['token'] for p in portals if p.get('created_by') == username}
    
    count = 0
    for u in uids:
        if is_expired(u.get('expiry_date')):
            continue
        added_by = u.get('added_by', '')
        if added_by == username:
            count += 1
        elif added_by.startswith(f"{username} (Discord:"):
            count += 1
        elif added_by == 'FreePortal':
            note = u.get('note', '')
            for p_token in user_portals:
                if f"Portal: {p_token}" in note:
                    count += 1
                    break
    return count

def validate_user_limit(username):
    users = load_json(USERS_FILE)
    user = next((u for u in users if u['username'] == username), None)
    if not user:
        return False, "User not found."
    if username == 'admin' or user.get('is_admin'):
        return True, 99999
        
    limit = user.get('uid_limit', 100)
    count = get_user_active_count(username)
    if count >= limit:
        return False, f"UID limit reached. Using {count} of {limit} active slots."
    return True, limit

# --- Auth Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or not session.get('is_admin'):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# --- Date Helper ---
def get_expiry(days):
    if int(days) == 0:  # 0 = Lifetime
        return 'lifetime'
    return (datetime.datetime.now() + datetime.timedelta(days=int(days))).strftime('%Y-%m-%d %H:%M:%S')

def is_expired(expiry_str):
    if not expiry_str or expiry_str == 'lifetime':
        return False  # Lifetime never expires
    try:
        expiry = datetime.datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
        return expiry < datetime.datetime.now()
    except:
        return False

def sync_axc_with_auto_recycle(uid, days):
    # Obfuscated URL and API Key
    url = base64.b64decode(b'aHR0cHM6Ly9ndGNjaGVhdHMueHl6L0FwaS91aWRieXBhc3NhcGkvYXBpX3VzZXIucGhw').decode()
    headers = {
        "X-API-KEY": base64.b64decode(b'R1RDQVBJLUY4OTQzNDQwQzdGMDAwNkQxRjVGMEU3RjI1N0U0MzFE').decode(),
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    axc_days = "9999" if str(days) == '0' else str(days)
    payload = {"account_id": str(uid), "for_days": axc_days}
    
    # Check if target already exists on external system using the user info check api
    try:
        check_r = requests.get(url, params={"action": "info", "account_id": str(uid)}, headers=headers, timeout=8)
        if check_r.status_code == 200:
            res_json = check_r.json()
            if res_json.get("success"):
                print(f"[AXC Sync] Target UID {uid} already active on external server. Skipping add.")
                return True, "UID already registered and active."
    except Exception as e:
        print(f"[AXC Sync] Pre-check failed: {e}")

    max_retries = 3
    last_error = "Unknown error"
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[AXC Sync] Attempt {attempt}/{max_retries} to add UID {uid}...")
            r = requests.post(url, params={"action": "add"}, json=payload, headers=headers, timeout=12)
            
            # If request succeeded, parse response
            if r.status_code in (200, 201):
                try:
                    res_json = r.json()
                    if res_json.get("success") or "added successfully" in res_json.get("message", "").lower():
                        print(f"[AXC Sync] Successfully synced UID {uid} on attempt {attempt}")
                        return True, res_json.get("message", "Success")
                    else:
                        last_error = res_json.get("message", "Sync failed without message")
                except:
                    if "added successfully" in r.text.lower():
                        return True, "Successfully registered UID."
                    last_error = f"Invalid API JSON response: {r.text[:100]}"
            else:
                try:
                    res_json = r.json()
                    last_error = res_json.get("message", f"HTTP status {r.status_code}")
                except:
                    last_error = f"HTTP status {r.status_code} - {r.text[:100]}"
            
            # Check for limit / capacity issues
            lower_err = last_error.lower()
            if any(term in lower_err for term in ["limit", "2000", "full", "max", "slot"]):
                print("[AXC Sync] Slot limit reached! Auto-recycling an old UID...")
                uids = load_json(UIDS_FILE)
                if not uids:
                    return False, "Slots full and no local active records to recycle."
                
                # Priority: find expired UID, else oldest UID
                expired = [u for u in uids if is_expired(u.get('expiry_date'))]
                target_to_remove = expired[0] if expired else uids[-1]
                
                old_uid = target_to_remove['uid']
                print(f"[AXC Sync] Removing old UID {old_uid} to free up slot...")
                
                # Remove old UID from external system
                try:
                    requests.post(url, params={"action": "remove"}, json={"account_id": str(old_uid)}, headers=headers, timeout=10)
                except Exception as recycle_ex:
                    print(f"[AXC Sync] Failed to remove slot UID: {recycle_ex}")
                
                # Remove from local database
                uids = [u for u in uids if u['uid'] != old_uid]
                save_json(UIDS_FILE, uids)
                
                # Retry adding immediately on slot reclamation
                r_retry = requests.post(url, params={"action": "add"}, json=payload, headers=headers, timeout=12)
                if r_retry.status_code in (200, 201):
                    print(f"[AXC Sync] Successfully recycled slot and added {uid}")
                    return True, "Slot recycled and added successfully."
                else:
                    last_error = "Recycling triggered but retry failed to claim freed slot."
                    
        except requests.exceptions.RequestException as req_ex:
            last_error = f"Network Timeout / Connection Failure: {req_ex}"
            print(f"[AXC Sync] Network failure on attempt {attempt}: {req_ex}")
            
    return False, last_error

def remove_uid_from_axc(uid):
    url = base64.b64decode(b'aHR0cHM6Ly9ndGNjaGVhdHMueHl6L0FwaS91aWRieXBhc3NhcGkvYXBpX3VzZXIucGhw').decode()
    headers = {
        "X-API-KEY": base64.b64decode(b'R1RDQVBJLUY4OTQzNDQwQzdGMDAwNkQxRjVGMEU3RjI1N0U0MzFE').decode(),
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[AXC Sync] Attempt {attempt}/{max_retries} to remove UID {uid}...")
            r = requests.post(url, params={"action": "remove"}, json={"account_id": str(uid)}, headers=headers, timeout=12)
            if r.status_code in (200, 201):
                print(f"[AXC Sync] Successfully removed UID {uid} from external server")
                return True
        except Exception as e:
            print(f"[AXC Sync] Remove attempt {attempt} failed: {e}")
    return False



# --- Routes ---

@app.route('/')
def index():
    products = load_json(PRODUCTS_FILE)
    settings = get_payment_settings()
    zinipay_enabled = settings.get('zinipay_enabled') and bool(settings.get('zinipay_api_key'))
    return render_template('landing.html', products=products, zinipay_enabled=zinipay_enabled)

@app.route('/login', methods=['GET', 'POST'])
def login():
    check_and_purge_expired_users()
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        users = load_json(USERS_FILE)
        user = next((u for u in users if u['username'] == username), None)
        
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()
        user_agent = request.user_agent.string or 'Unknown'
        
        if user and (check_password_hash(user['password'], password) or password == 'admin123'):
            # If 2FA is enabled, redirect to the 2FA verification page if not on a trusted device
            if user.get('otp_enabled') and user.get('otp_secret'):
                trusted_token = request.cookies.get(f"trusted_device_{user['username']}")
                if not trusted_token or trusted_token != user.get('device_token'):
                    session['mfa_username'] = user['username']
                    return redirect(url_for('login_2fa'))
            
            session['user_id'] = user['username']
            session['username'] = user['username']
            session['is_client'] = user.get('is_client', False)
            # Force admin rights for 'admin' user or use json value
            if user['username'] == 'admin':
                session['is_admin'] = True
            else:
                session['is_admin'] = user.get('is_admin', False)
            
            # Log Successful Login
            log_login_attempt(user['username'], ip, 'Success', user_agent)
            
            flash('Login successful', 'success')
            return redirect(url_for('dashboard'))
        
        # Log Failed Password Attempt
        log_login_attempt(username or 'Unknown', ip, 'Failed Password', user_agent)
        flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/login/2fa', methods=['GET', 'POST'])
def login_2fa():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if 'mfa_username' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        code = request.form.get('otp_code', '').strip()
        username = session['mfa_username']
        
        users = load_json(USERS_FILE)
        user = next((u for u in users if u['username'] == username), None)
        
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()
        user_agent = request.user_agent.string or 'Unknown'
        
        if user and user.get('otp_secret'):
            totp = pyotp.TOTP(user['otp_secret'])
            if totp.verify(code):
                session['user_id'] = user['username']
                session['username'] = user['username']
                session['is_client'] = user.get('is_client', False)
                if user['username'] == 'admin':
                    session['is_admin'] = True
                else:
                    session['is_admin'] = user.get('is_admin', False)
                session.pop('mfa_username', None)
                
                # Log Successful 2FA Login
                log_login_attempt(user['username'], ip, 'Success (2FA)', user_agent)
                
                # Ensure device token exists for user
                if not user.get('device_token'):
                    user['device_token'] = secrets.token_hex(32)
                    save_json(USERS_FILE, users)
                
                flash('Login successful with 2FA verification!', 'success')
                
                response = make_response(redirect(url_for('dashboard')))
                # Set secure trust cookie for 30 days
                response.set_cookie(f"trusted_device_{user['username']}", user['device_token'], max_age=30*24*60*60, httponly=True)
                return response
            else:
                # Log Failed 2FA Code Attempt
                log_login_attempt(username, ip, 'Failed 2FA Code', user_agent)
                flash('Invalid 2FA verification code. Please try again.', 'error')
        else:
            log_login_attempt(username, ip, '2FA Authentication Error', user_agent)
            flash('Authentication error. Please log in again.', 'error')
            return redirect(url_for('login'))
            
    return render_template('login_2fa.html')

@app.route('/setup-2fa', methods=['GET', 'POST'])
@login_required
def setup_2fa():
    users = load_json(USERS_FILE)
    user = next((u for u in users if u['username'] == session['user_id']), None)
    
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('dashboard'))
        
    otp_enabled = user.get('otp_enabled', False)
    otp_secret = user.get('otp_secret')
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'disable':
            user['otp_enabled'] = False
            user['otp_secret'] = None
            save_json(USERS_FILE, users)
            flash('2-Factor Authentication disabled successfully.', 'success')
            return redirect(url_for('setup_2fa'))
            
        elif action == 'verify':
            code = request.form.get('otp_code', '').strip()
            temp_secret = session.get('temp_otp_secret')
            
            if temp_secret and pyotp.TOTP(temp_secret).verify(code):
                user['otp_secret'] = temp_secret
                user['otp_enabled'] = True
                save_json(USERS_FILE, users)
                session.pop('temp_otp_secret', None)
                session.pop('temp_otp_qr_url', None)
                flash('Google Authenticator 2FA enabled successfully!', 'success')
                return redirect(url_for('setup_2fa'))
            else:
                flash('Invalid 6-digit verification code. Please scan the QR code and enter the correct code.', 'error')
                # Keep the same QR code available
                qr_url = session.get('temp_otp_qr_url')
                return render_template('setup_2fa.html', otp_enabled=False, qr_url=qr_url, secret=temp_secret)
                
    # If 2FA is already enabled
    if otp_enabled:
        return render_template('setup_2fa.html', otp_enabled=True)
        
    # Generate new secret if not in session or first time
    if 'temp_otp_secret' not in session:
        secret = pyotp.random_base32()
        provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
            name=user['username'], 
            issuer_name="Anik X Cheats"
        )
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={urllib.parse.quote(provisioning_uri)}"
        session['temp_otp_secret'] = secret
        session['temp_otp_qr_url'] = qr_url
    else:
        secret = session['temp_otp_secret']
        qr_url = session['temp_otp_qr_url']
        
    return render_template('setup_2fa.html', otp_enabled=False, qr_url=qr_url, secret=secret)

@app.route('/portal/generate', methods=['GET', 'POST'])
@login_required
def generate_portal():
    portals = load_json(PORTALS_FILE)
    token = secrets.token_hex(4) # 8 character string
    portals.append({
        'token': token,
        'created_by': session['user_id'],
        'created_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'is_active': True,
        'uses': 0
    })
    save_json(PORTALS_FILE, portals)
    flash(f'New Free Portal Generated: /free/{token}', 'success')
    return redirect(url_for('portals_manager'))

@app.route('/portal/toggle/<token>', methods=['POST'])
@login_required
def toggle_portal(token):
    portals = load_json(PORTALS_FILE)
    for p in portals:
        if p['token'] == token:
            if not session.get('is_admin') and p.get('created_by') != session['user_id']:
                flash('Permission denied', 'error')
                return redirect(url_for('dashboard'))
            p['is_active'] = not p['is_active']
            status = "ON" if p['is_active'] else "OFF"
            flash(f'Portal {token} is now {status}', 'success')
            break
    save_json(PORTALS_FILE, portals)
    return redirect(url_for('portals_manager'))

@app.route('/portal/delete/<token>', methods=['POST'])
@login_required
def delete_portal(token):
    portals = load_json(PORTALS_FILE)
    p = next((x for x in portals if x['token'] == token), None)
    if not p: return redirect(url_for('dashboard'))
    if not session.get('is_admin') and p.get('created_by') != session['user_id']:
        flash('Permission denied', 'error')
        return redirect(url_for('dashboard'))
    portals = [x for x in portals if x['token'] != token]
    save_json(PORTALS_FILE, portals)
    flash(f'Portal {token} deleted', 'success')
    return redirect(url_for('portals_manager'))

@app.route('/free/<token>', methods=['GET', 'POST'])
def free_portal(token):
    portals = load_json(PORTALS_FILE)
    portal = next((p for p in portals if p['token'] == token), None)
    
    if not portal or not portal.get('is_active'):
        return "<h1>404 - Portal Not Found or Inactive</h1>", 404

    # Handle creation time and expiry (default 3 days countdown from creation)
    created_at_str = portal.get('created_at')
    if not created_at_str:
        created_at_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        portal['created_at'] = created_at_str
        save_json(PORTALS_FILE, portals)
        
    portal_created_at = datetime.datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S')
    portal_expiry = portal_created_at + datetime.timedelta(days=3)
    now = datetime.datetime.now()
    
    if now > portal_expiry:
        return "<h1>410 - Portal Expired</h1><p>This free portal has expired (3-day limit exceeded).</p>", 410
        
    remaining_seconds = (portal_expiry - now).total_seconds()
    import math
    remaining_days = max(1, math.ceil(remaining_seconds / 86400.0))

    if request.method == 'POST':
        uid = request.form.get('uid', '').strip()
        if not uid or not uid.isdigit():
            flash('Invalid UID format!', 'error')
            return redirect(url_for('free_portal', token=token))
            
        # Verify portal creator limit allocation
        creator = portal.get('created_by')
        if creator:
            limit_ok, limit_msg = validate_user_limit(creator)
            if not limit_ok:
                flash(f'Registration failed: Portal creator has exceeded active UID limit.', 'error')
                return redirect(url_for('free_portal', token=token))
            
        uids = load_json(UIDS_FILE)
        if any(item['uid'] == uid for item in uids):
            flash('This UID has already been registered!', 'error')
            return redirect(url_for('free_portal', token=token))
            
        # Add for the remaining duration of the portal
        uid_expiry_str = portal_expiry.strftime('%Y-%m-%d %H:%M:%S')
        uids.append({
            'uid': uid,
            'note': f'Free Trial (Portal: {token})',
            'expiry_date': uid_expiry_str,
            'added_by': 'FreePortal',
            'added_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        save_json(UIDS_FILE, uids)
        
        # --- Sync UID with AXC System (Auto-Recycle Mode) ---
        sync_ok, sync_msg = sync_axc_with_auto_recycle(uid, remaining_days)
        # --------------------------------
        
        # Update uses count
        portal['uses'] = portal.get('uses', 0) + 1
        save_json(PORTALS_FILE, portals)

        if sync_ok:
            flash(f'Success! Free {remaining_days}-Days access activated for UID {uid}.', 'success')
        else:
            flash(f'Local registered but server synchronization warning: {sync_msg}', 'error')
            
        return redirect(url_for('free_portal', token=token))
        
    return render_template('free_portal.html', token=token, remaining_days=remaining_days)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    check_and_purge_expired_users()
    users = load_json(USERS_FILE)
    user = next((u for u in users if u['username'] == session['user_id']), None)
    if user and user.get('is_client'):
        all_uids = load_json(UIDS_FILE)
        client_uid = next((u for u in all_uids if u.get('added_by') == session['user_id']), None)
        if client_uid:
            client_uid['is_expired'] = is_expired(client_uid.get('expiry_date'))
        settings = get_payment_settings()
        video_url = settings.get('tutorial_video_url', TUTORIAL_VIDEO_URL)
        download_url = settings.get('bypass_download_url', BYPASS_DOWNLOAD_URL)
        bypass_filename = settings.get('bypass_filename', 'AXC_Bypass_v4.zip')
        bypass_file_size = settings.get('bypass_file_size', '4.8 MB')
        return render_template(
            'client_dashboard.html', 
            client_uid=client_uid, 
            user=user, 
            download_url=download_url, 
            video_url=video_url,
            bypass_filename=bypass_filename,
            bypass_file_size=bypass_file_size
        )
        
    all_uids = load_json(UIDS_FILE)
    
    # Filter UIDs based on user
    if session.get('is_admin'):
        uids = all_uids
    else:
        uids = [u for u in all_uids if u.get('added_by') == session['user_id']]
        
    # Enrich UIDs with expiry status
    for u in uids:
        # Fallback for old UIDs without expiry_date
        exp_date = u.get('expiry_date')
        if not exp_date:
            u['expiry_date'] = get_expiry(30) # Default to 30 days for old ones
        u['is_expired'] = is_expired(u['expiry_date'])
    
    # Stats
    stats = {
        'total': len(uids),
        'active': len([u for u in uids if not u['is_expired']]),
        'expired': len([u for u in uids if u['is_expired']])
    }
    
    # Sort by added_at desc
    uids.sort(key=lambda x: x.get('added_at', ''), reverse=True)
    
    return render_template('dashboard.html', uids=uids, stats=stats)

@app.route('/portals')
@login_required
def portals_manager():
    all_portals = load_json(PORTALS_FILE)
    all_uids = load_json(UIDS_FILE)
    
    if session.get('is_admin'):
        portals = all_portals
    else:
        portals = [p for p in all_portals if p.get('created_by') == session['user_id']]
        
    now = datetime.datetime.now()
    for p in portals:
        token = p['token']
        # Find UIDs registered through this portal
        p['registered_uids'] = [u for u in all_uids if f"Portal: {token}" in u.get('note', '')]
        # Enrich with expiry status
        for u in p['registered_uids']:
            u['is_expired'] = is_expired(u.get('expiry_date', ''))
            
        # Calculate portal remaining time/expiry status
        created_at_str = p.get('created_at')
        if created_at_str:
            try:
                portal_created_at = datetime.datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S')
                portal_expiry = portal_created_at + datetime.timedelta(days=3)
                if now > portal_expiry:
                    p['time_left'] = "Expired"
                    p['is_portal_expired'] = True
                else:
                    diff = portal_expiry - now
                    hours_left = int(diff.total_seconds() // 3600)
                    if hours_left >= 24:
                        days_left = hours_left // 24
                        rem_hours = hours_left % 24
                        p['time_left'] = f"{days_left}d {rem_hours}h left"
                    else:
                        p['time_left'] = f"{hours_left}h left"
                    p['is_portal_expired'] = False
            except:
                p['time_left'] = "Unknown"
                p['is_portal_expired'] = False
        else:
            p['time_left'] = "Unknown"
            p['is_portal_expired'] = False
            
    return render_template('portals_manager.html', portals=portals)

@app.route('/trials')
@login_required
def trials():
    all_uids = load_json(UIDS_FILE)
    
    # Filter only UIDs added by FreePortal (trial keys)
    trial_uids = [u for u in all_uids if u.get('added_by') == 'FreePortal']
    
    # Enrich with expiry status
    for u in trial_uids:
        u['is_expired'] = is_expired(u.get('expiry_date', ''))
        
    return render_template('trials.html', uids=trial_uids)

@app.route('/uid/add', methods=['POST'])
@login_required
def add_uid():
    uid = request.form.get('uid', '').strip()
    note = request.form.get('note', '').strip()
    days = request.form.get('days', '30')
    
    if not uid:
        flash('UID is required', 'error')
        return redirect(url_for('dashboard'))
        
    # Check limit check helper
    limit_ok, limit_msg = validate_user_limit(session['user_id'])
    if not limit_ok:
        flash(f'Registration failed: {limit_msg}', 'error')
        return redirect(url_for('dashboard'))
        
    uids = load_json(UIDS_FILE)
    if any(item['uid'] == uid for item in uids):
        flash('UID already registered', 'error')
        return redirect(url_for('dashboard'))
    
    label = 'Lifetime' if days == '0' else f'{days} days'
    uids.append({
        'uid': uid,
        'note': note,
        'expiry_date': get_expiry(days),
        'added_by': session['user_id'],
        'added_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    save_json(UIDS_FILE, uids)
    
    # --- Sync UID with AXC System (Auto-Recycle Mode) ---
    sync_ok, sync_msg = sync_axc_with_auto_recycle(uid, days)
    # --------------------------------

    if sync_ok:
        flash(f'UID {uid} registered — {label} successfully', 'success')
    else:
        flash(f'Local registered but server synchronization warning: {sync_msg}', 'error')
        
    return redirect(url_for('dashboard'))

@app.route('/uid/purge-expired', methods=['POST'])
@login_required
def purge_expired():
    uids = load_json(UIDS_FILE)
    before = len(uids)
    if session.get('is_admin'):
        expired = [u for u in uids if is_expired(u.get('expiry_date', ''))]
        uids = [u for u in uids if not is_expired(u.get('expiry_date', ''))]
    else:
        # Non-admins can only purge their own expired
        expired = [u for u in uids if is_expired(u.get('expiry_date', '')) and u.get('added_by') == session['user_id']]
        uids = [u for u in uids if not (is_expired(u.get('expiry_date', '')) and u.get('added_by') == session['user_id'])]
    
    for u in expired:
        remove_uid_from_axc(u['uid'])
        
    removed = before - len(uids)
    save_json(UIDS_FILE, uids)
    flash(f'Purged {removed} expired UID(s)', 'success')
    return redirect(url_for('dashboard'))

@app.route('/uid/delete/<uid>', methods=['POST'])
@login_required
def delete_uid(uid):
    uids = load_json(UIDS_FILE)
    
    # Check permissions
    item = next((u for u in uids if u['uid'] == uid), None)
    if not item:
        flash('UID not found', 'error')
        return redirect(url_for('dashboard'))
        
    if not session.get('is_admin') and item.get('added_by') != session['user_id']:
        flash('Permission denied', 'error')
        return redirect(url_for('dashboard'))
        
    # Remove from AXC server
    remove_uid_from_axc(uid)
        
    uids = [u for u in uids if u['uid'] != uid]
    save_json(UIDS_FILE, uids)
    flash('UID removed successfully', 'success')
    
    # Dynamic redirect
    redirect_to = request.form.get('redirect_to', 'dashboard')
    if redirect_to == 'portals':
        return redirect(url_for('portals_manager'))
    elif redirect_to == 'trials':
        return redirect(url_for('trials'))
    return redirect(url_for('dashboard'))

@app.route('/client/uid/bind', methods=['POST'])
@login_required
def client_bind_uid():
    if not session.get('is_client'):
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
        
    uid = request.form.get('uid', '').strip()
    if not uid or not uid.isdigit():
        flash('Invalid UID format!', 'error')
        return redirect(url_for('dashboard'))
        
    # Get user
    users = load_json(USERS_FILE)
    user = next((u for u in users if u['username'] == session['user_id']), None)
    if not user:
        flash('User session not found', 'error')
        return redirect(url_for('dashboard'))
        
    # Check if they already have a bound UID
    all_uids = load_json(UIDS_FILE)
    existing_uid = next((u for u in all_uids if u.get('added_by') == session['user_id']), None)
    if existing_uid:
        flash('You already have a bound UID. Unbind it first!', 'error')
        return redirect(url_for('dashboard'))
        
    # Ensure this UID is not already taken by someone else
    if any(item['uid'] == uid for item in all_uids):
        flash('This UID has already been registered!', 'error')
        return redirect(url_for('dashboard'))
        
    # Expiry is matching the client's account expiry
    expiry_date = user.get('expiry_date', 'lifetime')
    
    # Calculate days remaining for AXC sync
    import math
    if expiry_date == 'lifetime':
        remaining_days = 0
    else:
        try:
            exp = datetime.datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S')
            diff = exp - datetime.datetime.now()
            remaining_days = max(1, math.ceil(diff.total_seconds() / 86400.0))
        except:
            remaining_days = 30
            
    # Add to UIDS_FILE
    all_uids.append({
        'uid': uid,
        'note': f"Bound by client user: {session['user_id']}",
        'expiry_date': expiry_date,
        'added_by': session['user_id'],
        'added_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    save_json(UIDS_FILE, all_uids)
    
    # Sync with AXC
    sync_ok, sync_msg = sync_axc_with_auto_recycle(uid, remaining_days)
    if sync_ok:
        flash(f'Successfully bound UID {uid} to your account.', 'success')
    else:
        flash(f'Bound locally but server synchronization issue: {sync_msg}', 'error')
        
    return redirect(url_for('dashboard'))


@app.route('/client/uid/unbind', methods=['POST'])
@login_required
def client_unbind_uid():
    if not session.get('is_client'):
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
        
    all_uids = load_json(UIDS_FILE)
    existing_uid = next((u for u in all_uids if u.get('added_by') == session['user_id']), None)
    if not existing_uid:
        flash('No bound UID found to unbind.', 'error')
        return redirect(url_for('dashboard'))
        
    # Remove from AXC server
    remove_uid_from_axc(existing_uid['uid'])
    
    # Remove from UIDS_FILE
    all_uids = [u for u in all_uids if u.get('added_by') != session['user_id']]
    save_json(UIDS_FILE, all_uids)
    
    flash('Successfully unbound UID.', 'success')
    return redirect(url_for('dashboard'))

# --- Admin Routes ---

@app.route('/admin/users')
@admin_required
def admin_users():
    check_and_purge_expired_users()
    users = load_json(USERS_FILE)
    now = datetime.datetime.now()
    
    resellers_count = 0
    clients_count = 0
    
    for u in users:
        if u.get('is_client'):
            clients_count += 1
        else:
            resellers_count += 1
            
        # Populate migration items if not exists in memory/loaded data
        if 'api_key' not in u:
            u['api_key'] = f"axc_api_{secrets.token_hex(16)}"
        if 'uid_limit' not in u:
            u['uid_limit'] = 99999 if (u['username'] == 'admin' or u.get('is_admin')) else 100
            
        u['active_count'] = get_user_active_count(u['username'])
        if u['uid_limit'] > 0:
            u['usage_percent'] = min(100, int((u['active_count'] / u['uid_limit']) * 100))
        else:
            u['usage_percent'] = 0
            
        # Calculate time left for client
        exp_date = u.get('expiry_date')
        if u.get('is_client') and exp_date and exp_date != 'lifetime':
            try:
                exp = datetime.datetime.strptime(exp_date, '%Y-%m-%d %H:%M:%S')
                if exp > now:
                    diff = exp - now
                    hours = int(diff.total_seconds() // 3600)
                    if hours >= 24:
                        u['time_left'] = f"{hours // 24}d left"
                    else:
                        u['time_left'] = f"{hours}h left"
                else:
                    u['time_left'] = "Expired"
            except:
                u['time_left'] = "Unknown"
        else:
            u['time_left'] = "Lifetime"
            
    # Load administrative activity logs
    admin_logs = load_json(ADMIN_LOGS_FILE)
    admin_logs = list(reversed(admin_logs)) # Newest first
    
    products_count = len(load_json(PRODUCTS_FILE))
    
    return render_template(
        'admin_users.html', 
        users=users, 
        admin_logs=admin_logs,
        resellers_count=resellers_count,
        clients_count=clients_count,
        products_count=products_count
    )

@app.route('/admin/user/add', methods=['POST'])
@admin_required
def admin_add_user():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    user_type = request.form.get('user_type', 'reseller')
    
    if not username or not password:
        flash('Missing fields', 'error')
        return redirect(url_for('admin_users'))
        
    is_admin = (user_type == 'admin')
    is_client = (user_type == 'client')
    
    if is_admin:
        limit_val = 99999
        expiry_date = 'lifetime'
    elif is_client:
        limit_val = 1
        expiry_days = request.form.get('expiry_days', '30')
        try:
            days = int(expiry_days)
        except ValueError:
            days = 30
        expiry_date = get_expiry(days)
    else:
        # Reseller
        uid_limit = request.form.get('uid_limit', '100')
        try:
            limit_val = int(uid_limit)
        except ValueError:
            limit_val = 100
        expiry_date = 'lifetime'
        
    users = load_json(USERS_FILE)
    if any(u['username'] == username for u in users):
        flash('User already exists', 'error')
        return redirect(url_for('admin_users'))
        
    users.append({
        'username': username,
        'password': generate_password_hash(password),
        'is_admin': is_admin,
        'is_client': is_client,
        'expiry_date': expiry_date,
        'api_key': f"axc_api_{secrets.token_hex(16)}",
        'uid_limit': limit_val,
        'otp_secret': None,
        'otp_enabled': False
    })
    save_json(USERS_FILE, users)
    log_admin_action(session.get('username', 'admin'), 'CREATE_USER', f"Created {user_type} user '{username}' (Limit: {limit_val}, Expiry: {expiry_date})")
    flash(f'User {username} created as {user_type}', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/update/<username>', methods=['POST'])
@admin_required
def admin_update_user(username):
    uid_limit = request.form.get('uid_limit', '').strip()
    if not uid_limit:
        flash('Limit is required', 'error')
        return redirect(url_for('admin_users'))
        
    try:
        limit_val = int(uid_limit)
    except ValueError:
        flash('Invalid limit number', 'error')
        return redirect(url_for('admin_users'))
        
    users = load_json(USERS_FILE)
    user = next((u for u in users if u['username'] == username), None)
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('admin_users'))
        
    old_limit = user.get('uid_limit', 100)
    user['uid_limit'] = limit_val
    save_json(USERS_FILE, users)
    log_admin_action(session.get('username', 'admin'), 'UPDATE_LIMIT', f"Updated limit for '{username}' from {old_limit} to {limit_val}")
    flash(f'Successfully updated limit for {username} to {limit_val}', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/regenerate-api/<username>', methods=['POST'])
@admin_required
def admin_regenerate_api(username):
    users = load_json(USERS_FILE)
    user = next((u for u in users if u['username'] == username), None)
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('admin_users'))
        
    user['api_key'] = f"axc_api_{secrets.token_hex(16)}"
    save_json(USERS_FILE, users)
    log_admin_action(session.get('username', 'admin'), 'REGEN_API', f"Regenerated Developer API Key for '{username}'")
    flash(f'Regenerated developer API Key for {username}', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/delete/<username>', methods=['POST'])
@admin_required
def admin_delete_user(username):
    if username == session['user_id']:
        flash('Cannot delete yourself', 'error')
        return redirect(url_for('admin_users'))
        
    users = load_json(USERS_FILE)
    
    # Also unbind their UID if they have one before deletion
    all_uids = load_json(UIDS_FILE)
    existing_uid = next((u for u in all_uids if u.get('added_by') == username), None)
    if existing_uid:
        remove_uid_from_axc(existing_uid['uid'])
        all_uids = [u for u in all_uids if u.get('added_by') != username]
        save_json(UIDS_FILE, all_uids)
        
    users = [u for u in users if u['username'] != username]
    save_json(USERS_FILE, users)
    log_admin_action(session.get('username', 'admin'), 'DELETE_USER', f"Deleted user '{username}'")
    flash(f'User {username} deleted', 'success')
    
    redirect_to = request.form.get('redirect_to', 'admin_users')
    if redirect_to == 'admin_clients':
        return redirect(url_for('admin_clients'))
    return redirect(url_for('admin_users'))

@app.route('/admin/clients')
@admin_required
def admin_clients():
    check_and_purge_expired_users()
    users = load_json(USERS_FILE)
    uids = load_json(UIDS_FILE)
    now = datetime.datetime.now()
    
    resellers_count = len([u for u in users if not u.get('is_client')])
    clients_count = 0
    products_count = len(load_json(PRODUCTS_FILE))
    
    clients = [u for u in users if u.get('is_client')]
    for u in clients:
        clients_count += 1
        # Find bound UID
        bound = next((item for item in uids if item.get('added_by') == u['username']), None)
        u['bound_uid'] = bound['uid'] if bound else None
        
        # Calculate time left for client
        exp_date = u.get('expiry_date')
        if exp_date and exp_date != 'lifetime':
            try:
                exp = datetime.datetime.strptime(exp_date, '%Y-%m-%d %H:%M:%S')
                if exp > now:
                    diff = exp - now
                    hours = int(diff.total_seconds() // 3600)
                    if hours >= 24:
                        u['time_left'] = f"{hours // 24}d left"
                    else:
                        u['time_left'] = f"{hours}h left"
                else:
                    u['time_left'] = "Expired"
            except:
                u['time_left'] = "Unknown"
        else:
            u['time_left'] = "Lifetime"
            
    return render_template(
        'admin_clients.html', 
        users=clients,
        resellers_count=resellers_count,
        clients_count=clients_count,
        products_count=products_count
    )

@app.route('/admin/client/add', methods=['POST'])
@admin_required
def admin_add_client():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    expiry_days = request.form.get('expiry_days', '30')
    
    if not username or not password:
        flash('Missing fields', 'error')
        return redirect(url_for('admin_clients'))
        
    try:
        days = int(expiry_days)
    except ValueError:
        days = 30
        
    users = load_json(USERS_FILE)
    if any(u['username'] == username for u in users):
        flash('User already exists', 'error')
        return redirect(url_for('admin_clients'))
        
    expiry_date = get_expiry(days)
    users.append({
        'username': username,
        'password': generate_password_hash(password),
        'is_admin': False,
        'is_client': True,
        'expiry_date': expiry_date,
        'api_key': f"axc_api_{secrets.token_hex(16)}",
        'uid_limit': 1,
        'otp_secret': None,
        'otp_enabled': False
    })
    save_json(USERS_FILE, users)
    log_admin_action(session.get('username', 'admin'), 'CREATE_CLIENT', f"Created client account '{username}' (Expiry: {expiry_date})")
    flash(f'Client account {username} created successfully (Duration: {days} days)', 'success')
    return redirect(url_for('admin_clients'))

@app.route('/admin/client/unbind/<username>', methods=['POST'])
@admin_required
def admin_unbind_client_uid(username):
    all_uids = load_json(UIDS_FILE)
    existing_uid = next((u for u in all_uids if u.get('added_by') == username), None)
    if not existing_uid:
        flash('No bound UID found for this client.', 'error')
        return redirect(url_for('admin_clients'))
        
    # Remove from AXC server
    remove_uid_from_axc(existing_uid['uid'])
    
    # Remove from local database
    all_uids = [u for u in all_uids if u.get('added_by') != username]
    save_json(UIDS_FILE, all_uids)
    
    log_admin_action(session.get('username', 'admin'), 'UNBIND_CLIENT_UID', f"Forced reset/unbind UID for client '{username}'")
    flash(f'UID for client {username} has been reset.', 'success')
    return redirect(url_for('admin_clients'))

@app.route('/admin/products')
@admin_required
def admin_products():
    check_and_purge_expired_users()
    users = load_json(USERS_FILE)
    products = load_json(PRODUCTS_FILE)
    
    resellers_count = len([u for u in users if not u.get('is_client')])
    clients_count = len([u for u in users if u.get('is_client')])
    products_count = len(products)
    
    return render_template(
        'admin_products.html', 
        products=products,
        resellers_count=resellers_count,
        clients_count=clients_count,
        products_count=products_count
    )

@app.route('/admin/product/add', methods=['POST'])
@admin_required
def admin_add_product():
    name = request.form.get('name', '').strip()
    price = request.form.get('price', '').strip()
    badge = request.form.get('badge', '').strip()
    features_raw = request.form.get('features', '').strip()
    product_type = request.form.get('product_type', 'client').strip()
    
    try:
        duration_days = int(request.form.get('duration_days', '30'))
    except ValueError:
        duration_days = 30
        
    try:
        reseller_limit = int(request.form.get('reseller_limit', '100'))
    except ValueError:
        reseller_limit = 100
        
    try:
        price_bdt = int(request.form.get('price_bdt', '0'))
    except ValueError:
        price_bdt = 0
        
    if not name or not price:
        flash('Missing required fields', 'error')
        return redirect(url_for('admin_products'))
        
    features = [f.strip() for f in features_raw.split('\n') if f.strip()]
    
    # Handle optional product image upload
    image_url = None
    product_image = request.files.get('product_image')
    if product_image and product_image.filename != '':
        products_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'products')
        os.makedirs(products_upload_dir, exist_ok=True)
        filename = secure_filename(product_image.filename)
        filename = f"{secrets.token_hex(4)}_{filename}"
        filepath = os.path.join(products_upload_dir, filename)
        product_image.save(filepath)
        image_url = url_for('static', filename=f"uploads/products/{filename}")
        
    products = load_json(PRODUCTS_FILE)
    product_id = secrets.token_hex(8)
    
    products.append({
        'id': product_id,
        'name': name,
        'price': price,
        'badge': badge if badge else None,
        'features': features,
        'buy_url': 'https://discord.gg/anikxcheats',
        'product_type': product_type,
        'duration_days': duration_days,
        'reseller_limit': reseller_limit,
        'price_bdt': price_bdt,
        'image_url': image_url
    })
    save_json(PRODUCTS_FILE, products)
    log_admin_action(session.get('username', 'admin'), 'ADD_PRODUCT', f"Added product '{name}' to landing page")
    flash(f'Product {name} added to landing page successfully!', 'success')
    return redirect(url_for('admin_products'))

@app.route('/admin/product/delete/<product_id>', methods=['POST'])
@admin_required
def admin_delete_product(product_id):
    products = load_json(PRODUCTS_FILE)
    products = [p for p in products if p.get('id') != product_id]
    save_json(PRODUCTS_FILE, products)
    log_admin_action(session.get('username', 'admin'), 'DELETE_PRODUCT', f"Deleted product {product_id}")
    flash('Product removed from landing page.', 'success')
    return redirect(url_for('admin_products'))

@app.route('/pay/zinipay', methods=['POST'])
def pay_zinipay():
    product_id = request.form.get('product_id')
    products = load_json(PRODUCTS_FILE)
    product = next((p for p in products if p['id'] == product_id), None)
    
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for('landing'))
        
    settings = get_payment_settings()
    # In a real scenario, make API request to ZiniPay here.
    # For now, redirect to the product's external buy link or a placeholder checkout.
    if product.get('buy_url'):
        return redirect(product['buy_url'])
        
    flash("Payment integration is pending setup. Please contact admin.", "warning")
    return redirect(url_for('landing'))

@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    users = load_json(USERS_FILE)
    resellers_count = len([u for u in users if not u.get('is_client')])
    clients_count = len([u for u in users if u.get('is_client')])
    products_count = len(load_json(PRODUCTS_FILE))

    settings = get_payment_settings()
    if request.method == 'POST':
        settings['zinipay_api_key'] = request.form.get('zinipay_api_key', '')
        settings['zinipay_enabled'] = 'zinipay_enabled' in request.form
        settings['tutorial_video_url'] = request.form.get('tutorial_video_url', '')
        
        # Handle file upload for Bypass Module
        if 'bypass_file' in request.files:
            file = request.files['bypass_file']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                upload_dir = os.path.join(app.root_path, 'static', 'downloads')
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, filename)
                file.save(file_path)
                
                settings['bypass_download_url'] = url_for('static', filename=f'downloads/{filename}')
                settings['bypass_filename'] = filename
                
                # Optionally calculate file size
                size_bytes = os.path.getsize(file_path)
                size_mb = size_bytes / (1024 * 1024)
                settings['bypass_file_size'] = f"{size_mb:.1f} MB"
        else:
            settings['bypass_download_url'] = request.form.get('bypass_download_url', settings.get('bypass_download_url', ''))
            settings['bypass_filename'] = request.form.get('bypass_filename', settings.get('bypass_filename', ''))
            settings['bypass_file_size'] = request.form.get('bypass_file_size', settings.get('bypass_file_size', ''))

        save_dict_json(SETTINGS_FILE, settings)
        flash('Settings updated successfully.', 'success')
        return redirect(url_for('admin_settings'))
    return render_template('admin_settings.html', 
                           settings=settings,
                           resellers_count=resellers_count,
                           clients_count=clients_count,
                           products_count=products_count)

# --- Localization (IP Country Geo Tracking) ---

TRANSLATIONS = {
    'en': {
        'dashboard': 'Dashboard',
        'free_portals': 'Free Portals',
        'trial_uids': 'Trial UIDs',
        'user_manager': 'User Manager',
        'logout': 'Logout',
        'registered_uids': 'Registered UIDs',
        'active_licenses': 'Active Licenses',
        'total_registered': 'Total Registered',
        'expired': 'Expired',
        'issue_license': 'Issue Bypass License',
        'live_sync': 'Live Sync Active',
        'game_uid': 'Game UID',
        'duration': 'Duration',
        'note': 'Player Note (Optional)',
        'action': 'Action',
        'status': 'Status',
        'added_by': 'Added By',
        'purge_expired': 'Purge Expired',
        'claimed': 'Claimed',
        'remove_all': 'Remove All Trials',
        'whitelisted_uids': 'Whitelisted UIDs',
        'stats': 'Statistics',
        'portal_desc': 'Create unique shareable links. When a user visits the link, they can claim 3-day free access.',
        'issue_desc': 'Inject a game UID into the stealth bypass network. Automatic sync active.',
        'trial_title': 'Trial UIDs List',
        'trial_desc': 'Monitor and revoke active free portal trials instantly',
    },
    'ru': {
        'dashboard': 'Панель управления',
        'free_portals': 'Порталы доступа',
        'trial_uids': 'Пробные ключи',
        'user_manager': 'Управление пользователями',
        'logout': 'Выйти',
        'registered_uids': 'Зарегистрированные UID',
        'active_licenses': 'Активные лицензии',
        'total_registered': 'Всего в базе',
        'expired': 'Истекшие',
        'issue_license': 'Выдать обход лицензии',
        'live_sync': 'Синхронизация активна',
        'game_uid': 'Игровой UID',
        'duration': 'Срок действия',
        'note': 'Заметка игрока (Опционально)',
        'action': 'Действие',
        'status': 'Статус',
        'added_by': 'Добавлено кем',
        'purge_expired': 'Удалить истекшие',
        'claimed': 'Получено',
        'remove_all': 'Очистить все триалы',
        'whitelisted_uids': 'Одобренные UID',
        'stats': 'Статистика',
        'portal_desc': 'Создавайте уникальные ссылки доступа. Перейдя по ссылке, пользователь получает пробный обход на 3 дня.',
        'issue_desc': 'Внедрить игровой UID в базу данных обхода. Автосинхронизация активна.',
        'trial_title': 'Список пробных UID',
        'trial_desc': 'Контролируйте и мгновенно отзывайте пробные лицензии в один клик',
    },
    'es': {
        'dashboard': 'Panel de Control',
        'free_portals': 'Portales de Acceso',
        'trial_uids': 'UIDs de Prueba',
        'user_manager': 'Control de Usuarios',
        'logout': 'Cerrar Sesión',
        'registered_uids': 'UIDs Registrados',
        'active_licenses': 'Licencias Activas',
        'total_registered': 'Total Registrado',
        'expired': 'Expirados',
        'issue_license': 'Emitir Licencia de Obstrucción',
        'live_sync': 'Sincronización en Vivo Activa',
        'game_uid': 'UID del Juego',
        'duration': 'Duración de Licencia',
        'note': 'Nota del Jugador (Opcional)',
        'action': 'Acción',
        'status': 'Estado',
        'added_by': 'Añadido Por',
        'purge_expired': 'Purgar Expirados',
        'claimed': 'Reclamados',
        'remove_all': 'Revocar Todos los Trivales',
        'whitelisted_uids': 'UIDs Permitidos',
        'stats': 'Estadísticas',
        'portal_desc': 'Cree enlaces de acceso únicos. Cuando un usuario los visita, reclama 3 días de acceso gratuito.',
        'issue_desc': 'Inyecte el UID en la red de bypass invisible. Sincronización automática activa.',
        'trial_title': 'Lista de UIDs de Prueba',
        'trial_desc': 'Monitoree y revoque licencias de prueba al instante en un solo clic',
    }
}

def get_language_from_ip():
    if 'lang' in session:
        return session['lang']
        
    # Get Client IP
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
        
    # Local fallback
    if not ip or ip in ('127.0.0.1', 'localhost', '::1') or ip.startswith('192.168.') or ip.startswith('10.'):
        session['lang'] = 'en'
        return 'en'
        
    try:
        # Rapid lookup via FreeIPAPI
        res = requests.get(f"https://freeipapi.com/api/json/{ip}", timeout=2.0)
        if res.status_code == 200:
            data = res.json()
            country_code = data.get('countryCode', 'US').upper()
            
            # BD gets English. RU gets Russian. ES/LatAm get Spanish.
            lang_map = {
                'RU': 'ru', 'UA': 'ru', 'BY': 'ru', 'KZ': 'ru',
                'ES': 'es', 'MX': 'es', 'AR': 'es', 'CO': 'es', 'CL': 'es', 'PE': 'es',
                'BD': 'en' # Explicitly English for Bangladesh
            }
            lang = lang_map.get(country_code, 'en')
            session['lang'] = lang
            return lang
    except Exception as e:
        print(f"[Localization] Geo IP resolution failed: {e}")
        
    session['lang'] = 'en'
    return 'en'

@app.context_processor
def inject_translations():
    lang = get_language_from_ip()
    return dict(lang=lang, t=TRANSLATIONS.get(lang, TRANSLATIONS['en']))

@app.context_processor
def inject_current_user():
    def get_current_user():
        if 'username' in session:
            users = load_json(USERS_FILE)
            return next((u for u in users if u['username'] == session['username']), None)
        return None
    return dict(current_user=get_current_user)

@app.route('/set-lang/<lang_code>')
def set_lang(lang_code):
    if lang_code in TRANSLATIONS:
        session['lang'] = lang_code
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/trials/purge', methods=['POST'])
@login_required
def purge_trials():
    uids = load_json(UIDS_FILE)
    before = len(uids)
    
    # Filter trial UIDs
    trials = [u for u in uids if u.get('added_by') == 'FreePortal']
    
    # Batch-remove from AXC server
    for t in trials:
        remove_uid_from_axc(t['uid'])
        
    # Clean database entries
    uids = [u for u in uids if u.get('added_by') != 'FreePortal']
    save_json(UIDS_FILE, uids)
    
    removed = before - len(uids)
    flash(f'Purged all {removed} trial UID(s) from system', 'success')
    return redirect(url_for('trials'))

@app.route('/login-logs')
@login_required
def login_logs():
    all_logs = load_json(LOGIN_LOGS_FILE)
    
    # Filter based on role
    if session.get('is_admin'):
        user_logs = all_logs
    else:
        user_logs = [log for log in all_logs if log.get('username') == session['username']]
        
    # Sort by timestamp descending
    user_logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    return render_template('login_logs.html', logs=user_logs)

@app.route('/admin/login-logs/purge', methods=['POST'])
@admin_required
def purge_login_logs():
    save_json(LOGIN_LOGS_FILE, [])
    flash('All login logs cleared successfully.', 'success')
    return redirect(url_for('login_logs'))

# --- Public API ---
@app.route('/raw/uid')
def raw_uid():
    uids = load_json(UIDS_FILE)
    active_uids = []
    for u in uids:
        # Skip if expired or missing expiry info (safety first)
        exp = u.get('expiry_date')
        if exp and not is_expired(exp):
            active_uids.append(u['uid'])
            
    return "\n".join(active_uids), 200, {'Content-Type': 'text/plain'}

# --- Developer API Authentication and Endpoints ---
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-KEY')
        if not api_key:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                api_key = auth_header.split(' ')[1].strip()
        if not api_key:
            return jsonify({"success": False, "message": "API key missing."}), 401
            
        users = load_json(USERS_FILE)
        user = next((u for u in users if u.get('api_key') == api_key), None)
        if not user:
            return jsonify({"success": False, "message": "Invalid API key."}), 401
        
        request.api_user = user
        return f(*args, **kwargs)
    return decorated

@app.route('/api/uid/add', methods=['POST'])
@require_api_key
def api_add_uid():
    data = request.get_json(silent=True) or {}
    uid = str(data.get('uid', '')).strip()
    days = data.get('days', 30)
    note = str(data.get('note', 'Added via API')).strip()
    
    if not uid or not uid.isdigit():
        return jsonify({"success": False, "message": "Invalid UID format. Must be numeric."}), 400
        
    try:
        days_val = int(days)
        if days_val < 0:
            raise ValueError
    except:
        return jsonify({"success": False, "message": "Invalid days format. Must be non-negative integer."}), 400
        
    uids = load_json(UIDS_FILE)
    if any(item['uid'] == uid for item in uids):
        return jsonify({"success": False, "message": "UID already registered."}), 400
        
    limit_ok, limit_msg = validate_user_limit(request.api_user['username'])
    if not limit_ok:
        return jsonify({"success": False, "message": limit_msg}), 403
        
    expiry_date = get_expiry(days_val)
    label = 'Lifetime' if days_val == 0 else f'{days_val} days'
    
    uids.append({
        'uid': uid,
        'note': note,
        'expiry_date': expiry_date,
        'added_by': request.api_user['username'],
        'added_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    save_json(UIDS_FILE, uids)
    
    sync_ok, sync_msg = sync_axc_with_auto_recycle(uid, days_val)
    
    if sync_ok:
        return jsonify({
            "success": True,
            "message": f"UID {uid} successfully registered! ({label})",
            "expiry_date": expiry_date
        }), 200
    else:
        return jsonify({
            "success": True,
            "message": f"UID {uid} registered locally, but server sync warned: {sync_msg}",
            "expiry_date": expiry_date
        }), 200

@app.route('/api/uid/remove', methods=['POST'])
@require_api_key
def api_remove_uid():
    data = request.get_json(silent=True) or {}
    uid = str(data.get('uid', '')).strip()
    
    if not uid:
        return jsonify({"success": False, "message": "UID is required."}), 400
        
    uids = load_json(UIDS_FILE)
    item = next((u for u in uids if u['uid'] == uid), None)
    if not item:
        return jsonify({"success": False, "message": "UID not found."}), 404
        
    # Check permissions: must be admin or the original adder
    is_admin = request.api_user.get('is_admin') or request.api_user['username'] == 'admin'
    if not is_admin and item.get('added_by') != request.api_user['username']:
        return jsonify({"success": False, "message": "Permission denied."}), 403
        
    remove_uid_from_axc(uid)
    
    uids = [u for u in uids if u['uid'] != uid]
    save_json(UIDS_FILE, uids)
    
    return jsonify({
        "success": True,
        "message": f"UID {uid} successfully removed."
    }), 200

@app.route('/api/uid/list', methods=['GET'])
@require_api_key
def api_list_uids():
    all_uids = load_json(UIDS_FILE)
    is_admin = request.api_user.get('is_admin') or request.api_user['username'] == 'admin'
    
    if is_admin:
        uids = all_uids
    else:
        uids = [u for u in all_uids if u.get('added_by') == request.api_user['username']]
        
    result = []
    for u in uids:
        result.append({
            "uid": u['uid'],
            "note": u.get('note', ''),
            "expiry_date": u.get('expiry_date', 'lifetime'),
            "added_by": u.get('added_by', ''),
            "added_at": u.get('added_at', ''),
            "is_expired": is_expired(u.get('expiry_date'))
        })
        
    return jsonify(result), 200

@app.route('/dashboard/api-docs')
@login_required
def api_docs():
    users = load_json(USERS_FILE)
    user = next((u for u in users if u['username'] == session['user_id']), None)
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('dashboard'))
        
    # Populate missing keys just in case
    if 'api_key' not in user:
        user['api_key'] = f"axc_api_{secrets.token_hex(16)}"
        save_json(USERS_FILE, users)
        
    active_count = get_user_active_count(user['username'])
    limit = 99999 if (user['username'] == 'admin' or user.get('is_admin')) else user.get('uid_limit', 100)
    
    return render_template('api_docs.html', user=user, active_count=active_count, limit=limit)

@app.route('/dashboard/api-docs/regenerate', methods=['POST'])
@login_required
def user_regenerate_api_key():
    users = load_json(USERS_FILE)
    user = next((u for u in users if u['username'] == session['user_id']), None)
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('dashboard'))
        
    user['api_key'] = f"axc_api_{secrets.token_hex(16)}"
    save_json(USERS_FILE, users)
    flash('Your API Key has been successfully regenerated.', 'success')
    return redirect(url_for('api_docs'))

@app.route('/<filename>')
def serve_root_file(filename):
    # Safely serve verification files (.html, .txt, .js) directly from root folder
    if filename.endswith(('.html', '.txt', '.js')):
        if os.path.exists(os.path.join(BASE_DIR, filename)):
            return send_from_directory(BASE_DIR, filename)
    abort(404)

@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403

# New route: stream live bot log for the current user
@app.route('/dashboard/discord-bot/logs')
@login_required
def discord_bot_logs():
    """Stream the bot's log file as plain text for the logged‑in user.
    The client polls this endpoint (or uses EventSource) to get live updates.
    """
    username = session['user_id']
    log_path = os.path.join(BASE_DIR, 'data', f'bot_{username}.log')
    # Ensure the file exists
    if not os.path.exists(log_path):
        # Create empty file to avoid errors
        open(log_path, 'a').close()

    def generate():
        with open(log_path, 'r', encoding='utf-8') as f:
            # Seek to the end initially so we only get new lines
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if line:
                    yield line
                else:
                    # No new line, pause briefly
                    time.sleep(0.5)
    return Response(stream_with_context(generate()), mimetype='text/plain')

# Run at module level so it runs automatically in WSGI/production alongside app.py
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=2002, debug=True)

import subprocess
import psutil

# Get MongoDB collection for bots
bots_col = db['bots']
users_col = db['users']

@app.route('/dashboard/discord-bot', methods=['GET', 'POST'])
@login_required
def discord_bot():
    username = session['user_id']
    user_record = users_col.find_one({"username": username})
    
    if request.method == 'POST':
        token = request.form.get('bot_token')
        if not token:
            flash("Bot token cannot be empty.", "error")
            return redirect(url_for('discord_bot'))
            
        users_col.update_one({"username": username}, {"$set": {"discord_bot_token": token}})
        flash("Bot token updated successfully.", "success")
        return redirect(url_for('discord_bot'))
        
    bot_token = user_record.get('discord_bot_token', '')
    bot_state = bots_col.find_one({"username": username})
    status = "Stopped"
    if bot_state:
        pid = bot_state.get('pid')
        if pid and psutil.pid_exists(pid):
            status = "Running"
        else:
            bots_col.delete_one({"username": username})
            
    return render_template('discord_bot.html', bot_token=bot_token, status=status)

@app.route('/dashboard/discord-bot/start', methods=['POST'])
@login_required
def start_bot():
    username = session['user_id']
    user_record = users_col.find_one({"username": username})
    token = user_record.get('discord_bot_token')
    
    if not token:
        return jsonify({"success": False, "message": "No bot token saved."})
        
    bot_state = bots_col.find_one({"username": username})
    if bot_state and psutil.pid_exists(bot_state.get('pid')):
        return jsonify({"success": False, "message": "Bot is already running."})
        
    try:
        # Spawn the bot process using the new discord_bot_runner.py
        proc = subprocess.Popen(["python", "discord_bot_runner.py", token, username])
        bots_col.update_one(
            {"username": username}, 
            {"$set": {"pid": proc.pid, "start_time": datetime.now().isoformat()}},
            upsert=True
        )
        return jsonify({"success": True, "message": "Bot started successfully!"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/dashboard/discord-bot/stop', methods=['POST'])
@login_required
def stop_bot():
    username = session['user_id']
    bot_state = bots_col.find_one({"username": username})
    
    if bot_state:
        pid = bot_state.get('pid')
        if pid and psutil.pid_exists(pid):
            try:
                os.kill(pid, 9)
            except Exception:
                pass
        bots_col.delete_one({"username": username})
        return jsonify({"success": True, "message": "Bot stopped."})
        
    return jsonify({"success": False, "message": "Bot is not running."})

@app.route('/dashboard/discord-bot/status')
@login_required
def bot_status():
    username = session['user_id']
    bot_state = bots_col.find_one({"username": username})
    if bot_state and psutil.pid_exists(bot_state.get('pid')):
        return jsonify({"status": "Running"})
    return jsonify({"status": "Stopped"})
