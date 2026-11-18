"""QA-v2 engineering public rendering, never applied to frozen53."""
import re,collections
from step_six.common import norm,h
ATTRIBUTE_WORDS={'color':'color','cap_color':'cap color','lid_color':'lid color','material':'material','texture':'texture','shape':'shape'}
def noun(label):
 return re.sub(r'\b([A-Za-z_]+)\d+\b',r'\1',label).strip()
def render_p(q,objects):
 p=q['program'];scope=p['scope'];words={fid:noun(row['candidate_content']['label']) for (s,fid),row in objects.items() if s==scope};op=p['op']
 if op=='attribute':
  typ=p['type'];oid=p['object_id']
  if typ not in ATTRIBUTE_WORDS:return None,'UNSUPPORTED_PUBLIC_ATTRIBUTE'
  label=words.get(oid,'');value=norm(q['answer'])
  if value and value in norm(label):return None,'TARGET_ANSWER_IN_REFERENT'
  text=f'what is the {ATTRIBUTE_WORDS[typ]} of the {label}?';ids=[oid]
 elif op=='relation':
  a,b=p['subject_id'],p['object_id'];text=f'what spatial or contact relationship does the {words.get(a,"")} have with the {words.get(b,"")}? State the subject, relation, and object explicitly.';ids=[a,b]
 elif op=='identity':
  ls,li=p['left'].rsplit('/',1);rs,ri=p['right'].rsplit('/',1);left=objects.get((ls,li));right=objects.get((rs,ri))
  if not left or not right:return None,'IDENTITY_REFERENT_MISSING'
  ll=noun(left['candidate_content']['label']);rl=noun(right['candidate_content']['label'])
  for sc,lab in [(ls,ll),(rs,rl)]:
   if sum(s==sc and noun(row['candidate_content']['label'])==lab for (s,_),row in objects.items())!=1:return None,'NONUNIQUE_GRAPH_REFERENT'
  lt=left['source_keyframe']['time_sec'];rt=right['source_keyframe']['time_sec']
  if lt==rt:return None,'IDENTITY_REQUIRES_DIFFERENT_TIMES'
  return f'Is the {ll} at {lt:.3f} seconds the same physical object as the {rl} at {rt:.3f} seconds?',None
 else:return None,'UNSUPPORTED_PROGRAM_PUBLIC_RENDERER'
 for oid in ids:
  label=words.get(oid,'')
  if not label or label.lower() in ['object','thing','item','surface']:return None,'GENERIC_REFERENT'
  if list(words.values()).count(label)!=1:return None,'NONUNIQUE_GRAPH_REFERENT'
 time=q['metadata'].get('source_time')
 # Original public time is read from the frozen template; no boundary inferred.
 m=re.match(r'At ([0-9.]+) seconds,',q['question'])
 if not m:return None,'TIME_NOT_AVAILABLE'
 return f'At {m.group(1)} seconds, '+text,None

def s_public_check(q,a):
 if re.search(r'\b(?:[A-Za-z_]+\d+|o\d+|a\d+)\b',q):return 'INTERNAL_ID_IN_PUBLIC_TEXT'
 if re.search(r'\b(?:what is the attribute|what is the condition|throughout|entire video|consistently)\b',q,re.I):return 'UNDERSPECIFIED_ATTRIBUTE_OR_GLOBAL_ASSERTION'
 if 0<len(norm(a).split())<=4 and norm(a) not in ['yes','no'] and norm(a) in norm(q):return 'SHORT_ANSWER_IN_QUESTION'
 return None
