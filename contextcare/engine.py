"""Pseudonymisation, memory search, coreference and dialogue services."""
from __future__ import annotations
import re,json,hashlib,hmac,time
from datetime import datetime,timedelta
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from .core import uid,iso,now,Auth,PermissionEngine
from .nlp import NLP,IntentModel,PII_KINDS

ALIASES={'PERSON':['Avery','Blake','Casey','Devon','Ellis','Finley','Harper','Jordan','Morgan','Parker','Quinn','Riley','Taylor','Robin','Sage','Skyler','Emery','Jamie','Rowan','Reese','Alex','Charlie','Sam','Drew'], 'EMAIL':['masked-mail'], 'PHONE':['masked-phone'], 'ADDRESS':['masked-address'], 'ID':['masked-id']}
EMBED=HashingVectorizer(n_features=256,alternate_sign=False,ngram_range=(1,2),norm='l2',stop_words='english')

def embedding(text):return EMBED.transform([text]).toarray()[0].astype(np.float32)

class Privacy:
    def __init__(self,store):self.s=store
    def settings(self,user_id):
        row=self.s.one("SELECT value FROM user_preferences WHERE user_id=? AND key='mask_person'",(user_id,))
        return {'mask_person':row is None or row['value']=='true','always_mask':['EMAIL','PHONE','ADDRESS','ID']}
    def mask(self,user_id,text,entities):
        options=self.settings(user_id);replacements=[]
        for ent in entities:
            if ent.label not in PII_KINDS or (ent.label=='PERSON' and not options['mask_person']):continue
            original=ent.text
            if self.s.one('SELECT 1 FROM pseudonym_mappings WHERE user_id=? AND entity_type=? AND alias=?',(user_id,ent.label,original)):
                continue  # Already a synthetic alias, never re-vault it as a new real identity.
            vault_id=self.s.vault_add(user_id,ent.label,original)
            row=self.s.one('SELECT alias FROM pseudonym_mappings WHERE user_id=? AND vault_id=?',(user_id,vault_id))
            if row:alias=row['alias']
            else:
                candidates=ALIASES[ent.label]
                digest=hmac.new(self.s.key,f'{user_id}:{ent.label}:{original.casefold()}'.encode(),'sha256').digest()
                start=int.from_bytes(digest[:4],'big')%len(candidates)
                alias=None
                for i in range(max(len(candidates),10000)):
                    idx=(start+i)%len(candidates)
                    candidate=candidates[idx] if i<len(candidates) else f'{candidates[idx]}-{i//len(candidates)+1}'
                    used=self.s.one('SELECT 1 FROM pseudonym_mappings WHERE user_id=? AND entity_type=? AND alias=?',(user_id,ent.label,candidate))
                    if not used:alias=candidate;break
                if alias is None:raise RuntimeError('Alias capacity exhausted')
                is_self=int(bool(re.search(r'(?:my name is|call me|i am called|i.m called)\s+$',text[:ent.start],re.I)))
                self.s.execute('INSERT INTO pseudonym_mappings(id,user_id,vault_id,entity_type,alias,is_self) VALUES (?,?,?,?,?,?)',(uid(),user_id,vault_id,ent.label,alias,is_self))
            if re.search(r'(?:my name is|call me|i am called|i.m called)\s+$',text[:ent.start],re.I):
                self.s.execute('UPDATE pseudonym_mappings SET is_self=1 WHERE user_id=? AND vault_id=?',(user_id,vault_id))
            replacements.append((ent.start,ent.end,alias,ent.label))
        # Only a single reconstruction pass; entity spans come from detection on raw input.
        out=[];previous=0
        for a,b,alias,kind in sorted(replacements):
            if a<previous:continue
            out.extend((text[previous:a],alias));previous=b
        out.append(text[previous:]);return ''.join(out),replacements
    def reveal(self,user_id,masked):
        rows=self.s.all('SELECT p.alias,p.vault_id FROM pseudonym_mappings p WHERE p.user_id=?',(user_id,))
        alias_map={r['alias']:r['vault_id'] for r in rows}
        if not alias_map:return masked
        # Single-pass with bounded alias alternatives, avoiding chained substitution.
        pattern=re.compile(r'(?<!\w)(?:'+'|'.join(re.escape(a) for a in sorted(alias_map,key=len,reverse=True))+r')(?!\w)')
        result=pattern.sub(lambda m:self.s.vault_read(user_id,alias_map[m.group(0)]),masked)
        self.s.audit(user_id,'reveal_originals','message');return result
    def self_name(self,user_id):
        row=self.s.one("SELECT vault_id FROM pseudonym_mappings WHERE user_id=? AND is_self=1 AND entity_type='PERSON' ORDER BY rowid DESC LIMIT 1",(user_id,))
        return self.s.vault_read(user_id,row['vault_id']) if row else None
    def stats(self,user_id):
        rows=self.s.all('SELECT entity_type,COUNT(*) n FROM pseudonym_mappings WHERE user_id=? GROUP BY entity_type',(user_id,))
        return {'total':sum(r['n'] for r in rows),'by_category':{r['entity_type']:r['n'] for r in rows},'settings':self.settings(user_id)}

