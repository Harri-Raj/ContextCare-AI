from datetime import datetime,timezone
from contextcare.nlp import NLP,IntentModel

def test_entities():
    ents=NLP().entities('My name is Trishanth. I have a meeting with Rahul tomorrow at 4 PM for CAT.')
    found={(e.text,e.label) for e in ents}
    for pair in [('Trishanth','PERSON'),('Rahul','PERSON'),('CAT','EXAM'),('tomorrow','DATE'),('4 PM','TIME')]:assert pair in found,found

def test_temporal():
    n=NLP();base=datetime(2026,11,15,13,0,tzinfo=timezone.utc)
    t=n.temporal('meeting tomorrow at 4 PM',base)
    assert t['date']=='2026-11-16' and t['time']=='16:00' and not t['past']
    assert n.temporal('at 6',base)['ambiguous']
    assert n.temporal('in 2 hours',base)['due_at'] is not None
    assert n.temporal('tmrw at noon',base)['time']=='12:00'

def test_sentiment_negation():
    n=NLP();assert n.sentiment('I am not happy')['label']=='negative'
    assert n.sentiment('I feel frustrated')['frustrated']

def test_intent():
    assert IntentModel().predict('What is my name?')['intent']=='personal_information'
    assert IntentModel().predict('Remind me about that meeting')['intent']=='reminder_creation'
