"""Minimal typed AXML edit: enforce the actual minimum native API level (28).
All other manifest bytes, permissions and package identity remain unchanged.
"""
import struct

def enforce_min_sdk(data, minimum=28):
    out=bytearray(data);pos=8;resources=[];found=0
    kind,header,total=struct.unpack_from('<HHI',data)
    if kind!=3 or header!=8 or total!=len(data):raise ValueError('Unexpected binary manifest')
    while pos<len(data):
        kind,header,size=struct.unpack_from('<HHI',data,pos)
        if size<header or pos+size>len(data):raise ValueError('Invalid XML chunk')
        if kind==0x180:
            resources=list(struct.unpack_from('<'+'I'*((size-header)//4),data,pos+header))
        elif kind==0x102:
            start,stride,count=struct.unpack_from('<HHH',data,pos+24)
            for i in range(count):
                attr=pos+16+start+i*stride
                name=struct.unpack_from('<I',data,attr+4)[0]
                if name<len(resources) and resources[name]==0x0101020c:
                    if data[attr+15]!=0x10:raise ValueError('minSdkVersion is not a typed integer')
                    before=struct.unpack_from('<I',data,attr+16)[0]
                    struct.pack_into('<I',out,attr+16,max(before,minimum));found+=1
        pos+=size
    if found!=1:raise ValueError('Missing or duplicate minSdkVersion')
    return bytes(out)
