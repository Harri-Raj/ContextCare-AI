"""In-process Streamlit UI (no separate API daemon required)."""
import os,json,uuid
from pathlib import Path
import streamlit as st
from contextcare.core import Store,Auth,verify_password
from contextcare.engine import Assistant

st.set_page_config(page_title='ContextCare AI',page_icon='🛡️',layout='wide')
st.markdown('''<style>.stApp{background:#0b1220;color:#e9edf8}section[data-testid="stSidebar"]{background:#101c2e}.block-container{padding-top:1.8rem}h1,h2,h3{letter-spacing:-.025em}div[data-testid="stMetric"]{background:#17243a;border-radius:12px;padding:12px}</style>''',unsafe_allow_html=True)
@st.cache_resource
def get_service():
    return Assistant(Store(),model_path=str(Path(__file__).resolve().parent/'models/intent.joblib'))
a=get_service()
st.sidebar.title('🛡️ ContextCare AI')
st.sidebar.caption('Private • Offline-first • Context-aware')
if 'token' not in st.session_state:
    st.title('Welcome to ContextCare AI')
    mode=st.radio('Account',['Sign in','Create account'],horizontal=True)
    with st.form('auth'):
        username=st.text_input('Username');password=st.text_input('Password',type='password');submitted=st.form_submit_button('Continue',use_container_width=True)
    if submitted:
        try:
            if mode=='Create account':a.auth.register(username,password)
            st.session_state.token=a.auth.login(username,password);st.rerun()
        except (ValueError,PermissionError):st.error('Invalid credentials or account details.')
    st.stop()
try:user=a.auth.user(st.session_state.token)
except PermissionError:
    st.session_state.pop('token',None);st.error('Your session has expired. Sign in again.');st.stop()
user_id=user['id']
if st.sidebar.button('Sign out'):
    a.auth.logout(st.session_state.token);st.session_state.pop('token',None);st.rerun()
page=st.sidebar.radio('Navigation',['Dashboard','AI Chat','Conversation History','Semantic Memory Search','Tasks & Reminders','Privacy Dashboard','NLP Analysis','Settings','System Monitoring','About'])
if page=='Dashboard':
    st.title('Your daily overview')
    stats=a.privacy.stats(user_id);tasks=a.tasks(user_id)
    cols=st.columns(3);cols[0].metric('Tracked tasks',len(tasks));cols[1].metric('Protected identities',stats['total']);cols[2].metric('Saved memories',len(a.memory.list(user_id)))
    due=a.due(user_id)
    if due:
        st.warning(f'{len(due)} reminders due inside the app')
        for item in due:st.write(item['title'],item['due_at'])
    else:st.info('No overdue reminders. This app does not send device push notifications.')
elif page=='AI Chat':
    st.title('Context-aware chat')
    cs=a.s.all('SELECT id,title FROM conversations WHERE user_id=? ORDER BY rowid DESC',(user_id,))
    options={'New conversation':None,**{f"{r['title']} · {r['id'][:7]}":r['id'] for r in cs}}
    chosen=st.selectbox('Conversation',list(options));cid=options[chosen]
    if cid:
        for msg in a.history(user_id,cid):
            with st.chat_message(msg['role']):st.write(msg['masked_text'])
    prompt=st.chat_input('Tell me a plan, set a reminder, or ask about a meeting')
    if prompt:
        try:
            with st.spinner('Understanding context…'):res=a.chat(user_id,prompt,cid)
            st.session_state.latest_analysis=res['analysis'];st.session_state.latest_reply=res['reply'];st.rerun()
        except (ValueError,PermissionError):st.error('Unable to process that message.')
    if st.session_state.get('latest_reply'):
        st.success(st.session_state.pop('latest_reply'))
    if st.session_state.get('latest_analysis'):
        with st.expander('Last response: NLP analysis'):st.json(st.session_state['latest_analysis'])
elif page=='Conversation History':
    st.title('Conversation history')
    reveal=st.toggle('Reveal originals (audited)',value=False)
    if reveal:
        password=st.text_input('Re-enter password to reveal',type='password')
        reveal=bool(password and verify_password(password,user['password_hash']))
        if not reveal:st.info('Password verification required.')
    query=st.text_input('Search masked messages')
    cs=a.s.all('SELECT id,title FROM conversations WHERE user_id=? ORDER BY rowid DESC',(user_id,))
    for c in cs:
        with st.expander(f"{c['title']} · {c['id'][:8]}"):
            for m in a.history(user_id,c['id'],reveal=reveal):
                shown=m.get('display_text',m['masked_text'])
                if query.lower() in shown.lower():st.write(f"**{m['role']}**: {shown}")
            if st.button('Delete conversation',key='del'+c['id']):
                a.s.execute('DELETE FROM conversations WHERE id=? AND user_id=?',(c['id'],user_id));st.rerun()
