import asyncio,base64,json
import httpx,pytest
from fastapi.testclient import TestClient
import app
from travel import chat
from travel.config import Settings
from travel.maps import route_map

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j4l8AAAAASUVORK5CYII=')

def provider(static_ok=True,reflect=False):
 def handler(req):
  if req.url.path=='/v3/place/text':
   first=req.url.params['keywords']=='星光大道'
   return httpx.Response(200,json={'status':'1','pois':[{'id':'p1' if first else 'p2','name':'星光大道' if first else '诺士佛台','cityname':'香港','location':'114.175,22.293' if first else '114.175,22.302'}]})
  if req.url.path=='/v3/direction/walking':
   assert req.url.params['origin']=='114.175,22.293'
   return httpx.Response(200,json={'status':'1','route':{'paths':[{'distance':'950','duration':'720','steps':[{'instruction':'fixture-secret' if reflect else '沿梳士巴利道步行后右转','road':'梳士巴利道','orientation':'西','distance':'200','polyline':'114.175,22.293;114.174,22.295;114.175,22.302'}]}]}})
  assert req.url.path=='/v3/staticmap'
  assert 'key' in req.url.params
  return httpx.Response(200 if static_ok else 403,content=PNG if static_ok else b'no map')
 return httpx.MockTransport(handler)

def test_walking_route_steps_picture_and_navigation():
 result=asyncio.run(route_map(['avenue-stars','knutsford'],Settings(amap_api_key='fixture-secret'),provider()))
 assert result['mode']=='live' and result['distance_m']==950
 step=result['legs'][0]['steps'][0]
 assert step['instruction']=='沿梳士巴利道步行后右转' and step['distance_m']==200
 assert result['map_image'].startswith('data:image/png;base64,')
 assert result['navigation_url'].startswith('https://uri.amap.com/direction?')
 assert 'fixture-secret' not in json.dumps(result)

def test_missing_static_image_preserves_steps_without_fake_map():
 result=asyncio.run(route_map(['avenue-stars','knutsford'],Settings(amap_api_key='fixture-secret'),provider(False)))
 assert result['mode']=='live' and result['map_image'] is None
 assert result['legs'][0]['steps'] and result['navigation_url']

def test_route_steps_cannot_reflect_credential():
 result=asyncio.run(route_map(['avenue-stars','knutsford'],Settings(amap_api_key='fixture-secret'),provider(reflect=True)))
 assert result['mode']=='unavailable' and 'fixture-secret' not in json.dumps(result)

@pytest.mark.parametrize('body',[
 {'origin_id':'avenue-stars','destination_id':'avenue-stars'},
 {'origin_id':'unknown','destination_id':'knutsford'},
 {'origin_id':'avenue-stars','destination_id':'tai-o'},
 {'origin_id':'avenue-stars'},
])
def test_endpoint_rejects_invalid_or_nonwalking_pair(body,monkeypatch):
 async def forbidden(*args,**kwargs):pytest.fail('must validate before provider call')
 monkeypatch.setattr(chat,'route_map',forbidden)
 with TestClient(app.app) as client:assert client.post('/api/walking-map',json=body).status_code==422

def test_endpoint_passes_only_two_canonical_ids(monkeypatch):
 seen=[]
 async def stub(ids,cfg,**kwargs):seen.append(ids);return {'mode':'live','legs':[],'polylines':[],'map_image':None}
 monkeypatch.setattr(chat,'route_map',stub)
 with TestClient(app.app) as client:
  assert client.post('/api/walking-map',json={'origin_id':'avenue-stars','destination_id':'knutsford'}).status_code==200
 assert seen==[['avenue-stars','knutsford']]

def test_unconfigured_endpoint_is_explicit():
 with TestClient(app.app) as client:
  value=client.post('/api/walking-map',json={'origin_id':'avenue-stars','destination_id':'knutsford'}).json()
 assert value['mode']=='not_configured' and value['map_image'] is None and not value['legs']


