#include <stdio.h>
#include "mc_core.h"
#include "mc_png.h"
#include "mc_img.h"
static uint8_t*readfile(const char*p,long*sz){FILE*f=fopen(p,"rb");if(!f)return NULL;fseek(f,0,SEEK_END);*sz=ftell(f);fseek(f,0,SEEK_SET);uint8_t*b=(uint8_t*)malloc(*sz?*sz:1);if(*sz)fread(b,1,*sz,f);fclose(f);return b;}
int main(int argc,char**argv){
  if(argc>=9&&!strcmp(argv[1],"enc")){
    long sz;uint8_t*data=readfile(argv[2],&sz);if(!data){printf("sem arquivo\n");return 1;}
    int n=atoi(argv[4]),cm=atoi(argv[5]),nsym=atoi(argv[6]),px=atoi(argv[7]),quiet=atoi(argv[8]);
    int W=n-2*MC_BORDER;uint8_t*sym=(uint8_t*)calloc(W*W,1);
    if(!mc_encode(argv[3],data,(int)sz,n,cm,nsym,0,1,sym)){printf("encode falhou\n");return 1;}
    int side=(n+2*quiet)*px;uint8_t*rgb=(uint8_t*)malloc((size_t)side*side*3);
    mc_render(sym,n,cm,px,quiet,rgb);
    size_t pl;uint8_t*png=mc_png_write(rgb,side,side,&pl);
    FILE*o=fopen(argv[9],"wb");fwrite(png,1,pl,o);fclose(o);
    printf("enc ok side=%d pngbytes=%zu\n",side,pl);return 0;
  }
  if(argc>=4&&!strcmp(argv[1],"dec")){
    long sz;uint8_t*png=readfile(argv[2],&sz);if(!png){printf("sem png\n");return 1;}
    int w,h;uint8_t*rgb=mc_png_read(png,(size_t)sz,&w,&h);if(!rgb){printf("png invalido\n");return 1;}
    uint8_t*out=(uint8_t*)malloc(70000);char nm[300];uint32_t fi,tf;int dl,cm;
    if(!mc_decode_image(rgb,w,h,out,&dl,nm,&fi,&tf,&cm)){printf("decode falhou\n");return 1;}
    FILE*o=fopen(argv[3],"wb");fwrite(out,1,dl,o);fclose(o);
    printf("NOME=%s\nBYTES=%d\nFRAME=%u/%u\nCM=%d\nW=%d H=%d\n",nm,dl,fi,tf,cm,w,h);return 0;
  }
  printf("uso: gen enc <arq> <nome> <n> <cm> <nsym> <px> <quiet> <out.png> | gen dec <in.png> <out>\n");return 1;
}