elif page=='Semantic Memory Search':
    st.title('Semantic memory search')
    query=st.text_input('Search by meaning, e.g. exam preparation')
    if query:
        for m in a.memory.search(user_id,query):
            st.write(f"**{m['score']:.2f}** · {m['text']}")
            st.caption(f"Semantic: {m['semantic']:.2f}; keyword: {m['keyword']:.2f}")
    for m in a.memory.list(user_id):
        with st.expander(m['masked_text'][:110]):
            st.write(m['kind'],m['created_at'])
            if st.button('Delete memory',key=m['id']):a.s.execute('DELETE FROM long_term_memory WHERE id=? AND user_id=?',(m['id'],user_id));st.rerun()
elif page=='Tasks & Reminders':
    st.title('Tasks & reminders')
    with st.form('addtask'):
        title=st.text_input('Task title');kind=st.selectbox('Type',['task','meeting','reminder']);date=st.date_input('Due date',value=None);timeval=st.time_input('Time');submit=st.form_submit_button('Add task')
        if submit and title.strip():
            due=f'{date.isoformat()}T{timeval.strftime("%H:%M")}:00' if date else None
            a.create_task(user_id,None,title.strip(),kind,due);st.rerun()
    for t in a.tasks(user_id):
        c=st.columns([5,2,1,1]);c[0].write(f"{t['title']} · {t['due_at'] or 'unscheduled'}");c[1].write(t['status'])
        if c[2].button('Done',key='done'+t['id']):a.update_task(user_id,t['id'],status='completed');st.rerun()
        if c[3].button('Delete',key='delete'+t['id']):a.delete_task(user_id,t['id'],confirmed=True);st.rerun()
elif page=='Privacy Dashboard':
    st.title('Privacy dashboard')
    stats=a.privacy.stats(user_id);st.metric('Encrypted identity records',stats['total']);st.json(stats['by_category'])
    st.caption('Only aliases appear below. Original names are encrypted in the identity vault.')
    st.dataframe([dict(r) for r in a.s.all('SELECT entity_type,alias,is_self FROM pseudonym_mappings WHERE user_id=?',(user_id,))],use_container_width=True)
    st.subheader('Account data export')
    pwd=st.text_input('Account password',type='password',key='exportpwd')
    if pwd and verify_password(pwd,user['password_hash']):
        data={'messages':[dict(r) for r in a.s.all('SELECT role,masked_text FROM messages WHERE user_id=?',(user_id,))],'tasks':a.tasks(user_id),'memories':a.memory.list(user_id)}
        st.download_button('Export masked JSON',data=json.dumps(data,indent=2),file_name='contextcare_export.json')
    st.subheader('Security activity')
    st.dataframe([dict(r) for r in a.s.all('SELECT action,resource_type,created_at FROM audit_logs WHERE user_id=? ORDER BY rowid DESC LIMIT 30',(user_id,))],use_container_width=True)
elif page=='NLP Analysis':
    st.title('NLP analysis (preview only)')
    text=st.text_area('Test a sentence without storing it')
    if st.button('Analyse') and text.strip():
        try:st.json(a.analyze(user_id,text))
        except ValueError:st.error('Invalid input.')
elif page=='Settings':
    st.title('Settings')
    for key,label in [('memory_consent','Save conversational memory'),('mask_person','Mask personal names')]:
        row=a.s.one('SELECT value FROM user_preferences WHERE user_id=? AND key=?',(user_id,key))
        original=row is None or row['value']=='true'
        new=st.toggle(label,value=original,key=key)
        if new!=original:a.s.execute('INSERT INTO user_preferences(user_id,key,value) VALUES (?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value',(user_id,key,str(new).lower()));st.rerun()
    st.caption('Email, telephone, postal address and ID masking cannot be disabled. Memory disabling stops new saves; delete existing memories manually.')
elif page=='System Monitoring':
    st.title('System monitoring')
    events=a.s.all('SELECT event_type,COUNT(*) n,ROUND(AVG(duration_ms),2) ms FROM analytics_events WHERE user_id=? GROUP BY event_type',(user_id,))
    st.dataframe([dict(r) for r in events],use_container_width=True)
    st.write('NLP model:', 'TF-IDF + Logistic Regression' if a.intent.pipeline else 'Rule / seed fallback')
    st.write('spaCy model:',bool(a.nlp.spacy));st.write('Vector retrieval: 256-dimensional hashing + cosine')
elif page=='About':
    st.title('About ContextCare AI')
    st.write('A local-first final-year computational linguistics project with structured memory, rule-based entities and heuristics, a trained statistical intent classifier, encrypted identity storage and a persistent reminder engine.')
    st.warning('Privacy is pseudonymisation, not irreversible anonymisation. Optional neural embeddings and coreference models are not bundled. Reminders appear in this app only.')
    st.markdown('See `docs/ARCHITECTURE.md`, `docs/PRIVACY.md` and `docs/LIMITATIONS.md` for technical details.')
