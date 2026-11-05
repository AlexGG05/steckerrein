"""Dependency-free community server. Run with Python 3.12+."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import smtplib
import ssl
from email.message import EmailMessage
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).parent
DB = Path(os.environ.get('DATABASE_PATH', ROOT / 'data/community.db'))
CATEGORIES = {'allgemein': 'Allgemein', 'it': 'IT & Homelab', '3d-druck': '3D-Druck', 'projekte': 'Projekte & Builds'}
SESSION_TTL = 7 * 86400
VERIFY_TTL = 24 * 3600
RATE_LOCK = threading.Lock()

def connect():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE, password TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('forum','blog')), category TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, user_id INTEGER REFERENCES users(id), created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS comments_post ON comments(post_id);
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        db.execute('BEGIN IMMEDIATE')
        columns = {r['name'] for r in db.execute('PRAGMA table_info(users)')}
        if 'email' not in columns:
            db.execute('ALTER TABLE users ADD COLUMN email TEXT COLLATE NOCASE')
        if 'email_verified' not in columns:
            db.execute('ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0')
            # Existing accounts must verify as well. Revoke pre-migration sessions.
            db.execute('DELETE FROM sessions')
        db.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(email) WHERE email IS NOT NULL;
        CREATE TABLE IF NOT EXISTS email_tokens(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE, expires INTEGER NOT NULL, sent INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS rate_limits(bucket TEXT NOT NULL, subject TEXT NOT NULL, started INTEGER NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(bucket,subject));
        """)
        db.execute('CREATE TABLE IF NOT EXISTS topics(slug TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, description TEXT NOT NULL)')
        if not db.execute("SELECT 1 FROM metadata WHERE key='topics_initialized'").fetchone():
            descriptions={'it':'Server, Netzwerke, Software und dein eigenes Homelab.', '3d-druck':'Drucker, Filamente, Slicer und Hilfe beim nächsten Druck.', 'projekte':'Zeig deine Builds und entwickle gemeinsam neue Ideen.', 'allgemein':'Vorstellen, austauschen und über den Tellerrand schauen.'}
            for slug,name in CATEGORIES.items():
                db.execute('INSERT OR IGNORE INTO topics VALUES(?,?,?)',(slug,name,descriptions[slug]))
            db.execute("INSERT INTO metadata VALUES('topics_initialized','1')")
        if not db.execute("SELECT 1 FROM metadata WHERE key='initialized'").fetchone():
            articles = [
                ('it', 'Dein Homelab beginnt mit einer guten Frage', 'Ein eigener Server muss kein großes Rack sein. Ein ausrangierter Mini-PC mit 8 GB RAM reicht oft für die ersten Dienste.\n\nÜberlege zuerst, was du lernen möchtest: Backups, Container oder Netzwerke? Starte mit einem Dienst und dokumentiere die Einrichtung. Docker Compose macht Konfigurationen nachvollziehbar.\n\nBevor du Dienste ins Internet stellst, richte Updates, starke Zugangsdaten und Backups ein. Teste auch die Wiederherstellung. Für den Fernzugriff ist ein VPN oft der bessere Einstieg als offene Ports.\n\nWas läuft in deinem Homelab? Eröffne ein Thema im Forum und zeig uns dein Setup.'),
                ('3d-druck', 'Der erste Layer: die Grundlage für gute Drucke', 'Wenn die erste Schicht nicht haftet, helfen höhere Temperaturen allein selten weiter. Prüfe zuerst die Grundlagen.\n\nReinige die Druckplatte nach Herstellerangaben. Kontrolliere anschließend das Bett-Leveling und den Abstand der Düse. Die Linien sollten sich berühren, ohne dass die Düse Material über die Platte schiebt.\n\nNutze für einen Test das Standardprofil deines Druckers und Filaments. Ändere jeweils nur eine Einstellung und notiere das Ergebnis. So findest du die Ursache, statt mehrere Effekte zu vermischen.\n\nDu kommst nicht weiter? Beschreibe im Forum Drucker, Material, Temperaturen und das Fehlerbild.'),
                ('projekte', 'Von der Idee zum eigenen Projekt', 'Ein selbst gedrucktes Gehäuse für den Raspberry Pi? Eine Sensorstation für die Werkstatt? Hier treffen IT und 3D-Druck aufeinander.\n\nBeginne mit einer kleinen, überprüfbaren Funktion. Skizziere die Abmessungen und denke an Anschlüsse, Wärmeentwicklung und Wartung. Drucke zunächst ein kleines Passstück, bevor du das komplette Gehäuse fertigst.\n\nDokumentiere Material, Software und deine Entscheidungen. Auch Fehlversuche helfen anderen, ähnliche Probleme zu lösen.\n\nTeile deinen Fortschritt unter Projekte & Builds. Es muss noch nicht fertig sein.')]
            for i, (category, title, body) in enumerate(articles):
                db.execute('INSERT INTO posts(kind,category,title,body,created) VALUES(?,?,?,?,?)', ('blog',category,title,body,int(time.time())-i*60))
            db.execute("INSERT INTO metadata VALUES('initialized','1')")

