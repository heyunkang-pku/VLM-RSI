"""Lossless mechanical adapters for the Supplement's native text/list formats."""
import re,json

def plain(text):
    t=text.strip()
    if t.startswith('```'):t=re.sub(r'^```\w*\s*|\s*```$','',t).strip()
    return t

def object_classes(text):
    t=plain(text);m=re.search(r'(?:meaningful objects are|objects\s*:)?\s*\[([^\[\]]+)\]',t,re.I|re.S)
    if not m:raise ValueError('OBJECT_LIST_NOT_RECOGNIZED')
    values=[v.strip(' \n\t\"\'') for v in m.group(1).split(',')]
    if not values or any(not v for v in values):raise ValueError('EMPTY_OBJECT_CLASS')
    return list(dict.fromkeys(values))

def instances(text,label):
    t=plain(text);m=re.search(r'Quantity\s*:\s*\[?(\d+)',t,re.I)
    if not m:raise ValueError('INSTANCE_QUANTITY_NOT_RECOGNIZED')
    count=int(m.group(1));rows=[]
    for line in t.splitlines():
        m=re.match(r'\s*(\d+)\s*[.)]\s*(.+?)\s*:\s*(.+?)\s*$',line)
        if m:rows.append({'ordinal':int(m.group(1)),'instance_name':m.group(2).replace('[','').replace(']','').strip(),'distinctive_description':m.group(3).strip(' []')})
    if len(rows)!=count or sorted(r['ordinal'] for r in rows)!=list(range(1,count+1)):raise ValueError('INSTANCE_ROWS_QUANTITY_MISMATCH')
    return rows

def classification(text):
    t=plain(text).strip(' []\"\'.').lower()
    if t not in ['static','dynamic']:raise ValueError('CLASSIFICATION_NOT_STATIC_OR_DYNAMIC')
    return t

def attributes(text):
    # Preserve repeated keys in the Supplement's pseudo-JSON; never infer values.
    pairs=re.findall(r'["“]([^"”]+)["”]\s*:\s*["“]([^"”]+)["”]',plain(text))
    pairs=[(k,v) for k,v in pairs if k.lower() not in ['object','attributes']]
    if any(k in ['type','value'] for k,v in pairs):raise ValueError('ATTRIBUTE_TYPED_FORMAT_NOT_PREDECLARED')
    if not pairs:raise ValueError('ATTRIBUTE_PAIRS_NOT_RECOGNIZED')
    return [{'type':k,'value':v} for k,v in pairs]

def split_tuple(text):
    fields=[];stack=[];start=0;quote=False
    for i,ch in enumerate(text):
        if ch=='"':quote=not quote
        if quote:continue
        if ch in '[({':stack.append(ch)
        elif ch in '])}':
            if not stack or {'[':']','(':')','{':'}'}[stack.pop()]!=ch:raise ValueError('UNBALANCED_BRACKETS')
        elif ch==',' and not stack:fields.append(text[start:i].strip());start=i+1
    if stack or quote:raise ValueError('UNBALANCED_BRACKETS')
    fields.append(text[start:].strip())
    if len(fields)!=3 or any(not f for f in fields):raise ValueError('RELATION_TRIPLE_COMMA_AMBIGUITY')
    return fields

def triples(text):
    groups=re.findall(r'<([^<>]+)>',plain(text));rows=[split_tuple(x) for x in groups]
    if not rows and plain(text).strip().lower() not in ['[]','none','no relationships','no relations']:raise ValueError('RELATION_TRIPLES_NOT_RECOGNIZED')
    return [{'subject':a,'predicate':b,'object':c} for a,b,c in rows]

def canon(text):return re.sub(r'^(the|a|an)\s+','',' '.join(text.strip().strip('[]').lower().split()))

def target_candidates(text,nodes):
    exact=[n['id'] for n in nodes if canon(text) in {canon(n['instance_name']),canon(n['referent'])}]
    if exact:return exact
    # A shared class returns every instance, never an arbitrary single node.
    return [n['id'] for n in nodes if canon(text)==canon(n['label'])]

def triples_with_issues(text):
    groups=re.findall(r'<([^<>]+)>',plain(text));good=[];bad=[]
    for raw in groups:
        try:a,b,c=split_tuple(raw);good.append({'subject':a,'predicate':b,'object':c})
        except ValueError as e:bad.append({'raw_tuple':raw,'error':str(e)})
    if not groups and plain(text).strip().lower() not in ['[]','none','no relationships','no relations']:bad.append({'raw_response':text,'error':'RELATION_TRIPLES_NOT_RECOGNIZED'})
    return good,bad
