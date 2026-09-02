#include <stdio.h>
#include "mc_core.h"
/* grade serializada: [n:2 BE][W*W simbolos] */
int main(int argc,char**argv){
  if(argc>=7&&!strcmp(argv[1],"enc")){
    FILE*f=fopen(argv[2],"rb");if(!f){printf("sem arquivo\n");return 1;}
    fseek(f,0,SEEK_END);long sz=ftell(f);fseek(f,0,SEEK_SET);
    uint8_t*data=(uint8_t*)malloc(sz?sz:1);if(sz)fread(data,1,sz,f);fclose(f);
    int n=atoi(argv[4]),cm=atoi(argv[5]),nsym=atoi(argv[6]);
    int W=n-2*MC_BORDER;uint8_t*sym=(uint8_t*)calloc(W*W,1);
    if(!mc_encode(argv[3],data,(int)sz,n,cm,nsym,0,1,sym)){printf("encode falhou\n");return 1;}
    FILE*o=fopen(argv[7],"wb");uint8_t hh[2]={(uint8_t)(n>>8),(uint8_t)(n&255)};fwrite(hh,1,2,o);fwrite(sym,1,W*W,o);fclose(o);
    printf("enc ok n=%d cm=%d W=%d\n",n,cm,W);return 0;
  }
  if(argc>=4&&!strcmp(argv[1],"dec")){
    FILE*f=fopen(argv[2],"rb");if(!f){printf("sem grade\n");return 1;}
    uint8_t hh[2];fread(hh,1,2,f);int n=(hh[0]<<8)|hh[1];int W=n-2*MC_BORDER;
    uint8_t*sym=(uint8_t*)malloc(W*W);fread(sym,1,W*W,f);fclose(f);
    uint8_t*out=(uint8_t*)malloc(70000);char nm[300];uint32_t fi,tf;int dl,cm;
    if(!mc_decode(sym,n,out,&dl,nm,&fi,&tf,&cm)){printf("decode falhou\n");return 1;}
    FILE*o=fopen(argv[3],"wb");fwrite(out,1,dl,o);fclose(o);
    printf("NOME=%s\nBYTES=%d\nFRAME=%u/%u\nCM=%d\n",nm,dl,fi,tf,cm);return 0;
  }
  printf("uso: gen enc <arq> <nome> <n> <cm> <nsym> <grade> | gen dec <grade> <out>\n");return 1;
}
