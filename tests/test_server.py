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
        data={'name':'Heimautomatisierung','description':'Alles rund um smarte Geräte im eigenen Zuhause.','allow_posts':True}
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

    def test_13_topic_hierarchy_and_safe_deletion(self):
        admin,admin_user=self.register('hierarchyadmin'); member,_=self.register('hierarchymember')
        with server.connect() as db: db.execute('UPDATE users SET admin=1 WHERE id=?',(admin_user['id'],))
        def create(name,parent=None,allowed=False):
            status,value,_=self.request('/api/topics','POST',{'name':name,'description':'Ein Bereich für gemeinsame Projekte.','parent_slug':parent,'allow_posts':allowed,'allow_replies':allowed},admin)
            self.assertEqual(status,201,value);return value['slug']
        root=create('Hardware Oberthema');child=create('Server Unterthema',root,True);target=create('Ersatz Unterthema',root,True)
        def setting(name,parent,allowed):return {'name':name,'description':'Eine aktualisierte Beschreibung.','parent_slug':parent,'allow_posts':allowed,'allow_replies':allowed}
        for method in ('PATCH','DELETE'):
            self.assertEqual(self.request('/api/topics/'+root,method,{},None)[0],401)
            self.assertEqual(self.request('/api/topics/'+root,method,{},member)[0],403)
        self.assertEqual(self.request('/api/topics/'+root,'PATCH',setting('Hardware',child,False),admin)[0],400)
        self.assertEqual(self.request('/api/topics/'+child,'PATCH',setting('Server',child,True),admin)[0],400)
        self.assertEqual(self.request('/api/topics/'+child,'PATCH',setting('Server',root,'yes'),admin)[0],400)
        self.assertEqual(self.request('/api/topics/'+child,'PATCH',setting('Hardware Oberthema',root,True),admin)[0],409)
        self.assertEqual(self.request('/api/topics/'+child,'PATCH',setting('Server Wissen',root,True),admin)[0],200)
        post={'title':'Server zusammenbauen','body':'Wir bauen einen neuen Server für unser Homelab.','kind':'forum','category':root}
        self.assertEqual(self.request('/api/posts','POST',post,member)[0],403)
        status,value,_=self.request('/api/posts','POST',{**post,'category':child},member)
        self.assertEqual(status,201);pid=value['id']
        self.assertEqual(self.request('/api/posts/'+str(pid)+'/comments','POST',{'body':'Meine Antwort'},member)[0],201)
        self.assertEqual(self.request('/api/topics/'+child,'PATCH',setting('Server Wissen',root,False),admin)[0],200)
        self.assertEqual(self.request('/api/posts/'+str(pid)+'/comments','POST',{'body':'Noch eine Antwort'},member)[0],403)
        self.assertEqual(self.request('/api/posts/'+str(pid),'PATCH',{**post,'category':child,'title':'Korrigierter Serverbeitrag'},member)[0],200)
        self.assertEqual(self.request('/api/topics/'+root,'DELETE',{},admin)[0],409)
        self.assertEqual(self.request('/api/topics/'+child,'DELETE',{},admin)[0],409)
        self.assertEqual(self.request('/api/topics/'+child,'DELETE',{'move_to':child},admin)[0],400)
        self.assertEqual(self.request('/api/topics/'+child,'DELETE',{'move_to':root},admin)[0],400)
        self.assertEqual(self.request('/api/topics/'+child,'DELETE',{'move_to':'missing'},admin)[0],400)
        before=self.request('/api/posts/'+str(pid))[1]
        status,value,_=self.request('/api/topics/'+child,'DELETE',{'move_to':target},admin)
        self.assertEqual(status,200);self.assertEqual(value['moved'],1)
        after=self.request('/api/posts/'+str(pid))[1]
        self.assertEqual(after['comments'],before['comments'])
        self.assertEqual(after['post']['category'],target)
        self.assertEqual(after['post']['user_id'],before['post']['user_id'])
        self.assertEqual(self.request('/api/topics/'+child,'DELETE',{},admin)[0],404)
        self.assertEqual(self.request('/api/topics/'+target,'PATCH',setting('Verschobener Bereich',None,True),admin)[0],200)
        self.assertEqual(self.request('/api/topics/'+root,'DELETE',{},admin)[0],200)
        server.initialize()
        self.assertNotIn(root,[t['slug'] for t in self.request('/api/topics')[1]['topics']])

    def test_14_profiles_and_uploads(self):
        import io,base64
        from PIL import Image,PngImagePlugin
        owner,owner_user=self.register('profileowner');other,other_user=self.register('profileother')
        data={'display_name':'Alex Maker','bio':'Ich mag IT und 3D-Druck.','website':'https://example.test/projects'}
        self.assertEqual(self.request('/api/profile','PATCH',data)[0],401)
        self.assertEqual(self.request('/api/profile','PATCH',data,owner)[0],200)
        profile=self.request('/api/users/profileowner')[1]['profile']
        self.assertEqual(profile['display_name'],'Alex Maker');self.assertEqual(profile['bio'],data['bio'])
        for key in ('email','email_verified','password','token','avatar'):self.assertNotIn(key,profile)
        self.assertEqual(self.request('/users/profileowner')[0],200)
        self.assertEqual(self.request('/api/users/missing')[0],404)
        self.assertEqual(self.request('/api/users/profileowner/avatar')[0],404)
        # A supplied user_id cannot edit another account: /api/profile always targets the session owner.
        self.assertEqual(self.request('/api/profile','PATCH',{**data,'display_name':'Other Maker','user_id':owner_user['id']},other)[0],200)
        self.assertEqual(self.request('/api/users/profileowner')[1]['profile']['display_name'],'Alex Maker')
        image=Image.new('RGB',(400,200),'orange');stream=io.BytesIO();metadata=PngImagePlugin.PngInfo();metadata.add_text('private-location','do not preserve');image.save(stream,format='PNG',pnginfo=metadata)
        encoded=base64.b64encode(stream.getvalue()).decode()
        self.assertEqual(self.request('/api/profile','PATCH',{**data,'avatar':encoded},owner)[0],200)
        self.assertTrue(self.request('/api/users/profileowner')[1]['profile']['has_avatar'])
        # The test helper returns image bytes because they are not JSON.
        status,content,_=self.request('/api/users/profileowner/avatar')
        self.assertEqual(status,200)
        with Image.open(io.BytesIO(content)) as avatar:
            self.assertEqual(avatar.size,(256,256));self.assertNotIn('private-location',avatar.info)
        self.assertEqual(self.request('/api/profile','PATCH',{**data,'remove_avatar':True},owner)[0],200)
        self.assertEqual(self.request('/api/users/profileowner/avatar')[0],404)
        post={'title':'Ein Profilbeitrag','body':'Dieser öffentliche Beitrag gehört zum Profil.','category':'it'}
        self.assertEqual(self.request('/api/posts','POST',post,owner)[0],201)
        self.assertEqual(self.request('/api/posts?author=profileowner')[1]['total'],1)
        self.assertEqual(self.request('/api/posts?author=profileother')[1]['total'],0)

    def test_15_invalid_profile_data_and_images(self):
        import base64,io
        from PIL import Image
        cookie,_=self.register('imagechecks')
        data={'display_name':'Valid name','bio':'Eine normale Bio.','website':''}
        for website in ('javascript:alert(1)','data:text/html,bad','https://user:password@example.test','https://example.test:bad','https://exa mple.test'):
            self.assertEqual(self.request('/api/profile','PATCH',{**data,'website':website},cookie)[0],400)
        for image in ('not base64!',base64.b64encode(b'<svg onload="alert(1)"></svg>').decode(),base64.b64encode(b'x'*1048577).decode()):
            self.assertEqual(self.request('/api/profile','PATCH',{**data,'avatar':image},cookie)[0],400)
        buf=io.BytesIO();Image.new('RGB',(2100,2100)).save(buf,format='PNG')
        self.assertEqual(self.request('/api/profile','PATCH',{**data,'avatar':base64.b64encode(buf.getvalue()).decode()},cookie)[0],400)
        self.assertEqual(self.request('/api/profile','PATCH',{**data,'remove_avatar':'yes'},cookie)[0],400)
        self.assertEqual(self.request('/api/profile','PATCH',{**data,'bio':'x'*1001},cookie)[0],400)
        self.assertFalse(self.request('/api/users/imagechecks')[1]['profile']['has_avatar'])

    def test_16_tag_catalog_and_admin_permissions(self):
        admin,admin_user=self.register('tagadmin');member,_=self.register('tagmember')
        with server.connect() as db:db.execute('UPDATE users SET admin=1 WHERE id=?',(admin_user['id'],))
        data={'kind':'post','name':'Bambu Lab A1','color':'blue'}
        self.assertEqual(self.request('/api/admin/tags','POST',data)[0],401)
        self.assertEqual(self.request('/api/admin/tags','POST',data,member)[0],403)
        status,result,_=self.request('/api/admin/tags','POST',data,admin);self.assertEqual(status,201);tag_id=result['id']
        self.assertEqual(self.request('/api/admin/tags','POST',{**data,'name':'bambu lab a1'},admin)[0],409)
        self.assertEqual(self.request('/api/admin/tags','POST',{**data,'name':'Invalid','color':'url(javascript:bad)'},admin)[0],400)
        self.assertEqual(self.request('/api/admin/tags','POST',{**data,'kind':'admin'},admin)[0],400)
        for method in ('PATCH','DELETE'):
            self.assertEqual(self.request('/api/admin/tags/'+str(tag_id),method,data,member)[0],403)
        self.assertEqual(self.request('/api/admin/tags/'+str(tag_id),'PATCH',{**data,'name':'Bambu A1','color':'green'},admin)[0],200)
        self.assertEqual(self.request('/api/admin/tags/'+str(tag_id),'PATCH',{**data,'kind':'user'},admin)[0],400)
        self.assertEqual(self.request('/api/admin/users')[0],401)
        self.assertEqual(self.request('/api/admin/users',cookie=member)[0],403)
        result=self.request('/api/admin/users?q=tagmember',cookie=admin)[1]
        self.assertEqual(result['total'],1)
        for key in ('email','password','avatar'):self.assertNotIn(key,result['users'][0])
        self.assertEqual(self.request('/admin')[0],200)

    def test_17_post_tags_are_controlled_by_author_or_admin(self):
        admin,admin_user=self.register('posttagadmin');author,_=self.register('posttagauthor');other,_=self.register('posttagother')
        with server.connect() as db:db.execute('UPDATE users SET admin=1 WHERE id=?',(admin_user['id'],))
        catalog=self.request('/api/tags')[1]['tags'];open_id=next(t['id'] for t in catalog if t['kind']=='post' and t['name']=='Offen');solved_id=next(t['id'] for t in catalog if t['kind']=='post' and t['name']=='Gelöst')
        status,value,_=self.request('/api/admin/tags','POST',{'kind':'user','name':'Helfer','color':'purple'},admin);self.assertEqual(status,201);user_tag=value['id']
        post={'title':'Ein Druckerproblem','body':'Mein Drucker benötigt einen neuen Extruder.','category':'it','tag_ids':[open_id]}
        status,value,_=self.request('/api/posts','POST',post,author);self.assertEqual(status,201);pid=value['id']
        self.assertEqual(self.request('/api/posts/'+str(pid))[1]['post']['tags'][0]['name'],'Offen')
        self.assertEqual(self.request('/api/posts/'+str(pid),'PATCH',{**post,'tag_ids':[solved_id]},other)[0],403)
        self.assertEqual(self.request('/api/posts/'+str(pid),'PATCH',{**post,'tag_ids':[solved_id]},author)[0],200)
        for ids in ([user_tag],[999999],[open_id,open_id],['1'],[True],list(range(1,12))):
            self.assertEqual(self.request('/api/posts/'+str(pid),'PATCH',{**post,'title':'Darf nicht gespeichert werden','tag_ids':ids},author)[0],400)
        self.assertEqual(self.request('/api/posts/'+str(pid))[1]['post']['title'],post['title'])
        self.assertEqual(self.request('/api/posts/'+str(pid))[1]['post']['tags'][0]['name'],'Gelöst')
        self.assertEqual(self.request('/api/posts/'+str(pid),'PATCH',{**post,'tag_ids':[]},admin)[0],200)
        self.assertEqual(self.request('/api/posts/'+str(pid))[1]['post']['tags'],[])
        self.assertEqual(self.request('/api/posts','POST',{**post,'tag_ids':[user_tag]},author)[0],400)
        self.assertEqual(self.request('/api/posts?author=posttagauthor')[1]['total'],1)

    def test_18_user_tags_and_safe_tag_deletion(self):
        admin,admin_user=self.register('usertagadmin');member,member_user=self.register('usertagmember')
        with server.connect() as db:db.execute('UPDATE users SET admin=1 WHERE id=?',(admin_user['id'],))
        status,value,_=self.request('/api/admin/tags','POST',{'kind':'user','name':'3D-Druck Experte','color':'orange'},admin);self.assertEqual(status,201);tag=value['id']
        target='/api/admin/users/'+str(member_user['id'])+'/tags'
        self.assertEqual(self.request(target,'PATCH',{'tag_ids':[tag]})[0],401)
        self.assertEqual(self.request(target,'PATCH',{'tag_ids':[tag]},member)[0],403)
        self.assertEqual(self.request(target,'PATCH',{'tag_ids':[tag]},admin)[0],200)
        profile=self.request('/api/users/usertagmember')[1]['profile'];self.assertEqual(profile['tags'][0]['name'],'3D-Druck Experte');self.assertEqual(profile['admin'],0)
        self.assertEqual(self.request('/api/me',cookie=member)[1]['user']['admin'],0)
        post={'title':'Ein Expertenbeitrag','body':'Ein hilfreicher Beitrag mit einem öffentlichen Nutzertag.','category':'it'}
        status,value,_=self.request('/api/posts','POST',post,member);self.assertEqual(status,201);pid=value['id']
        self.assertEqual(self.request('/api/posts/'+str(pid))[1]['post']['author_tags'][0]['id'],tag)
        post_tag=next(t['id'] for t in self.request('/api/tags')[1]['tags'] if t['kind']=='post')
        self.assertEqual(self.request(target,'PATCH',{'tag_ids':[post_tag]},admin)[0],400)
        self.assertEqual(self.request('/api/users/usertagmember')[1]['profile']['tags'][0]['id'],tag)
        self.assertEqual(self.request('/api/admin/tags/'+str(tag),'DELETE',{},admin)[0],200)
        self.assertEqual(self.request('/api/users/usertagmember')[1]['profile']['tags'],[])
        self.assertEqual(self.request('/api/posts/'+str(pid))[0],200)
        self.assertEqual(self.request('/api/admin/users/999999/tags','PATCH',{'tag_ids':[]},admin)[0],404)
        server.initialize()
        self.assertNotIn(tag,[t['id'] for t in self.request('/api/tags')[1]['tags']])

    def test_19_replies_independent_of_new_posts(self):
        admin,admin_user=self.register('replyadmin');member,_=self.register('replymember')
        with server.connect() as db:db.execute('UPDATE users SET admin=1 WHERE id=?',(admin_user['id'],))
        settings={'name':'Tagwünsche','description':'Hier können Mitglieder gewünschte Tags vorschlagen.','allow_posts':True,'allow_replies':True}
        status,result,_=self.request('/api/topics','POST',settings,admin);self.assertEqual(status,201);slug=result['slug']
        post={'title':'Welche Tags wünscht ihr euch?','body':'Bitte antwortet hier mit euren gewünschten Tags.','category':slug}
        status,result,_=self.request('/api/posts','POST',post,admin);self.assertEqual(status,201);pid=result['id']
        self.assertEqual(self.request('/api/topics/'+slug,'PATCH',{**settings,'allow_posts':False},admin)[0],200)
        self.assertEqual(self.request('/api/posts','POST',post,member)[0],403)
        self.assertEqual(self.request('/api/posts/'+str(pid)+'/comments','POST',{'body':'Ich wünsche mir einen Druckermodell-Tag.'})[0],401)
        self.assertEqual(self.request('/api/posts/'+str(pid)+'/comments','POST',{'body':'Ich wünsche mir einen Druckermodell-Tag.'},member)[0],201)
        detail=self.request('/api/posts/'+str(pid))[1];self.assertEqual(detail['post']['allow_replies'],1)
        self.assertEqual(self.request('/api/topics/'+slug,'PATCH',{**settings,'allow_posts':True,'allow_replies':False},admin)[0],200)
        self.assertEqual(self.request('/api/posts/'+str(pid)+'/comments','POST',{'body':'Noch ein Wunsch'},member)[0],403)
        self.assertEqual(self.request('/api/posts','POST',post,member)[0],201)
        self.assertEqual(len(self.request('/api/posts/'+str(pid))[1]['comments']),1)
        self.assertEqual(self.request('/api/topics/'+slug,'PATCH',{**settings,'allow_replies':'yes'},admin)[0],400)
        # Older clients that omit the new setting must not silently change it.
        self.assertEqual(self.request('/api/topics/'+slug,'PATCH',{'name':settings['name'],'description':settings['description'],'allow_posts':False},admin)[0],200)
        self.assertEqual(self.request('/api/posts/'+str(pid))[1]['post']['allow_replies'],0)
        server.initialize()
        self.assertEqual(self.request('/api/posts/'+str(pid))[1]['post']['allow_replies'],0)

    def post_image(self, format='PNG', size=(400,200)):
        import base64,io
        from PIL import Image,PngImagePlugin
        image=Image.new('RGB',size,'steelblue');output=io.BytesIO()
        if format=='PNG':
            info=PngImagePlugin.PngInfo();info.add_text('private-location','must disappear');image.save(output,format=format,pnginfo=info)
        elif format=='JPEG':
            info=Image.Exif();info[270]='private camera note';image.save(output,format=format,exif=info)
        else:image.save(output,format=format)
        return {'data':base64.b64encode(output.getvalue()).decode()}

    def test_20_public_post_images_and_metadata(self):
        import io
        from PIL import Image
        cookie,_=self.register('pictureauthor')
        post={'title':'Mein Setup mit Bildern','body':'Hier seht ihr mein Homelab und meinen 3D-Drucker.','category':'it','images':[self.post_image(),self.post_image('JPEG',(3000,1800))]}
        status,result,_=self.request('/api/posts','POST',post,cookie);self.assertEqual(status,201);pid=result['id']
        detail=self.request('/api/posts/'+str(pid))[1]['post'];self.assertEqual(len(detail['images']),2)
        self.assertEqual(detail['images'][1]['width'],2560);self.assertEqual(detail['images'][1]['height'],1536)
        for picture in detail['images']:
            status,raw,_=self.request(picture['url']);self.assertEqual(status,200)
            with Image.open(io.BytesIO(raw)) as image:
                self.assertNotIn('private-location',image.info);self.assertNotIn('exif',image.info)
                self.assertEqual(image.size,(picture['width'],picture['height']))
        feed=self.request('/api/posts?author=pictureauthor')[1]['posts'][0]
        self.assertEqual(feed['images'],detail['images'])
        self.assertEqual(self.request('/media/'+'0'*32)[0],404)
        self.assertEqual(self.request('/api/posts/'+str(pid),'DELETE',{},cookie)[0],200)
        self.assertEqual(self.request(detail['images'][0]['url'])[0],404)

    def test_21_edit_image_permissions_and_retention(self):
        author,_=self.register('imageowner');other,_=self.register('imageother');admin,admin_user=self.register('imageadmin')
        with server.connect() as db:db.execute('UPDATE users SET admin=1 WHERE id=?',(admin_user['id'],))
        post={'title':'Ein bebilderter Beitrag','body':'Diese Bilder bleiben beim Bearbeiten erhalten.','category':'it','images':[self.post_image(),self.post_image('JPEG')]}
        status,result,_=self.request('/api/posts','POST',post,author);self.assertEqual(status,201);pid=result['id']
        pictures=self.request('/api/posts/'+str(pid))[1]['post']['images']
        self.assertEqual(self.request('/api/posts/'+str(pid),'PATCH',{**post,'images':[]},other)[0],403)
        self.assertEqual(self.request('/api/posts/'+str(pid),'PATCH',{**post,'images':[]})[0],401)
        self.assertEqual(self.request('/api/posts/'+str(pid),'PATCH',{**post,'images':[{'token':pictures[1]['token']}]},author)[0],200)
        self.assertEqual(self.request(pictures[0]['url'])[0],404)
        self.assertEqual(self.request(pictures[1]['url'])[0],200)
        # Omitting images leaves attachments untouched for older clients.
        no_images={k:v for k,v in post.items() if k!='images'}
        self.assertEqual(self.request('/api/posts/'+str(pid),'PATCH',no_images,author)[0],200)
        self.assertEqual(len(self.request('/api/posts/'+str(pid))[1]['post']['images']),1)
        status,value,_=self.request('/api/posts','POST',{**no_images,'images':[{'token':pictures[1]['token']}]},other)
        self.assertEqual(status,400)
        self.assertEqual(self.request('/api/posts?author=imageother')[1]['total'],0)
        self.assertEqual(self.request('/api/posts/'+str(pid),'PATCH',{**no_images,'images':[{'token':pictures[1]['token']},{'data':'bad'}]},author)[0],400)
        self.assertEqual(self.request(pictures[1]['url'])[0],200)
        self.assertEqual(self.request('/api/posts/'+str(pid),'PATCH',{**no_images,'images':[]},admin)[0],200)
        self.assertEqual(self.request(pictures[1]['url'])[0],404)

    def test_22_invalid_post_images_rollback(self):
        import base64
        cookie,_=self.register('imagevalidation')
        post={'title':'Ein Bild muss gültig sein','body':'Ungültige Bilder dürfen den Beitrag nicht speichern.','category':'it'}
        invalid=[None,{},[{'data':'bad base64!'}],[{'data':base64.b64encode(b'<svg></svg>').decode()}],[self.post_image('WEBP')],[self.post_image()]*6,[{'token':'not-owned'}]]
        for images in invalid:
            self.assertEqual(self.request('/api/posts','POST',{**post,'images':images},cookie)[0],400)
        self.assertEqual(self.request('/api/posts?author=imagevalidation')[1]['total'],0)
        self.assertEqual(self.request('/api/posts','POST',{**post,'images':[self.post_image()]} )[0],401)

if __name__=='__main__':unittest.main()
