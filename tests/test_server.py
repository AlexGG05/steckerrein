import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class CommunityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        server.DB=Path(cls.temp.name)/'test.db'
        server.initialize()
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.temp.cleanup()

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

    def register(self,name):
        status,data,cookie=self.request('/api/register','POST',{'username':name,'password':'correct horse battery'})
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
        self.assertEqual(self.request('/api/register','POST',{'username':'BUILDER','password':'correct horse battery'})[0],409)
        self.assertEqual(self.request('/api/login','POST',{'username':'builder','password':'wrong password'})[0],401)
        self.assertEqual(self.request('/api/login','POST',{'username':'builder','password':'correct horse battery'})[0],200)
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
        import time
        server.Handler.attempts['127.0.0.1']=(time.time(),20)
        self.assertEqual(self.request('/api/login','POST',{'username':'expired','password':'correct horse battery'})[0],429)
        server.Handler.attempts.clear()

if __name__=='__main__':unittest.main()
