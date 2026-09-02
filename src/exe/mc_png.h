/* PNG read/write + inflate (C). Le PNGs do APK/HTML (comprimidos) e grava PNGs proprios. */
#ifndef MC_PNG_H
#define MC_PNG_H
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
/* requer mc_core.h (mc_crc32) includo antes */

static uint32_t mc_adler32(const uint8_t*d,int n){uint32_t a=1,b=0;for(int i=0;i<n;i++){a=(a+d[i])%65521;b=(b+a)%65521;}return (b<<16)|a;}

/* ---- inflate (raw deflate) ---- */
typedef struct{const uint8_t*in;size_t inlen;size_t pos;int bitpos;uint8_t*out;size_t outlen,outcap;}Inf;
static int infBit(Inf*s){if(s->pos>=s->inlen)return -1;int b=(s->in[s->pos]>>(s->bitpos))&1;s->bitpos++;if(s->bitpos==8){s->bitpos=0;s->pos++;}return b;}
static int infBits(Inf*s,int n){int v=0;for(int i=0;i<n;i++){int b=infBit(s);if(b<0)return -1;v|=b<<i;}return v;}
static void infOut(Inf*s,uint8_t b){if(s->outlen<s->outcap)s->out[s->outlen++]=b;}
typedef struct{uint16_t counts[16];uint16_t syms[288];}Huff;
static void huffBuild(Huff*h,const uint8_t*len,int n){
  for(int i=0;i<16;i++)h->counts[i]=0;
  for(int i=0;i<n;i++)h->counts[len[i]]++;
  h->counts[0]=0;
  uint16_t offs[16];offs[1]=0;for(int i=1;i<15;i++)offs[i+1]=offs[i]+h->counts[i];
  for(int i=0;i<n;i++)if(len[i])h->syms[offs[len[i]]++]=(uint16_t)i;
}
static int huffDec(Inf*s,Huff*h){unsigned code=0,first=0;int idx=0;
  for(int len=1;len<16;len++){int b=infBit(s);if(b<0)return -1;code|=(unsigned)b;unsigned cnt=h->counts[len];
    if(code-first<cnt){int si=idx+(int)(code-first);if(si<0||si>=288)return -1;return h->syms[si];}
    idx+=(int)cnt;first+=cnt;first<<=1;code<<=1;}
  return -1;}
static const int LBASE[29]={3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258};
static const int LEXT[29]={0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0};
static const int DBASE[30]={1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577};
static const int DEXT[30]={0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13};
static int infStored(Inf*s){if(s->bitpos!=0){s->pos++;s->bitpos=0;}int len=infBits(s,16);infBits(s,16);for(int i=0;i<len;i++){int b=infBits(s,8);if(b<0)return -1;infOut(s,(uint8_t)b);}return 0;}
static int infBlock(Inf*s,Huff*hl,Huff*hd){
  for(;;){int sym=huffDec(s,hl);if(sym<0)return -1;
    if(sym<256)infOut(s,(uint8_t)sym);
    else if(sym==256)return 0;
    else{sym-=257;if(sym>=29)return -1;int len=LBASE[sym]+infBits(s,LEXT[sym]);
      int dsym=huffDec(s,hd);if(dsym<0||dsym>=30)return -1;int dist=DBASE[dsym]+infBits(s,DEXT[dsym]);
      for(int i=0;i<len;i++){if((size_t)dist>s->outlen)return -1;infOut(s,s->out[s->outlen-dist]);}}}
}
static int infFixed(Inf*s){uint8_t len[288];for(int i=0;i<144;i++)len[i]=8;for(int i=144;i<256;i++)len[i]=9;for(int i=256;i<280;i++)len[i]=7;for(int i=280;i<288;i++)len[i]=8;
  Huff hl;huffBuild(&hl,len,288);uint8_t dl[30];for(int i=0;i<30;i++)dl[i]=5;Huff hd;huffBuild(&hd,dl,30);return infBlock(s,&hl,&hd);}
