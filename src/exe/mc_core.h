/* MegaCode codec (C) - porta exata de src/web/mc.js. Garante compatibilidade C<->JS/APK. */
#ifndef MC_CORE_H
#define MC_CORE_H
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

#define MC_MAGIC0 0x4D
#define MC_MAGIC1 0x43
#define MC_VERSION 1
#define MC_BORDER 3
#define MC_HDR 24

static const int MC_SIZES[8]={64,80,96,112,128,160,192,224};
static const int MC_NSYM[5]={8,16,24,32,40};
static const int MC_SYNC[8]={0,1,0,1,0,1,1,0};
/* PAL[cm][idx][3] */
static const uint8_t MC_PAL[3][8][3]={
 {{0,0,0},{255,255,255},{0,0,0},{0,0,0},{0,0,0},{0,0,0},{0,0,0},{0,0,0}},
 {{0,0,0},{255,255,255},{255,32,32},{40,80,255},{0,0,0},{0,0,0},{0,0,0},{0,0,0}},
 {{0,0,0},{255,255,255},{255,32,32},{40,80,255},{32,200,64},{255,220,0},{0,220,220},{255,0,200}}
};
static const int MC_PALN[3]={2,4,8};

static int mc_bps(int cm){return cm+1;}
static int mc_interior(int n){return n-2*MC_BORDER;}
static int mc_sizeIndex(int n){for(int i=0;i<8;i++)if(MC_SIZES[i]==n)return i;return -1;}
static int mc_nsymIndex(int ns){for(int i=0;i<5;i++)if(MC_NSYM[i]==ns)return i;return -1;}
static int mc_nblocksFor(int n,int cm){int W=mc_interior(n),b=mc_bps(cm);int v=W*(W-2)*b/8/255;return v<1?1:v;}
static int mc_dataMax(int n,int cm,int nsym){int nb=mc_nblocksFor(n,cm);int v=nb*(255-nsym)-MC_HDR-4-256;if(v<0)v=0;if(v>65535)v=65535;return v;}
static int mc_fmts(int b){return (16+b-1)/b;}