def test_duplicate_names_require_confirmed_provider_ids():
 def handler(req):
  if req.url.path=='/v3/place/text':
   first=req.url.params['keywords']=='星光大道'
   if req.url.params['keywords']=='诺士佛台餐饮街区':return httpx.Response(200,json={'status':'1','pois':[]})
   name='星光大道' if first else '诺士佛台'
   return httpx.Response(200,json={'status':'1','pois':[{'id':str(i),'name':name,'cityname':'香港','location':f'114.17{i},22.29{i}'} for i in [1,2]]})
  return provider().handle_request(req)
 cfg=Settings(amap_api_key='fixture-secret');transport=httpx.MockTransport(handler)
 result=asyncio.run(route_map(['avenue-stars','knutsford'],cfg,transport))
 assert result['mode']=='ambiguous_location' and result['candidates']['knutsford']
 assert len(result['candidates']['avenue-stars'])==2 and not result['legs']
 invalid=asyncio.run(route_map(['avenue-stars','knutsford'],cfg,transport,poi_choices={'avenue-stars':'forged-id'}))
 assert invalid['mode']=='invalid_selection' and not invalid['legs']


def test_provider_selection_is_revalidated_before_routing():
 calls=[]
 def handler(req):
  calls.append(req.url.path)
  if req.url.path=='/v3/place/text':
   first=req.url.params['keywords']=='星光大道'
   return httpx.Response(200,json={'status':'1','pois':[{'id':str(i),'name':'星光大道' if first else '诺士佛台','cityname':'香港','location':f'114.17{i},22.29{i}'} for i in [1,2]]})
  if req.url.path=='/v3/direction/walking':
   assert req.url.params['origin']=='114.172,22.292'
   assert req.url.params['destination']=='114.171,22.291'
   return httpx.Response(200,json={'status':'1','route':{'paths':[{'distance':'200','duration':'150','steps':[{'instruction':'按道路步行至终点','polyline':'114.172,22.292;114.171,22.291'}]}]}})
  return httpx.Response(200,content=PNG)
 result=asyncio.run(route_map(['avenue-stars','knutsford'],Settings(amap_api_key='fixture-secret'),httpx.MockTransport(handler),poi_choices={'avenue-stars':'amap-2','knutsford':'amap-1'}))
 assert result['mode']=='live' and result['legs'][0]['steps']
 assert calls.count('/v3/direction/walking')==1


def test_search_outage_is_not_reported_as_a_place_name_problem():
 calls=[]
 def handler(req):
  calls.append(req.url.path)
  return httpx.Response(503)
 result=asyncio.run(route_map(['avenue-stars','knutsford'],Settings(amap_api_key='fixture-secret'),httpx.MockTransport(handler)))
 assert result['mode']=='unavailable' and not result['legs'] and result['map_image'] is None
 assert calls==['/v3/place/text']


@pytest.mark.parametrize('name',['PMQ元创方','PMQ 元創方','元创方（PMQ）'])
def test_provider_mixed_name_order_and_short_query_fallback(name):
 calls=[]
 def handler(req):
  calls.append((req.url.path,req.url.params.get('keywords')))
  if req.url.path=='/v3/place/text':
   query=req.url.params['keywords']
   pois=([{'id':'pmq-main','name':name,'cityname':'香港','location':'114.156867,22.28073'},
          {'id':'shop','name':'SOIL(PMQ元创方店)','cityname':'香港','location':'114.156676,22.280456'}] if query=='元创方 PMQ' else
         [] if query=='中环至半山自动扶梯' else
         [{'id':'escalator-main','name':'中环至半山自动扶梯','cityname':'香港','location':'114.158864,22.279343'}])
   return httpx.Response(200,json={'status':'1','pois':pois})
  if req.url.path=='/v3/direction/walking':
   assert req.url.params['origin']=='114.156867,22.28073'
   assert req.url.params['destination']=='114.158864,22.279343'
   return httpx.Response(200,json={'status':'1','route':{'paths':[{'distance':'400','duration':'360','steps':[{'instruction':'沿鸭巴甸街步行至扶梯','polyline':'114.156867,22.28073;114.158864,22.279343'}]}]}})
  assert req.url.path=='/v3/staticmap'
  return httpx.Response(200,content=PNG)
 result=asyncio.run(route_map(['pmq','escalator'],Settings(amap_api_key='fixture-secret'),httpx.MockTransport(handler)))
 assert result['mode']=='live' and result['map_image'] and result['distance_m']==400
 assert ('/v3/place/text','半山扶梯') in calls
 assert ('/v3/place/text','元創方') not in calls


