import pytest
from contextcare.core import Store
from contextcare.engine import Assistant

@pytest.fixture
def assistant(tmp_path):
    s=Store(tmp_path/'chat.db');a=Assistant(s);u=a.auth.register('userabc','password123');c=a.conversation(u)
    return s,a,u,c

def test_slot_filling_modify_delete(assistant):
    s,a,u,c=assistant
    first=a.chat(u,'I have a meeting tomorrow',c)
    assert 'What time' in first['reply']
    second=a.chat(u,'4 PM',c);assert 'Saved' in second['reply'];assert len(a.tasks(u))==1
    meeting=a.tasks(u)[0];assert meeting['due_at'].endswith('16:00') or meeting['due_at'].endswith('16:00:00')
    a.chat(u,'Change that to 7 PM',c);assert '19:00' in a.tasks(u)[0]['due_at']
    a.chat(u,'Delete that meeting',c);assert len(a.tasks(u))==1
    a.chat(u,'yes',c);assert not a.tasks(u)

def test_complete_task(assistant):
    s,a,u,c=assistant;a.chat(u,'Add a task to write notes',c)
    a.chat(u,'I finished that task',c)
    assert a.tasks(u)[0]['status']=='completed'

def test_memory_scoped_and_dedupe(assistant):
    s,a,u,c=assistant
    a.memory.add(u,c,'I am preparing for CAT','preparation')
    a.memory.add(u,c,'I am preparing for CAT','preparation')
    assert len(a.memory.list(u))==1
    assert a.memory.search(u,'preparing for CAT')
    u2=a.auth.register('newperson','password123')
    assert not a.memory.search(u2,'preparing for CAT')

def test_trishanth_full_story(assistant):
    s,a,u,c=assistant
    r=a.chat(u,'My name is Trishanth. I am preparing for my CAT exam, and I have a meeting with Rahul tomorrow at 4 PM.',c)
    assert 'Trishanth' not in r['analysis']['masked_text']
    assert 'Rahul' not in r['analysis']['masked_text']
    assert a.privacy.self_name(u)=='Trishanth'
    assert a.tasks(u),'Meeting should be created from compound utterance'
    follow=a.chat(u,'Remind me about that meeting',c)
    assert 'meeting' in follow['reply'].lower() and len(a.tasks(u))==1
    name=a.chat(u,'What is my name?',c)
    assert 'Trishanth' in name['reply']
    assert 'Trishanth' not in s.path.read_bytes().decode('latin1')
    assert 'Rahul' not in s.path.read_bytes().decode('latin1')
