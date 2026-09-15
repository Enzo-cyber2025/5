package com.ggufchat.app;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.util.*;

/** GGUF v2/v3 LE reader and streaming tensor-table merger. No Android dependency.
 * Reads actual metadata AND tensor descriptors. Never infers capability from filenames.
 * The output is one GGUF header, one KV table, one tensor table and aligned tensor data.
 */
public final class GgufFile {
    private static final long HEADER_LIMIT=128L*1024*1024;
    public final File file;
    public final LinkedHashMap<String,KV> metadata=new LinkedHashMap<>();
    public final LinkedHashMap<String,Tensor> tensors=new LinkedHashMap<>();
    public long dataOffset; public int alignment=32; public boolean imageTokens;
    public static final class KV {
        final File file; final String key; final long start,length; public final int type; public final Object value;
        KV(File f,String k,long s,long n,int t,Object v){file=f;key=k;start=s;length=n;type=t;value=v;}
    }
    public static final class Tensor {
        public final String name; public final long[] dims; public final int type;
        public final long offset,bytes;
        Tensor(String n,long[] d,int t,long o,long b){name=n;dims=d;type=t;offset=o;bytes=b;}
    }
    public interface Progress {
        void update(String stage,long done,long total,boolean complete);
        Progress NONE=(stage,done,total,complete)->{};
    }
    private GgufFile(File f){file=f;}
    private static IOException bad(String s){return new IOException("GGUF: "+s);}
    private static long add(long a,long b) throws IOException {if(a<0||b<0||a>Long.MAX_VALUE-b)throw bad("overflow de tamanho");return a+b;}
    private static long mul(long a,long b) throws IOException {if(a<0||b<0||(a!=0&&b>Long.MAX_VALUE/a))throw bad("overflow de dimensões");return a*b;}
    private static long align(long n,int a) throws IOException{return add(n,a-1)/a*a;}
    private static void check(RandomAccessFile f,long n) throws IOException {if(n<0||n>f.length()-f.getFilePointer())throw bad("arquivo truncado");}
    private static void skip(RandomAccessFile f,long n) throws IOException {check(f,n);f.seek(f.getFilePointer()+n);}
    private static int u32(RandomAccessFile f) throws IOException{return Integer.reverseBytes(f.readInt());}
    private static long u64(RandomAccessFile f) throws IOException {long n=Long.reverseBytes(f.readLong());if(n<0)throw bad("uint64 fora do intervalo suportado");return n;}
    private static String string(RandomAccessFile f) throws IOException {
        long n=u64(f);if(n>1024*1024)throw bad("string de metadados excessiva");check(f,n);
        byte[] b=new byte[(int)n];f.readFully(b);
        try{return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(b)).toString();}
        catch(CharacterCodingException e){throw bad("UTF-8 inválido");}
    }
    private static Object value(RandomAccessFile f,int type,int depth,GgufFile g,boolean tokens) throws IOException {
        switch(type) {
            case 0:return (long)f.readUnsignedByte();case 1:return (long)f.readByte();
            case 2:return (long)(Short.reverseBytes(f.readShort())&65535);case 3:return (long)Short.reverseBytes(f.readShort());
            case 4:return Integer.toUnsignedLong(u32(f));case 5:return (long)u32(f);
            case 6:return Float.intBitsToFloat(u32(f));
            case 7:int b=f.readUnsignedByte();if(b>1)throw bad("booleano inválido");return b==1;
            case 8:String s=string(f);if(tokens && (s.equals("<image>")||s.equals("<|image_pad|>")||s.equals("<start_of_image>")||s.equals("<|vision_start|>")))g.imageTokens=true;return s;
            case 9:
                if(depth!=0)throw bad("array aninhado não suportado");int element=u32(f);long count=u64(f);
                if(count>4000000||element<0||element>12||element==9)throw bad("array inválido/excessivo");
                for(long i=0;i<count;i++){value(f,element,1,g,tokens);if(f.getFilePointer()>HEADER_LIMIT)throw bad("metadados excessivos");}
                return null;
            case 10:return u64(f);case 11:return Long.reverseBytes(f.readLong());case 12:return Double.longBitsToDouble(Long.reverseBytes(f.readLong()));
            default:throw bad("tipo de metadado desconhecido: "+type);
        }
    }
    // block elements / stored bytes, pinned to llama.cpp b6500 GGML_QUANT_SIZES.
    private static final int[][] QUANT={{1,4},{1,2},{32,18},{32,20},{0,0},{0,0},{32,22},{32,24},{32,34},{32,40},{256,84},{256,110},{256,144},{256,176},{256,210},{256,292},{256,66},{256,74},{256,98},{256,50},{32,18},{256,110},{256,82},{256,136},{1,1},{1,2},{1,4},{1,8},{1,8},{256,56},{1,2},{0,0},{0,0},{0,0},{256,54},{256,66},{0,0},{0,0},{0,0},{32,17}};
    public static GgufFile read(File file) throws IOException {return read(file,Progress.NONE);}
    public static GgufFile read(File file,Progress progress) throws IOException {
        progress.update("identify",0,-1,false);
        GgufFile g=new GgufFile(file);
        try(RandomAccessFile f=new RandomAccessFile(file,"r")) {
            if(u32(f)!=0x46554747)throw bad("magic inválido (não é GGUF little-endian)");
            int version=u32(f);if(version!=2&&version!=3)throw bad("versão não suportada: "+version);
            long nt=u64(f),nk=u64(f);if(nt>200000||nk>200000)throw bad("tabela excessiva");
            long units=nk+2*nt;progress.update("identify",0,units,false);
            for(long i=0;i<nk;i++) {
                long start=f.getFilePointer();String key=string(f);int type=u32(f);
                Object v=value(f,type,0,g,key.equals("tokenizer.ggml.tokens"));
                if(g.metadata.put(key,new KV(file,key,start,f.getFilePointer()-start,type,v))!=null)throw bad("chave duplicada: "+key);
                if(f.getFilePointer()>HEADER_LIMIT)throw bad("metadados excessivos");
                progress.update("identify",i+1,units,false);
            }
            KV a=g.metadata.get("general.alignment");if(a!=null){if(a.type!=4)throw bad("alignment deve ser uint32");long n=(Long)a.value;if(n<1||n>65536||(n&(n-1))!=0)throw bad("alignment inválido");g.alignment=(int)n;}
            if(g.number("split.count")>1)throw bad("GGUF dividido em shards: reúna os shards antes de importar/unificar");
            for(long i=0;i<nt;i++) {
                String name=string(f);int nd=u32(f);if(nd<1||nd>4)throw bad("dimensões inválidas");
                long[] dims=new long[nd];long elements=1;
                for(int j=0;j<nd;j++){dims[j]=u64(f);if(dims[j]==0)throw bad("tensor vazio");elements=mul(elements,dims[j]);}
                int type=u32(f);long offset=u64(f);
                if(type<0||type>=QUANT.length||QUANT[type][0]==0)throw bad("quantização não suportada pelo motor: "+type);
                if(dims[0]%QUANT[type][0]!=0)throw bad("linha incompatível com bloco quantizado");
                long bytes=mul(elements/QUANT[type][0],QUANT[type][1]);
                if(offset%g.alignment!=0)throw bad("tensor desalinhado");
                if(g.tensors.put(name,new Tensor(name,dims,type,offset,bytes))!=null)throw bad("tensor duplicado: "+name);
                if(f.getFilePointer()>HEADER_LIMIT)throw bad("tabela excessiva");
                progress.update("identify",nk+i+1,units,false);
            }
            g.dataOffset=align(f.getFilePointer(),g.alignment);
            ArrayList<Tensor> sorted=new ArrayList<>(g.tensors.values());Collections.sort(sorted,new Comparator<Tensor>(){public int compare(Tensor a,Tensor b){return Long.compare(a.offset,b.offset);}});
            long end=0,checked=nk+nt;for(Tensor t:sorted){if(t.offset<end)throw bad("tensores sobrepostos");end=add(t.offset,t.bytes);if(add(g.dataOffset,end)>f.length())throw bad("dados truncados: "+t.name);progress.update("identify",++checked,units,false);}
            if(g.dataOffset>f.length())throw bad("cabeçalho truncado");
            progress.update("identify",units,units,true);
        }
        return g;
    }
    public String text(String key){KV k=metadata.get(key);return k!=null&&k.value instanceof String?(String)k.value:"";}
    public long number(String key){KV k=metadata.get(key);return k!=null&&k.value instanceof Number?((Number)k.value).longValue():0;}
    public boolean flag(String key){KV k=metadata.get(key);return k!=null&&Boolean.TRUE.equals(k.value);}
    public static boolean mediaTensor(String name){return name.startsWith("v.")||name.startsWith("a.")||name.startsWith("mm.")||name.startsWith("resampler.")||name.startsWith("adapter.")||name.equals("model.image_newline");}
    public boolean language(){return !text("general.architecture").isEmpty()&&!text("general.architecture").equals("clip")&&tensors.containsKey("token_embd.weight")&&metadata.containsKey("tokenizer.ggml.tokens");}
    public String visionProjectorType(){String type=text("clip.projector_type");return type.isEmpty()?text("clip.vision.projector_type"):type;}
    public boolean visionWeights(){
        boolean encoder=false,projector=false;
        for(String n:tensors.keySet()){encoder|=n.startsWith("v.blk.");projector|=n.startsWith("mm.")||n.startsWith("resampler.")||n.startsWith("adapter.");}
        return flag("clip.has_vision_encoder")&&!visionProjectorType().isEmpty()&&number("clip.vision.block_count")>0&&encoder&&projector;
    }
    /** Only intrinsically verified language may enter the language side of a pair. */
    public String pairingRole() throws IOException {
        if(projector())return "projector";
        if(language()&&!visionWeights())return "language";
        if(singleVision())throw bad("este arquivo já contém linguagem e visão; importe-o sozinho");
        throw bad("componente não reconhecido como linguagem ou projetor compatível: "+capability()+" (arquitetura="+text("general.architecture")+")");
    }
    public boolean singleVision(){return language()&&visionWeights();}
    public boolean projector(){return !language()&&visionWeights();}
    public String capability(){
        if(singleVision())return "VISION_SINGLE_GGUF";
        if(projector())return "VISION_PROJECTOR";
        if(flag("clip.has_audio_encoder"))return "AUDIO_DECLARED_UNSUPPORTED";
        for(String k:metadata.keySet())if(k.contains("vision")||k.contains("image_token")||k.contains("projector"))return "MULTIMODAL_DECLARED_INCOMPLETE";
        for(String n:tensors.keySet())if(mediaTensor(n)||n.contains("vision")||n.contains("visual"))return "MULTIMODAL_LAYOUT_UNSUPPORTED";
        if(!language())return "UNKNOWN_MODEL";
        return imageTokens?"IMAGE_TOKENS_ONLY":"TEXT_ONLY";
    }
    private static void u32(DataOutput out,int n) throws IOException{out.writeInt(Integer.reverseBytes(n));}
    private static void u64(DataOutput out,long n) throws IOException{out.writeLong(Long.reverseBytes(n));}
    private static void string(DataOutput out,String s) throws IOException{byte[] b=s.getBytes(StandardCharsets.UTF_8);u64(out,b.length);out.write(b);}
    private static void copy(RandomAccessFile in,RandomAccessFile out,long start,long n,byte[] buffer) throws IOException {
        in.seek(start);while(n>0){if(Thread.currentThread().isInterrupted())throw new InterruptedIOException("Unificação cancelada");int k=(int)Math.min(n,buffer.length);in.readFully(buffer,0,k);out.write(buffer,0,k);n-=k;}
    }
    /** Caller owns the transaction: output must be new; originals are never modified here. */
    public static GgufFile merge(File language,File projector,File output) throws IOException {return merge(language,projector,output,Progress.NONE);}
    public static GgufFile merge(File language,File projector,File output,Progress progress) throws IOException {
        progress.update("merge",0,-1,false);
        GgufFile a=read(language),b=read(projector);
        if(!a.language()||a.visionWeights()||!b.projector())throw bad("selecione linguagem + projetor de visão com parâmetros e tensores reais");
        if(a.number(a.text("general.architecture")+".embedding_length")<=0||b.number("clip.vision.projection_dim")<=0||a.number(a.text("general.architecture")+".embedding_length")!=b.number("clip.vision.projection_dim"))throw bad("dimensão do projetor incompatível com o modelo");
        for(String n:b.tensors.keySet())if(!mediaTensor(n)||a.tensors.containsKey(n))throw bad("tensor do projetor incompatível/duplicado: "+n);
        LinkedHashMap<String,KV> kv=new LinkedHashMap<>(a.metadata);kv.remove("general.alignment");
        for(Map.Entry<String,KV> e:b.metadata.entrySet()) {
            String key=e.getKey();if(key.startsWith("split."))continue;
            if(key.startsWith("general."))key="ggufchat.projector."+key;
            if(kv.containsKey(key))throw bad("metadado conflitante: "+key);
            kv.put(key,e.getValue());
        }
        int alignment=Math.max(a.alignment,b.alignment);
        if(!output.createNewFile())throw bad("arquivo de saída já existe");
        boolean complete=false;
        try(RandomAccessFile out=new RandomAccessFile(output,"rw");RandomAccessFile fa=new RandomAccessFile(language,"r");RandomAccessFile fb=new RandomAccessFile(projector,"r")) {
            byte[] buffer=new byte[128*1024];u32(out,0x46554747);u32(out,3);u64(out,a.tensors.size()+b.tensors.size());u64(out,kv.size()+1);
            for(Map.Entry<String,KV> item:kv.entrySet()) {
                KV entry=item.getValue();string(out,item.getKey());
                long prefix=8+entry.key.getBytes(StandardCharsets.UTF_8).length;
                copy(entry.file.equals(language)?fa:fb,out,entry.start+prefix,entry.length-prefix,buffer);
            }
            string(out,"general.alignment");u32(out,4);u32(out,alignment);
            long offset=0;ArrayList<Tensor> all=new ArrayList<>(a.tensors.values());all.addAll(b.tensors.values());
            for(Tensor t:all){string(out,t.name);u32(out,t.dims.length);for(long d:t.dims)u64(out,d);u32(out,t.type);u64(out,offset);offset=align(add(offset,t.bytes),alignment);}
            long data=align(out.getFilePointer(),alignment);out.setLength(add(data,offset));out.seek(data);offset=0;
            long total=0,done=0;for(Tensor t:all)total=add(total,t.bytes);
            progress.update("merge",0,total,false);
            for(Tensor t:all){boolean fromA=a.tensors.containsKey(t.name);out.seek(add(data,offset));
                RandomAccessFile input=fromA?fa:fb;input.seek(add(fromA?a.dataOffset:b.dataOffset,t.offset));
                for(long left=t.bytes;left>0;){
                    if(Thread.currentThread().isInterrupted())throw new InterruptedIOException("Unificação cancelada");
                    int n=(int)Math.min(left,buffer.length);input.readFully(buffer,0,n);out.write(buffer,0,n);
                    left-=n;done=add(done,n);progress.update("merge",done,total,false);
                }
                offset=align(add(offset,t.bytes),alignment);
            }
            out.getFD().sync();GgufFile merged=read(output);if(!merged.singleVision())throw bad("unificação não contém visão + linguagem");
            progress.update("merge",done,total,true);
            verifyPayload(a,b,merged,progress);complete=true;return merged;
        } finally {if(!complete)output.delete();}
    }
    /** Independent reread: exact tensor types, shapes AND every payload byte. */
    public static void verifyPayload(GgufFile a,GgufFile b,GgufFile output) throws IOException {verifyPayload(a,b,output,Progress.NONE);}
    public static void verifyPayload(GgufFile a,GgufFile b,GgufFile output,Progress progress) throws IOException {
        long total=0,done=0;for(GgufFile g:Arrays.asList(a,b))for(Tensor t:g.tensors.values())total=add(total,t.bytes);
        progress.update("verify",0,total,false);
        if(output.tensors.size()!=a.tensors.size()+b.tensors.size())throw bad("contagem de tensores alterada");
        byte[] x=new byte[128*1024],y=new byte[x.length];
        try(RandomAccessFile result=new RandomAccessFile(output.file,"r")) {
            for(GgufFile source:Arrays.asList(a,b))try(RandomAccessFile input=new RandomAccessFile(source.file,"r")) {
                for(Tensor t:source.tensors.values()) {
                    Tensor v=output.tensors.get(t.name);
                    if(v==null||v.type!=t.type||v.bytes!=t.bytes||!Arrays.equals(v.dims,t.dims))throw bad("tensor alterado: "+t.name);
                    input.seek(add(source.dataOffset,t.offset));result.seek(add(output.dataOffset,v.offset));
                    for(long left=t.bytes;left>0;) {
                        if(Thread.currentThread().isInterrupted())throw new InterruptedIOException("Validação cancelada");
                        int n=(int)Math.min(left,x.length);input.readFully(x,0,n);result.readFully(y,0,n);
                        for(int i=0;i<n;i++)if(x[i]!=y[i])throw bad("bytes alterados: "+t.name);
                        left-=n;done=add(done,n);progress.update("verify",done,total,false);
                    }
                }
            }
        }
        progress.update("verify",done,total,true);
    }
    public static void main(String[] args) throws Exception {
        GgufFile g=args.length==3?merge(new File(args[0]),new File(args[1]),new File(args[2])):read(new File(args[0]));
        System.out.println(g.capability()+" tensors="+g.tensors.size()+" architecture="+g.text("general.architecture"));
    }
}
