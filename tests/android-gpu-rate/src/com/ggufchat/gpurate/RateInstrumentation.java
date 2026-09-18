package com.ggufchat.gpurate;

import android.app.Instrumentation;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.os.PowerManager;
import android.util.Log;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;

/** Test-only observer. Loads the installed app's unchanged Native class/libraries.
 * Never injects a response, changes the model or recompiles a native library. */
public final class RateInstrumentation extends Instrumentation {
    private Bundle args;
    private Class<?> nativeClass,callbackClass;
    private long handle;
    private PowerManager power;
    private boolean sleeping;
    private final String prime="Explain ten practical ways to learn a language. Give a detailed example for each. Reply in English.";
    private final String follow="Give ten more practical recommendations, with detailed examples. Reply in English.";

    @Override public void onCreate(Bundle arguments){super.onCreate(arguments);args=arguments;start();}
    private static void require(boolean b,String message){if(!b)throw new IllegalStateException(message);}
    private Method method(String name,Class<?>... types)throws Exception{
        Method m=nativeClass.getDeclaredMethod(name,types);m.setAccessible(true);return m;
    }
    private void shell(String command)throws Exception{
        try(ParcelFileDescriptor p=getUiAutomation().executeShellCommand(command);
            InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(p)){
            byte[] b=new byte[1024];while(in.read(b)!=-1){}
        }
    }
    private static String digest(File file)throws Exception{
        MessageDigest d=MessageDigest.getInstance("SHA-256");
        try(InputStream in=new java.io.FileInputStream(file)){
            byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1)d.update(b,0,n);
        }
        StringBuilder out=new StringBuilder();for(byte b:d.digest())out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return out.toString();
    }
    private String render(String[] roles,String[] contents)throws Exception{
        String text=(String)method("applyTemplate",long.class,String.class,String[].class,String[].class)
            .invoke(null,handle,null,roles,contents);
        require(text!=null&&!text.isEmpty(),"Missing real native chat template");return text;
    }
    private JSONObject generate(String prompt,String stage)throws Exception{
        final ArrayList<String> chunks=new ArrayList<>(128);
        final long[] times=new long[1024];final int[] count={0};final boolean[] done={false},success={false};
        Object callback=Proxy.newProxyInstance(callbackClass.getClassLoader(),new Class<?>[]{callbackClass},(proxy,m,values)->{
            if(m.getName().equals("onToken")){
                long now=System.nanoTime();
                require(count[0]<times.length,"Too many callbacks");
                String text=(String)values[0];require(text!=null&&!text.isEmpty(),"Empty callback cannot identify a token interval");
                times[count[0]++]=now;chunks.add(text);return null;
            }
            if(m.getName().equals("onDone")){require(!done[0],"Duplicate completion");done[0]=true;success[0]=(Boolean)values[0];return null;}
            if(m.getName().equals("toString"))return "GPU rate observer";
            if(m.getName().equals("hashCode"))return System.identityHashCode(proxy);
            if(m.getName().equals("equals"))return proxy==values[0];
            throw new IllegalStateException("Unexpected callback method: "+m.getName());
        });
        require(power.isInteractive()!=sleeping,"Wrong actual screen state before generation");
        Log.i("GpuRateObserver","GPU_RATE_BEGIN stage="+stage);
        boolean ok=(Boolean)method("generate",long.class,String.class,int.class,float.class,float.class,float.class,float.class,float.class,int.class,int.class,callbackClass)
            .invoke(null,handle,prompt,128,0.0f,0.95f,40.0f,0.05f,1.1f,64,42,callback);
        require(ok&&done[0]&&success[0],"Native generation did not complete successfully");
        require(power.isInteractive()!=sleeping,"Wrong actual screen state after generation");
        // This count is NOT used as a token estimate. The host must independently
        // require native GGUF_NATIVE_COMPLETE tokens=128 AND exactly 128 callbacks.
        require(count[0]==128,"Callbacks coalesced or early EOS: no one-token interval rate may be claimed");
        JSONArray ticks=new JSONArray(),parts=new JSONArray();StringBuilder response=new StringBuilder();
        for(int i=0;i<count[0];i++){
            if(i>0)require(times[i]>times[i-1],"Non-increasing monotonic clock");
            ticks.put(times[i]);parts.put(chunks.get(i));response.append(chunks.get(i));
        }
        int[] input=(int[])method("tokenize",long.class,String.class).invoke(null,handle,prompt);
        require(input.length+128<=2048,"Context would reduce the output budget");
        JSONObject r=new JSONObject();r.put("stage",stage);r.put("prompt",prompt);r.put("prompt_token_ids",new JSONArray(input));
        r.put("response",response.toString());r.put("chunks",parts);r.put("callback_times_ns",ticks);r.put("callbacks",count[0]);
        r.put("interval_ns",times[count[0]-1]-times[0]);r.put("screen_asleep",sleeping);
        r.put("native_success",true);r.put("done_success",true);
        r.put("metric","native_token_delivery_intervals_excluding_first_token_and_prefill");
        Log.i("GpuRateObserver","GPU_RATE_END stage="+stage);return r;
    }
    @Override public void onStart(){
        JSONObject report=new JSONObject();PowerManager.WakeLock lease=null;
        try{
            require("1".equals(args.getString("emulator_confirmed")),"Disposable emulator required");
            JSONObject environment=new JSONObject();
            for(java.util.Map.Entry<String,String> e:System.getenv().entrySet())
                if(e.getKey().startsWith("GGML_")||e.getKey().startsWith("GGUF_"))environment.put(e.getKey(),e.getValue());
            report.put("vulkan_environment",environment);
            ClassLoader loader=getTargetContext().getClassLoader();
            nativeClass=Class.forName("com.ggufchat.app.Native",true,loader);
            callbackClass=Class.forName("com.ggufchat.app.Native$GenerateCallback",true,loader);
            File model=new File(getTargetContext().getFilesDir(),"gpu-rate.gguf");
            require(digest(model).equals("2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d"),"Model bytes changed");
            getUiAutomation().adoptShellPermissionIdentity(android.Manifest.permission.WAKE_LOCK);
            power=(PowerManager)getTargetContext().getSystemService(android.content.Context.POWER_SERVICE);
            lease=power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"GGUFTest:GpuRate");lease.acquire(1200000);
            handle=(Long)method("create",String.class,String.class,int.class,int.class,int.class,boolean.class)
                .invoke(null,model.getAbsolutePath(),"",2048,2,99,true);
            require(handle!=0,"Native load failed: "+method("lastError",long.class).invoke(null,handle));
            sleeping="asleep".equals(args.getString("state"));
            shell(sleeping?"input keyevent 223":"input keyevent 224; wm dismiss-keyguard");
            long until=android.os.SystemClock.uptimeMillis()+10000;
            while(power.isInteractive()==sleeping && android.os.SystemClock.uptimeMillis()<until)android.os.SystemClock.sleep(50);
            JSONObject warm=generate(render(new String[]{"user"},new String[]{prime}),"warmup");
            JSONObject sample=generate(render(new String[]{"user","assistant","user"},new String[]{prime,warm.getString("response"),follow}),"sample");
            report.put("warmup",warm);report.put("sample",sample);report.put("status","PASS_NATIVE_OBSERVER");
            report.put("model_sha256",digest(model));
            report.put("settings",new JSONObject().put("context",2048).put("threads",2).put("gpu_layers",99).put("predict",128)
                .put("temperature",0).put("top_p",0.95).put("top_k",40).put("min_p",0.05).put("repeat",1.1).put("last_n",64).put("seed",42).put("mmap",true));
        }catch(Throwable e){
            Log.e("GpuRateObserver","Native benchmark failed",e);
            try{report.put("status","FAIL");report.put("error",Log.getStackTraceString(e));}catch(Exception ignored){}
        }finally{
            try{if(handle!=0)method("destroy",long.class).invoke(null,handle);}catch(Exception e){Log.e("GpuRateObserver","destroy failed",e);}
            if(lease!=null&&lease.isHeld())lease.release();
            try{getUiAutomation().dropShellPermissionIdentity();}catch(Exception ignored){}
            try(FileOutputStream out=new FileOutputStream(new File(getTargetContext().getFilesDir(),"gpu-rate.json"))){out.write(report.toString(2).getBytes(StandardCharsets.UTF_8));}
            catch(Exception e){Log.e("GpuRateObserver","Report write failed",e);}
            Bundle result=new Bundle();result.putString("report",report.toString());finish(android.app.Activity.RESULT_OK,result);
        }
    }
}
