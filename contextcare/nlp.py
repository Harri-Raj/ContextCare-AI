"""Offline deterministic NLP with optional locally-installed statistical model."""
from __future__ import annotations
import re, difflib, calendar
from dataclasses import dataclass
from datetime import datetime,timedelta
from typing import Optional

@dataclass
class Entity:
    start:int; end:int; label:str; text:str; confidence:float=1.0

VOCAB={'tmrw':'tomorrow','tmr':'tomorrow','tomo':'tomorrow','pls':'please','plz':'please','remindr':'reminder','mtg':'meeting','2day':'today','prep':'prepare'}
MONTHS={name.lower():i for i,name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower():i for i,name in enumerate(calendar.month_abbr) if name})
PII_KINDS={'PERSON','EMAIL','PHONE','ADDRESS','ID'}
EMAIL=re.compile(r'(?<![\w.])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(?!\w)')
PHONE=re.compile(r'(?<!\w)(?:\+\d{1,3}[ -]?)?(?:\d[ -]?){10,12}(?!\w)')
ADDRESS=re.compile(r'\b\d{1,5}\s+(?:[A-Za-z][\w.-]*\s+){0,5}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Boulevard|Blvd)\b',re.I)
ID=re.compile(r'\b(?:ID|passport|aadhar|aadhaar|employee number)\s*(?:is|:|#)?\s*[A-Z0-9-]{5,20}\b',re.I)
SELF=re.compile(r"\b(?:my name is|i am called|i'm called|call me)\s+([A-Z][a-z]{2,}(?:\s+(?!and\b|with\b|for\b)[A-Z][a-z]{2,})?)",re.I)
WITH=re.compile(r'\b(?:with|meet|meeting with|talk to|called|ask)\s+([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?)')
EXAM=re.compile(r'\b(?:CAT|XAT|GMAT|GRE|NMAT|SNAP|UPSC|JEE|NEET)\b')
EVENT=re.compile(r'\b(?:meeting|appointment|interview|exam|call|class|birthday)\b',re.I)
MONEY=re.compile(r'(?:₹|\$|€)\s*\d[\d,]*(?:\.\d+)?')
DATE_WORDS=re.compile(r'\b(?:today|tomorrow|yesterday|next week|next (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|monday|tuesday|wednesday|thursday|friday|saturday|sunday|in \d+ (?:minutes?|hours?|days?)|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9})\b',re.I)
TIME_WORDS=re.compile(r'\b(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)|(?:[01]?\d|2[0-3]):[0-5]\d|noon|midnight|morning|afternoon|evening|night|at \d{1,2}(?!\s*(?:am|pm))\b)\b',re.I)

