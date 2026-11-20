from fastapi.testclient import TestClient
from contextcare import api
from contextcare.core import Store
from contextcare.engine import Assistant

def test_api_auth_chat_privacy_isolation(tmp_path,monkeypatch):
    api.service.cache_clear()
    svc=Assistant(Store(tmp_path/'api.db'));monkeypatch.setattr(api,'service',lambda:svc)
    c=TestClient(api.app)
    assert c.get('/health').status_code==200
    assert c.post('/auth/register',json={'username':'alice','password':'password123'}).status_code==200
    token=c.post('/auth/login',json={'username':'alice','password':'password123'}).json()['access_token'];h={'Authorization':'Bearer '+token}
    r=c.post('/chat/message',headers=h,json={'text':'My name is Trishanth and I have a meeting with Rahul tomorrow at 4 PM.'})
    assert r.status_code==200,r.text
    assert 'Trishanth' not in r.json()['analysis']['masked_text']
    assert c.get('/privacy/mappings',headers=h).status_code==200
    assert c.get('/tasks',headers=h).status_code==200
    assert c.get('/chat/sessions').status_code==401
    c.post('/auth/register',json={'username':'bob','password':'password123'})
    token2=c.post('/auth/login',json={'username':'bob','password':'password123'}).json()['access_token']
    assert c.get('/chat/history',params={'conversation_id':r.json()['conversation_id']},headers={'Authorization':'Bearer '+token2}).status_code==403
    assert c.post('/auth/logout',headers=h).status_code==200
    assert c.get('/tasks',headers=h).status_code==401
