"""Pinned UTF-16 AXML: declare honest specialUse for on-device AI, not dataSync.
No battery-optimization bypass, boot receiver, exported service or exact alarms.
"""
import struct

def compute_manifest(data):
    chunks=[];pos=8
    while pos<len(data):
        kind,header,size=struct.unpack_from('<HHI',data,pos)
        chunks.append((kind,bytearray(data[pos:pos+size])));pos+=size
    pool=next(c for k,c in chunks if k==1)
    _,header,_,count,styles,flags,start,style_start=struct.unpack_from('<HH6I',pool)
    assert header==28 and not styles and not style_start and not flags&0x100
    offsets=list(struct.unpack_from('<'+'I'*count,pool,28));strings=[]
    for offset in offsets:
        length=struct.unpack_from('<H',pool,start+offset)[0];assert length<0x8000
        strings.append(bytes(pool[start+offset+2:start+offset+2+length*2]).decode('utf-16le'))
    payload=bytearray(pool[start:])
    def index(s):
        if s not in strings:
            offsets.append(len(payload));b=s.encode('utf-16le');payload.extend(struct.pack('<H',len(b)//2)+b+b'\0\0');strings.append(s)
        return strings.index(s)
    assert 'com.ggufchat.app.ComputeService' not in strings
    ns=index('http://schemas.android.com/apk/res/android');name=index('name');value=index('value');exported=index('exported');typ=index('foregroundServiceType')
    service=index('service');prop=index('property');uses=index('uses-permission')
    classname=index('com.ggufchat.app.ComputeService');permission=index('android.permission.FOREGROUND_SERVICE_SPECIAL_USE')
    subtype=index('android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE')
    reason=index('User-initiated offline GGUF inference, weight import, physical tensor unification and native model validation while the display is off. Runs only until completion or cancellation.')
    def attr(k,t,v):return struct.pack('<IIIHBBI',ns,k,v if t==3 else 0xffffffff,8,0,t,v)
    def begin(tag,attrs):return struct.pack('<HHIII',0x102,16,36+20*len(attrs),1,0xffffffff)+struct.pack('<IIHHHHHH',0xffffffff,tag,20,20,len(attrs),0,0,0)+b''.join(attrs)
    def end(tag):return struct.pack('<HHIIIII',0x103,16,24,1,0xffffffff,0xffffffff,tag)
    property_node=begin(prop,[attr(name,3,subtype),attr(value,3,reason)])+end(prop)
    new_service=begin(service,[attr(name,3,classname),attr(exported,0x12,0),attr(typ,0x11,0x40000000)])+property_node+end(service)
    while len(payload)%4:payload.append(0)
    new_start=28+4*len(strings)
    new_pool=struct.pack('<HH6I',1,28,new_start+len(payload),len(strings),0,flags&~1,new_start,0)+struct.pack('<'+'I'*len(offsets),*offsets)+payload
    resources=next(c for k,c in chunks if k==0x180);ids=list(struct.unpack_from('<'+'I'*((len(resources)-8)//4),resources,8))
    ids.extend([0]*(len(strings)-len(ids)));ids[value]=0x01010024
    assert ids[name]==0x01010003 and ids[typ]!=0
    new_resources=struct.pack('<HHI',0x180,8,8+4*len(ids))+struct.pack('<'+'I'*len(ids),*ids)
    result=[];generation=False;changed=0
    for kind,chunk in chunks:
        if kind==1:result.append(new_pool);continue
        if kind==0x180:result.append(new_resources);continue
        tag=struct.unpack_from('<I',chunk,20)[0] if kind in (0x102,0x103) else -1
        if kind==0x102 and tag==index('application'):
            result.append(begin(uses,[attr(name,3,permission)])+end(uses))
        if kind==0x102 and tag==service:
            offset,stride,n=struct.unpack_from('<HHH',chunk,24)
            attrs=[16+offset+i*stride for i in range(n)]
            generation=any(struct.unpack_from('<I',chunk,a+4)[0]==name and strings[struct.unpack_from('<I',chunk,a+16)[0]] in ('.GenerationService','com.ggufchat.app.GenerationService') for a in attrs if chunk[a+15]==3)
            if generation:
                found=0
                for a in attrs:
                    if struct.unpack_from('<I',chunk,a+4)[0]==typ:
                        struct.pack_into('<I',chunk,a+8,0xffffffff);struct.pack_into('<I',chunk,a+16,0x40000000);found+=1
                assert found==1;changed+=1
        if kind==0x103 and tag==service and generation:result.append(property_node);generation=False
        if kind==0x103 and tag==index('application'):result.append(new_service)
        result.append(chunk)
    assert changed==1
    body=b''.join(result);return struct.pack('<HHI',3,8,8+len(body))+body