class NLP:
    def __init__(self):
        self.spacy=None
        try:
            import spacy
            self.spacy=spacy.load('en_core_web_sm')
        except (ImportError,OSError):pass
    def validate(self,text):
        if not isinstance(text,str) or not text.strip() or len(text)>5000:raise ValueError('Message must be 1-5000 characters')
        if '\x00' in text:raise ValueError('Invalid character')
        return re.sub(r'[\t\r ]+',' ',text.strip())
    def normalize(self,text):
        words=re.findall(r'\w+|[^\w\s]',text.lower())
        return ' '.join(VOCAB.get(w,w) for w in words)
    def tokenize(self,text):return re.findall(r"[\w']+|[^\w\s]",self.normalize(text))
    def lemmas(self,text):
        if self.spacy:return [t.lemma_ for t in self.spacy(self.normalize(text)) if not t.is_space]
        return [w[:-3] if len(w)>5 and w.endswith('ing') else w[:-1] if len(w)>4 and w.endswith('s') else w for w in self.tokenize(text)]
    def sentences(self,text):return [s.strip() for s in re.split(r'(?<=[.!?])\s+',text) if s.strip()]
    def entities(self,text):
        matches=[]
        def add(pattern,label,group=0,conf=1.0):
            for m in pattern.finditer(text):
                a,b=m.span(group);matches.append(Entity(a,b,label,text[a:b],conf))
        for pattern,label in ((EMAIL,'EMAIL'),(PHONE,'PHONE'),(ADDRESS,'ADDRESS'),(ID,'ID'),(EXAM,'EXAM'),(EVENT,'EVENT'),(MONEY,'MONEY'),(DATE_WORDS,'DATE'),(TIME_WORDS,'TIME')):add(pattern,label)
        add(SELF,'PERSON',1);add(WITH,'PERSON',1)
        if self.spacy:
            for ent in self.spacy(text).ents:
                label={'PERSON':'PERSON','GPE':'LOCATION','ORG':'ORGANIZATION','PRODUCT':'PRODUCT'}.get(ent.label_)
                if label:matches.append(Entity(ent.start_char,ent.end_char,label,ent.text,.75))
        # prefer specific and high-confidence spans; no PII may be overwritten by non-PII
        priority={'EMAIL':9,'PHONE':9,'ADDRESS':9,'ID':9,'PERSON':8,'EXAM':7,'TIME':6,'DATE':6,'EVENT':5}
        matches.sort(key=lambda e:(-priority.get(e.label,0),-e.confidence,-(e.end-e.start),e.start))
        chosen=[]
        for e in matches:
            if not any(e.start<c.end and c.start<e.end for c in chosen):chosen.append(e)
        return sorted(chosen,key=lambda e:e.start)
    def temporal(self,text,base=None):
        base=base or datetime.now().astimezone();lower=self.normalize(text)
        out={'date':None,'time':None,'due_at':None,'ambiguous':False,'past':False}
        if re.search(r'\btomorrow\b',lower):d=base.date()+timedelta(days=1)
        elif re.search(r'\btoday\b',lower):d=base.date()
        elif re.search(r'\bnext week\b',lower):d=base.date()+timedelta(days=7)
        else:
            d=None
            m=re.search(r'\b(?:next )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',lower)
            if m:
                day=list(calendar.day_name).index(m.group(1).capitalize());delta=(day-base.weekday())%7
                if delta==0 or lower[m.start():m.end()].startswith('next '):delta=delta or 7
                d=base.date()+timedelta(days=delta)
            m=re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\b',lower)
            if m and m.group(2) in MONTHS:
                try:
                    d=base.date().replace(month=MONTHS[m.group(2)],day=int(m.group(1)))
                    if d<base.date():d=d.replace(year=d.year+1)
                except ValueError:pass
        delta=re.search(r'\bin (\d+) (minute|hour|day)s?\b',lower)
        if delta:
            amount=int(delta.group(1));unit=delta.group(2)
            due=base+timedelta(**{unit+'s':amount});out.update(date=due.date().isoformat(),time=due.strftime('%H:%M'),due_at=due.isoformat(timespec='minutes'));return out
        time=None
        m=re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b',lower)
        if m:
            h=int(m.group(1))%12+(12 if m.group(3)=='pm' else 0);minute=int(m.group(2) or 0)
            if 1<=int(m.group(1))<=12 and minute<60:time=(h,minute)
        else:
            m=re.search(r'\b([01]?\d|2[0-3]):([0-5]\d)\b',lower)
            if m:time=(int(m.group(1)),int(m.group(2)))
            elif re.search(r'\bnoon\b',lower):time=(12,0)
            elif re.search(r'\bmidnight\b',lower):time=(0,0)
            elif re.search(r'\bat (\d{1,2})\b',lower):out['ambiguous']=True
        if d:out['date']=d.isoformat()
        if time:out['time']=f'{time[0]:02d}:{time[1]:02d}'
        if d and time:
            due=datetime.combine(d,datetime.min.time(),tzinfo=base.tzinfo).replace(hour=time[0],minute=time[1]);out['due_at']=due.isoformat(timespec='minutes');out['past']=due<base
        return out
    def sentiment(self,text):
        tokens=self.tokenize(text);pos={'happy','great','good','excited','love','thanks','thank','excellent'};neg={'sad','bad','worried','anxious','hate','terrible','upset','stressed','frustrated'}
        score=0
        for i,w in enumerate(tokens):
            val=int(w in pos)-int(w in neg)
            if 'not' in tokens[max(0,i-2):i]:val=-val
            score+=val
        t='positive' if score>0 else 'negative' if score<0 else 'neutral'
        lower=text.lower()
        return {'label':t,'score':score,'frustrated':bool(re.search('frustrat|annoy',lower)),'confused':bool(re.search('confus|don.t understand',lower)),'urgent':bool(re.search('urgent|asap|immediately',lower)),'safety':bool(re.search(r'\b(?:kill myself|end my life|suicide)\b',lower))}

