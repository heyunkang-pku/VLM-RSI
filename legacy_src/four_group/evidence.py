"""Unfiltered frozen-question evidence pages; human labels remain blank."""
from pathlib import Path
import json,csv,html,shutil
from step_six.common import h,rows,j,filehash
from stsg_pilot.runtime import save

def export(cfg,root):
 root=Path(root);folder=root/'BLIND_EVIDENCE';folder.mkdir(exist_ok=True);media={**j(Path(cfg['old33_root'])/'VIDEO_INPUTS_FROZEN.json'),**j(root/'VIDEO_INPUTS_FROZEN.json')};qs=[]
 for cohort in ['old33','new_batch']:
  for q in rows(root/cohort/'PER_QUESTION.jsonl'):qs.append((cohort,q))
 copied=set();videos=set();form=[];private=[];links=[];style='<style>body{font-family:system-ui;max-width:1200px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}img{width:100%}video{width:100%;max-height:620px}</style>'
 for cohort,q in qs:
  rid='review_'+h([cohort,q['question_id'],'four-group-v1'])[:12];vid=q['video_id'];m=media[vid];pics=[]
  for f in m['class_video_views']:
   digest=f['sha256'];src=Path(m['_root'])/f['file'];assert filehash(src)==digest
   if digest not in copied:dst=folder/'pixels'/(digest+'.png');dst.parent.mkdir(exist_ok=True);shutil.copy2(src,dst);copied.add(digest)
   pics.append('<figure><img loading="lazy" src="pixels/'+digest+'.png"><figcaption>'+str(f['time_sec'])+'s</figcaption></figure>')
  if vid not in videos:
   src=Path(cfg['pool_root'])/(vid+'.mp4')
   if src.exists():dst=folder/'videos'/src.name;dst.parent.mkdir(exist_ok=True);shutil.copy2(src,dst);videos.add(vid)
  text=html.escape(q['question']);(folder/(rid+'.html')).write_text('<!doctype html><meta charset="utf-8">'+style+'<h1>'+rid+'</h1><h2>'+text+'</h2><p>先独立作答。以下帧为共享Solver实际冻结输入；全视频额外证据需另记，不代表模型可见。</p><video controls preload="metadata" src="videos/'+vid+'.mp4"></video><div class="grid">'+''.join(pics)+'</div>');links.append('<li><a href="'+rid+'.html">'+rid+'</a> '+text+'</li>')
  form.append({'review_id':rid,'answerable_on_frozen_frames':'','independent_answer':'','supporting_times':'','ambiguous_referent':'','evidence_only_in_full_video':'','notes':''});private.append({'review_id':rid,'cohort':cohort,'question_id':q['question_id']})
 (folder/'index.html').write_text('<!doctype html><meta charset="utf-8">'+style+'<h1>四组对照证据页</h1><p>无候选答案或分组成绩。先填review.csv；评估结果不阻塞工程。</p><ol>'+''.join(links)+'</ol>')
 if form:
  with (folder/'review.csv').open('w',encoding='utf-8-sig',newline='') as fp:w=csv.DictWriter(fp,fieldnames=list(form[0]));w.writeheader();w.writerows(form)
 save(root/'PRIVATE_REVIEW_MAP.json',private)