/* ---- GF(256) poli 0x11d ---- */
static uint8_t MC_EXP[512],MC_LOG[256];
static void mc_gfInit(void){int x=1;for(int i=0;i<255;i++){MC_EXP[i]=(uint8_t)x;MC_LOG[x]=(uint8_t)i;x<<=1;if(x&0x100)x^=0x11d;}for(int i=255;i<512;i++)MC_EXP[i]=MC_EXP[i-255];}
static uint8_t mc_gmul(uint8_t a,uint8_t b){if(!a||!b)return 0;return MC_EXP[MC_LOG[a]+MC_LOG[b]];}
static uint8_t mc_ginv(uint8_t a){return MC_EXP[(255-MC_LOG[a])%255];}
static void mc_rsGen(int nsym,uint8_t*g){/* g[0..nsym], g[0]=1 highest-first */
  memset(g,0,nsym+1);g[0]=1;int len=1;
  for(int i=0;i<nsym;i++){uint8_t ng[257];memset(ng,0,len+2);
    ng[0]=g[0];for(int j=1;j<=len;j++)ng[j]=g[j]^mc_gmul(g[j-1],MC_EXP[i]);
    ng[len+1]=mc_gmul(g[len],MC_EXP[i]);
    for(int j=0;j<=len+1;j++)g[j]=ng[j];len++;}
}
static void mc_rsParity(const uint8_t*msg,int k,const uint8_t*gen,int nsym,uint8_t*par){
  uint8_t res[512];memset(res,0,k+nsym);memcpy(res,msg,k);
  for(int i=0;i<k;i++){uint8_t coef=res[i];if(coef)for(int j=1;j<=nsym;j++)res[i+j]^=mc_gmul(gen[j],coef);}
  memcpy(par,res+k,nsym);
}
static void mc_rsSynd(const uint8_t*cw,int n,int nsym,uint8_t*S){
  for(int i=0;i<nsym;i++){uint8_t v=0;for(int j=0;j<n;j++)v=mc_gmul(v,MC_EXP[i])^cw[j];S[i]=v;}
}
/* corrige cw (n=k+nsym). retorna 1 ok, corr em *pcorr, dados em data[0..k) */
static int mc_rsCorrect(uint8_t*cw,int n,int nsym,int k,uint8_t*data,int*pcorr){
  uint8_t S[256];mc_rsSynd(cw,n,nsym,S);int nz=0;for(int i=0;i<nsym;i++)if(S[i])nz=1;
  if(!nz){memcpy(data,cw,k);*pcorr=0;return 1;}
  int C[257],B[257];memset(C,0,sizeof(C));memset(B,0,sizeof(B));C[0]=1;B[0]=1;int L=0,m=1,b=1;
  for(int nn=0;nn<nsym;nn++){int d=S[nn];for(int i=1;i<=L;i++)d^=mc_gmul((uint8_t)C[i],S[nn-i]);
    if(d==0){m++;continue;}
    int coef=mc_gmul((uint8_t)d,mc_ginv((uint8_t)b));
    int T[257];memcpy(T,C,sizeof(C));
    for(int i=m;i<=nsym;i++)C[i]^=mc_gmul((uint8_t)coef,(uint8_t)B[i-m]);
    if(2*L<=nn){memcpy(B,T,sizeof(T));L=nn+1-L;b=d;m=1;}else m++;
  }
  if(L==0)return 0;
  int errPos[257],ne=0;
  for(int j=0;j<n;j++){int t=(255-((n-1-j)%255))%255;int v=0;for(int i=0;i<=L;i++)v^=mc_gmul((uint8_t)C[i],MC_EXP[(i*t)%255]);if(v==0)errPos[ne++]=j;}
  if(ne!=L)return 0;
  int Om[256];for(int i=0;i<nsym;i++){int v=0;for(int j=0;j<=(i<L?i:L);j++)v^=mc_gmul((uint8_t)C[j],S[i-j]);Om[i]=v;}
  uint8_t out[512];memcpy(out,cw,n);
  for(int e=0;e<ne;e++){int j=errPos[e];int Xe=(n-1-j)%255,t=(255-Xe)%255;
    int num=0;for(int i=0;i<nsym;i++)num^=mc_gmul((uint8_t)Om[i],MC_EXP[(i*t)%255]);
    int der=0;for(int i=1;i<=L;i+=2)der^=mc_gmul((uint8_t)C[i],MC_EXP[((i-1)*t)%255]);
    if(der==0)continue;int ev=mc_gmul((uint8_t)num,mc_ginv((uint8_t)der));ev=mc_gmul((uint8_t)ev,MC_EXP[Xe]);
    out[j]^=(uint8_t)ev;}
  mc_rsSynd(out,n,nsym,S);for(int i=0;i<nsym;i++)if(S[i])return 0;
  int corr=0;for(int i=0;i<n;i++)if(out[i]!=cw[i])corr++;
  memcpy(data,out,k);*pcorr=corr;return 1;
}

/* ---- CRC ---- */
static uint16_t mc_crc16(const uint8_t*b,int len){uint16_t crc=0xFFFF;for(int i=0;i<len;i++){crc^=(uint16_t)b[i]<<8;for(int j=0;j<8;j++)crc=(crc&0x8000)?(uint16_t)((crc<<1)^0x1021):(uint16_t)(crc<<1);}return crc;}
static uint32_t MC_CRC32T[256];static int mc_crc32init=0;
static uint32_t mc_crc32(const uint8_t*b,int len){if(!mc_crc32init){for(int i=0;i<256;i++){uint32_t c=i;for(int j=0;j<8;j++)c=(c&1)?(0xEDB88320u^(c>>1)):(c>>1);MC_CRC32T[i]=c;}mc_crc32init=1;}
  uint32_t c=0xFFFFFFFFu;for(int i=0;i<len;i++)c=MC_CRC32T[(c^b[i])&255]^(c>>8);return c^0xFFFFFFFFu;}

/* ---- formato ---- */
static uint16_t mc_fmtWord(int n,int cm,int nsym,int nb){int ni=mc_sizeIndex(n),si=mc_nsymIndex(nsym);
  return (uint16_t)(((ni&15)|((cm&3)<<4)|((si&7)<<6)|(((nb-1)&127)<<9))&0xFFFF);}
