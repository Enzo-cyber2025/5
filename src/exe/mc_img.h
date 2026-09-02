/* Imagem: render da grade -> RGB, e leitura RGB -> arquivo (porta do decode do mc.js). */
#ifndef MC_IMG_H
#define MC_IMG_H
#include "mc_core.h"
static int mc_lum(uint8_t r,uint8_t g,uint8_t b){return (r*77+g*151+b*28)>>8;}
static int mc_otsu(const uint8_t*g,int wh){
  double hist[256]={0};int total=wh;for(int i=0;i<wh;i++)hist[g[i]]++;
  double sum=0;for(int i=0;i<256;i++)sum+=i*hist[i];
  double sumB=0,wB=0,maxv=-1,bet[256];for(int i=0;i<256;i++)bet[i]=-1;
  for(int i=0;i<256;i++){wB+=hist[i];if(!wB)continue;double wF=total-wB;if(!wF)break;
    sumB+=i*hist[i];double mB=sumB/wB,mF=(sum-sumB)/wF;bet[i]=wB*wF*(mB-mF)*(mB-mF);if(bet[i]>maxv)maxv=bet[i];}
  if(maxv<=0)return 128;int lo=-1,hi=-1;for(int i=0;i<256;i++)if(bet[i]>=maxv*0.999){if(lo<0)lo=i;hi=i;}
  return lo<0?128:((lo+hi)>>1);
}
static int mc_classify(uint8_t r,uint8_t g,uint8_t b,int cm){int best=0;long bd=1<<30;
  for(int i=0;i<MC_PALN[cm];i++){int dr=r-MC_PAL[cm][i][0],dg=g-MC_PAL[cm][i][1],db=b-MC_PAL[cm][i][2];long d=dr*dr+dg*dg+db*db;if(d<bd){bd=d;best=i;}}
  return best;}
static void mc_rot(const uint8_t*g,int n,int o,uint8_t*out){if(o==0){memcpy(out,g,n*n);return;}
  for(int r=0;r<n;r++)for(int c=0;c<n;c++){int nr,nc;
    if(o==1){nr=c;nc=n-1-r;}else if(o==2){nr=n-1-r;nc=n-1-c;}else{nr=n-1-c;nc=r;}
    out[nr*n+nc]=g[r*n+c];}}
/* render: grade de simbolos (W*W) -> RGB (3B). retorna lado. */
static int mc_render(const uint8_t*sym,int n,int cm,int px,int quiet,uint8_t*rgb){
  int W=mc_interior(n),K=1<<mc_bps(cm),side=(n+2*quiet)*px;
  memset(rgb,255,(size_t)side*side*3);
  for(int gr=0;gr<n;gr++)for(int gc=0;gc<n;gc++){const uint8_t*col;
    if(gr<MC_BORDER||gr>=n-MC_BORDER||gc<MC_BORDER||gc>=n-MC_BORDER)col=MC_PAL[0][0];
    else col=MC_PAL[cm][sym[(gr-MC_BORDER)*W+(gc-MC_BORDER)]&(K-1)];
    int ox=(gc+quiet)*px,oy=(gr+quiet)*px;
    for(int y=0;y<px;y++)for(int x=0;x<px;x++){size_t o=((size_t)(oy+y)*side+ox+x)*3;rgb[o]=col[0];rgb[o+1]=col[1];rgb[o+2]=col[2];}}
  return side;
}
/* le imagem RGB -> arquivo. 1 ok. */
static int mc_decode_image(const uint8_t*rgb,int w,int h,uint8_t*out,int*outlen,char*outname,uint32_t*fi,uint32_t*tf,int*pcm){
  int wh=w*h;uint8_t*g=(uint8_t*)malloc(wh);for(int i=0;i<wh;i++)g[i]=(uint8_t)mc_lum(rgb[i*3],rgb[i*3+1],rgb[i*3+2]);
  int thr=mc_otsu(g,wh);
  int x0=w,y0=h,x1=-1,y1=-1;
  for(int y=0;y<h;y++)for(int x=0;x<w;x++)if(g[y*w+x]<=thr){if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y;}
  free(g);if(x1<0)return 0;
  int bw=x1-x0+1,bh=y1-y0+1;
  for(int si=0;si<8;si++){int n=MC_SIZES[si];if(bw<n||bh<n)continue;
    double pxX=(double)bw/n,pxY=(double)bh/n;
    uint8_t*cols=(uint8_t*)malloc(n*n*3);
    for(int r=0;r<n;r++){int cy=y0+(int)((r+0.5)*pxY);if(cy<0)cy=0;if(cy>=h)cy=h-1;
      for(int c=0;c<n;c++){int cx=x0+(int)((c+0.5)*pxX);if(cx<0)cx=0;if(cx>=w)cx=w-1;
        size_t o=((size_t)cy*w+cx)*3,d=((size_t)r*n+c)*3;cols[d]=rgb[o];cols[d+1]=rgb[o+1];cols[d+2]=rgb[o+2];}}
    int done=0;
    for(int cm=0;cm<3&&!done;cm++){int b=mc_bps(cm);uint8_t*sym0=(uint8_t*)malloc(n*n);
      for(int i=0;i<n*n;i++)sym0[i]=(uint8_t)mc_classify(cols[i*3],cols[i*3+1],cols[i*3+2],cm);
      uint8_t*symr=(uint8_t*)malloc(n*n);int W=mc_interior(n);
      for(int o=0;o<4&&!done;o++){mc_rot(sym0,n,o,symr);
        uint8_t row[256];if(W>256)break;for(int c=0;c<W;c++)row[c]=symr[MC_BORDER*n+MC_BORDER+c];
        uint16_t fw;if(mc_readFmt(row,W,b,&fw)){int un=MC_SIZES[fw&15],ucm=(fw>>4)&3;
          if(un==n&&ucm==cm){uint8_t*isym=(uint8_t*)malloc(W*W);
            for(int r=0;r<W;r++)for(int c=0;c<W;c++)isym[r*W+c]=symr[(MC_BORDER+r)*n+(MC_BORDER+c)];
            if(mc_decode(isym,n,out,outlen,outname,fi,tf,pcm))done=1;
            free(isym);}}}
      free(sym0);free(symr);}
    free(cols);if(done)return 1;}
  return 0;
}
#endif