def password_hash(password):
    salt = secrets.token_hex(16)
    return salt + ':' + hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()

def password_matches(password, stored):
    salt, expected = stored.split(':')
    actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, expected)


def public_url():
    value = os.environ.get('PUBLIC_URL', '').rstrip('/')
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise APIError(503, 'Die öffentliche HTTPS-Adresse ist noch nicht eingerichtet.')
    return value

def mail_configuration():
    public_url()
    if not all(os.environ.get(key) for key in ('MAIL_FROM', 'SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD')):
        raise APIError(503, 'Der E-Mail-Versand ist noch nicht eingerichtet. Bitte kontaktiere den Betreiber.')

def send_verification(email, token):
    link = public_url() + '/#verify/' + token
    subject = 'Bestätige deine E-Mail-Adresse – steckerrein.de'
    body = ('Willkommen bei steckerrein.de!\n\nBestätige deine E-Mail-Adresse über diesen Link:\n'
            + link + '\n\nDer Link ist 24 Stunden gültig und kann nur einmal verwendet werden. '
            'Danach kannst du dich anmelden. Wenn du diese Anfrage nicht gestellt hast, ignoriere diese Nachricht.')
    try:
        message = EmailMessage()
        message['Subject'] = subject
        message['From'] = os.environ['MAIL_FROM']
        message['To'] = email
        message.set_content(body)
        host = os.environ['SMTP_HOST']
        port = int(os.environ.get('SMTP_PORT', '587'))
        if port not in (465, 587): raise ValueError('Use TLS SMTP on 465 or 587')
        context = ssl.create_default_context()
        if port == 465:
            client = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
        else:
            client = smtplib.SMTP(host, port, timeout=15)
        with client:
            if port == 587: client.starttls(context=context)
            client.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
            client.send_message(message)
    except (OSError, ValueError, smtplib.SMTPException):
        # Never expose provider responses, recipient details or verification tokens.
        raise APIError(503, 'Die Bestätigungsmail konnte nicht versendet werden. Bitte versuche es später erneut.')

class APIError(Exception):
    def __init__(self, status, message, code=None):
        self.status, self.message, self.code = status, message, code

