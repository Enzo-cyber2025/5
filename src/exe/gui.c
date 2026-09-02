/* MegaCode .exe - janela Windows: gerar (pasta/arquivos/arrastar) e ler (importar PNG). */
#include <windows.h>
#include <commdlg.h>
#include <shlobj.h>
#include <stdio.h>
#include <string.h>
#include "mc_file.h"

static HWND hLog;
static int cfgN=224,cfgCM=0,cfgNS=32,cfgPX=4,cfgQ=2;

static void logf(const char*fmt,...){
  char b[2048];va_list ap;va_start(ap,fmt);vsnprintf(b,sizeof(b),fmt,ap);va_end(ap);
  int n=GetWindowTextLengthA(hLog);SendMessageA(hLog,EM_SETSEL,n,n);
  SendMessageA(hLog,EM_REPLACESEL,FALSE,(LPARAM)b);
  SendMessageA(hLog,EM_REPLACESEL,FALSE,(LPARAM)"\r\n");
}
static const char* baseName(const char*p){const char*b=p;for(const char*s=p;*s;s++)if(*s=='\\'||*s=='/')b=s+1;return b;}
static int pickFolder(char*out){
  BROWSEINFOA bi={0};bi.hwndOwner=NULL;bi.pszDisplayName=out;bi.lpszTitle="Escolha a pasta";bi.ulFlags=BIF_RETURNONLYFSDIRS;
  LPITEMIDLIST id=SHBrowseForFolderA(&bi);if(!id)return 0;SHGetPathFromIDListA(id,out);return 1;
}
/* ---- gerar ---- */
static void encodeOne(const char*path,const char*outdir){
  int k=mc_encode_file(path,baseName(path),outdir,cfgN,cfgCM,cfgNS,cfgPX,cfgQ);
  if(k>0)logf("OK  %s -> %d PNG",baseName(path),k); else logf("ERRO %s",path);
}
static void encodeFolder(const char*dir,const char*outdir){
  char pat[1024];snprintf(pat,sizeof(pat),"%s\\*",dir);
  WIN32_FIND_DATAA fd;HANDLE h=FindFirstFileA(pat,&fd);if(h==INVALID_HANDLE_VALUE)return;
  do{
    if(fd.cFileName[0]=='.')continue;
    char full[1024];snprintf(full,sizeof(full),"%s\\%s",dir,fd.cFileName);
    if(fd.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY)encodeFolder(full,outdir);
    else encodeOne(full,outdir);
  }while(FindNextFileA(h,&fd));
  FindClose(h);
}
static void doGenerate(BOOL folderMode){
  char out[MAX_PATH];if(!pickFolder(out))return; /* pasta de destino dos PNG */
  if(folderMode){char dir[MAX_PATH];if(!pickFolder(dir))return;logf("Gerando da pasta %s ...",dir);encodeFolder(dir,out);}
  else{
    static char fn[16384];fn[0]=0;
    OPENFILENAMEA of={0};of.lStructSize=sizeof(of);of.lpstrFilter="Todos\0*.*\0";of.lpstrFile=fn;of.nMaxFile=sizeof(fn);of.Flags=OFN_ALLOWMULTISELECT|OFN_EXPLORER;
    if(!GetOpenFileNameA(&of))return;
    /* multi-selecao: fn = dir \0 f1 \0 f2 ... */
    char*dir=fn;char*p=fn+strlen(fn)+1;
    if(*p==0){logf("Gerando %s ...",baseName(dir));encodeOne(dir,out);}
    else{while(*p){char full[1024];snprintf(full,sizeof(full),"%s\\%s",dir,p);logf("Gerando %s ...",p);encodeOne(full,out);p+=strlen(p)+1;}}
  }
  logf("Concluido. PNGs em %s",out);
}
/* ---- ler ---- */
typedef struct{char name[300];uint32_t fi,tf;uint8_t*data;int len;}Frame;
static void doRead(){
  static char fn[16384];fn[0]=0;
  OPENFILENAMEA of={0};of.lStructSize=sizeof(of);of.lpstrFilter="PNG\0*.png\0";of.lpstrFile=fn;of.nMaxFile=sizeof(fn);of.Flags=OFN_ALLOWMULTISELECT|OFN_EXPLORER;
  if(!GetOpenFileNameA(&of))return;
  /* coleta caminhos */
  char*paths[4096];int np=0;static char tmp[16384];
  char*dir=fn;char*p=fn+strlen(fn)+1;
  if(*p==0){paths[np++]=dir;}
  else{while(*p&&np<4096){snprintf(tmp+(p-fn),sizeof(tmp)-(p-fn),"%s\\%s",dir,p);paths[np++]=tmp+(p-fn);p+=strlen(p)+1;}}
  /* decodifica cada PNG */
  Frame fr[8192];int nf=0;
  for(int i=0;i<np&&nf<8192;i++){
    FILE*f=fopen(paths[i],"rb");if(!f)continue;fseek(f,0,SEEK_END);long sz=ftell(f);fseek(f,0,SEEK_SET);
    uint8_t*buf=(uint8_t*)malloc(sz);fread(buf,1,sz,f);fclose(f);
    int w,h;uint8_t*rgb=mc_png_read(buf,(size_t)sz,&w,&h);free(buf);if(!rgb){logf("PNG invalido: %s",paths[i]);continue;}
    uint8_t*data=(uint8_t*)malloc(70000);char nm[300];uint32_t fi,tf;int dl,cm;
    if(mc_decode_image(rgb,w,h,data,&dl,nm,&fi,&tf,&cm)){fr[nf].fi=fi;fr[nf].tf=tf;fr[nf].len=dl;fr[nf].data=data;strncpy(fr[nf].name,nm,299);nf++;}
    else{logf("sem codigo: %s",paths[i]);free(data);}
    free(rgb);
  }
  logf("%d quadro(s) decodificado(s).",nf);
  if(!nf)return;
  char out[MAX_PATH];if(!pickFolder(out))return;
  /* reagrupa por nome */
  for(int i=0;i<nf;i++){
    if(fr[i].name[0]==0)continue;
    /* ja salvo? */
    int dup=0;for(int j=0;j<i;j++)if(!strcmp(fr[j].name,fr[i].name)){dup=1;break;}
    if(dup)continue;
    int total=fr[i].tf;uint8_t*full=(uint8_t*)calloc(1,1);int flen=0;
    for(int k=0;k<total;k++){
      for(int j=0;j<nf;j++)if(!strcmp(fr[j].name,fr[i].name)&&fr[j].fi==(uint32_t)k){
        full=(uint8_t*)realloc(full,flen+fr[j].len);memcpy(full+flen,fr[j].data,fr[j].len);flen+=fr[j].len;break;}
    }
    char op[1024];snprintf(op,sizeof(op),"%s\\%s",out,fr[i].name);
    FILE*o=fopen(op,"wb");if(o){fwrite(full,1,flen,o);fclose(o);logf("SALVO %s (%d bytes)",fr[i].name,flen);}
    free(full);
  }
  for(int i=0;i<nf;i++)free(fr[i].data);
  logf("Concluido. Arquivos em %s",out);
}
static LRESULT CALLBACK WndProc(HWND h,UINT m,WPARAM w,LPARAM l){
  switch(m){
    case WM_COMMAND:
      if(LOWORD(w)==1)doGenerate(FALSE);
      else if(LOWORD(w)==2)doGenerate(TRUE);
      else if(LOWORD(w)==3)doRead();
      return 0;
    case WM_DROPFILES:{
      char out[MAX_PATH];if(!pickFolder(out))return 0;
      UINT c=DragQueryFileA((HDROP)w,0xFFFFFFFF,NULL,0);
      for(UINT i=0;i<c;i++){char p[MAX_PATH];DragQueryFileA((HDROP)w,i,p,sizeof(p));
        DWORD at=GetFileAttributesA(p);
        if(at&FILE_ATTRIBUTE_DIRECTORY){logf("Pasta %s ...",p);encodeFolder(p,out);}else encodeOne(p,out);}
      logf("Concluido (arrastados). PNGs em %s",out);return 0;}
    case WM_DESTROY:PostQuitMessage(0);return 0;
  }
  return DefWindowProcA(h,m,w,l);
}
int WINAPI WinMain(HINSTANCE hi,HINSTANCE hp,LPSTR cl,int cs){
  WNDCLASSA wc={0};wc.lpfnWndProc=WndProc;wc.hInstance=hi;wc.hCursor=LoadCursor(0,IDC_ARROW);wc.lpszClassName="MC";wc.hbrBackground=(HBRUSH)(COLOR_BTNFACE+1);
  RegisterClassA(&wc);
  HWND h=CreateWindowA("MC","MegaCode - Gerador/Leitor (preto=0 branco=1)",WS_OVERLAPPEDWINDOW|WS_VISIBLE,80,80,720,460,0,0,hi,0);
  CreateWindowA("BUTTON","Selecionar ARQUIVOS",WS_CHILD|WS_VISIBLE|BS_PUSHBUTTON,10,10,210,32,h,(HMENU)1,hi,0);
  CreateWindowA("BUTTON","Selecionar PASTA inteira",WS_CHILD|WS_VISIBLE|BS_PUSHBUTTON,230,10,210,32,h,(HMENU)2,hi,0);
  CreateWindowA("BUTTON","Ler / Importar PNG",WS_CHILD|WS_VISIBLE|BS_PUSHBUTTON,450,10,210,32,h,(HMENU)3,hi,0);
  hLog=CreateWindowA("EDIT","",WS_CHILD|WS_VISIBLE|WS_VSCROLL|ES_MULTILINE|ES_AUTOVSCROLL|ES_READONLY,10,52,690,360,h,0,hi,0);
  DragAcceptFiles(h,TRUE);
  logf("Pronto. Arraste arquivos/pastas na janela, ou use os botoes. n=%d cm=%d nsym=%d px=%d borda=%d",cfgN,cfgCM,cfgNS,cfgPX,cfgQ);
  MSG msg;while(GetMessageA(&msg,0,0,0)){TranslateMessage(&msg);DispatchMessageA(&msg);}
  return 0;
}
