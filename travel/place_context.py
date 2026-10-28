"""Bounded canonical place references, separate from untrusted conversation prose."""
import re
from .knowledge import get_place, normalize, places

REFERENCE=re.compile(r'这(?:两|俩|[二三四五六七八九0-9]|几|些)(?:个|处|地方|景点|地点)?|那(?:两|俩|[二三四五六七八九0-9]|几|些)(?:个|处|地方|景点|地点)?|它们|他们|上述|上面(?:的|推荐)|刚才(?:的|推荐)|这(?:个地方|个景点|个地点)|那(?:个地方|个景点|个地点)|那里|它(?:呢|怎么|有)|第[一二三四五六七八九十0-9]+个|前[一二两三四0-9]+个|后[一二两三四0-9]+个')
NUMBERS={'一':1,'二':2,'两':2,'俩':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}


def clean_ids(value):
    if not isinstance(value,list):return []
    known={p['id'] for p in places()}
    return list(dict.fromkeys(pid for pid in value if isinstance(pid,str) and pid in known))


def clean_context(value):
    value=value if isinstance(value,dict) else {}
    return {'listed_ids':clean_ids(value.get('listed_ids',[])),
            'focus_ids':clean_ids(value.get('focus_ids',[])),'kind':value.get('kind') if value.get('kind') in {'recommendation','plan','selection'} else 'recommendation'}


def visible_ids(result):
    if result.get('plan'):
        return clean_ids(list(dict.fromkeys(s['place']['id'] for day in result['plan']['days'] for s in day['stops'])))
    available={p['id'] for p in result.get('sources',[]) if isinstance(p,dict) and isinstance(p.get('id'),str)}
    answer=result.get('answer',{})
    cited=[pid for pid in answer.get('citations',[]) if pid in available]
    # Ordinals follow the visible prose order, not a provider's citation-array order.
    inline=re.findall(r'\[([a-z0-9-]+)\]',answer.get('text',''))
    ordered=[pid for pid in inline if pid in cited]
    return clean_ids(ordered or cited)


def hydrate_context(saved):
    """Read-only upgrade for histories written before structured references existed."""
    checkpoint=saved.get('checkpoint',{})
    if 'place_context' in checkpoint:return clean_context(checkpoint['place_context'])
    for turn in reversed(saved.get('turns',[])):
        result=turn.get('result',{});ids=visible_ids(result)
        if ids:return {'listed_ids':ids,'focus_ids':ids,'kind':'plan' if result.get('plan') else 'recommendation'}
        # Ignore an old failed attempt to search a pronoun as a new POI.
        if REFERENCE.search(normalize(turn.get('question',''))):continue
        if result.get('external_lookup'):break
    return clean_context({})


def next_context(old,result,reference=None):
    old=clean_context(old)
    if reference:
        if reference['kind']=='clarify':return old
        if reference.get('ids'):
            ids=clean_ids(reference['ids'])
            return {'listed_ids':ids if reference['kind']=='select' else old['listed_ids'] or ids,'focus_ids':ids,'kind':'selection' if reference['kind']=='select' else old['kind']}
    ids=visible_ids(result)
    if ids:return {'listed_ids':ids,'focus_ids':ids,'kind':'plan' if result.get('plan') else 'recommendation'}
    if result.get('external_lookup'):return clean_context({})
    return old


def _number(raw):
    return int(raw) if raw.isdigit() else NUMBERS.get(raw,0)


def resolve_reference(question,context):
    q=normalize(question);context=clean_context(context)
    has_ref=bool(REFERENCE.search(q))
    # A bare follow-up to the app's own "安排两天行程" suggestion binds the last list.
    bare_plan=bool(context['listed_ids'] and context['kind']=='recommendation' and re.fullmatch(r'(?:那|那么|好|请|帮我|给我|就)*(?:安排|规划|排)(?:[0-9一二两三四五六七八九十]+天)?(?:香港)?行程[。！!]*',q))
    # Exact canonical names can also confirm a choice, without a pronoun.
    mentions=[]
    for place in places():
        forms={normalize(place['name']),normalize(re.split(r'[（(]',place['name'])[0].strip())}
        if any(form and form in q for form in forms):mentions.append(place['id'])
    if (has_ref or mentions) and any(w in q for w in ['不去','不要','取消','排除','去掉','不选','不想去']):
        return {'kind':'clarify','ids':[],'message':'你想排除或取消哪些地点？请直接告诉我最后要保留的地点名称，我会按新的选择安排。'}
    explicit_choice=bool(mentions and any(w in q for w in ['只去','就去','想去','要去','我选','选择','安排','加入','必去']))
    if explicit_choice and not any(w in q for w in ['怎么','如何','介绍','特色','区别','有什么','值得']):
        return {'kind':'select','ids':mentions,'append':'加入' in q,'message':''}
    if not has_ref and not bare_plan:return None
    listed=context['listed_ids'];focus=context['focus_ids']
    def clarify(message):return {'kind':'clarify','ids':[],'message':message}
    if not listed and not focus:return clarify('还没有可对应的上一轮地点。请直接告诉我地点名称，或先让我推荐几个地方。')
    ordinals=re.findall(r'第([一二三四五六七八九十0-9]+)个',q)
    if ordinals:
        indexes=[_number(raw)-1 for raw in ordinals]
        if any(i<0 or i>=len(listed) for i in indexes):return clarify(f'上一轮列出了 {len(listed)} 个地点，请按这个列表选择序号或直接说名称。')
        selected=list(dict.fromkeys(listed[i] for i in indexes))
    else:
        edge=re.search(r'(前|后)([一二两三四0-9]+)个',q)
        count=re.search(r'[这那]([两俩二三四五六七八九0-9]+)(?:个|处|地方|景点|地点)?',q)
        if edge:
            n=_number(edge[2])
            if not 1<=n<=len(listed):return clarify('这个数量超出了上一轮地点列表，请说明想选哪几个。')
            selected=listed[:n] if edge[1]=='前' else listed[-n:]
        elif count:
            n=_number(count[1])
            if n!=len(listed):return clarify(f'上一轮列了 {len(listed)} 个地点，你说的“这{count[1]}个”具体是哪几个？可以说“第一个和第三个”，或直接说名称。')
            selected=listed
        elif any(word in q for word in ['这个地方','那个地方','这个景点','那个景点','这个地点','那个地点','那里','它呢','它怎么','它有']):
            if len(focus)!=1:return clarify('你指的是哪个地点？可以说第几个，或直接说名称。')
            selected=focus
        else:selected=listed or focus
    if any(w in q for w in ['怎么走','怎么去','如何去','如何走','之间','远吗','多远']):
        if len(selected)!=2:return clarify('要说明两地之间怎么走，请先明确起点和终点。')
        return {'kind':'transfer','ids':selected,'message':''}
    choosing=bare_plan or any(w in q for w in ['去','选','要这','要那','就这','就那','安排','规划','加入','加进去','必去'])
    if choosing and not any(w in q for w in ['介绍','特色','什么区别','有什么','好玩吗','值得去吗']):
        return {'kind':'select','ids':selected,'append':any(w in q for w in ['加入','加进去']),'message':''}
    return {'kind':'detail','ids':selected,'message':''}
