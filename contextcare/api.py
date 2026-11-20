"""FastAPI wrapper. Authentication is required for every user-owned operation."""
from __future__ import annotations
import os
from functools import lru_cache
from fastapi import FastAPI,Depends,Header,HTTPException
from pydantic import BaseModel,Field
from .core import Store,Auth
from .engine import Assistant

app=FastAPI(title='ContextCare AI',version='1.0',description='Offline-first privacy-preserving assistant')
@lru_cache(maxsize=1)
def service():return Assistant(Store(),model_path=str(__import__('pathlib').Path(__file__).resolve().parents[1]/'models/intent.joblib'))

def current(authorization:str=Header(default='')):
    if not authorization.startswith('Bearer '):raise HTTPException(401,'Bearer token required')
    try:return service().auth.user(authorization[7:])
    except PermissionError:raise HTTPException(401,'Session invalid or expired') from None

class Credentials(BaseModel):
    username:str=Field(min_length=3,max_length=40)
    password:str=Field(min_length=8,max_length=128)
class ChatIn(BaseModel):
    text:str=Field(min_length=1,max_length=5000)
    conversation_id:str|None=None
class TaskIn(BaseModel):
    title:str=Field(min_length=1,max_length=500)
    kind:str='task'
    due_at:str|None=None
class TaskPatch(BaseModel):
    title:str|None=None
    due_at:str|None=None
    status:str|None=None
class SettingIn(BaseModel):
    key:str
    value:bool
class ExportIn(BaseModel):
    password:str
    reveal_originals:bool=False

@app.exception_handler(PermissionError)
async def permission_error(request,exc):return __import__('fastapi').responses.JSONResponse(status_code=403,content={'detail':'Access denied'})
@app.exception_handler(ValueError)
async def validation_error(request,exc):return __import__('fastapi').responses.JSONResponse(status_code=422,content={'detail':'Invalid request or input'})

@app.get('/health')
def health():return {'status':'ok','service':'ContextCare AI'}
@app.post('/auth/register')
def register(data:Credentials):return {'user_id':service().auth.register(data.username,data.password)}
@app.post('/auth/login')
def login(data:Credentials):
    try:return {'access_token':service().auth.login(data.username,data.password),'token_type':'bearer'}
    except PermissionError:raise HTTPException(401,'Invalid credentials or temporarily locked') from None
@app.post('/auth/logout')
def logout(authorization:str=Header(default=''),user=Depends(current)):
    service().auth.logout(authorization[7:]);return {'ok':True}
@app.post('/chat/message')
def chat(data:ChatIn,user=Depends(current)):return service().chat(user['id'],data.text,data.conversation_id)
@app.get('/chat/sessions')
def sessions(user=Depends(current)):
    return [dict(r) for r in service().s.all('SELECT id,title,created_at FROM conversations WHERE user_id=? ORDER BY created_at DESC',(user['id'],))]
@app.get('/chat/history')
def history(conversation_id:str,user=Depends(current)):return service().history(user['id'],conversation_id)
@app.delete('/chat/sessions/{id}')
def delete_session(id:str,user=Depends(current)):
    service()._conversation(user['id'],id)
    service().s.execute('DELETE FROM conversations WHERE id=? AND user_id=?',(id,user['id']));return {'ok':True}
@app.get('/memory')
def memories(user=Depends(current)):return service().memory.list(user['id'])
@app.get('/memory/search')
def search_memory(q:str,user=Depends(current)):return service().memory.search(user['id'],q)
@app.delete('/memory/{id}')
def delete_memory(id:str,confirmed:bool=False,user=Depends(current)):
    service().permission.authorize(user['id'],user['id'],'delete_memory',confirmed)
    service().s.execute('DELETE FROM long_term_memory WHERE id=? AND user_id=?',(id,user['id']));service().s.audit(user['id'],'memory_deleted');return {'ok':True}
@app.get('/tasks')
def tasks(user=Depends(current)):return service().tasks(user['id'])
@app.post('/tasks')
def task_create(data:TaskIn,user=Depends(current)):
    if data.kind not in ('task','meeting','reminder'):raise ValueError('Invalid task type')
    return {'id':service().create_task(user['id'],None,data.title,data.kind,data.due_at)}
@app.patch('/tasks/{id}')
def task_update(id:str,data:TaskPatch,user=Depends(current)):
    vals=data.model_dump(exclude_unset=True)
    if 'status' in vals and vals['status'] not in ('open','completed','cancelled'):raise ValueError('Invalid status')
    service().update_task(user['id'],id,**vals);return {'ok':True}
@app.delete('/tasks/{id}')
def task_delete(id:str,confirmed:bool=False,user=Depends(current)):
    service().delete_task(user['id'],id,confirmed);return {'ok':True}
@app.get('/privacy/stats')
def privacy_stats(user=Depends(current)):return service().privacy.stats(user['id'])
@app.get('/privacy/settings')
def privacy_settings(user=Depends(current)):
    prefs=service().s.all('SELECT key,value FROM user_preferences WHERE user_id=?',(user['id'],))
    return {r['key']:r['value'] for r in prefs}
@app.put('/privacy/settings')
def privacy_setting(data:SettingIn,user=Depends(current)):
    if data.key not in ('mask_person','memory_consent'):raise ValueError('Unsupported setting')
    service().s.execute('INSERT INTO user_preferences(user_id,key,value) VALUES (?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value',(user['id'],data.key,str(data.value).lower()))
    return {'ok':True}
@app.get('/privacy/mappings')
def mappings(user=Depends(current)):
    return [dict(r) for r in service().s.all('SELECT entity_type,alias,is_self FROM pseudonym_mappings WHERE user_id=?',(user['id'],))]
@app.post('/privacy/export')
def export(data:ExportIn,user=Depends(current)):
    from .core import verify_password
    if not verify_password(data.password,user['password_hash']):raise HTTPException(403,'Password verification failed')
    conversations=[dict(r) for r in service().s.all('SELECT id,title FROM conversations WHERE user_id=?',(user['id'],))]
    messages=[]
    for c in conversations:messages+=service().history(user['id'],c['id'],reveal=data.reveal_originals)
    service().s.audit(user['id'],'export_originals' if data.reveal_originals else 'export_masked')
    return {'conversations':conversations,'messages':messages,'memories':service().memory.list(user['id']),'tasks':service().tasks(user['id'])}
@app.delete('/privacy/data')
def erase(password:str,user=Depends(current)):
    from .core import verify_password
    if not verify_password(password,user['password_hash']):raise HTTPException(403,'Password verification failed')
    service().s.execute('DELETE FROM users WHERE id=?',(user['id'],));return {'deleted':True}
@app.get('/metrics')
def metrics(user=Depends(current)):
    rows=service().s.all('SELECT event_type,COUNT(*) n,AVG(duration_ms) avg_ms FROM analytics_events WHERE user_id=? GROUP BY event_type',(user['id'],))
    return {'intents':[dict(r) for r in rows],'messages':service().s.one('SELECT COUNT(*) n FROM messages WHERE user_id=?',(user['id'],))['n']}
@app.post('/nlp/analyze')
def analyze(data:ChatIn,user=Depends(current)):return service().analyze(user['id'],data.text)
