"""Append one private URI-grant provider to pinned binary AXML; preserve existing indices."""
import struct
from mobile_manifest import enforce_min_sdk
from compute_manifest import compute_manifest


def attachment_manifest(data):
    data=enforce_min_sdk(data)
    chunks=[];pos=8
    while pos<len(data):
        kind,header,size=struct.unpack_from('<HHI',data,pos)
        chunks.append((kind,bytearray(data[pos:pos+size])));pos+=size
    pool=next(c for k,c in chunks if k==1)
    _,header,_,count,style_count,flags,start,styles=struct.unpack_from('<HH6I',pool)
    if header!=28 or style_count or styles or flags&0x100:raise ValueError('Expected pinned UTF-16 string pool without styles')
    offsets=list(struct.unpack_from('<'+'I'*count,pool,28))
    strings=[]
    for offset in offsets:
        length=struct.unpack_from('<H',pool,start+offset)[0]
        if length>=0x8000:raise ValueError('Unexpected long manifest string')
        strings.append(bytes(pool[start+offset+2:start+offset+2+length*2]).decode('utf-16le'))
    if 'com.ggufchat.app.AttachmentProvider' in strings:raise ValueError('Provider already present')
    payload=bytearray(pool[start:])
    def index(s):
        if s not in strings:
            offsets.append(len(payload));encoded=s.encode('utf-16le')
            payload.extend(struct.pack('<H',len(encoded)//2)+encoded+b'\0\0');strings.append(s)
        return strings.index(s)
    provider=index('provider');classname=index('com.ggufchat.app.AttachmentProvider');authority=index('com.ggufchat.app.attachments')
    authorities=index('authorities');grant=index('grantUriPermissions')
    name=index('name');exported=index('exported');ns=index('http://schemas.android.com/apk/res/android')
    while len(payload)%4:payload.append(0)
    new_start=28+len(strings)*4
    new_pool=struct.pack('<HH6I',1,28,new_start+len(payload),len(strings),0,flags&~1,new_start,0)+struct.pack('<'+'I'*len(offsets),*offsets)+payload
    resources=next(c for k,c in chunks if k==0x180)
    ids=list(struct.unpack_from('<'+'I'*((len(resources)-8)//4),resources,8))
    ids.extend([0]*(len(strings)-len(ids)));ids[authorities]=0x01010018;ids[grant]=0x0101001b
    new_resources=struct.pack('<HHI',0x180,8,8+4*len(ids))+struct.pack('<'+'I'*len(ids),*ids)
    def attr(key,typ,value):return struct.pack('<IIIHBBI',ns,key,value if typ==3 else 0xffffffff,8,0,typ,value)
    attrs=b''.join([attr(name,3,classname),attr(exported,0x12,0),attr(authorities,3,authority),attr(grant,0x12,0xffffffff)])
    begin=struct.pack('<HHIII',0x102,16,36+len(attrs),1,0xffffffff)+struct.pack('<IIHHHHHH',0xffffffff,provider,20,20,4,0,0,0)+attrs
    end=struct.pack('<HHIIIII',0x103,16,24,1,0xffffffff,0xffffffff,provider)
    result=[];added=0
    for kind,chunk in chunks:
        if kind==1:result.append(new_pool)
        elif kind==0x180:result.append(new_resources)
        else:
            if kind==0x103 and struct.unpack_from('<I',chunk,20)[0]==strings.index('application'):
                result.extend([begin,end]);added+=1
            result.append(chunk)
    if added!=1:raise ValueError('Expected one application element')
    body=b''.join(result)
    return compute_manifest(struct.pack('<HHI',3,8,8+len(body))+body)
