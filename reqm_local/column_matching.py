"""Exact column names first, then unique high-confidence near names."""
import re
from difflib import SequenceMatcher


def key(value):
    return re.sub(r'[^0-9a-z가-힣]','',str(value or '').casefold())


def find_column(headers, names, *, field='', excluded=()):
    candidates=[(i,key(h)) for i,h in enumerate(headers) if key(h) and i not in excluded]
    names=[key(n) for n in names if key(n)]
    for name in names:
        matches=[i for i,h in candidates if h==name]
        if len(matches)==1:return {'index':matches[0],'method':'일치','score':1.0}
        if len(matches)>1:return None
    ranked=[]
    for index,header in candidates:
        if field=='quantity' and any(word in header for word in ('취소','반품','금액','번호')):continue
        if field=='phone' and any(word in header for word in ('주문자','구매자')) and not any('주문자' in n or '구매자' in n for n in names):continue
        if field=='amount' and any(word in header for word in ('배송','공급','세액','할인')) and not any(word in n for n in names for word in ('배송','공급','세액','할인')):continue
        score=max((SequenceMatcher(None,name,header).ratio() for name in names),default=0)
        if score>=.8:ranked.append((score,index))
    ranked.sort(reverse=True)
    if ranked and (len(ranked)==1 or ranked[0][0]-ranked[1][0]>=.08):
        return {'index':ranked[0][1],'method':'근사','score':round(ranked[0][0],3)}
    return None


def match_columns(headers, aliases):
    result={};used=set()
    # Reserve every exact column before matching approximate names.
    for field,names in aliases.items():
        match=find_column(headers,names,field=field)
        if match and match['method']=='일치':result[field]=match;used.add(match['index'])
    for field,names in aliases.items():
        if field in result:continue
        match=find_column(headers,names,field=field,excluded=used)
        if match:result[field]=match;used.add(match['index'])
    return result
