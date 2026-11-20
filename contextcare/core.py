"""Database, authentication and authenticated encrypted identity storage."""
from __future__ import annotations
import os, re, hmac, hashlib, secrets, sqlite3, uuid, json, logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc

def now(): return datetime.now(UTC)
def iso(dt): return dt.isoformat(timespec='seconds')
def uid(): return uuid.uuid4().hex

class RedactFilter(logging.Filter):
    def filter(self, record):
        # Do not inspect/log arbitrary exception objects, request bodies or raw messages.
        record.msg = 'event_suppressed' if not isinstance(record.msg,str) or not re.fullmatch(r'[a-z_]{2,50}',record.msg) else record.msg
        record.args = (); record.exc_info = None; record.stack_info = None
        return True

logger=logging.getLogger('contextcare'); logger.addFilter(RedactFilter())

class Store:
    def __init__(self, path=None, key_path=None, key=None):
        self.path=Path(path or os.environ.get('CONTEXTCARE_DB', str(ROOT/'data/contextcare.db')))
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON'); self.db.execute('PRAGMA busy_timeout=5000')
        migration=(ROOT/'migrations/001_init.sql').read_text(encoding='utf8')
        self.db.executescript(migration)
        self.db.execute('INSERT OR IGNORE INTO schema_migrations(version) VALUES (1)'); self.db.commit()
        self.key_path=Path(key_path or self.path.with_suffix('.key'))
        envkey=os.environ.get('CONTEXTCARE_MASTER_KEY_HEX')
        if key is not None: self.key=key
        elif envkey:
            self.key=bytes.fromhex(envkey)
        elif self.key_path.exists(): self.key=self.key_path.read_bytes()
        else:
            if self.db.execute('SELECT COUNT(*) FROM identity_vault').fetchone()[0]:
                raise RuntimeError('Vault key missing: refusing to regenerate existing identity key')
            self.key=AESGCM.generate_key(bit_length=256)
            self.key_path.write_bytes(self.key)
            try: os.chmod(self.key_path,0o600)
            except OSError: pass
        if len(self.key)!=32: raise ValueError('AES-256 key must be exactly 32 bytes')

    def execute(self,sql,args=()):
        cursor=self.db.execute(sql,args);self.db.commit();return cursor
    def one(self,sql,args=()): return self.db.execute(sql,args).fetchone()
    def all(self,sql,args=()):return self.db.execute(sql,args).fetchall()
    def audit(self,user_id,action,resource_type=''):
        self.execute('INSERT INTO audit_logs(id,user_id,action,resource_type) VALUES (?,?,?,?)',(uid(),user_id,action,resource_type))
    def blind(self,user_id,kind,value,key=None):
        return hmac.new(key or self.key,f'{user_id}:{kind}:{value.casefold()}'.encode(),hashlib.sha256).hexdigest()
    def vault_add(self,user_id,kind,value):
        blind=self.blind(user_id,kind,value)
        found=self.one('SELECT id FROM identity_vault WHERE user_id=? AND entity_type=? AND blind_index=?',(user_id,kind,blind))
        if found:return found['id']
        v_id=uid();nonce=os.urandom(12)
        ct=AESGCM(self.key).encrypt(nonce,value.encode(),f'{user_id}:{kind}'.encode())
        self.execute('INSERT INTO identity_vault(id,user_id,entity_type,nonce,ciphertext,blind_index) VALUES (?,?,?,?,?,?)',(v_id,user_id,kind,nonce,ct,blind))
        return v_id
    def vault_read(self,user_id,vault_id):
        row=self.one('SELECT * FROM identity_vault WHERE id=? AND user_id=?',(vault_id,user_id))
        if not row:raise PermissionError('Vault record inaccessible')
        return AESGCM(self.key).decrypt(row['nonce'],row['ciphertext'],f"{user_id}:{row['entity_type']}".encode()).decode()
    def rotate_key(self,new_key):
        if len(new_key)!=32:raise ValueError('Invalid key length')
        rows=self.all('SELECT * FROM identity_vault')
        decrypted=[(r,self.vault_read(r['user_id'],r['id'])) for r in rows]
        with self.db:
            for row,original in decrypted:
                nonce=os.urandom(12)
                ct=AESGCM(new_key).encrypt(nonce,original.encode(),f"{row['user_id']}:{row['entity_type']}".encode())
                blind=self.blind(row['user_id'],row['entity_type'],original,key=new_key)
                self.db.execute('UPDATE identity_vault SET nonce=?,ciphertext=?,blind_index=? WHERE id=?',(nonce,ct,blind,row['id']))
        self.key=new_key
        if not os.environ.get('CONTEXTCARE_MASTER_KEY_HEX') and self.key_path:
            self.key_path.write_bytes(new_key)
    def close(self):self.db.close()