class IntentModel:
    INTENTS=['greeting','farewell','introduction','general_information','question_answering','reminder_creation','reminder_modification','reminder_deletion','task_creation','task_completion','schedule_management','follow_up','preference_declaration','personal_information','emotional_expression','clarification_request','unknown']
    SEEDS={
      'greeting':['hi','hello','hey there','good morning','how are you'],
      'farewell':['goodbye','bye','see you later','good night'],
      'introduction':['my name is Alex','I am called Jordan','call me Sara'],
      'general_information':['explain photosynthesis','what is machine learning','tell me about science','how do computers work'],
      'question_answering':['what did I say earlier','can you answer my question','what was the appointment about'],
      'reminder_creation':['remind me to study tomorrow at 4 PM','set a reminder for my meeting','please remind me about that meeting','I have a meeting tomorrow at 4 PM','remember my appointment'],
      'reminder_modification':['change that to 7 PM','reschedule my reminder','move the meeting to tomorrow','update that reminder'],
      'reminder_deletion':['delete my reminder','cancel that meeting','remove the appointment','forget the reminder'],
      'task_creation':['add a task to write notes','create a new todo','I need to finish my assignment'],
      'task_completion':['mark the task done','I finished that task','complete my todo'],
      'schedule_management':['show my schedule','what meetings are coming','list my upcoming appointments'],
      'follow_up':['what about it','help me prepare for it','tell me more about that','what was that meeting'],
      'preference_declaration':['I prefer tea','I like studying at night','my favourite colour is blue'],
      'personal_information':['what is my name','do you know my name','who am I'],
      'emotional_expression':['I am feeling anxious','I feel happy today','I am upset','I feel confused'],
      'clarification_request':['what do you mean','please clarify','can you explain that again'],
      'unknown':['quantum banana orchestra','random unrelated words','xyz abc qwerty','???']}
    def __init__(self,model_path=None):
        self.model_path=model_path
        self.pipeline=None
        if model_path:
            try:
                import joblib,sklearn
                payload=joblib.load(model_path)
                if payload['sklearn']==sklearn.__version__:self.pipeline=payload['model']
            except (ImportError,FileNotFoundError,KeyError,ValueError,AttributeError):pass
    def predict(self,text):
        low=text.lower().strip()
        # High-precision transactional rules take priority over statistical general intent.
        rules=[('personal_information',r'\b(?:what is my name|who am i|do you know my name)\b'),('reminder_deletion',r'\b(?:delete|cancel|remove)\b.*\b(?:meeting|reminder|appointment)\b'),('reminder_modification',r'\b(?:change|reschedule|move|update)\b.*\b(?:that|meeting|reminder|appointment|to \d)\b'),('task_completion',r'\b(?:finished|complete|done)\b.*\b(?:task|todo|that)\b'),('schedule_management',r'\b(?:show|list|what)\b.*\b(?:schedule|meetings|reminders|tasks)\b'),('reminder_creation',r'\b(?:remind me|set a reminder|meeting|appointment)\b'),('task_creation',r'\b(?:add a task|create a task|new todo|need to finish)\b'),('introduction',r'\b(?:my name is|i am called|call me)\b'),('preference_declaration',r'\b(?:i prefer|i like|my favourite|my favorite)\b'),('emotional_expression',r'\b(?:i feel|i am feeling)\b'),('follow_up',r'\b(?:about it|prepare for it|that meeting|what about that)\b')]
        for label,pattern in rules:
            if re.search(pattern,low):return {'intent':label,'confidence':.98,'probabilities':{label:.98},'source':'precision_rule'}
        if self.pipeline:
            try:
                scores=self.pipeline.predict_proba([text])[0]
                ordered=sorted(zip(self.pipeline.classes_,scores),key=lambda p:-p[1]);top=ordered[0];runner=ordered[1]
                label=top[0] if top[1]>=.34 and top[1]-runner[1]>=.04 else 'unknown'
                return {'intent':label,'confidence':round(float(top[1]),3),'probabilities':{k:round(float(v),3) for k,v in ordered[:5]},'source':'tfidf_logreg'}
            except (ValueError,AttributeError):pass
        for label,examples in self.SEEDS.items():
            if any(low==x.lower() for x in examples):return {'intent':label,'confidence':.9,'probabilities':{label:.9},'source':'exact_seed'}
        return {'intent':'unknown','confidence':0.,'probabilities':{},'source':'abstain'}
