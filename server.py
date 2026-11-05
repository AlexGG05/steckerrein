"""Dependency-free community server. Run with Python 3.12+."""
import argparse
import base64
import binascii
import io
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
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
TAG_COLORS = {'green','purple','blue','orange','red','gray'}

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
        for name,definition in (('display_name',"TEXT NOT NULL DEFAULT ''"),('bio',"TEXT NOT NULL DEFAULT ''"),('website',"TEXT NOT NULL DEFAULT ''"),('avatar','BLOB')):
            if name not in columns: db.execute(f'ALTER TABLE users ADD COLUMN {name} {definition}')
        db.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(email) WHERE email IS NOT NULL;
        CREATE TABLE IF NOT EXISTS email_tokens(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE, expires INTEGER NOT NULL, sent INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS rate_limits(bucket TEXT NOT NULL, subject TEXT NOT NULL, started INTEGER NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(bucket,subject));
        """)
        db.execute('CREATE TABLE IF NOT EXISTS topics(slug TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, description TEXT NOT NULL)')
        topic_columns={r['name'] for r in db.execute('PRAGMA table_info(topics)')}
        if 'parent_slug' not in topic_columns:
            db.execute('ALTER TABLE topics ADD COLUMN parent_slug TEXT REFERENCES topics(slug)')
        if 'allow_posts' not in topic_columns:
            db.execute('ALTER TABLE topics ADD COLUMN allow_posts INTEGER NOT NULL DEFAULT 1 CHECK(allow_posts IN (0,1))')
        db.executescript("""
        CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('post','user')), name TEXT NOT NULL COLLATE NOCASE, color TEXT NOT NULL, UNIQUE(kind,name));
        CREATE TABLE IF NOT EXISTS post_tags(post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE, PRIMARY KEY(post_id,tag_id));
        CREATE TABLE IF NOT EXISTS user_tags(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE, PRIMARY KEY(user_id,tag_id));
        """)
        if not db.execute("SELECT 1 FROM metadata WHERE key='tags_initialized'").fetchone():
            db.execute("INSERT OR IGNORE INTO tags(kind,name,color) VALUES('post','Offen','orange')")
            db.execute("INSERT OR IGNORE INTO tags(kind,name,color) VALUES('post','Gelöst','green')")
            db.execute("INSERT INTO metadata VALUES('tags_initialized','1')")
        if not db.execute("SELECT 1 FROM metadata WHERE key='topics_initialized'").fetchone():
            descriptions={'it':'Server, Netzwerke, Software und dein eigenes Homelab.', '3d-druck':'Drucker, Filamente, Slicer und Hilfe beim nächsten Druck.', 'projekte':'Zeig deine Builds und entwickle gemeinsam neue Ideen.', 'allgemein':'Vorstellen, austauschen und über den Tellerrand schauen.'}
            for slug,name in CATEGORIES.items():
                db.execute('INSERT OR IGNORE INTO topics(slug,name,description) VALUES(?,?,?)',(slug,name,descriptions[slug]))
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
        return db.execute('SELECT u.id,u.username,u.admin,u.email_verified,(u.avatar IS NOT NULL) AS has_avatar FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>?', (hashed,int(time.time()))).fetchone()

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
            maximum=1500000 if urlsplit(self.path).path=='/api/profile' else 40000
            if not 0 < length <= maximum: raise ValueError()
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
        if path in ('/forum','/blog','/admin') or re.fullmatch(r'/forum/[a-z0-9-]+|/posts/\d+|/users/[A-Za-z0-9_-]+',path): filename='index.html'
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

    def avatar(self, encoded):
        if not isinstance(encoded,str) or len(encoded)>1400000: raise APIError(400,'Profilbilder dürfen höchstens 1 MB groß sein.')
        try:
            raw=base64.b64decode(encoded,validate=True)
            if not raw or len(raw)>1048576: raise ValueError()
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format not in ('JPEG','PNG','WEBP') or image.width*image.height>4000000: raise ValueError()
                    image.load()
                    clean=ImageOps.exif_transpose(image).convert('RGBA')
                    clean=ImageOps.fit(clean,(256,256),method=Image.Resampling.LANCZOS)
                    clean.info.clear()
                    # Re-encode decoded pixels; never retain uploaded metadata or files.
                    output=io.BytesIO();clean.save(output,format='PNG')
                    return output.getvalue()
        except (ValueError,OSError,binascii.Error,UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise APIError(400,'Bitte lade ein gültiges PNG-, JPEG- oder WebP-Bild mit höchstens 1 MB und 4 Megapixeln hoch.')

    def tags_for(self, db, kind, item_id):
        if item_id is None: return []
        table,column=('post_tags','post_id') if kind=='post' else ('user_tags','user_id')
        return [dict(r) for r in db.execute(f'SELECT t.id,t.kind,t.name,t.color FROM tags t JOIN {table} m ON m.tag_id=t.id WHERE m.{column}=? ORDER BY t.name',(item_id,))]

    def post_data(self, db, row):
        return {**dict(row),'tags':self.tags_for(db,'post',row['id']),'author_tags':self.tags_for(db,'user',row['user_id'])}

    def assign_tags(self, db, kind, item_id, tag_ids):
        if not isinstance(tag_ids,list) or len(tag_ids)>10 or any(type(i) is not int or i<1 for i in tag_ids) or len(set(tag_ids))!=len(tag_ids):
            raise APIError(400,'Bitte wähle höchstens zehn unterschiedliche Tags.')
        for tag_id in tag_ids:
            if not db.execute('SELECT 1 FROM tags WHERE id=? AND kind=?',(tag_id,kind)).fetchone(): raise APIError(400,'Ein gewählter Tag existiert nicht oder hat die falsche Art.')
        table,column=('post_tags','post_id') if kind=='post' else ('user_tags','user_id')
        db.execute(f'DELETE FROM {table} WHERE {column}=?',(item_id,))
        db.executemany(f'INSERT INTO {table}({column},tag_id) VALUES(?,?)',[(item_id,tag_id) for tag_id in tag_ids])

    def topic_settings(self, db, data, topic=None):
        parent=data.get('parent_slug',topic['parent_slug'] if topic else None)
        allowed=data.get('allow_posts',bool(topic['allow_posts']) if topic else bool(parent))
        if type(allowed) is not bool: raise APIError(400,'Bitte lege fest, ob Beiträge erlaubt sind.')
        if parent is not None and (not isinstance(parent,str) or not db.execute('SELECT 1 FROM topics WHERE slug=?',(parent,)).fetchone()):
            raise APIError(400,'Übergeordneter Themenbereich nicht gefunden.')
        current=parent
        seen=set()
        while current is not None:
            if current in seen or (topic and current==topic['slug']):
                raise APIError(400,'Ein Themenbereich kann nicht sich selbst oder einem eigenen Unterthema untergeordnet werden.')
            seen.add(current)
            row=db.execute('SELECT parent_slug FROM topics WHERE slug=?',(current,)).fetchone()
            current=row['parent_slug'] if row else None
        return parent,allowed

    def api(self, db, method):
        parsed = urlsplit(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        if method=='GET' and path=='/api/tags':
            rows=db.execute("SELECT t.*,(SELECT COUNT(*) FROM post_tags p WHERE p.tag_id=t.id)+(SELECT COUNT(*) FROM user_tags u WHERE u.tag_id=t.id) AS uses FROM tags t ORDER BY t.kind,t.name").fetchall()
            return self.respond(200,{'tags':[dict(r) for r in rows]})
        if method=='GET' and path=='/api/admin/users':
            user=self.require_user(db)
            if not user['admin']: raise APIError(403,'Nur Administratoren haben Zugriff auf diesen Bereich.')
            search=query.get('q',[''])[0][:80]
            try: page=max(1,int(query.get('page',['1'])[0]))
            except ValueError: raise APIError(400,'Ungültige Seite.')
            pattern='%'+search+'%'
            rows=db.execute('SELECT id,username,display_name,admin,email_verified,created FROM users WHERE username LIKE ? OR display_name LIKE ? ORDER BY username LIMIT 50 OFFSET ?',(pattern,pattern,(page-1)*50)).fetchall()
            count=db.execute('SELECT COUNT(*) FROM users WHERE username LIKE ? OR display_name LIKE ?',(pattern,pattern)).fetchone()[0]
            return self.respond(200,{'users':[{**dict(r),'tags':self.tags_for(db,'user',r['id'])} for r in rows],'total':count})
        if method=='GET' and path=='/api/topics':
            rows=db.execute("SELECT t.*,(SELECT COUNT(*) FROM posts p WHERE p.category=t.slug AND p.kind='forum') AS posts,(SELECT COUNT(*) FROM posts p WHERE p.category=t.slug) AS items,(SELECT COUNT(*) FROM topics child WHERE child.parent_slug=t.slug) AS children FROM topics t ORDER BY t.rowid").fetchall()
            return self.respond(200,{'topics':[dict(r) for r in rows]})
        profile_match=re.fullmatch(r'/api/users/([A-Za-z0-9_-]+)(/avatar)?',path)
        if method=='GET' and profile_match:
            row=db.execute('SELECT id,username,admin,created,display_name,bio,website,avatar FROM users WHERE username=?',(profile_match[1],)).fetchone()
            if not row: raise APIError(404,'Profil nicht gefunden.')
            if profile_match[2]:
                if row['avatar'] is None: raise APIError(404,'Kein Profilbild vorhanden.')
                self.send_response(200);self.headers_common()
                self.send_header('Content-Type','image/png')
                self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(row['avatar'])))
                self.end_headers();self.wfile.write(row['avatar']);return
            public={key:row[key] for key in ('id','username','admin','created','display_name','bio','website')}
            public['has_avatar']=row['avatar'] is not None
            public['tags']=self.tags_for(db,'user',row['id'])
            public['posts']=db.execute('SELECT COUNT(*) FROM posts WHERE user_id=?',(row['id'],)).fetchone()[0]
            public['replies']=db.execute('SELECT COUNT(*) FROM comments WHERE user_id=?',(row['id'],)).fetchone()[0]
            return self.respond(200,{'profile':public})
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
            if query.get('author'):
                clauses.append('p.user_id=(SELECT id FROM users WHERE username=?)');values.append(query['author'][0])
            where=' WHERE '+' AND '.join(clauses) if clauses else ''
            try: page=max(1,int(query.get('page',['1'])[0]))
            except ValueError: raise APIError(400,'Ungültige Seite.')
            count=db.execute('SELECT COUNT(*) FROM posts p'+where,values).fetchone()[0]
            rows=db.execute("SELECT p.id,p.kind,p.category,p.title,p.user_id,(u.avatar IS NOT NULL) AS has_avatar,substr(p.body,1,200) AS excerpt,p.created,COALESCE(u.username,'Redaktion') AS author,(SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comments FROM posts p LEFT JOIN users u ON u.id=p.user_id"+where+' ORDER BY p.created DESC,p.id DESC LIMIT 12 OFFSET ?',values+[(page-1)*12]).fetchall()
            stats={'members':db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 'topics':db.execute("SELECT COUNT(*) FROM posts WHERE kind='forum'").fetchone()[0], 'articles':db.execute("SELECT COUNT(*) FROM posts WHERE kind='blog'").fetchone()[0]}
            return self.respond(200,{'posts':[self.post_data(db,r) for r in rows],'total':count,'stats':stats})
        match=re.fullmatch(r'/api/posts/(\d+)',path)
        if method=='GET' and match:
            post=db.execute("SELECT p.*,(u.avatar IS NOT NULL) AS has_avatar,COALESCE(u.username,'Redaktion') AS author FROM posts p LEFT JOIN users u ON u.id=p.user_id WHERE p.id=?",(match[1],)).fetchone()
            if not post: raise APIError(404,'Beitrag nicht gefunden.')
            comments=db.execute('SELECT c.id,c.body,c.created,c.user_id,(u.avatar IS NOT NULL) AS has_avatar,u.username AS author FROM comments c JOIN users u ON u.id=c.user_id WHERE c.post_id=? ORDER BY c.created,c.id',(match[1],)).fetchall()
            return self.respond(200,{'post':self.post_data(db,post),'comments':[{**dict(c),'author_tags':self.tags_for(db,'user',c['user_id'])} for c in comments]})
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
            user['has_avatar']=row['avatar'] is not None
            secure='; Secure' if os.environ.get('COOKIE_SECURE')=='1' else ''
            return self.respond(200,{'user':user},f'session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL}{secure}')
        user=self.require_user(db)
        tag_match=re.fullmatch(r'/api/admin/tags/(\d+)',path)
        if (method=='POST' and path=='/api/admin/tags') or (method in ('PATCH','DELETE') and tag_match):
            if not user['admin']: raise APIError(403,'Nur Administratoren dürfen Tags verwalten.')
            db.execute('BEGIN IMMEDIATE')
            existing=None
            if tag_match:
                existing=db.execute('SELECT * FROM tags WHERE id=?',(tag_match[1],)).fetchone()
                if not existing: raise APIError(404,'Tag nicht gefunden.')
            if method=='DELETE':
                db.execute('DELETE FROM tags WHERE id=?',(existing['id'],));db.commit()
                return self.respond(200,{'ok':True})
            kind=existing['kind'] if existing else data.get('kind')
            if kind not in ('post','user') or (existing and data.get('kind',kind)!=kind): raise APIError(400,'Ungültige Tag-Art.')
            name=self.field(data,'name',1,40)
            color=data.get('color','purple')
            if not isinstance(color,str) or color not in TAG_COLORS: raise APIError(400,'Bitte wähle eine gültige Tag-Farbe.')
            try:
                if existing:
                    db.execute('UPDATE tags SET name=?,color=? WHERE id=?',(name,color,existing['id']));tag_id=existing['id']
                else: tag_id=db.execute('INSERT INTO tags(kind,name,color) VALUES(?,?,?)',(kind,name,color)).lastrowid
            except sqlite3.IntegrityError: raise APIError(409,'Ein Tag mit diesem Namen existiert bereits in dieser Tag-Art.')
            db.commit()
            return self.respond(200 if existing else 201,{'id':tag_id})
        user_tag_match=re.fullmatch(r'/api/admin/users/(\d+)/tags',path)
        if method=='PATCH' and user_tag_match:
            if not user['admin']: raise APIError(403,'Nur Administratoren dürfen Nutzertags zuweisen.')
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM users WHERE id=?',(user_tag_match[1],)).fetchone(): raise APIError(404,'Mitglied nicht gefunden.')
            self.assign_tags(db,'user',int(user_tag_match[1]),data.get('tag_ids'))
            db.commit()
            return self.respond(200,{'ok':True})
        if method=='PATCH' and path=='/api/profile':
            display_name=self.field(data,'display_name',0,60)
            bio=self.field(data,'bio',0,1000)
            website=self.field(data,'website',0,300)
            if website:
                parsed=urlsplit(website)
                try: valid_port=parsed.port
                except ValueError: raise APIError(400,'Ungültige Website-Adresse.')
                if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in website) or any(ord(c)<32 for c in website):
                    raise APIError(400,'Website-Adressen müssen mit https:// oder http:// beginnen und dürfen keine Zugangsdaten enthalten.')
            if type(data.get('remove_avatar',False)) is not bool: raise APIError(400,'Ungültige Profilbildeinstellung.')
            if data.get('avatar') and data.get('remove_avatar'): raise APIError(400,'Bitte entweder ein Bild hochladen oder das Profilbild entfernen.')
            image=None
            if 'avatar' in data: image=self.avatar(data['avatar'])
            db.execute('UPDATE users SET display_name=?,bio=?,website=? WHERE id=?',(display_name,bio,website,user['id']))
            if image is not None or data.get('remove_avatar'):
                db.execute('UPDATE users SET avatar=? WHERE id=?',(image,user['id']))
            db.commit()
            return self.respond(200,{'ok':True})
        if method=='POST' and path=='/api/logout':
            cookie=SimpleCookie(self.headers.get('Cookie',''))
            db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(cookie['session'].value.encode()).hexdigest(),))
            db.commit()
            return self.respond(200,{'ok':True},'session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0')
        if method=='POST' and path=='/api/topics':
            if not user['admin']: raise APIError(403,'Nur Administratoren dürfen Themenbereiche erstellen.')
            db.execute('BEGIN IMMEDIATE')
            name=self.field(data,'name',3,80)
            description=self.field(data,'description',10,300)
            parent,allowed=self.topic_settings(db,data)
            slug=secrets.token_hex(8)
            try: db.execute('INSERT INTO topics(slug,name,description,parent_slug,allow_posts) VALUES(?,?,?,?,?)',(slug,name,description,parent,int(allowed)))
            except sqlite3.IntegrityError: raise APIError(409,'Diesen Themenbereich gibt es bereits.')
            db.commit()
            return self.respond(201,{'slug':slug})
        topic_match=re.fullmatch(r'/api/topics/([a-z0-9-]+)',path)
        if method in ('PATCH','DELETE') and topic_match:
            if not user['admin']: raise APIError(403,'Nur Administratoren dürfen Themenbereiche verwalten.')
            # Serialize membership checks and moves with concurrent post creation/editing.
            db.execute('BEGIN IMMEDIATE')
            slug=topic_match[1]
            topic=db.execute('SELECT * FROM topics WHERE slug=?',(slug,)).fetchone()
            if not topic: raise APIError(404,'Themenbereich nicht gefunden.')
            if method=='PATCH':
                name=self.field(data,'name',3,80)
                description=self.field(data,'description',10,300)
                parent,allowed=self.topic_settings(db,data,topic)
                try: db.execute('UPDATE topics SET name=?,description=?,parent_slug=?,allow_posts=? WHERE slug=?',(name,description,parent,int(allowed),slug))
                except sqlite3.IntegrityError: raise APIError(409,'Diesen Themenbereich gibt es bereits.')
                db.commit()
                return self.respond(200,{'slug':slug})
            if db.execute('SELECT 1 FROM topics WHERE parent_slug=?',(slug,)).fetchone():
                raise APIError(409,'Dieser Bereich enthält Unterthemen. Verschiebe oder entferne zuerst die Unterthemen.')
            count=db.execute('SELECT COUNT(*) FROM posts WHERE category=?',(slug,)).fetchone()[0]
            target=data.get('move_to')
            if target is not None:
                if not isinstance(target,str) or target==slug or not db.execute('SELECT 1 FROM topics WHERE slug=? AND allow_posts=1',(target,)).fetchone():
                    raise APIError(400,'Bitte wähle einen anderen Zielbereich, in dem Beiträge erlaubt sind.')
            if count and target is None:
                raise APIError(409,'Dieser Bereich enthält Beiträge oder Blogartikel. Wähle einen Zielbereich, damit alle Inhalte erhalten bleiben.')
            if target is not None: db.execute('UPDATE posts SET category=? WHERE category=?',(target,slug))
            db.execute('DELETE FROM topics WHERE slug=?',(slug,))
            db.commit()
            return self.respond(200,{'ok':True,'moved':count})
        if method=='POST' and path=='/api/posts':
            db.execute('BEGIN IMMEDIATE')
            kind=data.get('kind','forum')
            if kind not in ('forum','blog'): raise APIError(400,'Ungültiger Beitragstyp.')
            if kind=='blog' and not user['admin']: raise APIError(403,'Blogartikel können nur von der Redaktion veröffentlicht werden.')
            category=data.get('category')
            if not isinstance(category,str) or not db.execute('SELECT 1 FROM topics WHERE slug=?',(category,)).fetchone(): raise APIError(400,'Bitte wähle eine Kategorie.')
            if kind=='forum' and not db.execute('SELECT allow_posts FROM topics WHERE slug=?',(category,)).fetchone()['allow_posts']:
                raise APIError(403,'In diesem Themenbereich sind keine neuen Beiträge erlaubt. Wähle ein freigegebenes Unterthema.')
            title=self.field(data,'title',5,140); body=self.field(data,'body',20,15000)
            result=db.execute('INSERT INTO posts(kind,category,title,body,user_id,created) VALUES(?,?,?,?,?,?)',(kind,category,title,body,user['id'],int(time.time())))
            self.assign_tags(db,'post',result.lastrowid,data.get('tag_ids',[]))
            db.commit()
            return self.respond(201,{'id':result.lastrowid})
        comment=re.fullmatch(r'/api/posts/(\d+)/comments',path)
        if method=='POST' and comment:
            db.execute('BEGIN IMMEDIATE')
            parent_post=db.execute('SELECT p.kind,t.allow_posts FROM posts p JOIN topics t ON t.slug=p.category WHERE p.id=?',(comment[1],)).fetchone()
            if not parent_post: raise APIError(404,'Beitrag nicht gefunden.')
            if parent_post['kind']=='forum' and not parent_post['allow_posts']: raise APIError(403,'In diesem Themenbereich sind keine neuen Antworten erlaubt.')
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
            db.execute('BEGIN IMMEDIATE')
            post=db.execute('SELECT * FROM posts WHERE id=?',(match[1],)).fetchone()
            if not post: raise APIError(404,'Beitrag nicht gefunden.')
            if post['user_id']!=user['id'] and not user['admin']: raise APIError(403,'Nur Autor und Administratoren dürfen diesen Beitrag bearbeiten.')
            title=self.field(data,'title',5,140)
            body=self.field(data,'body',20,15000)
            category=data.get('category')
            if not isinstance(category,str) or not db.execute('SELECT 1 FROM topics WHERE slug=?',(category,)).fetchone(): raise APIError(400,'Bitte wähle eine Kategorie.')
            if post['kind']=='forum' and category!=post['category'] and not db.execute('SELECT allow_posts FROM topics WHERE slug=?',(category,)).fetchone()['allow_posts']:
                raise APIError(403,'Im gewählten Zielbereich sind keine Beiträge erlaubt.')
            db.execute('UPDATE posts SET title=?,body=?,category=? WHERE id=?',(title,body,category,match[1]))
            if 'tag_ids' in data: self.assign_tags(db,'post',int(match[1]),data['tag_ids'])
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