def hash_password(password,salt=None):
    if len(password)<8:raise ValueError('Password must have at least 8 characters')
    salt=salt or os.urandom(16)
    return f'{salt.hex()}:{hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1).hex()}'
def verify_password(password,encoded):
    try:
        salt_hex,digest=encoded.split(':')
        check=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt_hex),n=2**14,r=8,p=1)
        return hmac.compare_digest(check,bytes.fromhex(digest))
    except (ValueError,TypeError):return False

class Auth:
    def __init__(self,store):self.s=store
    def register(self,username,password):
        if not re.fullmatch(r'[a-zA-Z0-9_]{3,40}',username):raise ValueError('Username must be 3-40 letters, numbers or underscores')
        user_id=uid()
        try:self.s.execute('INSERT INTO users(id,username,password_hash) VALUES (?,?,?)',(user_id,username,hash_password(password)))
        except sqlite3.IntegrityError:raise ValueError('Username unavailable') from None
        self.s.audit(user_id,'register');return user_id
    def login(self,username,password):
        row=self.s.one('SELECT * FROM users WHERE username=?',(username,))
        if row and row['locked_until'] and datetime.fromisoformat(row['locked_until'])>now():raise PermissionError('Login temporarily locked')
        if not row or not verify_password(password,row['password_hash']):
            if row:
                attempts=row['failed_logins']+1
                locked=iso(now()+timedelta(minutes=15)) if attempts>=5 else None
                self.s.execute('UPDATE users SET failed_logins=?,locked_until=? WHERE id=?',(attempts,locked,row['id']))
            raise PermissionError('Invalid credentials')
        self.s.execute('UPDATE users SET failed_logins=0,locked_until=NULL WHERE id=?',(row['id'],))
        raw=secrets.token_urlsafe(36)
        self.s.execute('INSERT INTO auth_sessions(id,user_id,token_hash,expires_at) VALUES (?,?,?,?)',(uid(),row['id'],hashlib.sha256(raw.encode()).hexdigest(),iso(now()+timedelta(days=7))))
        self.s.audit(row['id'],'login');return raw
    def user(self,token):
        if not token:raise PermissionError('Authentication required')
        h=hashlib.sha256(token.encode()).hexdigest()
        row=self.s.one('SELECT u.* FROM auth_sessions a JOIN users u ON a.user_id=u.id WHERE a.token_hash=? AND a.revoked=0 AND a.expires_at>?',(h,iso(now())))
        if not row:raise PermissionError('Invalid or expired session')
        return row
    def logout(self,token):
        user=self.user(token)
        self.s.execute('UPDATE auth_sessions SET revoked=1 WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
        self.s.audit(user['id'],'logout')

class PermissionEngine:
    SENSITIVE={'delete_account','export_originals','reveal_originals','delete_task','delete_memory','rotate_key'}
    def authorize(self,actor_id,owner_id,action,confirmed=False,actor_role='user'):
        if actor_id!=owner_id and actor_role!='admin':raise PermissionError('Cross-user access denied')
        if action in self.SENSITIVE and not confirmed:raise PermissionError('Explicit confirmation required')
        return True