static int infDyn(Inf*s){int hlit=infBits(s,5)+257,hdist=infBits(s,5)+1,hclen=infBits(s,4)+4;
  static const int ORDER[19]={16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15};
  uint8_t clen[19];for(int i=0;i<19;i++)clen[i]=0;
  for(int i=0;i<hclen;i++)clen[ORDER[i]]=(uint8_t)infBits(s,3);
  Huff hc;huffBuild(&hc,clen,19);
  uint8_t len[320];int i=0;while(i<hlit+hdist){int sym=huffDec(s,&hc);if(sym<0)return -1;
    if(i>=hlit+hdist)return -1;
    if(sym<16)len[i++]=(uint8_t)sym;
    else{int rep;uint8_t p=0;if(sym==16){rep=3+infBits(s,2);p=i>0?len[i-1]:0;}else if(sym==17)rep=3+infBits(s,3);else rep=11+infBits(s,7);if(i+rep>hlit+hdist)return -1;while(rep--)len[i++]=p;}}
  Huff hl,hd;huffBuild(&hl,len,hlit);huffBuild(&hd,len+hlit,hdist);return infBlock(s,&hl,&hd);}
static int mc_inflate(const uint8_t*in,size_t inlen,uint8_t*out,size_t outcap){
  Inf s;memset(&s,0,sizeof(s));s.in=in;s.inlen=inlen;s.out=out;s.outcap=outcap;
  int last=0;do{last=infBit(&s);int type=infBits(&s,2);int r;
    if(type==0)r=infStored(&s);else if(type==1)r=infFixed(&s);else if(type==2)r=infDyn(&s);else return -1;
    if(r<0)return -1;}while(!last);
  return (int)s.outlen;}

