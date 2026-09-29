import json,os,urllib.request
p='wl/build.log'
log=open(p,'rb').read().decode('utf-8','replace')[-58000:] if os.path.exists(p) else '(no log)'
body={'body':'### build log (sha '+os.environ.get('GITHUB_SHA','')[:8]+')\n\n```\n'+log+'\n```\n'}
req=urllib.request.Request(
    f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/issues/7/comments",
    data=json.dumps(body).encode(),
    headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/json'},
    method='POST')
try:
    r=urllib.request.urlopen(req,timeout=30); print('POSTED',r.status)
except Exception as e:
    print('POST ERR',e)