static uint8_t mc_fmtRowSymbol(int col,int b,uint16_t fw){int maxs=(1<<b)-1;
  if(col<8)return MC_SYNC[col]?maxs:0;
  int idx=col-8,fs=mc_fmts(b),rep=idx/fs;
  if(rep>=3)return (col&1)?maxs:0;
  int bit=(idx%fs)*b;int v=0;
  for(int i=0;i<b;i++){int bb=(bit+i<16)?((fw>>(15-(bit+i)))&1):0;v=(v<<1)|bb;}
  return (uint8_t)v;}
static uint8_t mc_calRowSymbol(int col,int b){return b==1?(col&1):(col%(1<<b));}
static void mc_fileId(const char*name,int namelen,long long size,uint8_t out[8]){
  unsigned long long h=1469598103934665607ULL,F=1099511628211ULL;
  for(int i=0;i<namelen;i++){h^=(unsigned char)name[i];h*=F;}
  unsigned long long sz=(unsigned long long)size;
  for(int i=0;i<8;i++){h^=(sz>>(i*8))&255ULL;h*=F;}
  for(int i=0;i<8;i++)out[i]=(uint8_t)((h>>(i*8))&255ULL);
}

/* ---- ENCODE: arquivo -> simbolos da grade (W*W) ----
   retorna 1 ok. sym tamanho W*W. */
static int mc_encode(const char*name,const uint8_t*data,int dataLen,int n,int cm,int nsym,
                     uint32_t frameIndex,uint32_t totalFrames,uint8_t*sym){
  mc_gfInit();
  int W=mc_interior(n),b=mc_bps(cm),nb=mc_nblocksFor(n,cm),k=255-nsym;
  int namelen=(int)strlen(name);if(namelen>255)namelen=255;
  int extra=1+namelen;
  if(dataLen>nb*k-MC_HDR-extra-4)return 0;
  uint8_t*msg=(uint8_t*)calloc(nb*k,1);
  msg[0]=MC_MAGIC0;msg[1]=MC_MAGIC1;msg[2]=MC_VERSION;msg[3]=(uint8_t)cm;
  uint8_t fid[8];mc_fileId(name,namelen,dataLen,fid);memcpy(msg+4,fid,8);
  msg[12]=frameIndex>>24;msg[13]=frameIndex>>16;msg[14]=frameIndex>>8;msg[15]=frameIndex&255;
  msg[16]=totalFrames>>24;msg[17]=totalFrames>>16;msg[18]=totalFrames>>8;msg[19]=totalFrames&255;
  msg[20]=dataLen>>8;msg[21]=dataLen&255;
  uint16_t hc=mc_crc16(msg,22);msg[22]=hc>>8;msg[23]=hc&255;
  msg[MC_HDR]=(uint8_t)namelen;if(namelen)memcpy(msg+MC_HDR+1,name,namelen);
  memcpy(msg+MC_HDR+extra,data,dataLen);
  int cpos=MC_HDR+extra+dataLen;uint32_t crc=mc_crc32(msg,cpos);
  msg[cpos]=crc>>24;msg[cpos+1]=crc>>16;msg[cpos+2]=crc>>8;msg[cpos+3]=crc&255;
  uint8_t gen[257];mc_rsGen(nsym,gen);
  uint8_t*cw=(uint8_t*)calloc(nb*255,1);
  for(int bl=0;bl<nb;bl++){uint8_t par[256];mc_rsParity(msg+bl*k,k,gen,nsym,par);
    for(int i=0;i<k;i++)cw[i*nb+bl]=msg[bl*k+i];
    for(int i=0;i<nsym;i++)cw[k*nb+i*nb+bl]=par[i];}
  int cwLen=nb*255,totalBits=(W-2)*W*b;
  int bi=0;memset(sym,0,W*W);
  uint16_t fw=mc_fmtWord(n,cm,nsym,nb);
  for(int c=0;c<W;c++){sym[c]=mc_fmtRowSymbol(c,b,fw);sym[W+c]=mc_calRowSymbol(c,b);}
  for(int r=2;r<W;r++)for(int c=0;c<W;c++){int v=0;
    for(int bb=0;bb<b;bb++){int bt=0;int t=bi;if(t<cwLen*8&&t<totalBits)bt=(cw[t>>3]>>(7-(t&7)))&1;v=(v<<1)|bt;bi++;}
    sym[r*W+c]=(uint8_t)v;}
  free(msg);free(cw);return 1;
}

