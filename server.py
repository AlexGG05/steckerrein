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
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).parent
DB = Path(os.environ.get('DATABASE_PATH', ROOT / 'data/community.db'))
CATEGORIES = {'allgemein': 'Allgemein', 'it': 'IT & Homelab', '3d-druck': '3D-Druck', 'projekte': 'Projekte & Builds'}
SESSION_TTL = 7 * 86400

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

class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message

class Handler(BaseHTTPRequestHandler):
    server_version = 'Steckerrein'
    # Bounded local rate limit; proxy deployments should also rate-limit at the edge.
    attempts = {}

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
        return db.execute('SELECT u.id,u.username,u.admin FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>?', (hashed,int(time.time()))).fetchone()

    def require_user(self, db):
        user = self.user(db)
        if not user: raise APIError(401,'Bitte melde dich zuerst an.')
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
        if not filename: return self.respond(404,{'error':'Seite nicht gefunden.'})
        data = (ROOT/filename).read_bytes()
        mime = {'.html':'text/html','.css':'text/css','.js':'text/javascript'}[Path(filename).suffix]
        self.send_response(200)
        self.headers_common()
        self.send_header('Content-Type',mime+'; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-cache')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self): self.dispatch('POST')
    def do_DELETE(self): self.dispatch('DELETE')

    def dispatch(self, method):
        try:
            with connect() as db:
                self.api(db,method)
        except APIError as e: self.respond(e.status,{'error':e.message})
        except sqlite3.OperationalError:
            self.respond(503,{'error':'Die Datenbank ist gerade beschäftigt. Bitte versuche es erneut.'})
        except Exception:
            import traceback
            traceback.print_exc()
            self.respond(500,{'error':'Ein interner Fehler ist aufgetreten.'})

    def api(self, db, method):
        parsed = urlsplit(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
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
            comments=db.execute('SELECT c.id,c.body,c.created,u.username AS author FROM comments c JOIN users u ON u.id=c.user_id WHERE c.post_id=? ORDER BY c.created,c.id',(match[1],)).fetchall()
            return self.respond(200,{'post':dict(post),'comments':[dict(c) for c in comments]})
        if method not in ('POST','DELETE'): raise APIError(404,'Nicht gefunden.')
        data=self.body()
        if method=='POST' and path in ('/api/register','/api/login'):
            now=time.time(); ip=self.client_address[0]
            # Remove expired entries to bound memory consumption.
            for key in list(self.attempts):
                if self.attempts[key][0]<now-900: del self.attempts[key]
            started,count=self.attempts.get(ip,(now,0))
            if count>=20: raise APIError(429,'Zu viele Anmeldeversuche. Bitte warte 15 Minuten.')
            self.attempts[ip]=(started,count+1)
            username=self.field(data,'username',3,24)
            password=self.field(data,'password',10,128)
            if not re.fullmatch(r'[A-Za-z0-9_-]+',username): raise APIError(400,'Nutzername: nur Buchstaben, Zahlen, _ und -.')
            if path=='/api/register':
                try:
                    result=db.execute('INSERT INTO users(username,password,created) VALUES(?,?,?)',(username,password_hash(password),int(now)))
                    uid=result.lastrowid
                except sqlite3.IntegrityError: raise APIError(409,'Dieser Nutzername ist bereits vergeben.')
            else:
                row=db.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
                # Perform a hash even for unknown accounts.
                valid=password_matches(password,row['password']) if row else password_matches(password,'0'*32+':'+'0'*128)
                if not valid: raise APIError(401,'Nutzername oder Passwort stimmt nicht.')
                uid=row['id']
            token=secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<=?',(int(now),))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,int(now)+SESSION_TTL))
            db.commit()
            user=dict(db.execute('SELECT id,username,admin FROM users WHERE id=?',(uid,)).fetchone())
            secure='; Secure' if os.environ.get('COOKIE_SECURE')=='1' else ''
            return self.respond(200,{'user':user},f'session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL}{secure}')
        user=self.require_user(db)
        if method=='POST' and path=='/api/logout':
            cookie=SimpleCookie(self.headers.get('Cookie',''))
            db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(cookie['session'].value.encode()).hexdigest(),))
            db.commit()
            return self.respond(200,{'ok':True},'session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0')
        if method=='POST' and path=='/api/posts':
            kind=data.get('kind','forum')
            if kind not in ('forum','blog'): raise APIError(400,'Ungültiger Beitragstyp.')
            if kind=='blog' and not user['admin']: raise APIError(403,'Blogartikel können nur von der Redaktion veröffentlicht werden.')
            category=data.get('category')
            if category not in CATEGORIES: raise APIError(400,'Bitte wähle eine Kategorie.')
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
