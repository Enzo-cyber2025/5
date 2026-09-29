import json,os,urllib.request
body = {"body":"ping sha "+os.environ.get("GITHUB_SHA","")[:8]+" run="+os.environ.get("GITHUB_RUN_ID","")}
req=urllib.request.Request(
  f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/issues/7/comments",
  data=json.dumps(body).encode(),
  headers={"Authorization":"Bearer "+os.environ["GITHUB_TOKEN"],"Accept":"application/vnd.github+json","Content-Type":"application/json"},
  method="POST")
try:
  r=urllib.request.urlopen(req,timeout=30); print("PING OK",r.status)
except Exception as e:
  print("PING ERR",e)
