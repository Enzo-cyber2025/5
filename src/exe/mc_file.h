/* Multi-quadro: arquivo <-> varios PNGs. Usa mc_core/mc_png/mc_img. */
#ifndef MC_FILE_H
#define MC_FILE_H
#include <stdio.h>
#include "mc_core.h"
#include "mc_png.h"
#include "mc_img.h"
static int mc_payload(int n,int cm,int nsym,int nameLen){int nb=mc_nblocksFor(n,cm),k=255-nsym;int v=nb*k-MC_HDR-4-(1+nameLen);return v<0?0:v;}
/* codifica 1 arquivo em N PNGs dentro de outdir. retorna nro de PNGs ou -1. */
static int mc_encode_file(const char*path,const char*name,const char*outdir,int n,int cm,int nsym,int px,int quiet){
  FILE*f=fopen(path,"rb");if(!f)return -1;
  fseek(f,0,SEEK_END);long sz=ftell(f);fseek(f,0,SEEK_SET);
  uint8_t*data=(uint8_t*)malloc(sz?sz:1);if(sz&&fread(data,1,sz,f)!=(size_t)sz){fclose(f);return -1;}fclose(f);
  int nameLen=(int)strlen(name);if(nameLen>255)nameLen=255;
  int cap=mc_payload(n,cm,nsym,nameLen);if(cap<=0){free(data);return -1;}
  int total=(int)((sz+cap-1)/cap);if(total==0)total=1;
  int W=n-2*MC_BORDER;uint8_t*sym=(uint8_t*)malloc(W*W);
  int side=(n+2*quiet)*px;uint8_t*rgb=(uint8_t*)malloc((size_t)side*side*3);
  int made=0;
  for(int fr=0;fr<total;fr++){
    long off=(long)fr*cap;int len=(int)((sz-off<cap)?(sz-off):cap);if(len<0)len=0;
    if(!mc_encode(name,data+off,len,n,cm,nsym,(uint32_t)fr,(uint32_t)total,sym))continue;
    mc_render(sym,n,cm,px,quiet,rgb);
    size_t pl;uint8_t*png=mc_png_write(rgb,side,side,&pl);
    char out[1024];
    if(total==1)snprintf(out,sizeof(out),"%s/%s.png",outdir,name);
    else snprintf(out,sizeof(out),"%s/%s_%03d.png",outdir,name,fr+1);
    FILE*o=fopen(out,"wb");if(o){fwrite(png,1,pl,o);fclose(o);made++;}
    free(png);
  }
  free(sym);free(rgb);free(data);return made;
}
#endif