/* ---- PNG ---- */
static uint32_t be32(const uint8_t*p){return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];}
static int paeth(int a,int b,int c){int p=a+b-c;int pa=p-a;if(pa<0)pa=-pa;int pb=p-b;if(pb<0)pb=-pb;int pc=p-c;if(pc<0)pc=-pc;if(pa<=pb&&pa<=pc)return a;if(pb<=pc)return b;return c;}
/* le PNG (8-bit, RGB/RGBA/gray), sem interlace. retorna RGB(3B) mallocado. */
static uint8_t* mc_png_read(const uint8_t*buf,size_t len,int*w,int*h){
  if(len<8||memcmp(buf,"\x89PNG\r\n\x1a\n",8))return NULL;
  size_t p=8;int W=0,H=0,bitd=0,ctype=0;uint8_t*idat=NULL;size_t idatlen=0,idatcap=0;
  while(p+8<=len){uint32_t clen=be32(buf+p);const uint8_t*ty=buf+p+4;const uint8_t*cd=buf+p+8;
    if(!memcmp(ty,"IHDR",4)){W=be32(cd);H=be32(cd+4);bitd=cd[8];ctype=cd[9];}
    else if(!memcmp(ty,"IDAT",4)){if(idatlen+clen>idatcap){idatcap=(idatlen+clen)*2+1024;idat=(uint8_t*)realloc(idat,idatcap);}memcpy(idat+idatlen,cd,clen);idatlen+=clen;}
    else if(!memcmp(ty,"IEND",4))break;
    p+=12+clen;}
  if(!W||!H||bitd!=8||!idat)return NULL;
  int ch=(ctype==6)?4:(ctype==2)?3:(ctype==0)?1:(ctype==4)?2:0;if(!ch)return NULL;
  size_t rawcap=(size_t)H*((size_t)W*ch+1)+16;uint8_t*raw=(uint8_t*)malloc(rawcap);
  int rl=mc_inflate(idat+2,idatlen-2,raw,rawcap); /* pula cabecalho zlib 0x78 .. */
  if(rl<0){free(raw);free(idat);return NULL;}
  uint8_t*rgb=(uint8_t*)malloc((size_t)W*H*3);int stride=W*ch;
  uint8_t*line=raw,*prev=(uint8_t*)calloc(stride,1);
  for(int y=0;y<H;y++){uint8_t ft=*line++;uint8_t*cur=line;line+=stride;
    for(int x=0;x<stride;x++){int a=x>=ch?cur[x-ch]:0,b=prev[x],c=x>=ch?prev[x-ch]:0;int v=cur[x];
      if(ft==1)v+=a;else if(ft==2)v+=b;else if(ft==3)v+=(a+b)/2;else if(ft==4)v+=paeth(a,b,c);cur[x]=(uint8_t)v;}
    for(int x=0;x<W;x++){uint8_t r,g,bl;
      if(ch>=3){r=cur[x*ch];g=cur[x*ch+1];bl=cur[x*ch+2];}else{r=g=bl=cur[x];}
      size_t o=((size_t)y*W+x)*3;rgb[o]=r;rgb[o+1]=g;rgb[o+2]=bl;}
    memcpy(prev,cur,stride);}
  free(prev);free(raw);free(idat);*w=W;*h=H;return rgb;
}
/* grava PNG RGB (deflate armazenado, sem compressao) - mallocado, *outlen */
static uint8_t* mc_png_write(const uint8_t*rgb,int w,int h,size_t*outlen){
  size_t rawlen=(size_t)h*(1+(size_t)w*3);uint8_t*raw=(uint8_t*)malloc(rawlen);size_t rp=0;
  for(int y=0;y<h;y++){raw[rp++]=0;memcpy(raw+rp,rgb+(size_t)y*w*3,(size_t)w*3);rp+=(size_t)w*3;}
  size_t maxb=65535,nb=(rawlen+maxb-1)/maxb;if(nb==0)nb=1;
  size_t zlen=2+rawlen+5*nb+4;uint8_t*z=(uint8_t*)malloc(zlen);size_t zp=0;
  z[zp++]=0x78;z[zp++]=0x01;size_t left=rawlen,off=0;
  while(left){size_t b=left>maxb?maxb:left;int fin=(left<=maxb);z[zp++]=(uint8_t)fin;
    z[zp++]=(uint8_t)(b&255);z[zp++]=(uint8_t)(b>>8);z[zp++]=(uint8_t)(~b&255);z[zp++]=(uint8_t)((~b>>8)&255);
    memcpy(z+zp,raw+off,b);zp+=b;off+=b;left-=b;}
  uint32_t ad=mc_adler32(raw,(int)rawlen);z[zp++]=ad>>24;z[zp++]=ad>>16;z[zp++]=ad>>8;z[zp++]=ad&255;free(raw);
  /* chunks */
  size_t cap=8+ (25+12) + (zp+12) + 12;uint8_t*o=(uint8_t*)malloc(cap);size_t q=0;
  memcpy(o,"\x89PNG\r\n\x1a\n",8);q=8;
  uint8_t ihdr[13];ihdr[0]=w>>24;ihdr[1]=w>>16;ihdr[2]=w>>8;ihdr[3]=w;ihdr[4]=h>>24;ihdr[5]=h>>16;ihdr[6]=h>>8;ihdr[7]=h;ihdr[8]=8;ihdr[9]=2;ihdr[10]=0;ihdr[11]=0;ihdr[12]=0;
  uint8_t hdr[4]={ 'I','H','D','R'};
  o[q++]=0;o[q++]=0;o[q++]=0;o[q++]=13;memcpy(o+q,hdr,4);q+=4;memcpy(o+q,ihdr,13);q+=13;
  uint32_t c=mc_crc32(hdr,4);/*crc sobre tipo+dado*/
  {uint8_t tmp[4+13];memcpy(tmp,hdr,4);memcpy(tmp+4,ihdr,13);c=mc_crc32(tmp,17);}
  o[q++]=c>>24;o[q++]=c>>16;o[q++]=c>>8;o[q++]=c&255;
  uint8_t idt[4]={'I','D','A','T'};uint32_t zl=(uint32_t)zp;o[q++]=zl>>24;o[q++]=zl>>16;o[q++]=zl>>8;o[q++]=zl&255;memcpy(o+q,idt,4);q+=4;memcpy(o+q,z,zp);q+=zp;
  {uint8_t*tmp=(uint8_t*)malloc(4+zp);memcpy(tmp,idt,4);memcpy(tmp+4,z,zp);uint32_t cc=mc_crc32(tmp,4+zp);free(tmp);
   o[q++]=cc>>24;o[q++]=cc>>16;o[q++]=cc>>8;o[q++]=cc&255;}
  uint8_t iend[4]={'I','E','N','D'};o[q++]=0;o[q++]=0;o[q++]=0;o[q++]=0;memcpy(o+q,iend,4);q+=4;uint32_t ce=mc_crc32(iend,4);o[q++]=ce>>24;o[q++]=ce>>16;o[q++]=ce>>8;o[q++]=ce&255;
  free(z);*outlen=q;return o;
}
#endif