/* ---- leitura da linha de formato ---- */
static int mc_readFmt(const uint8_t*row,int W,int b,uint16_t*fw_out){
  int maxs=(1<<b)-1;
  for(int c=0;c<8;c++)if(row[c]!=(MC_SYNC[c]?maxs:0))return 0;
  int fs=mc_fmts(b);uint16_t words[3];
  for(int rep=0;rep<3;rep++){int fw=0;
    for(int j=0;j<fs;j++){int col=8+rep*fs+j;if(col>=W)return 0;int s=row[col]&maxs;
      for(int i=0;i<b;i++){int bp=15-(j*b+i);if(bp>=0)fw|=((s>>(b-1-i))&1)<<bp;}}
    words[rep]=(uint16_t)fw;}
  if(words[0]!=words[1]||words[1]!=words[2])return 0;
  *fw_out=words[0];return 1;
}
/* ---- DECODE: simbolos da grade (W*W, orientacao 0) -> arquivo ---- */
static int mc_decode(const uint8_t*sym,int n,uint8_t*outdata,int*outlen,char*outname,
                     uint32_t*frameIndex,uint32_t*totalFrames,int*pcm){
  mc_gfInit();int W=mc_interior(n);int found=0,cm=0,nsym=0,nb=0,b=0;
  for(int c=0;c<3;c++){int bb=mc_bps(c);uint16_t w;
    if(mc_readFmt(sym,W,bb,&w)){int un=MC_SIZES[w&15],ucm=(w>>4)&3,si=(w>>6)&7,unb=((w>>9)&127)+1;
      if(un==n&&ucm==c){cm=ucm;nsym=MC_NSYM[si];nb=unb;b=bb;found=1;break;}}}
  if(!found)return 0;
  int k=255-nsym,totalBits=(W-2)*W*b;
  uint8_t*bits=(uint8_t*)calloc(totalBits,1);int bi=0;
  for(int r=2;r<W;r++)for(int c=0;c<W;c++){int v=sym[r*W+c]&((1<<b)-1);
    for(int bb=0;bb<b;bb++)if(bi<totalBits)bits[bi++]=(v>>(b-1-bb))&1;}
  int cwLen=nb*255;uint8_t*cw=(uint8_t*)calloc(cwLen,1);
  for(int i=0;i<cwLen;i++){int byte=0;for(int bb=0;bb<8;bb++){int t=i*8+bb;if(t<totalBits)byte=(byte<<1)|bits[t];else byte<<=1;}cw[i]=(uint8_t)(byte&255);}
  uint8_t*msg=(uint8_t*)calloc(nb*k,1);
  for(int bl=0;bl<nb;bl++){uint8_t block[255];
    for(int i=0;i<k;i++)block[i]=cw[i*nb+bl];
    for(int i=0;i<nsym;i++)block[k+i]=cw[k*nb+i*nb+bl];
    int pc;uint8_t d[255];if(!mc_rsCorrect(block,255,nsym,k,d,&pc)){free(bits);free(cw);free(msg);return 0;}
    memcpy(msg+bl*k,d,k);}
  int ok=0;
  if(msg[0]==MC_MAGIC0&&msg[1]==MC_MAGIC1&&msg[2]==MC_VERSION){
    uint16_t hc=(uint16_t)((msg[22]<<8)|msg[23]);
    if(mc_crc16(msg,22)==hc){
      int dl=(msg[20]<<8)|msg[21];int nameLen=msg[MC_HDR];int extra=1+nameLen;
      if(dl<=nb*k-MC_HDR-extra-4){int cpos=MC_HDR+extra+dl;
        uint32_t crc=((uint32_t)msg[cpos]<<24)|((uint32_t)msg[cpos+1]<<16)|((uint32_t)msg[cpos+2]<<8)|msg[cpos+3];
        if(mc_crc32(msg,cpos)==crc){
          *frameIndex=((uint32_t)msg[12]<<24)|((uint32_t)msg[13]<<16)|((uint32_t)msg[14]<<8)|msg[15];
          *totalFrames=((uint32_t)msg[16]<<24)|((uint32_t)msg[17]<<16)|((uint32_t)msg[18]<<8)|msg[19];
          memcpy(outname,msg+MC_HDR+1,nameLen);outname[nameLen]=0;
          memcpy(outdata,msg+MC_HDR+extra,dl);*outlen=dl;*pcm=cm;ok=1;}}}
  }
  free(bits);free(cw);free(msg);return ok;
}
#endif
