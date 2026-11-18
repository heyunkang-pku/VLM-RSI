"""Deterministic V0 probability sample and offline human labels; no answers filled."""
import csv,json,hashlib,random,shutil,subprocess,concurrent.futures
from pathlib import Path
BASE=Path('/Users/kcnthunderup/.local/share/openresearch/files/vlm-rsi')
V0=BASE/'step_native_next_20261031';PRIVATE=BASE/'step_next_actions_20261101';PUBLIC=BASE/'step_human_review_v0_20261101';SEED=2026110101
FIELDS=['review_id','reviewer_id','verdict','referent_clear','object_exists','category_correct','referent_correct','same_instance','action_supported','description_too_strong','affected_object_clear','intermediate_evidence','evidence_start','evidence_end','error_type','notes','annotation_version','revision_reason']
def load(p):return json.loads(p.read_text())
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def dumpcsv(p,rows,fields):
 with p.open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def main():
 rng=random.Random(SEED);ridrng=random.Random(SEED+1);PUBLIC.mkdir(exist_ok=True);PRIVATE.mkdir(exist_ok=True)
 for x in ['images','clips']: (PUBLIC/x).mkdir(exist_ok=True)
 rows=[json.loads(x) for x in (V0/'NATIVE_VERIFICATION_LEDGER.jsonl').read_text().splitlines()];samples=[];strata=[]
 def draw(pool,n,layer,bytype=False):
  grouped={}
  for x in pool:grouped.setdefault((x['fact_type'] if bytype else '')+'|'+x['scope'].split('/')[0],[]).append(x)
  quotas={k:0 for k in grouped};remaining=n
  while remaining and any(quotas[k]<len(grouped[k]) for k in grouped):
   for k in sorted(grouped):
    if remaining and quotas[k]<len(grouped[k]):quotas[k]+=1;remaining-=1
  for k in sorted(grouped):
   ss=sorted(grouped[k],key=lambda x:(x['scope'],x['fact_id']));take=quotas[k];strata.append({'layer':layer,'stratum':k,'N':len(ss),'n':take,'pi':take/len(ss),'selection':'SRS without replacement within predetermined video/type strata; balanced quota roundrobin fixed lexical order'})
   for x in rng.sample(ss,take):samples.append((x,layer,take/len(ss),len(ss),take))
 for typ,n in [('object',20),('attribute',20),('relation',16)]:draw([x for x in rows if x['fact_type']==typ and x['state']=='ACCEPTED'],n,'accepted_'+typ)
 # Fixed four per fact type in each rejected super-layer, then balanced video SRS.
 for label,states in [('rejected_low_frequency',{'VISUAL_REJECTED','FREQUENCY_REJECTED'}),('alignment_parent',{'UNRESOLVED_ALIGNMENT','BLOCKED_PARENT'})]:
  for typ in ['object','attribute','relation']:draw([x for x in rows if x['fact_type']==typ and x['state'] in states],4,label+'_'+typ)
 assert len(samples)==80
 known=[('video_7793/src_000854',x) for x in ['o000','o001','o002','o003','o005','o009']]+[('video_516/src_000366','o002'),('video_369/src_000643','o003')]
 selected={(x['scope'],x['fact_id']) for x,*_ in samples};known_links=[]
 for scope,fid in known:
  if (scope,fid) not in selected:samples.append((next(x for x in rows if x['scope']==scope and x['fact_id']==fid),'known_extra',None,None,None))
  else:known_links.append({'scope':scope,'fact_id':fid,'already_random_sample':True})
 tasks={}
 for p in (V0/'raw/frozen_inputs').glob('*.json'):
  j=load(p)
  for t in j.get('all_tasks',[j] if 'scope' in j else []):tasks[t['scope']]=t
 aliases={'video_369':'video_A','video_516':'video_B','video_7793':'video_C'};durations={'video_A':27.691,'video_B':18.88,'video_C':34.411};jobs={};key={};items=[]
 def ident():return 'r_'+f'{ridrng.getrandbits(56):014x}'
 def media(scope,start,end,target=None):
  v=scope.split('/')[0];alias=aliases[v];lo=max(0,start-1);hi=min(durations[alias],end+1);tag=hashlib.sha256((alias+f':{lo:.8f}:{hi:.8f}').encode()).hexdigest()[:14];clip='clips/'+tag+'.mp4';jobs[tag]=(PUBLIC/'videos'/(alias+'.mp4'),PUBLIC/clip,lo,hi);return {'video':alias,'target_start':start,'target_end':end,'clip_start':lo,'clip_end':hi,'clip':clip,'full_video':'videos/'+alias+'.mp4'}
 for x,layer,pi,N,n in samples:
  rid=ident();scope=x['scope'];m=tasks[scope]['media'];t=m['calibration_view']['time_sec'];typ=x['fact_type'];graph=load(V0/'graphs'/(scope.replace('/','_')+'_candidate.json'));objs={o['id']:o['referent'] for o in graph['object_nodes']};c=x['candidate_content']
  if typ=='object':claim=c['referent'];referents=[c['referent']]
  elif typ=='attribute':referents=[objs[x['parent_ids'][0]]];claim=referents[0]+'；属性 '+c['type']+' = '+c['value']
  else:referents=[objs[c['subject_id']],objs[c['object_id']]];claim=referents[0]+'；关系 '+c['predicate']+'；另一端 '+referents[1]
  im='images/'+rid+'.png';shutil.copyfile(V0/'inputs'/(m['calibration_view']['sha256']+'.png'),PUBLIC/im)
  items.append({'review_id':rid,'kind':typ,'claim':claim,'referents':referents,'image':im,'section':'facts' if layer!='known_extra' else 'known','context':media(scope,t,t)})
  key[rid]={'version':'V0','fact_key':scope+'/'+x['fact_id']+'/V0','scope':scope,'fact_id':x['fact_id'],'fact_type':typ,'layer':layer,'pi':pi,'N':N,'n':n,'system_record':x,'human_truth':None}
 pairs=load(V0/'TEMPORAL_LEDGER.json');g=load(V0/'graphs/STSG_partial.json');nodes=g['source_nodes'];requestmap={p.stem:p for p in (V0/'requests').glob('*.json')}
 for pair in pairs:
  for e in pair.get('results',[]):
   if e['state'] not in ['STATIC_MERGED','MOTION_EXTRACTED_NOT_INDEPENDENTLY_VALIDATED','REFERENCE_CREATED']:continue
   rid=ident();l=nodes[e['left']];r=nodes[e['right']];t1=l['source_frame']['time_sec'];t2=r['source_frame']['time_sec'];kind='motion' if e['state'].startswith('MOTION') else 'identity';claim='这两个时间点的指代对象是否为同一物理实例？';refs=[l['object']['referent'],r['object']['referent']]
   if kind=='motion':
    narrative=load(requestmap[e['source_request_ids'][0]])['raw_response'];claim='核对动作：'+e['action']+'。待审完整描述：'+narrative
   ims=[]
   for side,nd in [('a',l),('b',r)]:
    fn='images/'+rid+'_'+side+'.png';shutil.copyfile(V0/'inputs'/(nd['source_frame']['sha256']+'.png'),PUBLIC/fn);ims.append(fn)
   members=[]
   if e['state']=='STATIC_MERGED':
    group=next(q for q in g['static_identity_groups'] if e['left'] in q)
    members=[{'time_sec':nodes[n]['source_frame']['time_sec'],'referent':nodes[n]['object']['referent']} for n in group]
   items.append({'review_id':rid,'kind':kind,'claim':claim,'referents':refs,'images':ims,'members':members,'section':'temporal','context':media(l['scope'],t1,t2)})
   key[rid]={'version':'V0','connection_key':e['id']+'/V0','layer':'temporal_census','pi':1,'system_record':e,'source_member_ids':group if e['state']=='STATIC_MERGED' else [e['left'],e['right']],'human_truth':None}
 rng.shuffle(items);assert sum(x['section']=='temporal' for x in items)==23
 for name,section in [('BLIND_FACTS.csv','facts'),('BLIND_TEMPORAL.csv','temporal'),('BLIND_KNOWN_CASES.csv','known')]:
  result=[]
  for x in items:
   if x['section']!=section:continue
   row={k:'' for k in FIELDS};row['review_id']=x['review_id'];row.update(item_type=x['kind'],video=x['context']['video'],target_start=x['context']['target_start'],target_end=x['context']['target_end'],claim=x['claim']);result.append(row)
  dumpcsv(PUBLIC/name,result,['review_id','item_type','video','target_start','target_end','claim']+FIELDS[1:])
 save(PRIVATE/'REVIEW_KEY.json',key);save(PRIVATE/'SAMPLING_MANIFEST.json',{'version':'V0','seed':SEED,'algorithm':'fixed quotas by fact type and video; SRS inside each stratum; no post-selection replacement','strata':strata,'ordinary_facts':80,'temporal_census':23,'known_extras':sum(x['section']=='known' for x in items),'known_already_sampled':known_links,'aliases':aliases,'freeze_before_human_labels':True,'labels_received':False,'correlated_frame_video_warning':True});save(PRIVATE/'BLIND_CONTENT_FROZEN.json',items)
 def clip(job):
  source,out,lo,hi=job
  if out.exists():return
  subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-ss',str(lo),'-i',str(source),'-t',str(hi-lo),'-vf','scale=960:-2','-an','-c:v','libx264','-preset','fast','-crf','19','-threads','1','-movflags','+faststart',str(out)],check=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:list(ex.map(clip,jobs.values()))
 save(PRIVATE/'CLIP_INDEX.json',[{'clip':str(out.relative_to(PUBLIC)),'video':source.name,'start_source_seconds':lo,'end_source_seconds':hi,'sha256':hashlib.sha256(out.read_bytes()).hexdigest()} for source,out,lo,hi in jobs.values()]);write_html(items)
 print(json.dumps({'facts':80,'temporal':23,'known_extra':sum(x['section']=='known' for x in items),'clips':len(jobs),'public':str(PUBLIC)}))

def write_html(items):
 data=json.dumps(items,ensure_ascii=False).replace('</','<\\/');fields=json.dumps(FIELDS);template=Path(__file__).with_name('blind_template.html').read_text();(PUBLIC/'BLIND_REVIEW.html').write_text(template.replace('@@DATA@@',data).replace('@@FIELDS@@',fields),encoding='utf-8')
if __name__=='__main__':main()