class Handler(BaseHTTPRequestHandler):
    server_version = 'Steckerrein'

    def log_message(self, fmt, *args):
        # Never log request bodies, passwords, cookies or query strings.
        print(f'{self.client_address[0]} {self.command} {urlsplit(self.path).path} {args[1] if len(args)>1 else ""}', flush=True)

    def respond(self, status, data, cookie=None):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.headers_common()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        if cookie: self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(raw)

    def headers_common(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','strict-origin-when-cross-origin')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")

    def user(self, db):
        cookie = SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception: return None
        token = cookie.get('session')
        if not token: return None
        hashed = hashlib.sha256(token.value.encode()).hexdigest()
        return db.execute('SELECT u.id,u.username,u.admin,u.email_verified FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>?', (hashed,int(time.time()))).fetchone()

    def require_user(self, db):
        user = self.user(db)
        if not user: raise APIError(401,'Bitte melde dich zuerst an.')
        if not user['email_verified']: raise APIError(403,'Bitte bestätige zuerst deine E-Mail-Adresse.', 'EMAIL_UNVERIFIED')
        return user

    def body(self):
        # JSON + custom header prevent cross-site simple requests; no CORS is enabled.
        if self.headers.get('X-Requested-With') != 'Steckerrein' or self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            raise APIError(403,'Ungültige Anfrage. Bitte lade die Seite neu.')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site': raise APIError(403,'Anfrage von fremder Website abgelehnt.')
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'): raise APIError(403,'Ungültiger Ursprung.')
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 40000: raise ValueError()
            data = json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError()
            return data
        except (ValueError, UnicodeError): raise APIError(400,'Ungültige Eingabe oder Beitrag zu groß.')

    def field(self, data, name, minimum, maximum):
        value = data.get(name,'')
        if not isinstance(value,str) or not minimum <= len(value.strip()) <= maximum:
            raise APIError(400,f'Bitte prüfe das Feld {name} ({minimum}–{maximum} Zeichen).')
        return value.strip()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/api/'):
            return self.dispatch('GET')
        files = {'/':'index.html','/index.html':'index.html','/style.css':'style.css','/script.js':'script.js','/impressum.html':'impressum.html','/datenschutz.html':'datenschutz.html'}
        filename = files.get(path)
        if path in ('/forum','/blog') or re.fullmatch(r'/forum/[a-z0-9-]+|/posts/\d+',path): filename='index.html'
        if not filename: return self.respond(404,{'error':'Seite nicht gefunden.'})
        data = (ROOT/filename).read_bytes()
        mime = {'.html':'text/html','.css':'text/css','.js':'text/javascript'}[Path(filename).suffix]
        self.send_response(200)
        self.headers_common()
        self.send_header('Content-Type',mime+'; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self): self.dispatch('POST')
    def do_PATCH(self): self.dispatch('PATCH')
    def do_DELETE(self): self.dispatch('DELETE')

    def dispatch(self, method):
        try:
            with connect() as db:
                self.api(db,method)
        except APIError as e: self.respond(e.status,{'error':e.message, 'code':e.code})
        except sqlite3.OperationalError:
            self.respond(503,{'error':'Die Datenbank ist gerade beschäftigt. Bitte versuche es erneut.'})
        except Exception:
            import traceback
            traceback.print_exc()
            self.respond(500,{'error':'Ein interner Fehler ist aufgetreten.'})

    def rate_limit(self, db, bucket, limit):
        # Use the TCP peer, not spoofable forwarded IP headers. Proxy deployments
        # must additionally apply client-IP limits at the trusted edge.
        subject=hashlib.sha256(self.client_address[0].encode()).hexdigest()
        now=int(time.time())
        with RATE_LOCK:
            db.execute('DELETE FROM rate_limits WHERE started<?',(now-900,))
            row=db.execute('SELECT count FROM rate_limits WHERE bucket=? AND subject=?',(bucket,subject)).fetchone()
            if row and row['count']>=limit: raise APIError(429,'Zu viele Versuche. Bitte warte 15 Minuten.')
            db.execute('INSERT INTO rate_limits VALUES(?,?,?,1) ON CONFLICT(bucket,subject) DO UPDATE SET count=count+1',(bucket,subject,now))
            db.commit()

    def email(self, data):
        email=self.field(data,'email',3,254).lower()
        if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}",email):
            raise APIError(400,'Bitte gib eine gültige E-Mail-Adresse ein.')
        return email

    def verification(self, db, uid, email):
        token=secrets.token_urlsafe(32)
        now=int(time.time())
        db.execute('BEGIN IMMEDIATE')
        previous=db.execute('SELECT sent FROM email_tokens WHERE user_id=?',(uid,)).fetchone()
        if previous and previous['sent']>now-60:
            raise APIError(429,'Bitte warte eine Minute, bevor du eine neue Bestätigungsmail anforderst.')
        db.execute('INSERT INTO email_tokens VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET token=excluded.token,expires=excluded.expires,sent=excluded.sent',
                   (hashlib.sha256(token.encode()).hexdigest(),uid,now+VERIFY_TTL,now))
        db.commit()
        try: send_verification(email,token)
        except APIError:
            # Permit an immediate retry after provider failure; keep the pending account.
            db.execute('UPDATE email_tokens SET sent=0 WHERE user_id=? AND token=?',(uid,hashlib.sha256(token.encode()).hexdigest()))
            db.commit()
            raise

    def api(self, db, method):
        parsed = urlsplit(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        if method=='GET' and path=='/api/topics':
            rows=db.execute("SELECT t.*,(SELECT COUNT(*) FROM posts p WHERE p.category=t.slug AND p.kind='forum') AS posts FROM topics t ORDER BY t.rowid").fetchall()
            return self.respond(200,{'topics':[dict(r) for r in rows]})
        if method=='GET' and path=='/api/me':
            user=self.user(db)
            return self.respond(200,{'user':dict(user) if user else None})
        if method=='GET' and path=='/api/posts':
            clauses, values = [], []
            for field in ('kind','category'):
                if query.get(field): clauses.append(f'p.{field}=?'); values.append(query[field][0])
            if query.get('q'):
                clauses.append('(p.title LIKE ? OR p.body LIKE ?)')
                values.extend(['%'+query['q'][0][:120]+'%']*2)
            where=' WHERE '+' AND '.join(clauses) if clauses else ''
            try: page=max(1,int(query.get('page',['1'])[0]))
            except ValueError: raise APIError(400,'Ungültige Seite.')
            count=db.execute('SELECT COUNT(*) FROM posts p'+where,values).fetchone()[0]
            rows=db.execute("SELECT p.id,p.kind,p.category,p.title,substr(p.body,1,200) AS excerpt,p.created,COALESCE(u.username,'Redaktion') AS author,(SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comments FROM posts p LEFT JOIN users u ON u.id=p.user_id"+where+' ORDER BY p.created DESC,p.id DESC LIMIT 12 OFFSET ?',values+[(page-1)*12]).fetchall()
            stats={'members':db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 'topics':db.execute("SELECT COUNT(*) FROM posts WHERE kind='forum'").fetchone()[0], 'articles':db.execute("SELECT COUNT(*) FROM posts WHERE kind='blog'").fetchone()[0]}
            return self.respond(200,{'posts':[dict(r) for r in rows],'total':count,'stats':stats})
        match=re.fullmatch(r'/api/posts/(\d+)',path)
        if method=='GET' and match:
            post=db.execute("SELECT p.*,COALESCE(u.username,'Redaktion') AS author FROM posts p LEFT JOIN users u ON u.id=p.user_id WHERE p.id=?",(match[1],)).fetchone()
            if not post: raise APIError(404,'Beitrag nicht gefunden.')
            comments=db.execute('SELECT c.id,c.body,c.created,c.user_id,u.username AS author FROM comments c JOIN users u ON u.id=c.user_id WHERE c.post_id=? ORDER BY c.created,c.id',(match[1],)).fetchall()
            return self.respond(200,{'post':dict(post),'comments':[dict(c) for c in comments]})
        if method not in ('POST','DELETE','PATCH'): raise APIError(404,'Nicht gefunden.')
        data=self.body()
        if method=='POST' and path=='/api/verify-email':
            self.rate_limit(db, 'verify', 30)
            token=self.field(data, 'token', 40, 100)
            hashed=hashlib.sha256(token.encode()).hexdigest()
            # One transaction makes concurrent redemption single-use.
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM email_tokens WHERE token=? AND expires>?',(hashed,int(time.time()))).fetchone()
            if not row: raise APIError(400,'Dieser Bestätigungslink ist ungültig oder abgelaufen. Fordere bitte einen neuen an.')
            db.execute('UPDATE users SET email_verified=1 WHERE id=?',(row['user_id'],))
            db.execute('DELETE FROM email_tokens WHERE user_id=?',(row['user_id'],))
            db.commit()
            return self.respond(200,{'ok':True})
        if method=='POST' and path in ('/api/register','/api/login','/api/request-verification'):
            self.rate_limit(db, 'auth', 20)
            password=data.get('password','')
            if not isinstance(password,str) or not 10 <= len(password) <= 128:
                raise APIError(400,'Das Passwort muss 10–128 Zeichen lang sein.')
            if path=='/api/register':
                mail_configuration()
                username=self.field(data,'username',3,24)
                if not re.fullmatch(r'[A-Za-z0-9_-]+',username): raise APIError(400,'Nutzername: nur Buchstaben, Zahlen, _ und -.')
                email=self.email(data)
                try:
                    result=db.execute('INSERT INTO users(username,password,created,email) VALUES(?,?,?,?)',(username,password_hash(password),int(time.time()),email))
                    uid=result.lastrowid
                    db.commit()
                except sqlite3.IntegrityError: raise APIError(409,'Nutzername oder E-Mail-Adresse ist bereits vergeben. Melde dich an oder fordere eine neue Bestätigung an.')
                self.verification(db,uid,email)
                return self.respond(201,{'verification_required':True, 'message':'Bitte bestätige deine E-Mail-Adresse. Schau auch im Spam-Ordner nach.'})
            identifier=self.field(data,'identifier',3,254)
            row=db.execute('SELECT * FROM users WHERE username=? OR email=?',(identifier,identifier)).fetchone()
            valid=password_matches(password,row['password']) if row else password_matches(password,'0'*32+':'+'0'*128)
            if not valid: raise APIError(401,'Zugangsdaten stimmen nicht.')
            if path=='/api/request-verification':
                mail_configuration()
                if row['email_verified']: return self.respond(200,{'message':'Deine E-Mail-Adresse ist bereits bestätigt. Du kannst dich anmelden.'})
                email=row['email'] or self.email(data)
                if not row['email']:
                    try:
                        db.execute('UPDATE users SET email=? WHERE id=?',(email,row['id']))
                        db.commit()
                    except sqlite3.IntegrityError: raise APIError(409,'Diese E-Mail-Adresse kann nicht verwendet werden.')
                self.verification(db,row['id'],email)
                return self.respond(200,{'message':'Bestätigungsmail versendet. Bitte prüfe dein Postfach und den Spam-Ordner.'})
            if not row['email_verified']:
                raise APIError(403,'Bitte bestätige zuerst deine E-Mail-Adresse. Bestehende Konten können hier ihre Adresse ergänzen.', 'EMAIL_UNVERIFIED')
            token=secrets.token_urlsafe(32)
            now=int(time.time())
            db.execute('DELETE FROM sessions WHERE expires<=?',(now,))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],now+SESSION_TTL))
            db.commit()
            user={key:row[key] for key in ('id','username','admin','email_verified')}
            secure='; Secure' if os.environ.get('COOKIE_SECURE')=='1' else ''
            return self.respond(200,{'user':user},f'session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL}{secure}')
        user=self.require_user(db)
        if method=='POST' and path=='/api/logout':
            cookie=SimpleCookie(self.headers.get('Cookie',''))
            db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(cookie['session'].value.encode()).hexdigest(),))
            db.commit()
            return self.respond(200,{'ok':True},'session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0')
        if method=='POST' and path=='/api/topics':
            if not user['admin']: raise APIError(403,'Nur Administratoren dürfen Themenbereiche erstellen.')
            name=self.field(data,'name',3,80)
            description=self.field(data,'description',10,300)
            slug=secrets.token_hex(8)
            try: db.execute('INSERT INTO topics VALUES(?,?,?)',(slug,name,description))
            except sqlite3.IntegrityError: raise APIError(409,'Diesen Themenbereich gibt es bereits.')
            db.commit()
            return self.respond(201,{'slug':slug})
        if method=='POST' and path=='/api/posts':
            kind=data.get('kind','forum')
            if kind not in ('forum','blog'): raise APIError(400,'Ungültiger Beitragstyp.')
            if kind=='blog' and not user['admin']: raise APIError(403,'Blogartikel können nur von der Redaktion veröffentlicht werden.')
            category=data.get('category')
            if not isinstance(category,str) or not db.execute('SELECT 1 FROM topics WHERE slug=?',(category,)).fetchone(): raise APIError(400,'Bitte wähle eine Kategorie.')
            title=self.field(data,'title',5,140); body=self.field(data,'body',20,15000)
            result=db.execute('INSERT INTO posts(kind,category,title,body,user_id,created) VALUES(?,?,?,?,?,?)',(kind,category,title,body,user['id'],int(time.time())))
            db.commit()
            return self.respond(201,{'id':result.lastrowid})
        comment=re.fullmatch(r'/api/posts/(\d+)/comments',path)
        if method=='POST' and comment:
            if not db.execute('SELECT id FROM posts WHERE id=?',(comment[1],)).fetchone(): raise APIError(404,'Beitrag nicht gefunden.')
            body=self.field(data,'body',2,5000)
            db.execute('INSERT INTO comments(post_id,user_id,body,created) VALUES(?,?,?,?)',(comment[1],user['id'],body,int(time.time())))
            db.commit()
            return self.respond(201,{'ok':True})
        comment_match=re.fullmatch(r'/api/comments/(\d+)',path)
        if method in ('PATCH','DELETE') and comment_match:
            row=db.execute('SELECT user_id FROM comments WHERE id=?',(comment_match[1],)).fetchone()
            if not row: raise APIError(404,'Antwort nicht gefunden.')
            if row['user_id']!=user['id'] and not user['admin']: raise APIError(403,'Nur Autor und Administratoren dürfen diese Antwort bearbeiten.')
            if method=='PATCH':
                body=self.field(data,'body',2,5000)
                db.execute('UPDATE comments SET body=? WHERE id=?',(body,comment_match[1]))
            else: db.execute('DELETE FROM comments WHERE id=?',(comment_match[1],))
            db.commit()
            return self.respond(200,{'ok':True})
        if method=='PATCH' and match:
            post=db.execute('SELECT * FROM posts WHERE id=?',(match[1],)).fetchone()
            if not post: raise APIError(404,'Beitrag nicht gefunden.')
            if post['user_id']!=user['id'] and not user['admin']: raise APIError(403,'Nur Autor und Administratoren dürfen diesen Beitrag bearbeiten.')
            title=self.field(data,'title',5,140)
            body=self.field(data,'body',20,15000)
            category=data.get('category')
            if not isinstance(category,str) or not db.execute('SELECT 1 FROM topics WHERE slug=?',(category,)).fetchone(): raise APIError(400,'Bitte wähle eine Kategorie.')
            db.execute('UPDATE posts SET title=?,body=?,category=? WHERE id=?',(title,body,category,match[1]))
            db.commit()
            return self.respond(200,{'ok':True})
        if method=='DELETE' and match:
            post=db.execute('SELECT user_id FROM posts WHERE id=?',(match[1],)).fetchone()
            if not post: raise APIError(404,'Beitrag nicht gefunden.')
            if post['user_id']!=user['id'] and not user['admin']: raise APIError(403,'Keine Berechtigung.')
            db.execute('DELETE FROM posts WHERE id=?',(match[1],)); db.commit()
            return self.respond(200,{'ok':True})
        raise APIError(404,'Nicht gefunden.')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--promote',metavar='USERNAME',help='Grant editorial permissions to an existing account')
    args=parser.parse_args()
    initialize()
    if args.promote:
        with connect() as db:
            result=db.execute('UPDATE users SET admin=1 WHERE username=?',(args.promote,))
            if not result.rowcount: parser.error('Account nicht gefunden. Zuerst registrieren.')
        print('Redaktionsrechte vergeben.')
    else:
        port=int(os.environ.get('PORT','8095'))
        print(f'Steckerrein listening on port {port}',flush=True)
        ThreadingHTTPServer((os.environ.get('BIND','0.0.0.0'),port),Handler).serve_forever()
