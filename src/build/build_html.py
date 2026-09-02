import os
base=os.path.dirname(os.path.abspath(__file__)); web=os.path.join(base,'..','web')
html=open(os.path.join(web,'index.html')).read()
mc=open(os.path.join(web,'mc.js')).read(); app=open(os.path.join(web,'app.js')).read()
html=html.replace('<script src="mc.js"></script>','<script>\n'+mc+'\n</script>')
html=html.replace('<script src="app.js"></script>','<script>\n'+app+'\n</script>')
out=os.path.join(base,'..','..','entrega','MegaCode.html'); open(out,'w').write(html)
print('wrote',out,len(html),'bytes')