class Memory:
    def __init__(self,store):self.s=store
    def enabled(self,user_id):
        row=self.s.one("SELECT value FROM user_preferences WHERE user_id=? AND key='memory_consent'",(user_id,))
        return row is None or row['value']=='true'
    def add(self,user_id,conversation_id,text,kind='fact',expires_at=None):
        if not self.enabled(user_id):return None
        key=hashlib.sha256(f'{kind}|{text.strip().casefold()}'.encode()).hexdigest()
        old=self.s.one('SELECT id FROM long_term_memory WHERE user_id=? AND normalized_key=?',(user_id,key))
        if old:return old['id']
        mid=uid();self.s.execute('INSERT INTO long_term_memory(id,user_id,conversation_id,kind,masked_text,normalized_key,expires_at) VALUES (?,?,?,?,?,?,?)',(mid,user_id,conversation_id,kind,text,key,expires_at))
        self.s.execute('INSERT INTO memory_embeddings(memory_id,user_id,vector) VALUES (?,?,?)',(mid,user_id,embedding(text).tobytes()))
        return mid
    def search(self,user_id,query,k=5,threshold=.19):
        qvec=embedding(query);qterms=set(re.findall(r'\w+',query.lower()))-{'it','the','a','i','to','me','you','my','for','can','about','that'}
        rows=self.s.all('SELECT m.*,e.vector FROM long_term_memory m JOIN memory_embeddings e ON m.id=e.memory_id WHERE m.user_id=? AND (m.expires_at IS NULL OR m.expires_at>?)',(user_id,iso(now())))
        results=[]
        for row in rows:
            vec=np.frombuffer(row['vector'],dtype=np.float32)
            sim=float(np.dot(qvec,vec)/(np.linalg.norm(qvec)*np.linalg.norm(vec)+1e-9))
            terms=set(re.findall(r'\w+',row['masked_text'].lower()));keyword=len(terms&qterms)/max(1,len(qterms))
            # Recency is too weak to resurrect unrelated memories.
            score=.72*sim+.27*keyword+.01
            if score>=threshold:results.append({'id':row['id'],'text':row['masked_text'],'kind':row['kind'],'score':round(score,3),'semantic':round(sim,3),'keyword':round(keyword,3)})
        return sorted(results,key=lambda x:-x['score'])[:k]
    def list(self,user_id):
        return [dict(r) for r in self.s.all('SELECT id,masked_text,kind,created_at,expires_at FROM long_term_memory WHERE user_id=? ORDER BY created_at DESC',(user_id,))]

