package com.ggufchat.app;

import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;

/** Persistence additions deliberately independent of Android UI classes. */
public final class RecordFields {
    public static void readModel(Object model,JSONObject j) throws Exception {
        model.getClass().getField("capability").set(model,j.optString("capability","NOT_INSPECTED"));
    }
    public static void writeModel(Object model,JSONObject j) throws Exception {
        Object value=model.getClass().getField("capability").get(model);j.put("capability",value==null?"NOT_INSPECTED":value);
    }
    public static void readChat(Object chat,JSONObject j) throws Exception {
        chat.getClass().getField("systemPrompt").set(chat,j.has("systemPrompt")&&!j.isNull("systemPrompt")?j.getString("systemPrompt"):null);
    }
    public static void writeChat(Object chat,JSONObject j) throws Exception {
        Object value=chat.getClass().getField("systemPrompt").get(chat);j.put("systemPrompt",value==null?JSONObject.NULL:value);
    }
    /** Never delete the previous index to retry a failed rename. Fail closed. */
    public static void writeAtomic(File dest,String text) throws IOException {
        File temp=File.createTempFile(dest.getName()+"-",".new",dest.getParentFile());
        try {
            try(FileOutputStream out=new FileOutputStream(temp)){out.write(text.getBytes(StandardCharsets.UTF_8));out.getFD().sync();}
            Files.move(temp.toPath(),dest.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        }finally{temp.delete();}
    }
}
