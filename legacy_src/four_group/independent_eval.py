"""Blind stage1 all-question review and paired stage2 evaluation contract."""
from pathlib import Path
import json,csv,html,hashlib,shutil,collections,random
from step_six.common import j,rows,jl,norm
from stsg_pilot.runtime import save

def export(base,root,old,new,media):
 root=Path(root);folder=root/'BLIND_STAGE1';folder.mkdir(exist_ok=True);review=[];private=[];index=[]
 allrows=[dict(q,cohort='old84') for q in old]+new
 for q in allrows:
  rid='review_'+hashlib.sha256((q['cohort']+q['question_id']).encode()).hexdigest()[:12];vid=q['video_id'];m=media[vid];images=[]
  for f in m['class_video_views']:
   src=Path(f['file']);assert hashlib.sha256(src.read_bytes()).hexdigest()==f['sha256'];dst=folder/'pixels'/vid/src.name;dst.parent.mkdir(parents=True,exist_ok=True)
   if not dst.exists():shutil.copy2(src,dst)
   images.append(f'<figure style="display:inline-block;width:250px"><img width="250" loading="lazy" src="pixels/{vid}/{src.name}"><figcaption>{f["frame_id"]} PTS={f.get("pts")} {f["time_sec"]}s</figcaption></figure>')
  (folder/(rid+'.html')).write_text('<!doctype html><meta charset="utf-8"><h1>'+rid+'</h1><h2>'+html.escape(q['question'])+'</h2><p>仅按公共32帧独立作答。必须回看原视频时标记公共帧不足。</p>'+''.join(images));index.append(f'<li><a href="{rid}.html">{rid}</a></li>')
  review.append({'review_id':rid,'annotator_id':'','independent_answer':'','evidence_frame_ids':'','answerable_on_public32':'','ambiguity':'','requires_full_video':'','notes':''});private.append({'review_id':rid,'question_id':q['question_id'],'cohort':q['cohort'],'route':q['route'],'question_type':q.get('question_type','native_QRA'),'candidate_answer':q.get('answer',q.get('candidate_answer'))})
 with (folder/'REVIEW.csv').open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=list(review[0]));w.writeheader();w.writerows(review)
 (folder/'index.html').write_text('<!doctype html><meta charset="utf-8"><h1>独立评价：阶段一</h1><p>全部题目均提供，包含一致、分歧和弃答，未只挑争议题；填写REVIEW.csv，记录每位审核者ID。单人标注也需如实记录，疑难题优先复核。图/投票答案在另一目录，不应先打开。</p><ul>'+''.join(index)+'</ul>');save(root/'PRIVATE_STAGE2_MAP.json',private)
 with (root/'STAGE2_ADJUDICATION_TEMPLATE.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['review_id','graph_correct','vote_correct','graph_answered','vote_answered','independent_answer_collected','public32_sufficient','adjudicator_id']);w.writeheader()
  for p in private:w.writerow({'review_id':p['review_id']})
 # Existing dataset labels are not automatically gold for generated questions.
 files=[str(p) for p in Path('/scratch/haozhe/.cache/vlm-rsi/multisource-proxy-v1/PerceptionTest').glob('*.json')];save(root/'GOLD_ALIGNMENT_AUDIT.json',{'searched_files':files,'matches':[],'reason':'No established question/entity/time/granularity mapping; no dataset-label or majority-vote pseudo gold substituted','correctness_metrics':'PENDING'})
 save(root/'EVALUATION_STATUS.json',{'independent_labels':'PENDING','annotator_count':'UNKNOWN_UNTIL_FILLED','accuracy':'PENDING','coverage':'engineering answer availability only','all_question_pages':len(allrows),'sampling':'all questions included, no selective controversy sample','protocol':'Stage1 independent answer/evidence first, Stage2 judge frozen candidates and vote against independent answer; label insufficiency/ambiguity separately'})

def paired_evaluate(labels,mapping):
 rows_by={r['review_id']:r for r in mapping};buckets=collections.defaultdict(list)
 for r in labels:
  if r['independent_answer_collected']!='yes' or r['public32_sufficient']!='yes':continue
  if r['graph_correct'] not in ['yes','no'] or r['vote_correct'] not in ['yes','no']:continue
  m=rows_by[r['review_id']];buckets[(m['cohort'],m['route'],m['question_type'])].append(r)
 out=[]
 for group,rr in buckets.items():
  out.append({'cohort_route_type':group,'independently_evaluated':len(rr),'graph_correct_labels':sum(r['graph_correct']=='yes' for r in rr),'vote_correct_labels':sum(r['vote_correct']=='yes' for r in rr),'graph_coverage':sum(r['graph_answered']=='yes' for r in rr)/len(rr),'vote_coverage':sum(r['vote_answered']=='yes' for r in rr)/len(rr),'paired_both_answered':dict(collections.Counter('graph_'+r['graph_correct']+'_vote_'+r['vote_correct'] for r in rr if r['graph_answered']==r['vote_answered']=='yes'))})
 return out

if __name__=='__main__':
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--labels',required=True);ap.add_argument('--mapping',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
 with open(a.labels,encoding='utf-8-sig') as fp:labels=list(csv.DictReader(fp))
 result=paired_evaluate(labels,j(a.mapping))
 for r in result:
  r['graph_accuracy_answered']=r['graph_correct_labels']/(r['graph_coverage']*r['independently_evaluated']) if r['graph_coverage'] else None
  r['vote_accuracy_answered']=r['vote_correct_labels']/(r['vote_coverage']*r['independently_evaluated']) if r['vote_coverage'] else None
 save(a.output,{'groups':result,'pending':not result,'annotator_ids':sorted({r.get('adjudicator_id','') for r in labels if r.get('adjudicator_id')})})