class Assistant:
    def __init__(self,store,model_path=None):
        self.s=store;self.nlp=NLP();self.intent=IntentModel(model_path);self.auth=Auth(store);self.privacy=Privacy(store);self.memory=Memory(store);self.permission=PermissionEngine()
    def conversation(self,user_id,title='New conversation'):
        cid=uid();self.s.execute('INSERT INTO conversations(id,user_id,title) VALUES (?,?,?)',(cid,user_id,title));return cid
    def _conversation(self,user_id,cid):
        row=self.s.one('SELECT * FROM conversations WHERE id=? AND user_id=?',(cid,user_id))
        if not row:raise PermissionError('Conversation not found')
        return row
    def state(self,user_id,cid):
        self._conversation(user_id,cid)
        row=self.s.one('SELECT state_json FROM dialogue_states WHERE conversation_id=? AND user_id=?',(cid,user_id))
        return json.loads(row['state_json']) if row else {}
    def set_state(self,user_id,cid,state):
        self.s.execute('INSERT INTO dialogue_states(conversation_id,user_id,state_json) VALUES (?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP',(cid,user_id,json.dumps(state)))
    def tasks(self,user_id,status=None):
        return [dict(r) for r in self.s.all('SELECT id,title,kind,status,due_at,created_at FROM tasks WHERE user_id=? '+('AND status=? ' if status else '')+'ORDER BY due_at IS NULL,due_at,created_at',(user_id,status) if status else (user_id,))]
    def _task(self,user_id,id):
        row=self.s.one('SELECT * FROM tasks WHERE id=? AND user_id=?',(id,user_id))
        if not row:raise PermissionError('Task not found')
        return row
    def create_task(self,user_id,cid,title,kind='task',due=None):
        title=self.privacy.mask(user_id,self.nlp.validate(title),self.nlp.entities(title))[0]
        tid=uid();self.s.execute('INSERT INTO tasks(id,user_id,conversation_id,title,kind,due_at) VALUES (?,?,?,?,?,?)',(tid,user_id,cid,title,kind,due))
        if due:self.s.execute('INSERT INTO reminders(id,task_id,user_id,remind_at) VALUES (?,?,?,?)',(uid(),tid,user_id,due))
        self.s.audit(user_id,'task_created','task');return tid
    def update_task(self,user_id,id,**changes):
        self._task(user_id,id)
        for field,value in changes.items():
            if field not in ('title','status','due_at'):raise ValueError('Unsupported update field')
            if field=='title': value=self.privacy.mask(user_id,self.nlp.validate(value),self.nlp.entities(value))[0]
            self.s.execute(f'UPDATE tasks SET {field}=? WHERE id=? AND user_id=?',(value,id,user_id))
        if 'due_at' in changes:
            self.s.execute('DELETE FROM reminders WHERE task_id=? AND user_id=?',(id,user_id))
            if changes['due_at']:self.s.execute('INSERT INTO reminders(id,task_id,user_id,remind_at) VALUES (?,?,?,?)',(uid(),id,user_id,changes['due_at']))
        self.s.audit(user_id,'task_updated','task')
    def delete_task(self,user_id,id,confirmed=False):
        self.permission.authorize(user_id,user_id,'delete_task',confirmed)
        self._task(user_id,id);self.s.execute('DELETE FROM tasks WHERE id=? AND user_id=?',(id,user_id));self.s.audit(user_id,'task_deleted','task')
    def due(self,user_id):
        return [dict(r) for r in self.s.all("SELECT t.id,t.title,t.due_at FROM tasks t WHERE t.user_id=? AND t.status='open' AND t.due_at IS NOT NULL AND t.due_at<=? ORDER BY t.due_at",(user_id,iso(now())))]
    def history(self,user_id,cid,reveal=False):
        self._conversation(user_id,cid)
        rows=[dict(r) for r in self.s.all('SELECT id,role,masked_text,created_at FROM messages WHERE conversation_id=? AND user_id=? ORDER BY rowid',(cid,user_id))]
        if reveal:
            for row in rows:row['display_text']=self.privacy.reveal(user_id,row['masked_text'])
        return rows
    def _record(self,user_id,cid,role,text):
        mid=uid();self.s.execute('INSERT INTO messages(id,conversation_id,user_id,role,masked_text) VALUES (?,?,?,?,?)',(mid,cid,user_id,role,text));return mid
    def _last_task(self,user_id,state):
        tid=state.get('active_task')
        if tid:
            row=self.s.one('SELECT * FROM tasks WHERE id=? AND user_id=?',(tid,user_id))
            if row:return row
        return self.s.one('SELECT * FROM tasks WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(user_id,))
    def _task_title(self,text,kind):
        # Work only on masked text, preserving event names without generic instructions.
        out=re.sub(r'\b(?:remind me (?:to|about)|set a reminder (?:to|for)|i have|please|create a task to|add a task to)\b','',text,flags=re.I)
        out=re.sub(r'\b(?:tomorrow|today|next week|on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b','',out,flags=re.I)
        return ' '.join(out.split()).strip(' .,') or ('Meeting' if kind=='meeting' else 'Reminder')
    def chat(self,user_id,text,cid=None):
        started=time.perf_counter();text=self.nlp.validate(text)
        cid=cid or self.conversation(user_id)
        self._conversation(user_id,cid)
        entities=self.nlp.entities(text)
        masked,replacements=self.privacy.mask(user_id,text,entities)
        # Only masked text passes into NLP feature generation, embeddings, state and logs.
        intent=self.intent.predict(masked);temporal=self.nlp.temporal(masked);sentiment=self.nlp.sentiment(masked)
        state=self.state(user_id,cid);kind=intent['intent'];low=masked.lower();pending=state.get('pending');task=self._last_task(user_id,state)
        self._record(user_id,cid,'user',masked)
        if self.memory.enabled(user_id):
            self.s.execute('INSERT INTO short_term_memory(id,user_id,conversation_id,masked_text) VALUES (?,?,?,?)',(uid(),user_id,cid,masked))
        for a,b,alias,label in replacements:
            mid=self.s.one('SELECT id FROM messages WHERE conversation_id=? AND user_id=? ORDER BY rowid DESC LIMIT 1',(cid,user_id))['id']
            self.s.execute('INSERT INTO conversation_entities(id,message_id,user_id,entity_type,alias) VALUES (?,?,?,?,?)',(uid(),mid,user_id,label,alias))
        reply=None
        if sentiment['safety']:
            reply='I am sorry you are going through this. If you might harm yourself, contact local emergency services now and reach out to someone you trust. Are you safe right now?'
        elif pending and pending.get('type')=='delete':
            if re.fullmatch(r'\s*(yes|confirm|delete it|sure)\s*[.!]?\s*',low):
                target=pending['task_id'];self.delete_task(user_id,target,confirmed=True);state.pop('pending',None);state.pop('active_task',None);reply='The selected item has been deleted.'
            elif re.fullmatch(r'\s*(no|cancel|nevermind|never mind)\s*[.!]?\s*',low):state.pop('pending',None);reply='Deletion cancelled.'
            else:reply='Please answer yes or no to confirm deletion.'
        elif pending and pending.get('type')=='slots':
            due=temporal['due_at']
            if due and not temporal['past']:
                tid=self.create_task(user_id,cid,pending['title'],pending['kind'],due);state['active_task']=tid;state.pop('pending',None)
                reply=f"Saved {pending['kind']}: {pending['title']} for {due}. I'll show it inside the app when due."
            else:
                if temporal['date']:pending['date']=temporal['date']
                if temporal['time']:pending['time']=temporal['time']
                if pending.get('date') and pending.get('time'):
                    due=pending['date']+'T'+pending['time']+':00'
                    tid=self.create_task(user_id,cid,pending['title'],pending['kind'],due);state['active_task']=tid;state.pop('pending',None)
                    reply=f"Saved {pending['kind']}: {pending['title']} for {due}. I'll show it inside the app when due."
                else:reply='What date and time should I use?' if not pending.get('date') else 'What time? Please include AM or PM.'
        elif kind=='personal_information':
            name=self.privacy.self_name(user_id)
            reply=f'Your name is {name}.' if name else 'You have not told me your name yet.'
            # Name is intentionally displayed to owner but must not be persisted in plaintext.
            stored_reply='I retrieved your name securely from your encrypted identity vault.' if name else reply
        elif kind=='reminder_deletion':
            if task:state['pending']={'type':'delete','task_id':task['id']};reply=f"Delete {task['title']}? Reply yes or no."
            else:reply='I could not find a reminder or meeting to delete.'
        elif kind=='reminder_modification':
            if not task:reply='Which meeting or reminder would you like to change?'
            elif temporal['ambiguous']:reply='Did you mean AM or PM?'
            elif temporal['due_at'] and not temporal['past']:
                self.update_task(user_id,task['id'],due_at=temporal['due_at']);state['active_task']=task['id'];reply=f"Updated {task['title']} to {temporal['due_at']}."
            elif temporal['time'] and task['due_at']:
                day=task['due_at'][:10];due=day+'T'+temporal['time']+':00'
                self.update_task(user_id,task['id'],due_at=due);reply=f"Updated {task['title']} to {due}."
            else:reply='What new date and time should I use?'
        elif kind=='task_completion':
            if task:self.update_task(user_id,task['id'],status='completed');reply=f"Marked {task['title']} complete."
            else:reply='I could not find a task to complete.'
        elif kind=='schedule_management':
            entries=self.tasks(user_id,'open')[:8]
            reply='\n'.join(f"• {t['title']} ({t['due_at'] or 'no due date'})" for t in entries) if entries else 'No open tasks or reminders.'
        elif kind in ('reminder_creation','task_creation'):
            is_meeting='meeting' in low or 'appointment' in low
            task_kind='meeting' if is_meeting else ('task' if kind=='task_creation' else 'reminder')
            # A follow-up mentioning "that meeting" refers to the existing meeting, not a new one.
            if task and re.search(r'\b(?:that meeting|the meeting|that reminder)\b',low) and re.search(r'\bremind me\b',low):
                state['active_task']=task['id'];reply=f"Your {task['kind']} is {task['title']} at {task['due_at'] or 'an unspecified time'}. It is tracked in your reminders."
            elif temporal['ambiguous']:reply='Please specify AM or PM for that time.'
            elif temporal['past']:reply='That time is in the past. Please give a future date and time.'
            else:
                title=self._task_title(masked,task_kind);due=temporal['due_at']
                if task_kind!='task' and not due:
                    state['pending']={'type':'slots','title':title,'kind':task_kind,'date':temporal['date'],'time':temporal['time']}
                    reply='What time? Please include AM or PM.' if temporal['date'] else 'What date and time should I use?'
                else:
                    tid=self.create_task(user_id,cid,title,task_kind,due);state['active_task']=tid
                    reply=f"Saved {task_kind}: {title}"+(f' for {due}' if due else '')+'. Reminders appear inside this app.'
        elif kind=='introduction':
            if re.search(r'\b(?:preparing for|studying for)\b',low):
                self.memory.add(user_id,cid,masked,'preparation')
            if re.search(r'\b(?:meeting|appointment)\b',low):
                title=self._task_title(masked.split('meeting',1)[-1], 'meeting')
                title='Meeting '+title if title else 'Meeting'
                if temporal['due_at'] and not temporal['past']:
                    tid=self.create_task(user_id,cid,title,'meeting',temporal['due_at'])
                    state['active_task']=tid
                    reply=f"Nice to meet you. I saved your meeting: {title} for {temporal['due_at']}."
                else:
                    state['pending']={'type':'slots','title':title,'kind':'meeting','date':temporal['date'],'time':temporal['time']}
                    reply='Nice to meet you. What date and time is the meeting?'
            else:reply='Nice to meet you. I can remember your name securely for this account.'
        elif kind=='preference_declaration':
            self.memory.add(user_id,cid,masked,'preference');reply='I saved that preference to memory.' if self.memory.enabled(user_id) else 'Memory is disabled, so I did not save that preference.'
        elif kind=='emotional_expression':
            reply='That sounds difficult. Would you like to describe what is troubling you?' if sentiment['label']=='negative' else 'Thanks for sharing how you feel.'
        elif kind=='greeting':reply='Hello! You can tell me about plans, save reminders, or ask about previous conversations.'
        elif kind=='farewell':reply='Goodbye!'
        else:
            # Extract masked exam/interview facts into retrievable memory.
            if re.search(r'\b(?:preparing for|studying for|getting ready for)\b',low):
                self.memory.add(user_id,cid,masked,'preparation')
            elif re.search(r'\b(?:i have|i am|my)\b',low) and kind not in ('follow_up','unknown'):
                self.memory.add(user_id,cid,masked,'fact')
            if re.search(r'\b(?:that meeting|the meeting|about it)\b',low) and task:
                reply=f"The meeting is {task['title']} at {task['due_at'] or 'an unspecified time'}."
            else:
                matches=self.memory.search(user_id,masked)
                if re.search(r'\b(?:help me prepare for it|prepare for it)\b',low):
                    related=[m for m in self.memory.list(user_id) if m['kind']=='preparation']
                    reply=f"You previously said: {related[-1]['masked_text']}. We can make a study plan for that." if related else 'What would you like to prepare for?'
                elif matches and re.search(r'\b(?:remember|earlier|previous|what did i|what about)\b',low):
                    reply='Relevant memory: '+matches[0]['text']
                else:reply='I can help track your tasks and reminders, recall saved context, or analyse your message. What would you like to do?' if kind=='unknown' else 'Tell me what you would like to know or schedule.'
        state.update({'intent':kind,'topic':'meeting' if 'meeting' in low else state.get('topic'),'status':'active'})
        self.set_state(user_id,cid,state)
        if kind=='personal_information' and self.privacy.self_name(user_id):self._record(user_id,cid,'assistant',stored_reply)
        else:self._record(user_id,cid,'assistant',reply)
        elapsed=(time.perf_counter()-started)*1000
        self.s.execute('INSERT INTO analytics_events(id,user_id,event_type,duration_ms) VALUES (?,?,?,?)',(uid(),user_id,kind,elapsed))
        return {'conversation_id':cid,'reply':reply,'analysis':{'masked_text':masked,'entities':[{'type':e.label,'text':masked[a:b] if not replacements else next((alias for x,y,alias,typ in replacements if x==e.start and y==e.end),e.text) if e.label not in PII_KINDS else '***'} for a,b,e in [(x.start,x.end,x) for x in entities]],'intent':intent,'sentiment':sentiment,'temporal':temporal,'memory_matches':self.memory.search(user_id,masked)[:3]},'latency_ms':round(elapsed,2)}
    def analyze(self,user_id,text):
        text=self.nlp.validate(text);entities=self.nlp.entities(text)
        # Preview-only: no vault writes, use generic placeholders.
        masked=text
        for e in sorted([x for x in entities if x.label in PII_KINDS],key=lambda e:-e.start):masked=masked[:e.start]+f'[{e.label}]'+masked[e.end:]
        return {'masked_preview':masked,'tokens':self.nlp.tokenize(masked),'lemmas':self.nlp.lemmas(masked),'entities':[{'type':e.label,'text':'[MASKED]' if e.label in PII_KINDS else e.text} for e in entities],'temporal':self.nlp.temporal(masked),'sentiment':self.nlp.sentiment(masked),'intent':self.intent.predict(masked)}
