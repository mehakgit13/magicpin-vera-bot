from fastapi.testclient import TestClient
from app.main import app, contexts, conversations, sent_suppression

client = TestClient(app)


def reset():
    for s in contexts:
        contexts[s].clear()
    conversations.clear()
    sent_suppression.clear()


def push(scope, cid, payload, version=1):
    r = client.post('/v1/context', json={'scope': scope, 'context_id': cid, 'version': version, 'payload': payload})
    assert r.status_code == 200


def test_full_flow_and_versioning():
    reset()
    category = {
        'slug': 'dentists',
        'voice': {'tone': 'peer_clinical'},
        'peer_stats': {'avg_ctr': 0.03},
        'digest': [{'id': 'd1', 'title': 'Recall update cuts recurrence', 'source': 'JIDA p.14', 'patient_segment': 'high_risk_adults'}],
        'seasonal_beats': [],
    }
    merchant = {
        'merchant_id': 'm1', 'category_slug': 'dentists',
        'identity': {'name': "Dr. Test Dental", 'owner_first_name': 'Test', 'locality': 'Delhi'},
        'offers': [{'title': 'Dental Cleaning @ ₹299', 'status': 'active'}],
        'customer_aggregate': {'high_risk_adult_count': 12},
    }
    trigger = {
        'id': 't1', 'scope': 'merchant', 'kind': 'research_digest', 'source': 'external',
        'merchant_id': 'm1', 'customer_id': None,
        'payload': {'top_item_id': 'd1'}, 'urgency': 2, 'suppression_key': 's1'
    }
    push('category', 'dentists', category)
    push('merchant', 'm1', merchant)
    push('trigger', 't1', trigger)
    stale = client.post('/v1/context', json={'scope':'merchant','context_id':'m1','version':0,'payload':merchant})
    assert stale.status_code == 409
    tick = client.post('/v1/tick', json={'now':'2026-09-25T10:00:00Z','available_triggers':['t1']})
    assert tick.status_code == 200
    action = tick.json()['actions'][0]
    assert action['conversation_id']
    assert 'JIDA p.14' in action['body']
    assert action['cta'] == 'open_ended'
    again = client.post('/v1/tick', json={'now':'2026-09-25T10:05:00Z','available_triggers':['t1']})
    assert again.json()['actions'] == []
    reply = client.post('/v1/reply', json={
        'conversation_id': action['conversation_id'], 'merchant_id':'m1', 'from_role':'merchant',
        'message':'Yes, send it', 'turn_number':2
    })
    assert reply.status_code == 200 and reply.json()['action'] == 'send'


def test_customer_consent_and_reply():
    reset()
    push('category','gyms',{'slug':'gyms','offer_catalog':[],'seasonal_beats':[]})
    push('merchant','m2',{'merchant_id':'m2','category_slug':'gyms','identity':{'name':'Test Gym','owner_first_name':'Karan'},'offers':[{'title':'3 FREE Trial Classes','status':'active'}]})
    push('customer','c2',{'customer_id':'c2','merchant_id':'m2','identity':{'name':'Riya','language_pref':'en'},'preferences':{'reminder_opt_in':True},'consent':{'scope':['promotional_offers']}})
    push('trigger','t2',{'id':'t2','scope':'customer','kind':'customer_lapsed_hard','merchant_id':'m2','customer_id':'c2','payload':{'days_since_last_visit':57,'previous_focus':'weight loss'},'suppression_key':'s2'})
    r=client.post('/v1/tick',json={'now':'2026-09-25T10:00:00Z','available_triggers':['t2']})
    assert r.status_code==200
    assert r.json()['actions'][0]['send_as']=='merchant_on_behalf'
