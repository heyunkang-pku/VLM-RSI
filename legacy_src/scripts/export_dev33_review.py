"""CPU-only frozen development-set blind evidence export; no model calls."""
from pathlib import Path
import json,hashlib,html,csv,shutil,zipfile
BASE=Path('/Users/kcnthunderup/.local/share/openresearch/files/vlm-rsi')
def main():
 old=BASE/'step_six_group_pilot_20261101';frozen=BASE/'step33_verifier_v2_20261101/raw/frozen';out=BASE/'step33_dev_review_20261102';stage=out/'BLIND_STAGE1';stage.mkdir(parents=True,exist_ok=True);sealed=out/'STAGE2_SEALED';sealed.mkdir(exist_ok=True);private=[];forms=[];second=[];qs=[]
 for name in ['S_FROZEN_QA.jsonl','P_FROZEN_QA.jsonl']:qs.extend(json.loads(l) for l in (frozen/name).read_text().splitlines())
 facts=json.loads((frozen/'FACT_REGISTRY.json').read_text());media=json.loads((frozen/'VIDEO_INPUTS_FROZEN.json').read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();images=set();links=[]
 def picture(frame,role):
  h=frame['sha256'];images.add(h);return '<figure><img loading="lazy" src="pixels/'+h+'.png"><figcaption>'+html.escape(role)+f' · {frame["time_sec"]:.6f}s</figcaption></figure>'
 style='<style>body{font-family:system-ui;max-width:1250px;margin:24px auto;padding:16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}img{width:100%}figure{margin:0;border:1px solid #ddd;padding:8px}video{width:100%;max-height:620px}</style>'
 for q in sorted(qs,key=lambda q:hashlib.sha256(('blind-dev33-v3'+q['question_id']).encode()).hexdigest()):
  rid='review_'+hashlib.sha256(('blind-dev33-v3'+q['question_id']).encode()).hexdigest()[:12];vid=q['video_id'];private.append({'review_id':rid,'question_id':q['question_id'],'video_id':vid,'route_private':q['route'],'frozen_question_sha256':hashlib.sha256(q['question'].encode()).hexdigest()});m=media[vid];keyframes={}
  for fid in q.get('fact_ids',[]):
   f=facts.get(fid,{})
   for of in ([f]+[facts.get(x,{}) for x in f.get('parent_ids',[])]):
    if of.get('media'):fr=of['media']['calibration_view'];keyframes[fr['sha256']]=fr
  common=''.join(picture(x,'共享冻结视频帧') for x in m['class_video_views']);keys=''.join(picture(x,'对应图来源关键帧（未按答题效果筛选）') for x in sorted(keyframes.values(),key=lambda x:x['time_sec']))
  title=html.escape(q['question']);doc='<!doctype html><meta charset="utf-8">'+style+'<h1>'+rid+'</h1><h2>'+title+'</h2><p>开发集33题；此页无候选答案、推理、分组和核验结果。先独立作答。全视频证据与实际冻结输入证据分开记录。</p><video controls preload="metadata" src="videos/'+vid+'.mp4"></video><h2>共享冻结视频输入</h2><p>这批帧用于原有共享视频输入；不表示每次核验均编码了全部帧。不得用全视频额外信息代替冻帧证据。</p><div class="grid">'+common+'</div><h2>图来源关键帧</h2><p>按冻结问题事实来源展示全部关联关键帧，不展示图事实值；不代表它们已足以支持答案。</p><div class="grid">'+keys+'</div>'
  (stage/(rid+'.html')).write_text(doc);links.append('<li><a href="'+rid+'.html">'+rid+'</a> '+title+'</li>')
  forms.append({'review_id':rid,'answerability_frozen_frames':'','independent_answer':'','needed_referents':'','verifiable_answer_assertions':'','evidence_times_frames':'','question_ambiguity':'','relation_answer_completeness':'','extra_full_video_evidence':'','confidence':'','notes':''})
  second.append({'review_id':rid,'candidate_answer':q['answer'],'rationale':q.get('rationale'),'answer_assertions_correct':'','reference_resolved':'','evidence_sufficient':'','answer_complete':'','rationale_only_errors':'','rationale_needed_for_answer':'','notes':''})
  (sealed/(rid+'.md')).write_text('# '+rid+'\n\n问题：'+q['question']+'\n\n候选答案：'+json.dumps(q['answer'],ensure_ascii=False)+'\n\n推理（单独审查）：\n'+str(q.get('rationale') or '无原生rationale；程序轨迹在私有工程记录中。')+'\n\n先完成Stage1并锁定独立答案，再打开本页；不显示实验组名和成绩。\n')
 (stage/'index.html').write_text('<!doctype html><meta charset="utf-8">'+style+'<h1>33题开发集证据页</h1><p>先填写review.csv，再打开单独保存的Stage2。不能用于最终泛化结论。</p><ol>'+''.join(links)+'</ol>')
 for p in (old/'videos').glob('*.mp4'):d=stage/'videos'/p.name;d.parent.mkdir(exist_ok=True);shutil.copy2(p,d)
 for h in images:
  p=old/'visual_inputs/pixels'/(h+'.png');assert sha(p)==h;d=stage/'pixels'/p.name;d.parent.mkdir(exist_ok=True);shutil.copy2(p,d)
 for folder,name,data in [(stage,'review.csv',forms),(sealed,'answer_reasoning_review.csv',second)]:
  with (folder/name).open('w',encoding='utf-8-sig',newline='') as fp:w=csv.DictWriter(fp,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
 (out/'PRIVATE_ID_MAP.json').write_text(json.dumps(private,indent=2,ensure_ascii=False));(stage/'README.md').write_text('打开index.html逐题观看，先填写review.csv。独立答案填写完成后再打开单独Stage2包。空白表示待审，不能自动视为否或通过。候选答案正确性、推理错误、关系完整性、指代歧义分开评价。33题已用于反复调试，固定标记为开发集。\n')
 manifest={'split':'DEVELOPMENT_ONLY','questions':len(qs),'pages':len(list(stage.glob('review_*.html'))),'images':len(images),'blind_stage1_has_answers':False,'human_fields':'PENDING','held_out_evaluation':'NOT_RUN; select unseen video IDs only after rule freeze'};assert manifest['pages']==33;(out/'MANIFEST.json').write_text(json.dumps(manifest,indent=2))
 for label,folder in [('BLIND_EVIDENCE',stage),('STAGE2_SEALED',sealed)]:
  z=BASE/('STEP33_DEV_'+label+'_20261102.zip')
  with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED,strict_timestamps=False) as fp:
   for p in sorted(folder.rglob('*')):
    if p.is_file():fp.write(p,str(p.relative_to(folder)))
  with zipfile.ZipFile(z) as fp:assert fp.testzip() is None
  print(z.name,z.stat().st_size)
 print(json.dumps(manifest))
if __name__=='__main__':main()