def test_pmq_shop_is_not_accepted_as_the_attraction():
 def handler(req):
  assert req.url.path=='/v3/place/text'
  return httpx.Response(200,json={'status':'1','pois':[{'id':'shop','name':'SOIL(PMQ元创方店)','cityname':'香港','location':'114.156676,22.280456'}]})
 result=asyncio.run(route_map(['pmq','escalator'],Settings(amap_api_key='fixture-secret'),httpx.MockTransport(handler)))
 assert result['mode']=='ambiguous_location' and result['map_image'] is None and not result['legs']


def test_provider_format_variants_keep_ambiguous_places_for_user_choice():
 def handler(req):
  assert req.url.path=='/v3/place/text'
  first=req.url.params['keywords']=='元创方 PMQ'
  pois=([{'id':str(i),'name':name,'cityname':'香港','location':f'114.15{i},22.28073'} for i,name in [(1,'PMQ元创方'),(2,'元创方（PMQ）')]] if first else [{'id':'escalator','name':'中环至半山自动扶梯','cityname':'香港','location':'114.158864,22.279343'}])
  return httpx.Response(200,json={'status':'1','pois':pois})
 result=asyncio.run(route_map(['pmq','escalator'],Settings(amap_api_key='fixture-secret'),httpx.MockTransport(handler)))
 assert result['mode']=='ambiguous_location' and len(result['candidates']['pmq'])==2 and not result['legs']


@pytest.mark.parametrize('branches',[['兰芳园(中环大厦店)'],['兰芳园(中环大厦店)','兰芳园(重庆大厦店)']])
def test_food_branches_require_explicit_confirmation_and_keep_provider_ids(branches):
 calls=[]
 def handler(req):
  calls.append(req.url.path)
  if req.url.path=='/v3/place/text':
   first=req.url.params['keywords']=='香港动植物公园'
   pois=([{'id':'park','name':'香港动植物公园','cityname':'香港','location':'114.160739,22.275103'}] if first else
         [{'id':f'branch-{i}','name':name,'cityname':'香港','location':'114.1588,22.279878' if i==0 else '114.177931,22.293623'} for i,name in enumerate(branches)]+[{'id':'other-brand','name':'兰芳华厦','cityname':'香港','location':'114.16,22.29'}])
   return httpx.Response(200,json={'status':'1','pois':pois})
  if req.url.path=='/v3/direction/walking':
   assert req.url.params['origin']=='114.160739,22.275103'
   assert req.url.params['destination']=='114.1588,22.279878'
   return httpx.Response(200,json={'status':'1','route':{'paths':[{'distance':'800','duration':'700','steps':[{'instruction':'沿公园出口步行至餐厅','polyline':'114.160739,22.275103;114.1588,22.279878'}]}]}})
  return httpx.Response(200,content=PNG)
 cfg=Settings(amap_api_key='fixture-secret');transport=httpx.MockTransport(handler)
 choice=asyncio.run(route_map(['zoological-gardens','lan-fong-yuen'],cfg,transport))
 assert choice['mode']=='ambiguous_location' and not choice['legs'] and '/v3/direction/walking' not in calls
 assert len(choice['candidates']['lan-fong-yuen'])==len(branches)
 result=asyncio.run(route_map(['zoological-gardens','lan-fong-yuen'],cfg,transport,poi_choices={'lan-fong-yuen':'amap-branch-0'}))
 assert result['mode']=='live' and result['map_image'] and result['legs'][0]['destination']=='兰芳园(中环大厦店)'


@pytest.mark.parametrize('name',['SOIL(PMQ元创方店)','兰芳园咖啡(中环店)','兰芳华厦(中环店)','兰芳园旁边的小店'])
def test_branch_matching_does_not_use_substring_for_other_businesses(name):
 from travel.maps import is_food_branch
 from travel.knowledge import get_place
 assert not is_food_branch(get_place('lan-fong-yuen'),name)
 assert not is_food_branch(get_place('pmq'),name)
