import pytest,os,sqlite3
from pathlib import Path
from cryptography.exceptions import InvalidTag
from contextcare.core import Store,Auth,PermissionEngine
from contextcare.engine import Assistant

@pytest.fixture
def context(tmp_path):
    s=Store(tmp_path/'test.db');a=Assistant(s);u=a.auth.register('testuser','password123');return s,a,u

def test_auth_lockout_and_sessions(context):
    s,a,u=context
    for _ in range(5):
        with pytest.raises(PermissionError):a.auth.login('testuser','wrongpassword')
    with pytest.raises(PermissionError):a.auth.login('testuser','password123')

def test_encryption_wrong_key_tamper_rotation(context):
    s,a,u=context;v=s.vault_add(u,'PERSON','Trishanth');assert s.vault_read(u,v)=='Trishanth'
    wrong=Store(s.path,key_path=s.key_path,key=os.urandom(32))
    with pytest.raises(InvalidTag):wrong.vault_read(u,v)
    new=os.urandom(32);s.rotate_key(new);assert s.vault_read(u,v)=='Trishanth'
    s.execute('UPDATE identity_vault SET ciphertext=? WHERE id=?',(b'bad ciphertext',v))
    with pytest.raises(InvalidTag):s.vault_read(u,v)

def test_vault_missing_key_refuses_regeneration(context):
    s,a,u=context;s.vault_add(u,'PERSON','Trishanth');s.close();s.key_path.unlink()
    with pytest.raises(RuntimeError,match='refusing'):Store(s.path)

def test_scoped_alias_and_no_pii_in_db(context):
    s,a,u=context;c=a.conversation(u)
    result=a.chat(u,'My name is Trishanth and I have a meeting with Rahul tomorrow at 4 PM.',c)
    assert 'Trishanth' not in result['analysis']['masked_text'];assert 'Rahul' not in result['analysis']['masked_text']
    assert 'Trishanth' not in s.path.read_bytes().decode('latin1')
    assert 'Rahul' not in s.path.read_bytes().decode('latin1')
    assert a.privacy.self_name(u)=='Trishanth'
    user2=a.auth.register('another','password123');assert a.privacy.self_name(user2) is None
    with pytest.raises(PermissionError):a.history(user2,c)

def test_alias_reuse_and_bijection(context):
    s,a,u=context;c=a.conversation(u)
    a.chat(u,'My name is Trishanth.',c);a.chat(u,'My name is Trishanth.',c)
    rows=s.all("SELECT alias FROM pseudonym_mappings WHERE user_id=? AND entity_type='PERSON'",(u,))
    assert len(rows)==1
    assert a.privacy.reveal(u,'My name is '+rows[0]['alias'])=='My name is Trishanth'

def test_delete_confirmation(context):
    s,a,u=context;c=a.conversation(u);tid=a.create_task(u,c,'Study CAT')
    with pytest.raises(PermissionError):a.delete_task(u,tid)
    assert a._task(u,tid)
    a.delete_task(u,tid,confirmed=True)
    with pytest.raises(PermissionError):a._task(u,tid)
