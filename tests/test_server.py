import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import hashlib
import time
import os
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class CommunityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        server.DB=Path(cls.temp.name)/'test.db'
        cls.env=patch.dict(os.environ, {'PUBLIC_URL':'https://steckerrein.de','SMTP_HOST':'smtp.example.test','SMTP_PORT':'587','SMTP_USER':'test','SMTP_PASSWORD':'test-only','MAIL_FROM':'forum@example.test'})
        cls.env.start()
        cls.mail=patch('server.send_verification')
        cls.mail_mock=cls.mail.start()
        server.initialize()
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.temp.cleanup();cls.mail.stop();cls.env.stop()

    def request(self,path,method='GET',data=None,cookie=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.http.server_port)
        hdr={'Content-Type':'application/json','X-Requested-With':'Steckerrein'}
        if cookie:hdr['Cookie']=cookie
        if headers:hdr.update(headers)
        conn.request(method,path,json.dumps(data) if data is not None else None,hdr)
        response=conn.getresponse();raw=response.read()
        value=json.loads(raw) if response.getheader('Content-Type','').startswith('application/json') else raw
        result=(response.status,value,response.getheader('Set-Cookie'))
        conn.close();return result

    def setUp(self):
        with server.connect() as db: db.execute('DELETE FROM rate_limits')
        self.mail_mock.reset_mock()

    def pending(self,name):
        status,data,cookie=self.request('/api/register','POST',{'username':name,'email':name+'@example.test','password':'correct horse battery'})
        self.assertEqual(status,201,data)
        self.assertIsNone(cookie)
        self.assertTrue(data['verification_required'])
        self.assertNotIn('user',data)
        return self.mail_mock.call_args.args[1]

    def register(self,name):
        token=self.pending(name)
        self.assertEqual(self.request('/api/verify-email','POST',{'token':token})[0],200)
        status,data,cookie=self.request('/api/login','POST',{'identifier':name,'password':'correct horse battery'})
        self.assertEqual(status,200,data)
        return cookie.split(';')[0],data['user']

    def test_01_static_and_seed(self):
        status,data,_=self.request('/api/posts')
        self.assertEqual(status,200);self.assertEqual(len(data['posts']),3)
        self.assertEqual(data['stats']['members'],0)
        for name in ('index.html','style.css','script.js','impressum.html','datenschutz.html'):
            status,body,_=self.request('/'+name)
            self.assertEqual(status,200);self.assertEqual(body,(server.ROOT/name).read_bytes())
        self.assertEqual(self.request('/server.py')[0],404)
        self.assertEqual(self.request('/.git/config')[0],404)
        server.initialize()
        self.assertEqual(self.request('/api/posts')[1]['total'],3)

    def test_02_authentication(self):
        cookie,user=self.register('builder')
        self.assertFalse(user['admin'])
        self.assertEqual(self.request('/api/me',cookie=cookie)[1]['user']['username'],'builder')
        self.assertEqual(self.request('/api/register','POST',{'username':'BUILDER','email':'builder@example.test','password':'correct horse battery'})[0],409)
        self.assertEqual(self.request('/api/login','POST',{'identifier':'builder','password':'wrong password'})[0],401)
        self.assertEqual(self.request('/api/login','POST',{'identifier':'builder','password':'correct horse battery'})[0],200)
        self.assertEqual(self.request('/api/logout','POST',{},cookie)[0],200)
        self.assertIsNone(self.request('/api/me',cookie=cookie)[1]['user'])

    def test_03_posts_comments_and_permissions(self):
        cookie,user=self.register('maker');other,_=self.register('reader')
        post={'title':'Mein erstes Homelab','body':'Ein Mini-PC wird zum eigenen Server.','category':'it','kind':'forum'}
        self.assertEqual(self.request('/api/posts','POST',post)[0],401)
        status,data,_=self.request('/api/posts','POST',post,cookie)
        self.assertEqual(status,201);pid=data['id']
        self.assertEqual(self.request(f'/api/posts/{pid}/comments','POST',{'body':'Tolle Idee!'},other)[0],201)
        detail=self.request(f'/api/posts/{pid}')[1]
        self.assertEqual(detail['comments'][0]['author'],'reader')
        self.assertEqual(self.request('/api/posts?q=Homelab&kind=forum')[1]['total'],1)
        self.assertEqual(self.request('/api/posts?category=3d-druck&kind=forum')[1]['total'],0)
        self.assertEqual(self.request(f'/api/posts/{pid}','DELETE',{},other)[0],403)
        self.assertEqual(self.request('/api/posts','POST',{**post,'kind':'blog'},cookie)[0],403)
        self.assertEqual(self.request(f'/api/posts/{pid}','DELETE',{},cookie)[0],200)
        self.assertEqual(self.request(f'/api/posts/{pid}')[0],404)
        with server.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM comments WHERE post_id=?',(pid,)).fetchone()[0],0)

    def test_04_editor(self):
        cookie,user=self.register('editor')
        with server.connect() as db:db.execute('UPDATE users SET admin=1 WHERE id=?',(user['id'],))
        status,data,_=self.request('/api/posts','POST',{'title':'Ein neuer Artikel','body':'Dieser Artikel stammt aus der Redaktion.','category':'projekte','kind':'blog'},cookie)
        self.assertEqual(status,201)
        self.assertEqual(self.request(f"/api/posts/{data['id']}")[1]['post']['author'],'editor')

    def test_05_validation_and_csrf(self):
        cookie,_=self.register('secure')
        post={'title':'Ein neues Thema','body':'Hier steht ein vollständiger Beitrag.','category':'it'}
        for override in ({'category':'unknown'},{'title':'x'},{'body':'x'},{'kind':'bad'}):
            self.assertEqual(self.request('/api/posts','POST',{**post,**override},cookie)[0],400)
        for hdr in ({'X-Requested-With':''},{'Origin':'https://evil.example'},{'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.request('/api/posts','POST',post,cookie,hdr)[0],403)
        self.assertEqual(self.request('/api/posts','POST',[],cookie)[0],400)
        self.assertEqual(self.request('/api/posts?page=oops')[0],400)
        self.assertEqual(self.request('/api/posts/999999/comments','POST',{'body':'Hallo'},cookie)[0],404)
        with server.connect() as db:
            row=db.execute('SELECT password FROM users WHERE username=?',('secure',)).fetchone()
            self.assertNotIn('correct horse battery',row['password'])
            self.assertTrue(server.password_matches('correct horse battery',row['password']))

    def test_06_expiry_and_rate_limit(self):
        cookie,user=self.register('expired')
        with server.connect() as db:db.execute('UPDATE sessions SET expires=0 WHERE user_id=?',(user['id'],))
        self.assertIsNone(self.request('/api/me',cookie=cookie)[1]['user'])
        with server.connect() as db:
            ip=hashlib.sha256(b'127.0.0.1').hexdigest()
            db.execute('INSERT INTO rate_limits VALUES(?,?,?,?) ON CONFLICT(bucket,subject) DO UPDATE SET count=20',('auth',ip,int(time.time()),20))
        self.assertEqual(self.request('/api/login','POST',{'identifier':'expired','password':'correct horse battery'})[0],429)

    def test_07_verification_required_single_use_and_expiry(self):
        token=self.pending('unverified')
        self.assertEqual(self.request('/api/login','POST',{'identifier':'unverified','password':'correct horse battery'})[0],403)
        with server.connect() as db:
            row=db.execute('SELECT token FROM email_tokens WHERE token=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            self.assertIsNotNone(row)
            self.assertNotEqual(row['token'],token)
        self.assertEqual(self.request('/api/verify-email','POST',{'token':token})[0],200)
        self.assertEqual(self.request('/api/verify-email','POST',{'token':token})[0],400)
        self.assertEqual(self.request('/api/login','POST',{'identifier':'unverified@example.test','password':'correct horse battery'})[0],200)
        stale=self.pending('stale')
        with server.connect() as db: db.execute('UPDATE email_tokens SET expires=0 WHERE token=?',(hashlib.sha256(stale.encode()).hexdigest(),))
        self.assertEqual(self.request('/api/verify-email','POST',{'token':stale})[0],400)
        self.assertEqual(self.request('/api/verify-email','POST',{'token':'x'*43})[0],400)

    def test_08_resend_and_legacy_account(self):
        old=self.pending('resender')
        data={'identifier':'resender','password':'correct horse battery'}
        self.assertEqual(self.request('/api/request-verification','POST',data)[0],429)
        with server.connect() as db: db.execute('UPDATE email_tokens SET sent=0')
        self.assertEqual(self.request('/api/request-verification','POST',data)[0],200)
        fresh=self.mail_mock.call_args.args[1]
        self.assertNotEqual(fresh,old)
        self.assertEqual(self.request('/api/verify-email','POST',{'token':old})[0],400)
        self.assertEqual(self.request('/api/verify-email','POST',{'token':fresh})[0],200)
        with server.connect() as db:
            db.execute('INSERT INTO users(username,password,created) VALUES(?,?,?)',('legacy',server.password_hash('legacy password'),int(time.time())))
        self.assertEqual(self.request('/api/request-verification','POST',{'identifier':'legacy','password':'wrong password','email':'legacy@example.test'})[0],401)
        self.assertEqual(self.request('/api/request-verification','POST',{'identifier':'legacy','password':'legacy password','email':'legacy@example.test'})[0],200)
        self.assertEqual(self.request('/api/verify-email','POST',{'token':self.mail_mock.call_args.args[1]})[0],200)
        self.assertEqual(self.request('/api/login','POST',{'identifier':'legacy@example.test','password':'legacy password'})[0],200)

    def test_09_topics_and_edit_permissions(self):
        owner,_=self.register('owner'); outsider,_=self.register('outsider'); admin,admin_user=self.register('administrator')
        with server.connect() as db: db.execute('UPDATE users SET admin=1 WHERE id=?',(admin_user['id'],))
        data={'name':'Heimautomatisierung','description':'Alles rund um smarte Geräte im eigenen Zuhause.'}
        self.assertEqual(self.request('/api/topics','POST',data)[0],401)
        self.assertEqual(self.request('/api/topics','POST',data,owner)[0],403)
        status,result,_=self.request('/api/topics','POST',data,admin)
        self.assertEqual(status,201);slug=result['slug']
        self.assertIn(slug,[r['slug'] for r in self.request('/api/topics')[1]['topics']])
        self.assertEqual(self.request('/api/topics','POST',data,admin)[0],409)
        post={'title':'Ein neues Projekt','body':'Ich baue eine Steuerung für mein Zuhause.','category':slug,'kind':'forum'}
        status,result,_=self.request('/api/posts','POST',post,owner);self.assertEqual(status,201);pid=result['id']
        updated={**post,'title':'Das aktualisierte Projekt'}
        for method in ('PATCH','DELETE'):
            self.assertEqual(self.request(f'/api/posts/{pid}',method,updated)[0],401)
            self.assertEqual(self.request(f'/api/posts/{pid}',method,updated,outsider)[0],403)
        self.assertEqual(self.request(f'/api/posts/{pid}','PATCH',updated,owner)[0],200)
        self.assertEqual(self.request(f'/api/posts/{pid}','PATCH',{**updated,'title':'Vom Admin bearbeitet'},admin)[0],200)
        self.assertEqual(self.request(f'/api/posts/{pid}')[1]['post']['title'],'Vom Admin bearbeitet')
        self.assertEqual(self.request(f'/api/posts/{pid}/comments','POST',{'body':'Eine Antwort'},owner)[0],201)
        cid=self.request(f'/api/posts/{pid}')[1]['comments'][0]['id']
        self.assertEqual(self.request(f'/api/comments/{cid}','PATCH',{'body':'Manipuliert'},outsider)[0],403)
        self.assertEqual(self.request(f'/api/comments/{cid}','PATCH',{'body':'Korrigiert'},owner)[0],200)
        self.assertEqual(self.request(f'/api/comments/{cid}','PATCH',{'body':'Moderiert'},admin)[0],200)
        self.assertEqual(self.request(f'/api/comments/{cid}','DELETE',{},admin)[0],200)
        self.assertEqual(self.request(f'/api/posts/{pid}','DELETE',{},admin)[0],200)

    def test_10_mail_failure_and_missing_configuration(self):
        with patch.dict(os.environ,{'SMTP_HOST':''}):
            self.assertEqual(self.request('/api/register','POST',{'username':'configmissing','email':'missing@example.test','password':'correct horse battery'})[0],503)
        self.mail_mock.side_effect=server.APIError(503,'Versand fehlgeschlagen')
        try:
            self.assertEqual(self.request('/api/register','POST',{'username':'mailfailed','email':'mailfailed@example.test','password':'correct horse battery'})[0],503)
        finally: self.mail_mock.side_effect=None
        self.assertEqual(self.request('/api/login','POST',{'identifier':'mailfailed','password':'correct horse battery'})[0],403)
        self.assertEqual(self.request('/api/request-verification','POST',{'identifier':'mailfailed','password':'correct horse battery'})[0],200)
        for route in ('/forum','/blog','/forum/it','/posts/1'):
            self.assertEqual(self.request(route)[0],200)

    def test_11_old_database_migration(self):
        original=server.DB
        try:
            server.DB=Path(self.temp.name)/'legacy.db'
            with server.connect() as db:
                db.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,admin INTEGER DEFAULT 0,created INTEGER); CREATE TABLE sessions(token TEXT PRIMARY KEY,user_id INTEGER,expires INTEGER);")
                db.execute('INSERT INTO users VALUES(1,?,?,1,0)',('existing',server.password_hash('old password')))
                db.execute('INSERT INTO sessions VALUES(?,?,?)',('old-session',1,int(time.time())+1000))
            server.initialize();server.initialize()
            with server.connect() as db:
                row=db.execute('SELECT * FROM users WHERE id=1').fetchone()
                self.assertEqual(row['admin'],1);self.assertEqual(row['email_verified'],0)
                self.assertIsNone(row['email'])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM topics').fetchone()[0],4)
        finally: server.DB=original

    def test_12_smtp_tls_and_message(self):
        # Exercise real message construction and TLS selection with a fake SMTP transport.
        self.mail.stop()
        try:
            with patch('server.smtplib.SMTP') as smtp:
                server.send_verification('recipient@example.test','test-token')
                client=smtp.return_value
                client.starttls.assert_called_once()
                client.login.assert_called_once_with('test','test-only')
                message=client.send_message.call_args.args[0]
                self.assertEqual(message['To'],'recipient@example.test')
                self.assertIn('https://steckerrein.de/#verify/test-token',message.get_content())
            with patch.dict(os.environ,{'SMTP_PORT':'465'}),patch('server.smtplib.SMTP_SSL') as smtp:
                server.send_verification('recipient@example.test','another-token')
                smtp.return_value.starttls.assert_not_called()
            with patch('server.smtplib.SMTP',side_effect=OSError('offline')):
                with self.assertRaises(server.APIError): server.send_verification('recipient@example.test','unprinted-token')
        finally: self.mail_mock=self.mail.start();type(self).mail_mock=self.mail_mock

if __name__=='__main__':unittest.main()
